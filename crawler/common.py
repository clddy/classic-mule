# 공통 유틸: 세션, 날짜/분류 추출
import os, re, hashlib, time
import requests
import urllib3
from bs4 import BeautifulSoup
urllib3.disable_warnings()

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

def new_session():
    s = requests.Session()
    s.headers.update(UA)
    return s

# 파이썬(OpenSSL)·크로미엄(BoringSSL) TLS 지문을 차단하는 호스트 — 같은 UA로도 응답을
# 안 주고 매달아 둔다(read timeout). 윈도우 curl(Schannel TLS)만 통과함을 확인
# (2026-08-02 cwcf: requests 40초 hang / playwright 30초 hang / curl 0.26초 200).
# 국내 관공서 보안장비가 윈도우 TLS 스택을 허용목록으로 쓰는 것으로 보인다.
# 이 호스트는 get()이 시스템 curl 서브프로세스로 투명하게 우회한다.
# ※ 리눅스(Actions)의 curl은 OpenSSL이라 우회가 안 됨 — 국내 PC 크롤이 주력인 이유 하나 추가.
TLS_BLOCKED_HOSTS = ("cwcf.or.kr",)
_CURL = r"C:\Windows\System32\curl.exe"

def tls_blocked(url):
    return any(h in (url or "") for h in TLS_BLOCKED_HOSTS)

class _BypassResponse:
    """curl 우회 결과를 requests.Response 처럼 보이게 하는 최소 껍데기 —
    호출부(r.text·r.status_code·r.url·r.content)가 구분 없이 쓰도록."""
    def __init__(self, url, content, encoding=None):
        self.url = url
        self.content = content or b""
        self.status_code = 200 if content else 599
        self.headers = {}
        if not encoding:  # euc-kr 구형 ASP(cwcf 등) 대응 — 메타 태그로 판별
            head = self.content[:2000].lower()
            encoding = "euc-kr" if (b"euc-kr" in head or b"ks_c_5601" in head) else "utf-8"
        self.encoding = encoding
        self.text = self.content.decode(encoding, "replace")

def curl_get(url, referer=None, timeout=25, encoding=None):
    """Schannel TLS 우회 GET (윈도우 curl.exe). 실패 시 빈 599 응답."""
    import subprocess
    if not os.path.exists(_CURL):
        return _BypassResponse(url, b"")
    args = [_CURL, "-s", "-L", "-k", "-m", str(timeout), "-A", UA["User-Agent"], url]
    if referer:
        args += ["-e", referer]
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout + 10)
        return _BypassResponse(url, p.stdout if p.returncode == 0 else b"", encoding)
    except Exception:
        return _BypassResponse(url, b"")

def get(s, url, encoding=None, retries=2, **kw):
    """GET + 네트워크 오류 재시도.

    공공기관 사이트는 간헐적으로 응답이 멎는다 — 대구문화예술회관은 같은 URL에
    40초 타임아웃 2연속 뒤 3회째에 0.9초로 정상 응답했다(2026-07-27 측정).
    재시도가 없으면 이런 딸꾹질 한 번에 그 소스의 하루치 수집이 통째로 날아간다.
    HTTP 상태코드는 호출부가 판단하므로 여기선 연결·타임아웃 계열만 재시도한다.
    """
    if tls_blocked(url):
        return curl_get(url, referer=(kw.get("headers") or {}).get("Referer"), encoding=encoding)
    last = None
    for attempt in range(retries + 1):
        try:
            r = s.get(url, timeout=20, verify=False, **kw)
            if encoding:
                r.encoding = encoding
            elif r.encoding in (None, "ISO-8859-1"):
                r.encoding = r.apparent_encoding
            time.sleep(0.8)  # 예의상 간격
            return r
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))   # 2초 → 4초 백오프
    raise last

DATE_PAT = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")

def norm_date(m):
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

def find_date(text):
    m = DATE_PAT.search(text or "")
    return norm_date(m) if m else None

# "2026. 7. 1.(화) ~ 7. 15.(화)" — 뒤 날짜에 연도가 생략되는 기간 표기
RANGE_PAT = re.compile(
    r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})[^~∼～]{0,30}[~∼～]\s*"
    r"(?:(20\d{2})\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
# "26. 7. 13" — 2자리 연도 (공문에서 흔함)
YY_DATE = re.compile(r"(?<![\d.])(2[0-9])\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})")
# "25.6.11(목) ~ 6.25(목)" — 2자리 연도 기간 (종료일 연도 생략 포함)
YY_RANGE = re.compile(
    r"(?<![\d.])(2[0-9])\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})[^~∼～\d]{0,20}[~∼～]\s*"
    r"(?:(2[0-9])\s*[.년]\s*)?(\d{1,2})\s*[.월]\s*(\d{1,2})")
# OCR이 점을 소실시킨 압축 표기: "2026.71.(수)~713.(월)" = 7.1~7.13
OCR_RANGE = re.compile(
    r"(20\d{2})\s*[.\-/]\s*(\d{2,4})\s*\.?\s*(?:\([^)]{1,3}\))?[^~∼～]{0,15}[~∼～]\s*"
    r"(?:(20\d{2})\s*[.\-/]\s*)?(\d{2,4})")

def _split_md(s):
    """'71'→(7,1), '713'→(7,13) — 월 1자리 우선, 실패 시 2자리"""
    for cut in (1, 2):
        mo, d = s[:cut], s[cut:]
        if mo and d and 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            return int(mo), int(d)
    return None

# "7. 2 ~ 7. 13" — 연도 전체 생략 기간
NOYEAR_RANGE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*[./월]\s*(\d{1,2})[^~∼～\d]{0,20}[~∼～]\s*(\d{1,2})\s*[./월]\s*(\d{1,2})")
# "7. 13.(월) 18:00까지", "6월 7일(일) 자정까지" — 연도 생략 단일
NOYEAR_KKAJI = re.compile(
    r"(?<![\d.])(\d{1,2})\s*[./월]\s*(\d{1,2})\s*일?\s*\.?\s*(?:\([^)]{1,4}\))?"
    # 날짜와 '까지' 사이에 시각이 낀 형태. 아래 [^0-9] 필러는 숫자를 못 넘어서
    # 주석이 예시로 든 "7. 13.(월) 18:00까지"조차 실제로는 못 읽고 있었다 (2026-08-07 규명).
    r"(?:[^0-9]{0,6}\d{1,2}\s*[:시]\s*\d{0,2}\s*분?)?"
    r"[^0-9]{0,14}까지")
# "모집마감 8.31.(월) 18:00" — '~'도 '까지'도 없이 마감 낱말 뒤에 날짜만 오는 표기.
# 포스터/이미지 공고가 이 꼴을 즐겨 쓰는데 위 두 패턴이 전부 비켜 가서 마감일을 통째로
# 놓쳤다 (2026-08-07 통영국제음악재단 포스터, 사용자 지적).
# 뒤에 ':' 나 '배·명'이 붙으면 경쟁률·인원이지 날짜가 아니므로 배제한다("2.5:1", "1.5배수").
NOYEAR_BARE = re.compile(
    r"(?:마감|기한)\s*[:\-]?\s*(?<![\d.])(\d{1,2})\s*[./]\s*(\d{1,2})(?![\d.]*\s*(?:배|명|:))")

def _valid(y, mo, d):
    return 1 <= int(mo) <= 12 and 1 <= int(d) <= 31

def _mk(y, mo, d):
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}" if _valid(y, mo, d) else None

# '접수'와 무관한 다른 기간 항목들. 여기를 넘어가면 그건 지원 마감일이 아니다.
# 경남교육청 공고는 '접수기간 시작일 - 종료일'을 빈 칸으로 두는데, 윈도가 그 빈 칸을
# 지나쳐 뒤의 '계약기간 2026.8.31 ~ 2027.2.28'을 물어 왔다 — 화정초 공고에 마감일이
# 2027-02-28로 박힌 이유다 (2026-08-08 규명).
#
# 더 근본적으로는, 윈도를 '다음 항목이 시작되는 곳'에서 끊는다. 게시판 상세는 대개
# "라벨 값 라벨 값 …" 으로 이어지는데, 값이 비어 있으면 라벨 두 개가 붙어 버린다
# ("접수기간 시작일 - 종료일 첨부파일 …"). 고정 300자만 보면 그 빈칸을 못 알아채고
# 다음 항목 값까지 넘어가 읽는다. 라벨에서 끊으면 '이 항목은 비었다'가 저절로 드러난다.
_OTHER_PERIOD = re.compile(
    r"계약\s*기간|근무\s*기간|고용\s*기간|활동\s*기간|사업\s*기간|교육\s*기간"
    r"|공연\s*기간|연수\s*기간|위촉\s*기간|임용\s*기간|수업\s*기간|운영\s*기간|강의\s*기간"
    # 값이 비었음을 대놓고 말해 주는 자리표시자
    r"|시작일\s*[-~]\s*종료일"
    # 다음 항목 라벨들
    r"|첨부\s*파일|문의\s*처|담당\s*자|전화\s*번호|연락\s*처|모집\s*인원|채용\s*인원"
    r"|직종|세부\s*분류|채용\s*상태|접수\s*상태|근무\s*지|자격\s*요건|응시\s*자격"
    r"|제출\s*서류|전형\s*방법|선발\s*방법|이전\s*글|다음\s*글|목록\s*보기")


def _window_deadline(window, ref_year):
    """한 키워드 윈도 안에서 마감일 후보 — 신뢰도 높은 패턴 순서로"""
    # 다른 기간 항목이 나오면 거기서 끊는다. 우리가 찾는 건 '언제까지 지원하나'뿐이다.
    window = _OTHER_PERIOD.split(window, 1)[0]
    # 1) 4자리 연도 기간 종료일
    for m in RANGE_PAT.finditer(window):
        c = _mk(m.group(4) or m.group(1), m.group(5), m.group(6))
        if c:
            return c
    # 2) 2자리 연도 기간 ("25.6.11 ~ 6.25")
    m = YY_RANGE.search(window)
    if m:
        y = 2000 + int(m.group(4) or m.group(1))
        c = _mk(y, m.group(5), m.group(6))
        if c:
            return c
    # 2.5) OCR 점 소실 압축 표기 ("2026.71~713")
    m = OCR_RANGE.search(window)
    if m and len(m.group(4)) >= 3:  # '713'처럼 3자리 이상만 (오탐 방지)
        md = _split_md(m.group(4))
        if md:
            c = _mk(m.group(3) or m.group(1), md[0], md[1])
            if c:
                return c
    # 3) 4자리 연도 단일 날짜(마지막)
    dates = [norm_date(m) for m in DATE_PAT.finditer(window) if _valid(m.group(1), m.group(2), m.group(3))]
    if dates:
        return max(dates)
    # 4) 2자리 연도 단일 ("26. 7. 13")
    yy = [_mk(2000 + int(m.group(1)), m.group(2), m.group(3)) for m in YY_DATE.finditer(window)]
    yy = [c for c in yy if c]
    if yy:
        return max(yy)
    # 5) 연도 생략 기간 → ref_year로 보정
    m = NOYEAR_RANGE.search(window)
    if m:
        c = _mk(ref_year, m.group(3), m.group(4))
        if c:
            return c
    # 6) "M.D까지"
    m = NOYEAR_KKAJI.search(window)
    if m:
        return _mk(ref_year, m.group(1), m.group(2))
    # 7) "마감 M.D" (맨 뒤 수단 — 다른 패턴이 전부 실패했을 때만)
    #    윈도 앞머리로 제한한다. 키워드에서 멀어질수록 '마감'과 무관한 숫자를 물 위험이 커진다.
    m = NOYEAR_BARE.search(window[:60])
    if m:
        c = _mk(ref_year, m.group(1), m.group(2))
        if c:
            return c
    return None

# 게시판 CMS가 본문 아래 붙이는 '이전글/다음글·목록·페이징' 영역의 클래스 이름들.
# 사이트마다 이름이 다르지만 어휘는 몇 개로 수렴한다 (navi/prev/next/paging…).
_NAVI_CLS = re.compile(r"(?:txt-)?navi|prev[-_]?next|next[-_]?prev|board[-_]?nav|article[-_]?nav"
                       r"|paging|pagination|pager", re.I)
NAVI_MAX_CHARS = 400   # 이 길이를 넘으면 네비가 아니라 본문 래퍼로 보고 손대지 않는다


def strip_navi(soup):
    """이전글·다음글·페이징 영역을 지운다 (본문을 읽기 전 공통 전처리).

    이 영역은 '다른 공고의 제목'을 본문인 척 끼워 넣는다 — 연세대 음대 공고 요약에
    엉뚱한 '강남생활문화축제 동호회 모집'이 실렸다(2026-08-04, div.txt-navi-wrap).
    거기 붙은 날짜가 마감일로 잘못 잡힐 위험도 함께 없앤다.
    본문 요약과 마감일 추출이 서로 다른 soup를 쓰므로 양쪽에서 이 함수를 호출한다.
    """
    # 먼저 대상을 모아둔다 — 순회 중에 지우면 이미 사라진 자식 태그를 다시 만져 터진다
    navi = [t for t in soup.find_all(attrs={"class": True})
            if _NAVI_CLS.search(" ".join(t.get("class") or []))]
    for tag in navi:
        if tag.parent is None:          # 조상이 먼저 지워졌으면 건너뛴다
            continue
        # ★ 길면 건드리지 않는다. 이전글·다음글 줄은 짧다(제목 한둘). 클래스 이름만 보고
        #   지웠더니 본문을 감싼 래퍼까지 날아가 요약 채움률이 87%→6%로 무너졌다
        #   (2026-08-07, 연세대 div.txt-navi-wrap이 본문 영역까지 감싸고 있었다).
        if len(tag.get_text(" ", strip=True)) > NAVI_MAX_CHARS:
            continue
        tag.decompose()
    return soup


def body_text(html_or_soup, parser="lxml"):
    """공고 페이지에서 본문 텍스트 추출 — 크롬(헤더·푸터·내비)만 걷어내고 본문은 지킨다.

    script/style은 항상 제거. header/footer/nav도 제거하되, **그 결과가 원문의 40% 미만으로
    쪼그라들면 제거를 취소하고 원문을 쓴다.**

    시맨틱을 무시하고 본문 전체를 <header>로 감싸는 사이트가 있기 때문이다 — 대전교육청은
    접수기간·채용인원·학교명이 전부 <header> 안에 있어서, 무조건 제거하면 우리가 스스로 본문을
    날려 마감일을 영영 못 찾았다(2026-07-27 규명: 크롬 제거 시 3302자 → 44자, 1%만 남음).
    정상 페이지는 59~100%가 남으므로 40% 컷이 둘을 안전하게 가른다.
    """
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(html_or_soup, parser)
    for tag in soup(["script", "style"]):
        tag.decompose()
    strip_navi(soup)
    full = soup.get_text(" ", strip=True)
    chrome = soup(["header", "footer", "nav"])
    if not chrome:
        return full
    # 제거는 파괴적이라 되돌릴 수 없다 → 사본에서 시험해 보고 채택 여부를 정한다
    trial = BeautifulSoup(str(soup), parser)
    for tag in trial(["header", "footer", "nav"]):
        tag.decompose()
    stripped = trial.get_text(" ", strip=True)
    return stripped if full and len(stripped) >= len(full) * 0.4 else full


# 우선 키워드(접수기간류)에서 찾으면 즉시 확정 — 활동기간·공연일 오인 방지
# 남은기간: 기독정보넷 상세의 "남은기간 2026-05-31 23:59:59 까지" 대응
_KW_PRIORITY = re.compile(r"원서 ?접수|접수 ?기간|접수 ?기한|접수 ?마감|서류 ?접수|지원 ?기간|응시원서|남은 ?기간")
_KW_FALLBACK = re.compile(r"접수|마감|기한|제출|지원서|모집 ?기간")
# 게시판 목록이 본문 뒤에 딸려 들어온 자리 — 여기를 넘어가면 '남의 공고 날짜'다.
# 군산시립교향악단 공고는 자기 접수기간이 "접수기간 : 2"에서 잘려 있어서, 윈도가
# 옆 목록의 '군산시가족센터 신규직원 26.07.28'까지 넘어가 그 날짜를 물었다 (2026-08-07).
_LIST_SEP = re.compile(r"\s\|\s|시험/채용|채용/시험|더보기|목록보기")


def _is_attach_name(text, pos):
    """"응시원서.hwp" 처럼 키워드 바로 뒤가 확장자면 첨부파일명이지 본문이 아니다."""
    return bool(re.match(r"\s*[_\-]?\s*\.(hwpx?|pdf|docx?|xlsx?|zip)", text[pos:pos + 8], re.I))

def priority_deadlines(text, ref_year=None):
    """확정 어휘(원서접수·접수기간·남은기간…) 윈도에서 찾은 마감일 후보 **전부**.

    지난 날짜를 근거로 공고를 내릴 때 쓴다. 후보가 여럿으로 갈리면 그 페이지엔 남의 공고
    목록이 섞였다는 뜻이므로(군산시립교향악단 상세에 시청 채용공고 목록이 통째로 딸려
    온다 — 2026-08-07), 개수를 감추지 않고 그대로 넘겨 호출부가 보류를 고르게 한다.
    """
    if not text:
        return []
    from datetime import date as _d
    ref_year = ref_year or _d.today().year
    text = re.sub(r"\s+", " ", text)
    out = []
    for kw in _KW_PRIORITY.finditer(text):
        if _is_attach_name(text, kw.end()):
            continue
        c = _window_deadline(_LIST_SEP.split(text[kw.start(): kw.start() + 300], 1)[0], ref_year)
        if c and c not in out:
            out.append(c)
    return sorted(out)


def extract_deadline(text, ref_year=None, priority_only=False):
    """본문에서 접수 마감일 추출 — '원서접수/접수기간' 윈도를 최우선으로

    priority_only=True 면 '원서접수·접수기간·남은기간' 같은 확정 어휘 윈도만 본다.
    지난 날짜를 근거로 공고를 **내릴 때** 쓰는 모드다 — 여기서의 오탐은 살아있는 공고를
    지우는 것이라, 리허설·공연일을 물 수 있는 폭넓은 폴백 키워드를 아예 끈다.
    """
    if not text:
        return None
    from datetime import date as _d
    ref_year = ref_year or _d.today().year
    text = re.sub(r"\s+", " ", text)
    def _is_filename(kw):
        # "응시원서.hwp" 같은 첨부파일명 매칭은 제외
        return bool(re.match(r"\s*[_\-]?\s*\.(hwpx?|pdf|docx?|xlsx?|zip)", text[kw.end():kw.end() + 8], re.I))

    for kw in _KW_PRIORITY.finditer(text):
        if _is_filename(kw):
            continue
        win = text[kw.start(): kw.start() + 300]
        if priority_only:
            win = _LIST_SEP.split(win, 1)[0]
        c = _window_deadline(win, ref_year)
        if c:
            return c
    if priority_only:
        return None
    best = None
    for kw in _KW_FALLBACK.finditer(text):
        if _is_filename(kw):
            continue
        c = _window_deadline(text[kw.start(): kw.start() + 300], ref_year)
        if c and (best is None or c > best):
            best = c
    return best

def deadline_from_title(title, ref_year=None):
    """제목 안의 마감 표기: '(~7.7)', '~2026.7.13', '7.7까지', '마감 7/13'"""
    from datetime import date as _d
    ref_year = ref_year or _d.today().year
    m = re.search(r"[~∼～]\s*(20\d{2})\s*[./년]\s*(\d{1,2})\s*[./월]?\s*(\d{1,2})", title)
    if m:
        return _mk(m.group(1), m.group(2), m.group(3))
    m = re.search(r"[~∼～]\s*(\d{1,2})\s*[./]\s*(\d{1,2})", title)
    if m:
        return _mk(ref_year, m.group(1), m.group(2))
    m = re.search(r"(?:마감|까지)[^\d]{0,4}(\d{1,2})\s*[./]\s*(\d{1,2})", title) \
        or re.search(r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*(?:까지|마감)", title)
    if m:
        return _mk(ref_year, m.group(1), m.group(2))
    return None

# 제외: 지원자에게만 해당하는 진행 공지 (심사일정·실기전형·악보·합격자 등)
# — 우리는 "언제까지 / 누구를 / 몇 명 뽑는지"가 담긴 모집 공고 자체만 수집한다
EXCLUDE = re.compile(
    r"합격자|합격 ?자|결과|최종 ?발표|선정|취소 ?공고|발표 및"
    r"|심사|실기 ?전형|서류 ?전형|면접|오디션 ?안내|오디션 ?일정"
    r"|악보|과제곡|지정곡|전형 ?일정|일정 ?안내|세부 ?안내|세부사항|응시표|수험표|대기실"
    r"|[1-3] ?차 ?(?:심사|전형|시험|발표|합격|서류|면접|실기|안내)"
    r"|워크숍|워크샵|수강생 ?모집"
    r"|대관 ?(?:모집|공고|안내)|레지던시|자원봉사|서포터즈|기자단|친인척|입주 ?작가"
    r"|관람 ?해설|사진 ?공모|미술관|박물관"
    # 대학 '입학' 공지(수시·정시·실기곡목)는 구인이 아니다 — 서울대 음대 수시모집 안내 유입 사고(2026-07-23).
    # '신입 단원 모집'과 헷갈리지 않게 입시 전용 어휘만 건다.
    r"|수시 ?모집|정시 ?모집|신[입편] ?학생|입학 ?(?:설명회|안내|요강|전형)|실기 ?곡목|모집 ?요강|편입학")
# 수집 대상 (모집/채용 의도 — 교회 게시판식 "구합니다/모십니다" 포함)
INCLUDE = re.compile(r"모집|채용|오디션|공개모집|공개채용|초빙|구합니다|구인|모십니다|찾습니다|임용 ?공고|위촉")

# 구인이 아닌 '프로그램 참가자·수강생·관람객' 모집 — 이런 건 사람을 '뽑는' 게 아니라
# '참여시키는' 것이라 구인구직판 대상이 아니다 (예: 음악창작소 투어 참여자 모집 = 학생 대상).
_PARTICIPANT = re.compile(
    r"참[여가]자\s*(?:모집|신청|선착|접수|모심)|참가\s*신청|참가팀|참여\s*학생"
    r"|스튜디오\s*투어|투어\s*참[여가]|체험\s*(?:단|참[여가]|프로그램|신청|학습|교실)|견학"
    r"|관람객|관객\s*모집|수강생|수강\s*신청|교육생\s*모집|아카데미\s*(?:생|수강)"
    r"|동아리원\s*모집|모니터(?:단|링)|평가단|명예\s*기자|해설사\s*양성|양성\s*과정"
    r"|영재\s*선발|학생\s*여러분|재능 ?있는 ?학생"
    # '○○ 아카데미 모집'은 일반인 수강생을 받는 교육사업이지 채용이 아니다
    # (국립합창단 합창 아카데미, 안산뮤직아카데미 — 2026-08-08).
    # 아래 _HIRE_ROLE 보호가 있어 '아카데미 강사 모집'은 그대로 남는다.
    r"|아카데미"
    r"|참가\s*단체"     # 영재교육원 '학생 선발'·합창제 '참가단체'는 구인이 아님
    # 사람이 아니라 '단체'를 부르는 공고 — 페스티벌에 나올 오케스트라·합창단을 모으는 것이라
    # 연주자 개인이 지원할 자리가 아니다 (2026-08-07 통영 '모두의 오케스트라 페스티벌 참가
    # 오케스트라 모집'). 흔한 유형은 아니지만 개인 공고와 섞이면 헛걸음을 만든다.
    r"|참가\s*(?:오케스트라|합창단|앙상블|밴드|팀)"
    r"|(?:오케스트라|합창단|앙상블|동호회|단체)\s*모집(?!\s*공고문)")
# 위 참가자 신호가 있어도 실제 '채용 직무'가 함께 있으면 구인이므로 보호(예: 체험단 강사 모집)
_HIRE_ROLE = re.compile(
    r"단원|강사|반주|지휘|교원|교수|연주자|악장|수석|성악가|객원|교습|레슨|트레이너"
    r"|사무국|직원|스태프|음악감독|코치|상근|위촉\s*(?:연주|단원)")

# 아동·청소년 '단원' 모집은 채용이 아니라 참여다 — 시립소년소녀합창단 지원서가 <소속> <학교
# 학년 반>을 적어 내게 돼 있다(2026-08-07 통영시립소년소녀합창단). '단원'이 _HIRE_ROLE 보호
# 어휘라 아래 참가자 규칙으로는 절대 안 걸려서 따로 둔다.
# 같은 단체의 지도자·지휘자·반주자 모집은 진짜 채용이므로 '단원'일 때만 건다.
_YOUTH_MEMBER = re.compile(
    r"(?:소년소녀|어린이|유소년|청소년|주니어|키즈)\s*"
    r"(?:합창단|오케스트라|국악단|무용단|관현악단|교향악단|앙상블)?[^,·\n]{0,6}?"
    r"(?:신규\s*|신입\s*)?단원\s*(?:모집|선발|모심)")


def participant_only(title):
    """참가자·수강생 모집인데 채용 직무가 없는가 — 최종 단계에서 다시 보기 위한 창구.

    relevant()는 수집 시점에만 돈다. 이미 실려 있던 공고는 승계로 들어와 그 관문을
    통과하지 않으므로, 제외 규칙을 새로 넣은 날 기존 분이 그대로 남는다.
    """
    t = title or ""
    return bool(_PARTICIPANT.search(t)) and not _HIRE_ROLE.search(t)


def youth_member(title):
    """아동·청소년 '단원' 모집인가 — 채용이 아니라 참여."""
    return bool(_YOUTH_MEMBER.search(title or ""))


def relevant(title):
    if youth_member(title):
        return False
    # 참가자/수강생 모집인데 채용 직무가 없으면 구인 아님 → 제외
    if _PARTICIPANT.search(title) and not _HIRE_ROLE.search(title):
        return False
    return bool(INCLUDE.search(title)) and not EXCLUDE.search(title)

def classify_kind(title):
    """교수(대학 전임/초빙) / 단원(상임) / 객원·대체(비상임·기간제) / 반주 / 강사 / 직원 / 기타
    — 연주자 모집이 행정직과 한 공고에 섞이면 연주자 쪽으로 분류"""
    # 대학 교원 초빙은 '객원단원'의 객원과 겹치지 않도록 먼저 판정
    if re.search(r"전임 ?교원|초빙 ?교원|겸임 ?교원|비전임 ?교원|산학 ?교원|객원 ?교원|초빙 ?교수"
                 r"|교수 ?(?:초빙|채용|공개채용|임용|모집)|교원 ?(?:초빙|채용|공개채용|신규 ?채용|임용)", title):
        return "교수"
    if re.search(r"객원|비상임|대체(?:근로|인력|연주)?|기간제.*단원|단원.*기간제", title):
        return "객원·대체"
    if re.search(r"사무단원|기획운영단원|사무국|행정|안내원|매니저|팀장|본부장|시설|미화|보안", title):
        return "직원"
    if re.search(r"반주자|반주 ?단원", title):
        return "반주"
    if re.search(r"강사|교습|레슨|트레이너|지도자", title):
        return "강사"
    # 지휘·솔리스트는 '단원'과 다른 자리다. 예전엔 '지휘자'가 단원 규칙 안에 있어
    # '성가대 지휘자 초빙'이 단원으로, '테너 솔리스트 모집'은 아무 데도 안 걸려
    # '기타'로 떨어졌다 (2026-08-02 잠실 성현교회 카드에서 발견).
    # 교회 3대 포지션(반주·지휘·솔리스트)은 포디엄의 비치헤드라 정확히 갈라야 한다.
    if re.search(r"지휘자|상임 ?지휘|객원 ?지휘|음악 ?감독|예술 ?감독", title):
        return "지휘"
    if re.search(r"솔리스트|솔로이스트", title):
        return "솔리스트"
    if re.search(r"단원|악장|수석|부수석|차석|연주자|오디션|성악가", title):
        return "단원"
    if re.search(r"직원|인턴|근로자|교육생", title):
        return "직원"
    return "기타"

# ---------- 음악인 대상 여부 (행정·홍보·시설 등 비음악 직군 차단) ----------
STAFF_EXCLUDE = re.compile(
    r"통합채용|본부장|사무국|사무직|사무단원|행정|홍보|안내원|매표|하우스|시설|미화|경비"
    r"|사서|무대 ?기술|조명|음향(?! ?감독)|공무직|기간제 ?근로자|경영지원|회계|전산|주차|보안|기획팀|마케팅"
    r"|용역|제안서|입찰|평가 ?위원|심의 ?위원|비엔날레|운송|업무직|물품|구매|납품|공사|단장 ?공개|단장 ?채용"
    r"|아역|아동 ?배우|어린이 ?배우|임원|이사장|대표이사|실·관장|리셉셔니스트|리셉션"
    # 창원 '기록자료 관리지원 — 사진영상 촬영관리 분야 채용'이 통과했다(2026-08-03).
    # 아카이빙·촬영 직군은 예술단 소속이라도 음악인 자리가 아니다.
    r"|촬영|기록자료|아카이브|아키비스트")
_MUSIC_KEEP = re.compile(r"악기|악보|조율|지휘|반주|연주|성악|합창|오케스트라|(?<![사무])단원|수석|악장|강사")
# 타 장르(무용·미술·연극 등) 공고 — '단원'만으로는 음악 공고로 인정하지 않음
# 공예·도예 추가(2026-08-03): 창원 '공예공간 기록 프로젝트 <산단사이 2기> 모집'이 통과했다
NONMUSIC_ART = re.compile(r"무용|발레|안무|댄스|연극|배우|미술|공예|도예|(?<!대)전시(?!립)|사진 ?(?:공모|작가)|문학|서예|디자인")
_MUSIC_STRONG = re.compile(
    r"악기|악보|조율|지휘|반주|성악|합창|오케스트라|콰르텟|앙상블|피아니스트|수석|악장"
    r"|바이올린|비올라|첼로|더블 ?베이스|플루트|오보에|클라리넷|바순|호른|트럼펫|트롬본|튜바|팀파니|타악|하프"
    r"|음악")   # 학교 공고는 '(음악, 미술)' 혼합 표기가 흔함 — 음악 명시면 타장르 혼재여도 수집

# 국악은 별도 사이트(풍류)로 분리 — 포디엄(서양 클래식)에서는 국악 공고 전면 제외
GUGAK_EXCLUDE = re.compile(
    r"국악|창극|판소리|가야금|거문고|아쟁|해금|대금|소금|단소|태평소|생황"
    r"|정가|시조창|사물놀이|풍물|농악|시나위|병창|고법|꽹과리|정악|산조|장구|장고")

# 포디엄 = 서양 클래식(성악·기악·지휘·작곡·이론) 전용. 실용음악(대중·재즈)·무용은 범위 밖 → 제외.
# 단, '무용 반주자'처럼 무용을 위해 연주하는 클래식 연주자(반주·피아노)는 음악인이므로 NONMUSIC_ART(약필터)로 별도 처리.
POP_EXCLUDE = re.compile(
    r"실용음악|실용 ?음악|생활음악|대중음악|재즈|힙합|밴드 ?(?:지도|강사|음악)|보컬 ?트레이"
    r"|싱어송라이터|K-?POP|작사|디제이|일렉트로닉|세션 ?(?:기타|드럼|베이스)|어쿠스틱 ?기타"
    # 악기로서의 '기타'(guitar)는 클래식기타라고 명시된 경우만 우리 범위다. 학교 방과후
    # '1인 1악기 기타 강사'는 통기타 수업이라 클래식 음악인 공고가 아니다 (2026-08-02 김포여중).
    # ※ '기타 사항·기타 문의'처럼 '그 외' 뜻으로 쓰인 말과 섞이지 않게 '강사/반/레슨'이
    #   바로 뒤에 붙은 형태만 건다. '클래식 기타'는 앞의 부정형 전방탐색으로 살려둔다.
    r"|(?<!클래식)(?<!클래식 )기타 ?(?:예술)?(?:강사|레슨|반\b)|\(기타\) ?강사|통기타")

# '(과학12, 즐생8, 음악2)' 같은 과목별 주당 시수 나열 — 학교 계약제·기간제 공고 특유의 표기
_HOUR_PAIR = re.compile(r"([가-힣]{1,6}?)\s*(\d{1,2})\s*(?=[,)、·/]|시간)")

def music_minor_in_hours(title):
    """과목별 시수를 나열한 학교 공고에서 음악이 곁다리인지 판정.

    '연천초 계약제교원 채용(과학12, 즐생8, 음악2)' — 본질은 과학 담당 초등교사 채용이고
    음악은 주 2시간 얹힌 것. 음악 시수가 다른 과목 최대 시수보다 적으면 음악인 공고가
    아니라고 본다 (2026-07-27 사용자 판정: 우리가 다룰 공고가 아님).
    음악만 있거나 음악이 주력이면 통과 — '음악 12시간' 단독 공고는 살아남는다."""
    pairs = _HOUR_PAIR.findall(title)
    if not pairs:
        return False
    music = [int(n) for s, n in pairs if re.search(r"음악|국악", s)]
    others = [int(n) for s, n in pairs if not re.search(r"음악|국악", s)]
    return bool(music) and bool(others) and max(others) > max(music)

def musician_relevant(title, kind, org=""):
    """음악인(연주·지휘·반주·강사)이 대상인 공고인지 — 행정직·스태프는 제외.
    기관명 속 '오케스트라/합창단'이 음악 키워드로 오인되지 않도록 기관명을 제거 후 판정.
    ※ 무용은 NONMUSIC_ART 약필터로 처리 — 순수 무용(무용수·안무가)은 빼되
      '무용단 반주자'처럼 클래식 연주 역할은 살린다(고객=클래식 음악인)."""
    if GUGAK_EXCLUDE.search(f"{title} {org}"):
        return False
    if music_minor_in_hours(title):     # 음악이 곁다리인 다과목 교사 채용
        return False
    if POP_EXCLUDE.search(f"{title} {org}"):   # 실용음악(대중·재즈 전공) 전면 제외
        return False
    # 참가자·학생 선발(구인 아님) — 승계 경로로 들어온 항목도 최종 필터에서 확실히 제거
    if _PARTICIPANT.search(title) and not _HIRE_ROLE.search(title):
        return False
    t = re.sub(r"사무 ?단원|기획운영단원|연수 ?단원", "", title)
    # 제목 속 단체명(국립·시립 ○○단, [괄호 접두어])은 음악 키워드 판정에서 제외
    t = re.sub(r"\[[^\]]{2,25}\]|[가-힣A-Za-z()]{0,12}(?:국립|시립|구립|도립)[가-힣]{0,8}단", "", t)
    if org:
        for token in re.split(r"[()\s·]", org):
            if len(token) >= 3:
                t = t.replace(token, "")
    if STAFF_EXCLUDE.search(title) and not _MUSIC_KEEP.search(t):
        return False
    if kind == "직원" and not _MUSIC_KEEP.search(t):
        return False
    # 무용·미술 등 타 장르 공고는 강한 음악 키워드가 있어야 통과
    # (단체명 제거 전 원제목으로 검사 — '시립무용단'이 단체명 제거에 지워지는 것 방지)
    if NONMUSIC_ART.search(title) and not _MUSIC_STRONG.search(title):
        return False
    return True

# (세부악기, 악기군) — 순서 중요: 더블베이스가 성악 베이스보다 먼저
INST_DETAILS = [
    ("더블베이스", "현악", r"더블 ?베이스|콘트라베이스"),
    ("바이올린", "현악", r"바이올린"),
    ("비올라", "현악", r"비올라"),
    ("첼로", "현악", r"첼로"),
    ("하프", "기타", r"하프"),
    ("플루트", "목관", r"플루트|피콜로"),
    ("오보에", "목관", r"오보에"),
    ("클라리넷", "목관", r"클라리넷"),
    ("바순", "목관", r"바순|파곳"),
    ("호른", "금관", r"호른"),
    ("트럼펫", "금관", r"트럼펫"),
    ("트롬본", "금관", r"트롬본"),
    ("튜바", "금관", r"튜바"),
    ("색소폰", "금관", r"색소폰|색스폰|saxophone"),
    ("타악", "타악", r"타악|팀파니|퍼커션"),
    ("피아노", "건반", r"피아노|오르간|건반|반주"),
    ("소프라노", "성악", r"소프라노"),
    ("메조소프라노", "성악", r"메조"),
    ("알토", "성악", r"알토"),
    ("테너", "성악", r"테너"),
    ("바리톤", "성악", r"바리톤"),
    ("베이스(성악)", "성악", r"베이스(?!기타)"),
    ("지휘", "지휘", r"지휘"),
]

# 파트를 군 단위로만 밝힌 공고도 태그가 붙어야 한다 — 군산시향은 '접수분야: 피아노,
# 현악부, 관악부, 타악부'인데 피아노·타악만 태그돼 현악·관악 지원자가 놓쳤다(2026-08-02).
# '관악'은 목관·금관을 아우르는 말이라 프론트에서 두 군 모두에 매치시킨다.
INST_GROUP_TERMS = [
    ("현악", "현악", r"현악(?:부|파트|군|기)?"),
    ("목관", "목관", r"목관(?:부|파트|군|기)?"),
    ("금관", "금관", r"금관(?:부|파트|군|기)?"),
    ("관악", "목관", r"관악(?:부|파트|군|기)?"),
]


def classify_insts(title):
    """제목에서 세부 악기 전부 추출 → (악기군, [세부악기...])"""
    t = re.sub(r"더블 ?베이스|콘트라베이스", "◆DBASS◆", title)
    details, groups = [], []
    for name, group, pat in INST_DETAILS:
        target = title if name == "더블베이스" else t
        if re.search(pat, target):
            details.append(name)
            if group not in groups:
                groups.append(group)
    for name, group, pat in INST_GROUP_TERMS:      # 군 단위 표기도 태그로
        if name not in details and re.search(pat, t):
            details.append(name)
            if group not in groups:
                groups.append(group)
    if not details:
        if re.search(r"현악", title): return "현악", []
        if re.search(r"목관|관악", title): return "목관", []
        if re.search(r"금관", title): return "금관", []
        if re.search(r"성악|합창", title): return "성악", []
        return "전체", []
    return groups[0], details

# 첨부 공고문 안의 '모집 분야' 구획 머리말 — 이 뒤 몇 줄에 파트표가 온다.
# 본문 전체를 훑으면 오디션 곡목("모차르트 바이올린 협주곡")·시설 안내("피아노 비치") 같은
# 잡음까지 악기로 오인하므로, 구획을 찾았을 때만 그 창(window) 안에서 추출한다.
# 구획이 없으면 추측하지 않는다 — '미분류는 미분류로' 원칙과 같은 논리.
_RECRUIT_HDR = re.compile(
    r"(?:모집|채용|접수|초빙|위촉|응시|지원)\s*(?:분야|부문|파트|과목|직종)"
    r"|파트\s*별|분야\s*별|모집\s*인원|채용\s*인원|(?:분야|파트)\s*및\s*인원")
_RECRUIT_WINDOW = 700


def insts_from_recruit_text(text):
    """본문·첨부 텍스트의 모집분야 구획에서 악기 추출 → (악기군, [세부악기...]).

    제목엔 '예능단원 공개채용'뿐이고 파트가 첨부 공고표에만 있는 공고(대전시향 등)가
    악기 미상의 최대 원인이었다(2026-08-02, 보강대상 163건 중 161건이 첨부에만 존재).
    """
    if not text:
        return "", []
    details, groups = [], []
    for m in _RECRUIT_HDR.finditer(text[:20_000]):
        g, d = classify_insts(text[m.start():m.start() + _RECRUIT_WINDOW])
        for x in d:
            if x not in details:
                details.append(x)
        if d and g not in groups:
            groups.append(g)
    return (groups[0] if groups else ""), details

# ---------- 연령 (지원자 기준): 성인 / 미성년 ----------
# 미성년 = '지원하는 사람 자체가 미성년'인 공고 (소년소녀합창단·유스오케 단원 모집 등).
# 청소년단체라도 지휘자·강사·반주 등 성인이 지원하는 자리는 성인.
_YOUTH_TARGET = re.compile(r"소년소녀|청소년|유스|youth|유소년|아동|어린이|주니어|키즈|초등부|중등부")
_ADULT_ROLE = re.compile(r"지휘|강사|교사|교수|반주자|트레이너|코치|스태프|사무|행정|감독|매니저"
                         r"|악장|수석|차석|부수석|튜티|직원|인턴|근로자|안내|보조|상근|위촉")

def age_group(title, org=""):
    """지원자 연령 구분 — 미성년 본인이 지원하는 단원모집만 '미성년', 나머지 '성인'."""
    t = f"{title} {org}"
    if _YOUTH_TARGET.search(t) and not _ADULT_ROLE.search(t):
        return "미성년"
    return "성인"

# ---------- 등급: 단일 축 '연주냐 가르치냐, 가르치면 누구를' (지시서 3-1 우선순위) ----------
#   연주            = 가서 연주하고 오는 일 (단원·객원·반주·세션·지휘·음악감독 + 오브리)
#   교육 — 대학      = 음대생·전공생을 가르침 (교수·시간강사·겸임·초빙 + 대학)
#   교육 — 입시·전공  = 예중·예고생·입시생을 가르침 (실기강사·입시레슨·콩쿠르지도)
#   교육 — 취미·입문  = 일반인·아동을 가르침 (학원·문화센터·방과후·복지관·꿈의오케·초중고 기간제/방과후)
#   미분류          = 어디에도 안 걸림 → 추측 금지, 사람 확인 큐
# 대학 교원 역할 — 대학(_EDU_UNIV_PLACE)과 함께면 '교육 — 대학'. 대학 공고는 보통 '강사'로만 표기됨.
_EDU_UNIV = re.compile(r"교수|전임 ?교원|시간 ?강사|겸임 ?교원|초빙 ?교원|조교수|부교수|비전임 ?교원|산학 ?교원|초빙 ?교수|강사|교원|초빙")
_EDU_UNIV_PLACE = re.compile(r"대학교|대학원|음악대학|음대(?!\w)|대학\b")
_EDU_IPSI = re.compile(r"예중|예고|예술 ?중|예술 ?고|음악 ?중점|입시|콩쿠르 ?지도|실기 ?지도|입시 ?레슨|예술 ?영재")
_EDU_HOBBY = re.compile(
    r"학원|아카데미|문화 ?센터|방과 ?후|방과후학교|늘봄|복지관|꿈의 ?오케|꿈의오케스트라|평생 ?교육|기간제|계약제 ?교[원사]"
    r"|오케스트라 ?강사|예술 ?강사|협력강사|1 ?인 ?1 ?악기|주민 ?센터|음악 ?교실"
    r"|초등학교|중학교|고등학교|특수학교|유치원|어린이집|정교사|기간제교사|기간제교원"
    r"|\d ?학년|악기뱅크|울림프로젝트"
    # 초등돌봄교실 특기적성(창의음악 등)도 학교 취미·입문 수업이다 — 없으면 미분류로 샌다
    r"|돌봄 ?교실|특기 ?적성")   # '6학년 우쿨렐레 강사' 등 학년 표기 학교 공고
_PLAY = re.compile(
    r"단원|오디션|객원|대타|대체 ?(?:연주|인력)?|반주자|세션|지휘자|음악 ?감독"
    r"|연주자 ?(?:모집|채용)|수석|악장|솔리스트|성악가")
# 오브리(교회·웨딩·행사) — 별도 태그 아님. 연주로 분류하되 하위 필터로 노출.
_OBRI = re.compile(r"교회|성당|예배|성가대|찬양|주일|전례|미사|웨딩|결혼식|예식|부활절|성탄절|추수감사|특송|축가|행사 ?연주|기업 ?행사")
_OBRI_PLAY = re.compile(r"반주|연주|성가|찬양|지휘|솔리스트|성악|테너|베이스|바리톤|소프라노|메조|알토|피아노|오르간|첼로|바이올린")

def is_obri(title, org=""):
    """오브리(교회·웨딩·행사 연주) 여부 — 연주 태그의 하위 필터용."""
    return bool(_OBRI.search(f"{title} {org}"))

def classify_tier(title, org=""):
    """연주 / 교육 — 대학 / 교육 — 입시·전공 / 교육 — 취미·입문 / 미분류.
    지시서 3-1 우선순위: 대학교원 → 입시·전공 → 취미·입문 → 연주 → 오브리연주 → 미분류.
    교육 신호를 연주보다 먼저 봐서 '오케스트라 강사(초등)'=교육, '오케스트라 객원'=연주로 갈린다."""
    t = f"{title} {org}"
    # 예중·예고가 함께 보이면(대학 부설 예고 등) 입시·전공이 우선 — 대학 규칙에서 먼저 배제
    if _EDU_UNIV.search(t) and _EDU_UNIV_PLACE.search(t) and not _EDU_IPSI.search(t):
        return "교육 — 대학"
    if _EDU_IPSI.search(t):
        return "교육 — 입시·전공"
    if _EDU_HOBBY.search(t):
        return "교육 — 취미·입문"
    if _PLAY.search(t):
        return "연주"
    if _OBRI.search(t) and _OBRI_PLAY.search(t):     # 교회·행사 + 연주 성격
        return "연주"
    return "미분류"                                   # 추측 금지 — 사람 확인 큐

# ---------- 자격요건 필드 (태그가 아니라 필터 가능한 필드) ----------
# 사실: 대학교수·시간강사=교원자격증 불필요 / 초중고 정교사·임용=필요 / 방과후·예술강사=대체로 불필요.
_CERT_YES = re.compile(r"정교사|교원 ?자격|교사 ?자격|교직 ?이수|임용|기간제 ?교[사원]|계약제 ?교[사원]|중등 ?교사|초등 ?교사|담임")
_CERT_NO_ROLE = re.compile(r"방과 ?후|예술 ?강사|협력강사|늘봄|1 ?인 ?1 ?악기|꿈의 ?오케|학원|문화 ?센터|레슨|아카데미")

def cert_required(tier, title, text=""):
    """교원자격증(정교사) 필요 여부: 예 / 아니오 / 무관. 확실치 않으면 무관."""
    blob = f"{title} {text}"
    if _CERT_YES.search(blob) and not _CERT_NO_ROLE.search(blob):
        return "예"
    if tier == "교육 — 대학":
        return "아니오"          # 대학 교원 = 교원자격증 불필요(사실)
    if tier == "연주":
        return "무관"            # 연주직은 교직과 무관
    if _CERT_NO_ROLE.search(blob):
        return "아니오"          # 방과후·예술강사·학원·레슨 = 대체로 불필요
    return "무관"

def degree_req(text):
    """학위 요건: 박사 / 석사 / 학사 / 무관 (본문에서 가장 높은 요건)."""
    if not text:
        return "무관"
    if "박사" in text:
        return "박사"
    if "석사" in text:
        return "석사"
    if re.search(r"학사|대졸|4년제|학위 ?소지", text):
        return "학사"
    return "무관"

# 경력 요건: 무관 / 필요 / 미기재 (숫자 대신 3값). '경력 우대'는 지원 문턱이 없으므로 무관으로 본다.
_CAREER_NONE = re.compile(r"경력 ?무관|경력 ?관계 ?없|경력 ?불문|신입 ?가능|무경력 ?가능|경력 ?우대")
_CAREER_REQ = re.compile(r"경력 ?\d+ ?년 ?이상|경력자에 ?한|경력 ?필수|경력 ?필요|유경험자|재직 ?\d+ ?년|\d+ ?년 ?이상 ?경력")

def career_req(text):
    """경력 요건: 무관 / 필요 / 미기재. 명시 없으면 미기재."""
    if not text:
        return "미기재"
    if _CAREER_NONE.search(text):
        return "무관"
    if _CAREER_REQ.search(text):
        return "필요"
    return "미기재"

# 텍스트에서 시도 단위 지역 추출 (집계 노드용)
# 전국 17개 시도 정규화 — 시도 정식명·약칭 + 주요 도시를 소재 시도로 매핑.
# (구체적인 도시/정식명을 먼저 두어 약칭보다 우선 매칭)
# 2026-07-01 전남광주통합특별시 출범 — 전라남도·광주광역시 폐지되고 단일 광역단체가 됐다(약칭 광주특별시).
# 검색하는 쪽은 여전히 '광주' 또는 '전남'으로 떠올리므로 한 칸에 둘 다 보이게 '광주·전남'으로 표기한다.
GWANGJU_JEONNAM = "광주·전남"
REGION_ORDER = ["서울", "경기", "인천", "강원", "대전", "세종", "충북", "충남",
                "대구", "경북", "부산", "울산", "경남", GWANGJU_JEONNAM, "전북", "제주"]
# 옛 수집분(region이 '광주'/'전남')을 새 표기로 옮긴다 — 프론트도 같은 표를 쓴다.
REGION_MIGRATE = {"광주": GWANGJU_JEONNAM, "전남": GWANGJU_JEONNAM}
_REGION_TOKENS = [
    # 광역시·특별시
    ("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"),
    ("대전", "대전"), ("울산", "울산"), ("세종", "세종"),
    ("전남광주", GWANGJU_JEONNAM), ("광주광역", GWANGJU_JEONNAM), ("광주특별", GWANGJU_JEONNAM),
    # 경기 광주시 — 아래 맨 끝의 맨 '광주'에 먹히지 않도록 반드시 먼저 본다.
    # 시도명이 떨어져 있는 경우가 많아('광주시 ○○센터 곤지암') 경기 광주시에만 있는 읍면도 함께 본다.
    ("경기 광주", "경기"), ("경기도 광주", "경기"), ("경기광주", "경기"),
    ("곤지암", "경기"), ("오포", "경기"), ("초월읍", "경기"), ("퇴촌", "경기"), ("도척", "경기"),
    # 경기
    ("경기", "경기"), ("수원", "경기"), ("성남", "경기"), ("용인", "경기"),
    ("고양", "경기"), ("부천", "경기"), ("안산", "경기"), ("안양", "경기"),
    ("남양주", "경기"), ("화성", "경기"), ("평택", "경기"), ("의정부", "경기"),
    ("시흥", "경기"), ("파주", "경기"), ("김포", "경기"), ("광명", "경기"),
    ("군포", "경기"), ("하남", "경기"), ("오산", "경기"), ("양주", "경기"),
    ("구리", "경기"), ("안성", "경기"), ("포천", "경기"), ("의왕", "경기"),
    ("여주", "경기"), ("과천", "경기"), ("이천", "경기"),
    # 강원
    ("강원", "강원"), ("원주", "강원"), ("춘천", "강원"), ("강릉", "강원"),
    ("속초", "강원"), ("동해", "강원"), ("삼척", "강원"), ("태백", "강원"),
    # 충북
    ("충청북", "충북"), ("충북", "충북"), ("청주", "충북"), ("충주", "충북"),
    ("제천", "충북"),
    # 충남
    ("충청남", "충남"), ("충남", "충남"), ("천안", "충남"), ("아산", "충남"),
    ("서산", "충남"), ("당진", "충남"), ("공주", "충남"), ("논산", "충남"),
    ("보령", "충남"),
    # 경북
    ("경상북", "경북"), ("경북", "경북"), ("포항", "경북"), ("구미", "경북"),
    ("경주", "경북"), ("안동", "경북"), ("김천", "경북"), ("영주", "경북"),
    ("상주", "경북"), ("문경", "경북"),
    # 경남
    ("경상남", "경남"), ("경남", "경남"), ("창원", "경남"), ("마산", "경남"),
    ("진주", "경남"), ("김해", "경남"), ("양산", "경남"), ("통영", "경남"),
    ("거제", "경남"), ("사천", "경남"), ("밀양", "경남"),
    # 전북
    ("전라북", "전북"), ("전북", "전북"), ("전주", "전북"), ("익산", "전북"),
    ("군산", "전북"), ("정읍", "전북"), ("김제", "전북"), ("남원", "전북"),
    # 전남 (통합특별시 편입 — 표기는 광주·전남)
    ("전라남", GWANGJU_JEONNAM), ("전남", GWANGJU_JEONNAM), ("목포", GWANGJU_JEONNAM),
    ("여수", GWANGJU_JEONNAM), ("순천", GWANGJU_JEONNAM), ("광양", GWANGJU_JEONNAM),
    ("나주", GWANGJU_JEONNAM), ("담양", GWANGJU_JEONNAM), ("강진", GWANGJU_JEONNAM),
    # 제주
    ("제주", "제주"), ("서귀포", "제주"),
    # 맨 '광주' — 위에서 '경기 광주'를 먼저 걸렀으므로 여기 오면 통합특별시 쪽이다
    ("광주", GWANGJU_JEONNAM),
]

# '세종문화회관'(서울)·'세종대'(서울)·'세종로' 등이 세종시로 오분류되지 않게 제거 후 매칭
_SEJONG_FALSE = re.compile(r"세종문화|세종대학|세종캠퍼스|세종로|세종연구|세종교향|세종체임버|세종솔로이스츠")

def region_from(text, default="기타"):
    t = _SEJONG_FALSE.sub("", text or "")
    for token, region in _REGION_TOKENS:
        if token in t:
            return region
    return default

def item_id(url, title):
    return hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:16]

# 제목에서 모집 인원 추출 ("바이올린 객원 2명" → "객원 2명", "단원 1명" → "단원 1명")
PERSONNEL_PAT = re.compile(r"(?:([가-힣A-Za-z]{1,10})\s*)?(\d+)\s*명")

def extract_personnel(title):
    m = PERSONNEL_PAT.search(title)
    if not m:
        return None
    prefix = (m.group(1) or "").strip()
    return f"{prefix} {m.group(2)}명" if prefix else f"{m.group(2)}명"

# ---------- 직책(포지션) 체계 ----------
# 우선순위 높은 것부터 (긴 것 먼저 매칭)
POSITION_LIST = ["종신수석", "부악장", "악장", "수석대우", "부수석", "차석", "수석",
                 "상임지휘자", "부지휘자", "지휘자", "악장대우", "반주자", "단원", "튜티"]
POSITION_PAT = re.compile("|".join(POSITION_LIST))

def find_position(text):
    m = POSITION_PAT.search(text or "")
    return m.group(0) if m else None

# ---------- 대학 교수 초빙: 전공/과목 추출 ----------
# 악기(INST_DETAILS)로 못 잡히는 학과·전공 계열
_ACAD_SUBJECTS = ["작곡", "음악학", "지휘", "성악", "기악", "관현악", "피아노", "오르간",
                  "음악교육", "교회음악", "실용음악", "재즈", "뮤지컬", "이론", "반주", "음악치료"]

def find_subject(text):
    """대학 교원 초빙 제목/본문에서 '어떤 전공의 교수인지' 추출.
    악기가 명시되면 악기(가장 구체적), 없으면 '○○과/전공' 학과명, 그다음 계열어."""
    if not text:
        return None
    # 1) 세부 악기 (바이올린·플루트 등) — 가장 구체적
    _, insts = classify_insts(text)
    if insts:
        return " · ".join(insts)
    # 2) "○○과(…)" / "○○ 전공" + 교원/교수 인접
    m = re.search(r"([가-힣]{2,8})(?:과|학과|전공)\s*(?:\(([^)]{1,20})\))?\s*"
                  r"(?:분야\s*)?(?:전임|초빙|겸임|비전임|객원|산학)?\s*교[원수]", text)
    if m and 2 <= len(m.group(1)) <= 8:
        return f"{m.group(1)}({m.group(2)})" if m.group(2) else m.group(1)
    # 3) 계열 키워드
    for w in _ACAD_SUBJECTS:
        if w in text:
            return w
    return None

# ---------- 대학 '전체 강사 초빙'의 채용 교과목표에서 음악 전공만 골라내기 ----------
# 대학이 전 학과 강사를 한 공고로 내면 hibrain 음악학 카테고리에도 뜬다. 세부 전공은
# 첨부(HWP/XLSX)의 교과목표에만 있어, 여기서 '음악 관련 전공/학과'만 추려 subject로 쓴다.
# 반환이 None이고 첨부 본문이 충실했다면 → 그 대학엔 음악 교과목이 없음(비음악 확정).
# 음악 '학과/전공'만 정밀 추출 — 전화번호·긴 설명셀에 섞여 있어도 학과명만 깔끔히 집는다.
# '별 음악회' 같은 행사명(…회)은 학과 접미사가 아니라 매칭 안 됨 → 비음악으로 올바르게 판정.
# 실용음악·국악은 포디엄(서양 클래식) 범위 밖 — 전공/교과목 추출에서도 제외(→ 해당만 있으면 비음악 처리).
_MUSIC_DEPT = re.compile(
    r"[가-힣]{0,5}(?:음악|성악|기악|작곡|관현악|교회음악|음악학|음악교육|피아노)"
    r"[가-힣]{0,6}(?:학과|전공|학부|계열|과)")
# 학과명에 음악어가 없어도 음악을 확정지을 수 있는 전용 교과목/실기
_MUSIC_COURSE = re.compile(r"대위법|화성법|시창|청음|음악사|작곡법|지휘법|반주법|성악실기|기악실기")
# 실용음악·국악 계열은 서양 클래식 밖 → 전공/교과목으로 인정하지 않음(해당만 있으면 비음악)
_NONCLASSIC_SUBJ = re.compile(r"실용|대중음악|생활음악|재즈|국악|전통음악|판소리")

def find_music_subjects(text, max_n=6):
    """첨부 교과목표에서 음악 '학과/전공'을 정밀 추출(전화번호·잡음 제거).
    학과명이 없어도 음악 전용 교과목이 있으면 그것으로 대체. 음악이 전혀 없으면 None."""
    if not text:
        return None
    depts = []
    for m in _MUSIC_DEPT.finditer(text):
        t = m.group(0).strip()
        if _NONCLASSIC_SUBJ.search(t):     # 실용음악과·국악과 등 제외
            continue
        if 3 <= len(t) <= 16 and t not in depts:
            depts.append(t)
    if depts:
        return depts[:max_n]
    courses = list(dict.fromkeys(_MUSIC_COURSE.findall(text)))
    return courses[:max_n] if courses else None

# 담당 교과목명 추출 — 전공(학과)이 아니라 '무엇을 가르치는지'를 패널에 구체적으로 보여주기 위함.
_COURSE_SIG = re.compile(
    r"음악|성악|합창|관현악|기악|피아노|바이올린|비올라|첼로|더블베이스|콘트라베이스|플룻|플루트|오보에"
    r"|클라리넷|바순|호른|트럼펫|트롬본|튜바|색소폰|타악|팀파니|하프|오르간|작곡|대위법|화성법|시창|청음"
    r"|음악사|지휘|반주|국악|실용음악|앙상블|중주|실기|악기론|음악이론|음악교육론")

_COURSE_EVENT = re.compile(r"음악회|연주회|발표회|축제|콘서트|페스티벌|공연")
_INSTR_SILGI = re.compile(
    r"(?:바이올린|비올라|첼로|더블베이스|콘트라베이스|플룻|플루트|오보에|클라리넷|바순|호른|트럼펫|트롬본"
    r"|튜바|색소폰|타악|팀파니|하프|오르간|피아노|성악|기악)(?:실기|전공실기)")
_KNOWN_COURSE = re.compile(r"대위법|화성법|시창청음|시창|청음|음악사|작곡법|지휘법|반주법|음악교육론|음악이론|악기론|합창지휘")
_BARE_INSTR = re.compile(
    r"^(?:바이올린|비올라|첼로|더블베이스|콘트라베이스|플루트|플룻|오보에|클라리넷|바순|호른|트럼펫|트롬본"
    r"|튜바|색소폰|타악|팀파니|하프|오르간|피아노|성악|작곡|지휘|국악|반주)$")
_COURSE_STOP = re.compile(
    r"학위|이상|우수|경력|시행|평가|면접|실험|실습|서류|접수|지원|자격|규정|계획|현황|기준|명단|첨부"
    r"|참조|변경|사정|우대|담당|인원|박사|석사|년제|해당|점수|비고|기타|증빙|제출|모집|채용|공고")

def find_music_courses(text, max_n=5):
    """첨부 교과목표에서 '음악 담당 교과목명'을 정제해 리스트로 반환(학과명·전화·코드·행사명 제외)."""
    if not text:
        return None
    out, seen = [], set()
    def add(c):
        c = c.strip()
        if len(c) >= 2 and c not in seen and not _COURSE_EVENT.search(c):
            seen.add(c)
            out.append(c)
    # 1) 악기실기 + 알려진 이론 교과목은 긴 설명 셀에 묻혀 있어도 직접 추출
    for m in _INSTR_SILGI.findall(text):
        add(m)
    for m in _KNOWN_COURSE.findall(text):
        add(m)
    # 2) 독립 셀의 음악 과목명 (순천대 '음악으로 세상 읽기' 등) — 자격·절차·코드 문구는 배제
    for c in re.split(r"[|\n\t;,/]+", text):
        c = re.sub(r"\s+", " ", c).strip(" ·-—[]．.")
        c = re.sub(r"\s*\((?:[A-Za-z]{1,3}|성악|기악)\)\s*$", "", c)   # 끝의 악기코드 (FI)
        if _BARE_INSTR.match(c):        # 단독 악기명(플루트·비올라 등)은 짧아도 유효
            add(c)
            continue
        if not (4 <= len(c) <= 18) or not _COURSE_SIG.search(c):
            continue
        if _COURSE_STOP.search(c) or c.count("(") != c.count(")"):   # 자격·절차 문구 / 잘린 괄호
            continue
        if re.search(r"[A-Za-z]{2,}\s?\d|\d{2,}[-)]\d|@", c):   # 과목코드·전화·이메일
            continue
        if re.search(r"(전공|학과|학부|계열|과)$", c):     # 학과명은 subject가 담당
            continue
        c = re.sub(r"\s*[0-9Ⅰ-Ⅹ]+\s*$", "", c).strip()  # 끝 번호/로마자
        if len(c) >= 4:      # 정제 후 3자 조각(원음악·교음악)은 배제, 온전한 명칭만
            add(c)
    return out[:max_n] if out else None

# ---------- 채용부문/직책/인원 표 파싱 ----------
_HDR_PART = ["채용부문", "모집부문", "모집분야", "선발부문", "모집파트", "부문", "파트"]
_HDR_POS = ["직책", "직급", "구분", "포지션"]
_HDR_NUM = ["인원", "명"]

def _hcol(headers, names):
    for idx, h in enumerate(headers):
        if any(n in h for n in names):
            return idx
    return None

def parse_recruit_table(soup):
    """채용부문/직책/인원 HTML 표 → [{part, position, count}] (없으면 None)"""
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        htxt = " ".join(headers)
        if not any(k in htxt for k in _HDR_PART):
            continue
        ci_part = _hcol(headers, _HDR_PART)
        ci_pos = _hcol(headers, _HDR_POS)
        ci_num = _hcol(headers, _HDR_NUM)
        if ci_part is None:
            continue
        out = []
        for tr in rows[1:]:
            cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
            if len(cells) <= ci_part:
                continue
            part = cells[ci_part].strip()
            if not part or len(part) > 24 or any(k in part for k in _HDR_PART):
                continue
            pos = cells[ci_pos].strip() if ci_pos is not None and ci_pos < len(cells) else ""
            # 직책 칸에 값이 없으면 부문 칸에서 직책 단어 탐색
            if not pos or not POSITION_PAT.search(pos):
                pos = find_position(pos) or find_position(part) or pos
            num = cells[ci_num] if ci_num is not None and ci_num < len(cells) else ""
            nm = re.search(r"\d+", num)
            out.append({"part": part, "position": pos or "", "count": nm.group(0) if nm else ""})
        if out:
            return out
    return None

def summarize_recruit(parts):
    """recruitParts → (요약문자열, 직책set, 총인원). 예: '비올라 부수석 1 · 타악기 수석 1'"""
    if not parts:
        return None, None, None
    segs, positions, total = [], [], 0
    for p in parts:
        seg = p["part"]
        if p.get("position"):
            seg += f" {p['position']}"
            positions.append(p["position"])
        if p.get("count"):
            seg += f" {p['count']}명"
            try:
                total += int(p["count"])
            except ValueError:
                pass
        segs.append(seg)
    uniq_pos = list(dict.fromkeys(positions))
    return " · ".join(segs), uniq_pos, (total or None)

# ---------- 다과목 공고 제목 정리: 음악 외 과목명만 제거 ----------
# 한 공고가 영어·미술·음악 등 여러 과목 강사를 함께 뽑을 때, 제목엔 '음악'만 남긴다(타 과목명 노출 방지).
# ★★★ 악기 종류(바이올린·칼림바·우쿨렐레·플루트 등)는 절대 지우지 않는다 — 반드시 표기돼야 함(사용자 강조). ★★★
# (_OTHER_SUBJECT 목록에 악기명은 넣지 말 것. 앞뒤 한글 경계로 부분매칭 방지: '외국어'의 '국어' 오제거 방지)
_OTHER_SUBJECT = re.compile(
    r"(?<![가-힣])(?:영어|수학|국어|일반사회|사회|과학|생명과학|생물|지구과학|지학|물리|화학|한국사|국사|세계사|역사|지리|도덕|윤리|한문|중국어|일본어|스페인어|프랑스어|독일어|베트남어"
    r"|상업|공업|농업|수산|가사|회계|무역|관광|조경|토목|건축|전기|전자|기계|자동차|미용|이용|축산"
    r"|정보|컴퓨터|코딩|소프트웨어|로봇|드론|바둑|장기|체스|주산|한자|속독|논술|독서|글쓰기|웅변|스피치|토론|리더십"
    r"|미술|서예|캘리그라피|공예|도예|만들기|그리기|웹툰|애니메이션|카툰|디자인|사진|영상|미디어"
    r"|체육|축구|농구|배구|야구|탁구|배드민턴|테니스|줄넘기|태권도|검도|유도|합기도|스포츠|요가|필라테스|수영"
    r"|무용|댄스|발레|치어리딩|방송댄스|스트릿댄스"
    r"|조리|요리|제빵|베이킹|바리스타|플로리스트|원예|텃밭|보드게임|마술|연극|연기|진로|상담|심리|과학실험|생태|환경|숲해설"
    r"|실과|기술가정|가정|기술|보건|간호|유아|특수교육|특수"
    # 초등 통합교과(즐거운생활 등) — '(과학12, 즐생8, 음악2)'식 시수 표기에서 등장
    r"|즐거운 ?생활|즐생|바른 ?생활|슬기로운 ?생활|통합교과)(?![가-힣])")
# 과목명에 주당 시수가 붙은 표기('과학12') — 과목만 지우면 숫자가 고아로 남는다
_OTHER_SUBJECT_H = re.compile(r"(?:" + _OTHER_SUBJECT.pattern + r")\s*\d{0,2}")

def music_only_title(title):
    """다과목 나열 공고에서 음악 외 과목명 제거. 음악 신호가 없으면 원본 유지(악기명은 항상 보존)."""
    if not title or not _MUSIC_STRONG.search(title):
        return title
    t = _OTHER_SUBJECT_H.sub("", title)   # 과목명+붙은 시수를 함께 제거 ('과학12'→'', '12' 고아 방지)
    if t == title:
        return title
    t = re.sub(r"\s*-\s*(?=[,)、·/])", "", t)              # 과목 제거 후 남은 고아 대시 ('초등-,')
    t = re.sub(r"(?:\s*[,·/、]\s*){2,}", ", ", t)          # 연속 구분자 → 하나로
    t = re.sub(r"[(\[（]\s*(?:[,·/、]\s*)+", lambda m: m.group(0)[0], t)   # 여는 괄호 뒤 구분자
    t = re.sub(r"(?:[,·/、]\s*)+\s*([)\]）])", r"\1", t)     # 닫는 괄호 앞 구분자
    t = re.sub(r"[(\[（]\s*[)\]）]", "", t)                  # 빈 괄호 제거
    t = re.sub(r"^[\s,·/、]+|[\s,·/、]+$", "", re.sub(r"\s{2,}", " ", t))
    return t.strip() or title

def compact_title(title):
    """행정 상투구를 걷어내 제목을 카드에 맞게 압축. 악기명·기관명 등 알맹이는 건드리지 않는다.

    앞머리: '2026학년도 (제2학기)', '제2026-15호', '붙임' 같은 접두 상투구
    꼬리: '… 공고(문)', '… - 2026. 7. 8. 자'(KBS식 게시일 꼬리)
    결과가 너무 짧아지면(6자 미만) 원본 유지 — 과잉 절단 방지."""
    t = title
    t = re.sub(r"^\s*\[?(?:NEW|새글|N|오늘 ?마감|마감 ?임박|D-\d+)\]?\s+", "", t)   # 게시판 배지가 제목에 섞여온 경우 (세종교육청 새글, 경기 '오늘마감')
    t = re.sub(r"^\s*(?:붙임\s*)?제?\s*20\d{2}\s*[-–]\s*\d+\s*호\s*", "", t)      # 공고번호
    t = re.sub(r"^\s*(?:붙임\s*)?20\d{2}(?:\s*[~·\-]\s*20\d{2})?\s*학?년도?\s*(?:제?\s*[12]\s*학기\s*)?", "", t)
    t = re.sub(r"\s*[-–]\s*20\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?\s*자?\s*$", "", t)
    t = re.sub(r"\s*(?:새글|NEW)\s*$", "", t)               # 꼬리에 붙은 게시판 새글 배지 (부산교육청)
    t = re.sub(r"\s*(?:재공고|공고문|공고)\s*$", "", t)      # '채용 공고'→'채용' (의미 유지)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–·,")
    return t if len(t) >= 6 else title

def make_item(org, region, source, title, url, date=None, deadline=None):
    group, details = classify_insts(title)   # 악기는 원제목에서 추출(정리 전) — 악기 정보 보존
    # 음악 곁다리 판정은 반드시 '정리 전' 원제목으로 — 정리기가 타과목 시수(과학12·즐생8)를
    # 지워버리면 '(음악2)'만 남아 판정 근거가 사라진다 (2026-07-27 연천초 2차 생존 사고)
    non_music = music_minor_in_hours(title)
    clean = compact_title(music_only_title(re.sub(r"\s+", " ", title).strip()))
    kind = classify_kind(title)
    # 지역 정규화: 소스가 '기타'로 넘긴 경우 기관명·제목에서 시도를 유도
    # (교육청·generic·집계 소스가 지역을 안 채워도 전국 17개 시도로 분류되도록)
    if region in (None, "", "기타"):
        region = region_from(f"{org} {clean}")
    # 세션ID가 박힌 링크는 만료·비이식성 → 제거 (새올·JSP 게시판 대응)
    url = re.sub(r";jsessionid=[^?&#]*", "", url, flags=re.I)
    return {
        "id": item_id(url, title),
        "org": org, "region": region, "source": source,
        "title": clean,
        "nonMusic": non_music or None,   # 음악 곁다리(타과목 주력) — 수집 루프가 걸러냄
        "url": url,
        "date": date,          # 게시일 (모르면 None)
        "deadline": deadline,  # 접수 마감 (모르면 None)
        "kind": kind,
        "tier": classify_tier(clean, org),
        "obri": is_obri(clean, org),         # 오브리(교회·행사) — 연주 태그의 하위 필터
        "certReq": cert_required(classify_tier(clean, org), clean),   # 교원자격증: 예/아니오/무관
        "degreeReq": degree_req(clean),      # 학위 요건 (본문 보강은 main.enrich)
        "careerReq": career_req(clean),      # 경력: 무관/필요/미기재
        "ageGroup": age_group(clean, org),   # 지원자 연령 (필터 별도축)
        "inst": group,
        "instDetails": details,  # 세부 악기 (복수 가능: "비올라, 오보에")
        "personnel": extract_personnel(clean),  # 모집 인원 (제목에서, 없으면 None)
        # 대학 교수 초빙: 제목에서 전공/과목 (본문에서 보강은 main.enrich)
        "subject": find_subject(clean) if kind == "교수" else None,
    }
