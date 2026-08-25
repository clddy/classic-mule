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
    HTTP 상태코드는 대체로 호출부가 판단한다 — **다만 5xx 는 여기서 예외로 올린다.**
    점검 안내 페이지도 본문은 멀쩡한 HTML 이라 목록 파서가 조용히 0건을 돌려주고,
    그러면 헬스체크가 '목록 파서 깨짐 의심'(🔴)으로 오진한다. 경남교육청이 계획 점검
    (2026-08-21 19:00 ~ 08-24 08:00)에 들어가며 503 을 주자 실제로 그렇게 찍혔다.
    예외로 올리면 크롤 루프가 이전 수집분을 승계하고 소스를 ok=False 로 기록하며,
    헬스체크는 '서버 오류(5xx) 1일차 — 관찰 중'으로 조용히 지나갔다가 사흘 이어질 때
    알린다. 'FAIL 없이 조용히 0건이 되는 게 제일 위험하다'는 원칙 그대로다 (2026-08-22).
    """
    if tls_blocked(url):
        return curl_get(url, referer=(kw.get("headers") or {}).get("Referer"), encoding=encoding)
    last = None
    for attempt in range(retries + 1):
        try:
            r = s.get(url, timeout=20, verify=False, **kw)
            if 500 <= r.status_code < 600:
                # 5xx 도 딸꾹질일 수 있다 — 타임아웃과 같은 백오프로 다시 물어본다
                raise requests.HTTPError(f"{r.status_code} {r.reason}", response=r)
            if encoding:
                r.encoding = encoding
            elif r.encoding in (None, "ISO-8859-1"):
                r.encoding = r.apparent_encoding
            time.sleep(0.8)  # 예의상 간격
            return r
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
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
    r"|공연\s*기간|연수\s*기간|위촉\s*기간|수업\s*기간|운영\s*기간|강의\s*기간"
    # 낱말과 '기간' 사이에 괄호가 끼는 표기가 흔하다 — '임용(계약)기간'이 이 목록을 빠져나가
    # 한국교원대 공고의 마감이 임용 종료일(2028-02-28)로 잡혔다 (2026-08-17)
    r"|(?:임용|계약|위촉|근무|고용)\s*(?:\([^)]{0,8}\))?\s*기간"
    # 값이 비었음을 대놓고 말해 주는 자리표시자
    r"|시작일\s*[-~]\s*종료일"
    # 전형 일정 — 접수기간 윈도가 이 너머의 날짜를 물면 발표일·위촉일이 마감이 된다.
    # 종로구립은 '응시원서' 윈도가 '위촉 예정일 2026.9.8'까지 삼켜 마감이 9/8로 밀렸다 (2026-08-18)
    r"|합격자\s*발표|발표\s*일|위촉\s*예정|임용\s*예정|심사\s*일|면접\s*일|시험\s*일"
    # 다음 항목 라벨들
    r"|첨부\s*파일|문의\s*처|담당\s*자|전화\s*번호|연락\s*처|모집\s*인원|채용\s*인원"
    r"|직종|세부\s*분류|채용\s*상태|접수\s*상태|근무\s*지|자격\s*요건|응시\s*자격"
    r"|제출\s*서류|전형\s*방법|선발\s*방법|이전\s*글|다음\s*글|목록\s*보기")


# "2026. 8. 12. 10:00 ~ 18. 12:00" — 끝이 '일'만 있고 시각이 붙는 범위.
# 시각을 양쪽 다 요구하므로 '8. 12 ~ 18' 같은 모호한 표기에는 걸리지 않는다.
# 뽑는 값은 (연, 시작월, 끝일) — 월은 시작에서 물려받는다.
DAYONLY_TIME_RANGE = re.compile(
    r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*\.?\s*(?:\([^)]{1,3}\))?\s*"
    r"\d{1,2}\s*:\s*\d{2}\s*[~∼～]\s*(\d{1,2})\s*\.\s*(?:\([^)]{1,3}\))?\s*\d{1,2}\s*:\s*\d{2}")


def _dayonly_range_end(m):
    """'Y.M.D HH:MM ~ D HH:MM' 매치 → 끝 날짜. 끝 일이 시작 일보다 작으면 다음 달로 넘긴다."""
    y, mo, d1, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    if d2 < d1:                     # "8. 28. ~ 3." = 다음 달 3일
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    return _mk(y, mo, d2)


def _window_deadline(window, ref_year):
    """한 키워드 윈도 안에서 마감일 후보 — 신뢰도 높은 패턴 순서로"""
    # 다른 기간 항목이 나오면 거기서 끊는다. 우리가 찾는 건 '언제까지 지원하나'뿐이다.
    window = _OTHER_PERIOD.split(window, 1)[0]
    # 1) 끝이 '일 + 시각'인 범위 — "2026. 8. 12. 10:00 ~ 18. 12:00" (계명대).
    #    RANGE_PAT 보다 먼저 본다. 그쪽은 끝의 '18. 12:00'을 월 18·일 12로 읽어 실패하거나,
    #    월을 넘기는 '8. 28. ~ 3. 12:00'을 3월 12일로 읽어 과거 날짜를 만들었다 (2026-08-17).
    #    양쪽에 시각(HH:MM)이 명시된 꼴만 받으므로 모호한 표기에는 걸리지 않는다.
    m = DAYONLY_TIME_RANGE.search(window)
    if m:
        c = _dayonly_range_end(m)
        if c:
            return c
    # 2) 4자리 연도 기간 종료일
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


# 값이 태그 사이가 아니라 속성에 들어 있는 칸 — 관공서 게시판은 읽기 전용 정보를
# 입력폼처럼 그린다. 경남교육청 구인 상세는 접수기간을 <input value="2026.08.21"> 로
# 렌더해서, 본문 텍스트에는 '접수기간 시작일 - 종료일' 이라는 라벨만 남는다.
# 마감일이 화면에 뻔히 보이는데 3회차까지 못 찾아 사람에게 넘어왔다 (남해정보산업고,
# 2026-08-21). get_text() 는 속성을 보지 않으므로 여기서 따로 이어 붙인다.
def _inline_input_values(soup):
    """입력칸의 값을 **그 자리의 텍스트로** 바꿔 넣는다.

    끝에 몰아 붙이면 안 된다 — 마감 추출은 '접수기간' 같은 라벨 **근처의** 날짜를 찾는데,
    값이 문서 끝에 떨어져 있으면 라벨과 이어지지 않아 못 읽는다. 제자리에 넣어야
    '접수기간 2026.08.21 - 2026.08.25' 로 읽힌다 (2026-08-21).
    """
    n = 0
    for el in soup.find_all(["input", "option", "textarea"]):
        if el.name == "input":
            if (el.get("type") or "text").lower() in ("hidden", "submit", "button", "image", "checkbox", "radio"):
                continue
            v = el.get("value")
        elif el.name == "option":
            v = el.get("value") if el.has_attr("selected") else None
        else:
            v = None      # textarea 는 get_text 가 이미 읽는다
        v = (v or "").strip()
        # 값처럼 보이는 것만 — 버튼 문구나 빈 칸은 본문을 어지럽히기만 한다
        if 3 <= len(v) <= 60 and re.search(r"\d", v):
            el.replace_with(" " + v + " ")
            n += 1
    return n


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
    _inline_input_values(soup)
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
_KW_PRIORITY = re.compile(r"원서 ?접수|접수 ?기간|접수 ?기한|접수 ?마감|서류 ?접수|지원 ?기간|응시원서|남은 ?기간"
                          # '지원 접수 및 공고 기간 : …~ 2026. 8. 19.' (한국교원대) — 확정 어휘인데
                          # 빠져 있어 폴백으로 밀렸고, 폴백이 임용 종료일을 물었다 (2026-08-17)
                          r"|지원 ?접수|모집 ?종료일|접수 ?종료일"
                          # OCR 이 '접수기간'을 '첨수기간·점수기간'으로 오독한다 — 종로구립어르신합창단
                          # 재공고 이미지가 그랬다. '기간'이 붙을 때만 받아 오탐을 막는다 (2026-08-18)
                          r"|[첨점]수 ?기간"
                          # '제출기한/제출기간'도 확정 어휘다. 이게 빠져 있어서 예울마루 공고가
                          # 폴백으로 밀렸고, 폴백은 가장 늦은 날짜를 고르는 탓에 페이지에 딸려 온
                          # 수강신청서 양식의 '오늘 날짜'가 이겨 매일 '오늘 마감'으로 떴다
                          # (2026-08-08. 진짜 마감은 '제출기한 … ~ 2026.6.24.'였다).
                          r"|제출 ?기한|제출 ?기간|서류 ?제출 ?기한")
# '제출'은 서술어로도 쓰인다 — 신청서 양식 맨 끝의 "위와 같이 신청서를 제출합니다. 2026년
# 08월 08일 신청인"이 그렇다. 그 날짜는 서명란이라 늘 오늘 날짜가 찍히는데, 폴백은 가장 늦은
# 날짜를 고르므로 그게 매번 이긴다. 항목 이름으로 쓰인 '제출'만 본다 (2026-08-08).
#  · 한글 공고문은 칸을 맞추려고 낱말 사이를 띄운다 — '기 한 : …', '접 수 처 : …'.
#    서울발레시어터 공고가 '기 한'이라 우리 규칙을 비켜 갔다 (2026-08-09).
#  · '공고기간'은 게시 기간이지만, 접수기간을 따로 안 밝힌 공고에서는 사실상 접수 창이다.
#    우선 어휘가 아니라 폴백에 둬서 접수기간이 있으면 그쪽이 이기게 한다.
_KW_FALLBACK = re.compile(r"접\s?수|마\s?감|기\s?한|제출(?!\s*합니다|\s*하[여시는])|지원서"
                          r"|모집 ?기간|공고 ?기간")
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
    text = squash_spaced_labels(re.sub(r"\s+", " ", text))
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
    text = squash_spaced_labels(re.sub(r"\s+", " ", text))
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
        # 폴백 키워드가 '채용종료일·근무기간·채용기간' 같은 다른 기간 라벨의 일부이거나
        # 그 라벨 바로 뒤라면, 거기서 나온 날짜는 접수 마감이 아니다 — 기각하고 빈칸 유지
        # ("빈칸 > 오염", 2026-08-15 워크오더 B4. 인천 방과후 첼로의 채용종료일 11/26 오표기)
        if re.search(r"(?:채용\s*종료|채용\s*시작|근무\s*기|채용\s*기|계약\s*기|위촉\s*기)\s*$",
                     text[max(0, kw.start() - 12):kw.start()]):
            continue
        c = _window_deadline(text[kw.start(): kw.start() + 300], ref_year)
        if c and (best is None or c > best):
            best = c
    if best:
        return best
    # 최후 수단: 양쪽에 시각이 붙은 날짜 범위는 접수기간일 수밖에 없다 — 근무시간엔 날짜가,
    # 임용일·계약기간엔 시각이 안 붙는다. 상명대 공고 이미지는 머리글('강사채용 공고 및 접수')이
    # 남색 배경 흰 글씨라 OCR에서 통째로 사라져, 날짜가 어떤 키워드보다 앞에 있었다 (2026-08-18).
    # 문서 전체를 본다 — 앞머리 한정으로는 원문(내비게이션 잔해)+OCR 을 이어 붙인 보관층
    # 텍스트에서 OCR 부분이 영영 사정거리 밖이다. 대신 바로 앞이 다른 기간 라벨이면 기각한다.
    for pat in (DAYONLY_TIME_RANGE,
                re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*\.?\s*(?:\([^)]{1,3}\))?\s*"
                           r"\d{1,2}\s*:\s*\d{2}\s*[~∼～]\s*(?:(20\d{2})\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})"
                           r"\s*\.?\s*(?:\([^)]{1,3}\))?\s*\d{1,2}\s*:\s*\d{2}")):
        for m in pat.finditer(text):
            if re.search(r"(?:등록|수강|계약|임용|근무|공연|행사|교육|연수)\s*(?:기간|일자|신청)?\s*[:：]?\s*$",
                         text[max(0, m.start() - 14):m.start()]):
                continue
            c = (_dayonly_range_end(m) if pat is DAYONLY_TIME_RANGE
                 else _mk(m.group(4) or m.group(1), m.group(5), m.group(6)))
            if c:
                return c
    return None

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
# 사람이 아니라 '단위'를 받는 공모 — 통영국제음악재단 '스쿨콘서트 참가 학교 모집'
# (2026-08-23). 공연을 보러 올 학교를 받는 것이라 어떤 뜻으로도 채용이 아니다.
# **_HIRE_ROLE 보호를 주지 않는다** — '예술강사 지원사업 참여 학교 모집'처럼 제목에
# 직무 어휘가 섞여 있어도 뽑는 대상은 학교지 사람이 아니다.
_PARTICIPANT_UNIT = re.compile(
    r"참[가여]\s*(?:학교|기관|단체|팀|가족|시설|병원|학급)"
    r"|(?:신청|수혜|공모|선정)\s*(?:학교|기관|단체)")


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


def dance_member(title, org=""):
    """발레·무용 단체의 단원 모집인가 — 무용수 자리라 포디엄 범위 밖 (워크오더 E14).
    같은 단체의 반주자·피아니스트·연주자 모집은 음악인 자리이므로 남긴다."""
    blob = f"{title} {org}"
    if not re.search(r"발레|무용", blob):
        return False
    if re.search(r"반주|피아노|피아니스트|연주자|음악감독|지휘", blob):
        return False
    return bool(re.search(r"단원|무용수", blob))


def rope_skipping_only(title, org=""):
    """음악줄넘기 단독 모집인가 — 음악은 배경일 뿐 체육 강사 자리다 (2026-08-16 결정).

    난타는 반대로 남긴다. 타악 연주 기술이 직접 쓰이는 자리라 타악 전공자의 실질 일감이다.
    그래서 운산초 '특성화(난타, 음악줄넘기, 합창) 강사'처럼 여러 분야를 함께 뽑는 공고는
    난타·합창 쪽이 살아 있으므로 제외하지 않는다 — 단독 모집만 걷어낸다.
    판단 이력은 docs/scope-decisions.md 참고.
    """
    blob = f"{title} {org}"
    if not re.search(r"음악\s*줄넘기", blob):
        return False
    # 음악줄넘기 말고 다른 음악 분야가 함께 걸려 있으면 그건 혼합 공고다
    rest = re.sub(r"음악\s*줄넘기", " ", blob)
    return not re.search(
        r"난타|합창|오케스트라|관현악|기악|성악|국악|밴드|중창|重唱|피아노|바이올린|첼로"
        r"|플[루룻]트|플룻|클라리넷|색소폰|타악|드럼|우쿨렐레|기타|가야금|해금|장구|사물놀이"
        r"|음악\s*교[사원]|음악\s*강사|악기", rest)


def youth_member(title):
    """아동·청소년 '단원' 모집인가 — 채용이 아니라 참여.

    '꿈의 오케스트라'는 이름에 어린이·청소년이 없지만 사업 자체가 아동 대상
    (엘시스테마형 초등 오케스트라)이다 — 파주·통영 단원 모집이 제목만 봐서는 성인
    채용처럼 보여 그대로 실렸다 (2026-08-12 사용자 지적). 단, 같은 사업의 강사·
    지도자·교육단원·운영 인력 모집은 진짜 채용이므로 남긴다.
    """
    t = title or ""
    if re.search(r"꿈의\s*오케스트라", t) and re.search(r"단원\s*(?:모집|선발|모심)", t)             and not re.search(r"강사|지도자?|교육\s*단원|음악\s*감독|운영|위탁|매니저", t):
        return True
    return bool(_YOUTH_MEMBER.search(t))


def student_target(qual, age_limit=None):
    """자격·나이 문구가 '재학 중인 학생'을 가리키는가 — 몸통 기반 아동 판정.

    제목으로는 성인 채용처럼 보여도 자격 칸에 '초등학교 3학년~6학년에 재학 중인 학생'이라
    적혀 있으면 참여 모집이다. 제목 규칙(youth_member)이 놓친 것을 몸통에서 받친다.
    """
    t = f"{qual or ''} {age_limit or ''}"
    return bool(re.search(r"(?:초등|중|고등)학교.{0,14}재학|재학\s*중인\s*학생"
                          r"|[1-6]\s*학년\s*[~∼-]\s*[1-6]\s*학년", t))


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
    # '교원 채용'만으로 교수를 주면 초·중·고 기간제교사가 전부 교수가 된다(성서중·매송중,
    # 2026-08-15 워크오더 D9). 교수는 대학 신호가 있을 때만.
    if re.search(r"전임 ?교원|초빙 ?교원|겸임 ?교원|비전임 ?교원|산학 ?교원|객원 ?교원|초빙 ?교수"
                 r"|교수 ?(?:초빙|채용|공개채용|임용|모집)", title):
        return "교수"
    # 초·중·고 교원(기간제·계약제·정교사·교과전담) — 대학 교수와 다른 자리다
    if re.search(r"기간제 ?교[사원]|계약[제직] ?교[사원]|정교사|교과 ?전담|휴직 ?대체.*교[사원]"
                 r"|교[사원] ?(?:채용|임용|모집)", title):
        return "교원"
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
    r"|촬영|기록자료|아카이브|아키비스트"
    # 사업 운영을 맡는 자리 — 포항문화재단 '꿈의 스튜디오 운영인력(코디네이터)'
    # (2026-08-23). 문화재단 사업이라 음악 어휘가 기관명에 묻어 오지만, 그 자리에서
    # 쓰이는 것은 운영·행정 기술이지 연주나 지도가 아니다.
    r"|코디네이터|코디네이션|운영\s*인력|운영\s*요원|운영\s*스태프|진행\s*요원|보조\s*인력")
_MUSIC_KEEP = re.compile(r"악기|악보|조율|지휘|반주|연주|성악|합창|오케스트라|(?<![사무])단원|수석|악장|강사")
# 타 장르(무용·미술·연극 등) 공고 — '단원'만으로는 음악 공고로 인정하지 않음
# 공예·도예 추가(2026-08-03): 창원 '공예공간 기록 프로젝트 <산단사이 2기> 모집'이 통과했다
# '극단(劇團)'은 연극이다 — '꿈의 예술단(극단) 예술감독'이 지휘 자리처럼 통과했다 (2026-08-18).
# '극단적'(extreme)과 갈라놓고, 오페라는 _MUSIC_STRONG 쪽에 둬 오페라 단체는 살린다.
NONMUSIC_ART = re.compile(r"무용|발레|안무|댄스|연극|극단(?!적)|배우|미술|공예|도예|(?<!대)전시(?!립)|사진 ?(?:공모|작가)|문학|서예|디자인")
_MUSIC_STRONG = re.compile(
    r"악기|악보|조율|지휘|반주|성악|합창|오케스트라|콰르텟|앙상블|피아니스트|수석|악장"
    r"|바이올린|비올라|첼로|더블 ?베이스|플루트|오보에|클라리넷|바순|호른|트럼펫|트롬본|튜바|팀파니|타악|하프"
    r"|오페라"   # 오페라 단체의 음악 자리는 극단 제외 규칙에 밀리면 안 된다
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
    r"|(?<!클래식)(?<!클래식 )기타 ?(?:예술)?(?:강사|레슨|반\b)|\(기타\) ?강사|통기타"
    # 드럼(드럼세트)도 실용음악이다. 관현악 타악(팀파니·퍼커션)과 헷갈리지 않게 '드럼'만 건다
    # — 안양예고 '음악과 전공 주간실기 강사(드럼)'이 클래식 공고로 실려 있었다 (2026-08-08).
    r"|드럼(?!\s*통)|드럼 ?세트|타악 ?드럼")

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
    # 사람이 아니라 학교·기관을 받는 공모 — 직무 어휘가 섞여도 채용이 아니다
    if _PARTICIPANT_UNIT.search(title):
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
    ("첼로", "현악", r"첼로|비올론첼로"),
    ("하프", "기타", r"하프"),
    ("플루트", "목관", r"플루[트룻륫]|플룻|피콜로"),
    ("오보에", "목관", r"오보에"),
    ("클라리넷", "목관", r"클라리[넷네][트]?"),
    ("바순", "목관", r"바순|파곳"),
    ("호른", "금관", r"호른|프렌치\s?호른"),
    ("트럼펫", "금관", r"트럼펫"),
    ("트롬본", "금관", r"트롬본"),
    ("튜바", "금관", r"튜바"),
    ("색소폰", "금관", r"색소폰|색스폰|saxophone"),
    # 드럼(드럼세트)은 실용음악이라 여기 넣지 않는다 — 포디엄 범위는 클래식이다.
    # 관현악 타악(팀파니·퍼커션)과는 다른 악기다 (2026-08-08 사용자 지시).
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
    ("현악", "현악", r"현악(?![초중고대구산로동학원])(?:부|파트|군|기)?"),
    ("목관", "목관", r"목관(?:부|파트|군|기)?"),
    ("금관", "금관", r"금관(?:부|파트|군|기)?"),
    ("관악", "목관", r"관악(?![초중고대구산로동학원])(?:부|파트|군|기)?"),   # 관악초·관악구 방지 (워크오더 D12)
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
    # '기간제'는 학교 계약제 교원 어휘로 넣은 것 — 합창단·예술단의 '기간제 (비상임) 단원'을
    # 물면 연주직이 취미·입문으로 둔갑한다 (울산시립합창단, 2026-08-19 L4 검출)
    r"학원|아카데미|문화 ?센터|방과 ?후|방과후학교|늘봄|복지관|꿈의 ?오케|꿈의오케스트라|평생 ?교육"
    r"|기간제(?!\s*(?:비상임|상임|객원)?\s*단원)|계약제 ?교[원사]"
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

# 음악 공간·악기 관리직 — 지도 직무가 아니므로 교육 계열에 넣지 않는다 (docs/scope-decisions.md).
# 대상어(실기실·연습실·악기·시설)를 앞에 요구해 '예술감독·음악감독'과 갈라놓는다.
_FACILITY_KEEPER = re.compile(
    r"(?:실기실|연습실|연습 ?공간|악기|시설|공간|기자재)\s*(?:관리|감독|지킴이|당직|경비|운영\s*요원)")


def classify_tier(title, org=""):
    """연주 / 교육 — 대학 / 교육 — 입시·전공 / 교육 — 취미·입문 / 미분류.
    지시서 3-1 우선순위: 대학교원 → 입시·전공 → 취미·입문 → 연주 → 오브리연주 → 미분류.
    교육 신호를 연주보다 먼저 봐서 '오케스트라 강사(초등)'=교육, '오케스트라 객원'=연주로 갈린다."""
    t = f"{title} {org}"
    # 음악 공간·악기를 지키고 관리하는 자리 — 전공자의 실질 일감이지만 가르치는 일이 아니다.
    # 학교 이름 때문에 '교육 — 입시·전공'으로 가던 선화예고 실기실 감독이 계기 (2026-08-17).
    # '예술감독·음악감독'은 지휘 자리이므로 걸리지 않게 대상어를 앞에 못 박는다.
    if _FACILITY_KEEPER.search(t):
        return "그 외"
    # 예중·예고가 함께 보이면(대학 부설 예고 등) 입시·전공이 우선 — 대학 규칙에서 먼저 배제
    if _EDU_UNIV.search(t) and _EDU_UNIV_PLACE.search(t) and not _EDU_IPSI.search(t):
        return "교육 — 대학"
    if _EDU_IPSI.search(t):
        return "교육 — 입시·전공"
    # 학교 정규 교과 교원(교원자격증 요구 채용)은 취미·입문이 아니다 (워크오더 D10)
    # 시간강사도 학교 수업이다 — 대학 시간강사는 위의 대학 규칙이 먼저 문다 (워크오더 08-16 §3)
    if re.search(r"기간제 ?교[사원]|계약[제직] ?교[사원]|정교사|교과 ?전담|휴직 ?대체"
                 r"|시간 ?강사", t):
        return "교육 — 학교"
    if _EDU_HOBBY.search(t):
        return "교육 — 취미·입문"
    if _PLAY.search(t):
        return "연주"
    if _OBRI.search(t) and _OBRI_PLAY.search(t):     # 교회·행사 + 연주 성격
        return "연주"
    return "미분류"                                   # 추측 금지 — 사람 확인 큐

# ---------- 자격요건 필드 (태그가 아니라 필터 가능한 필드) ----------
# 사실: 대학교수·시간강사=교원자격증 불필요 / 초중고 정교사·임용=필요 / 방과후·예술강사=대체로 불필요.
_CERT_YES = re.compile(r"정교사|교원 ?자격|교사 ?자격|교직 ?이수|임용|기간제 ?교[사원]|계약[제직] ?교[사원]|중등 ?교사|초등 ?교사|담임")
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

# 주소 맨 앞의 정식 시도명. 토큰 훑기보다 **먼저** 본다 — 목록은 '경기'가 '경상남'보다
# 앞서 있어서, 지오코딩이 돌려준 '경상남도 양산시 양주로'가 뒤쪽 '양주(경기 양주시)'에
# 걸려 경남 공고를 경기로 보냈다 (2026-08-23 양산남부고). 주소는 맨 앞이 곧 답이다.
_SIDO_HEAD = [
    ("서울특별시", "서울"), ("부산광역시", "부산"), ("대구광역시", "대구"),
    ("인천광역시", "인천"), ("광주광역시", GWANGJU_JEONNAM), ("대전광역시", "대전"),
    ("울산광역시", "울산"), ("세종특별자치시", "세종"),
    ("경기도", "경기"), ("강원특별자치도", "강원"), ("강원도", "강원"),
    ("충청북도", "충북"), ("충청남도", "충남"),
    ("전북특별자치도", "전북"), ("전라북도", "전북"),
    ("전남특별자치도", GWANGJU_JEONNAM), ("전라남도", GWANGJU_JEONNAM),
    ("경상북도", "경북"), ("경상남도", "경남"),
    ("제주특별자치도", "제주"),
]


def region_from(text, default="기타"):
    t = _SEJONG_FALSE.sub("", text or "")
    ts = t.lstrip()
    for head, region in _SIDO_HEAD:
        if ts.startswith(head):
            return region
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
    r"|참조|변경|사정|우대|담당|인원|박사|석사|년제|해당|점수|비고|기타|증빙|제출|모집|채용|공고"
    # 각주·단서 문구가 교과목으로 실렸다 — '*실기과목의 경우' (2026-08-09 사용자 지적)
    r"|경우|다만|단서|이하|참고|안내")

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
        c = re.sub(r"\s+", " ", c).strip()
        # 각주 표시로 시작하면 교과목이 아니라 단서 문구다 — 통째로 버린다
        if re.match(r"^[*※]", c):
            continue
        # hwp 글머리표가 문자로 바뀌어 붙어 온다 — 'º 호른 전공', 'ㅇ 음악교육'
        # (º 는 hwp 의 'ㅇ' 글머리가 서수 기호로 변환된 것. 2026-08-09 사용자 지적)
        c = re.sub(r"^[\sºo°ㅇ○◦•∙·\-–—\[\]．.]+", "", c).strip(" ·-—[]．.")
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

_YEAR_TERM = re.compile(r"\s*20\d{2}\s*(?:[~·\-–]\s*20\d{2}\s*)?학년도\s*(?:제?\s*[12]\s*학기\s*)?")

# 악기명만 담긴 괄호는 제목에서 뺀다 — 악기는 카드에 태그로 따로 붙으므로 제목에서 또
# 말할 이유가 없다 (2026-08-08 사용자 지시. 이전의 '악기명 절대 삭제 금지' 규칙을 뒤집은
# 것이며, 뒤집은 근거는 그때는 없던 악기 태그가 지금은 있다는 점이다).
# ★ 괄호 안이 **악기·숫자·구분점만**일 때에만 지운다. '(음악 시간강사)', '(6학년, 음악)',
#   '(합창, 메이커)', '(상임지휘자)' 처럼 직무·과목이 섞이면 손대지 않는다.
_INST_WORD = (r"(?:바이올린|비올라|첼로|더블\s?베이스|콘트라베이스|플루[트룻]|플룻|피콜로|오보에"
              r"|클라리[넷네]트?|바순|파곳|호른|트럼펫|트롬본|튜바|색소폰|타악|팀파니|퍼커션|하프"
              r"|피아노|오르간|소프라노|메조소프라노|메조|알토|테너|바리톤|베이스|지휘|현악|목관"
              r"|금관|관악|드럼)")
_INST_ONLY_PAREN = re.compile(rf"\s*[(（]\s*(?:{_INST_WORD}\s*\d*\s*[,·/、]?\s*)+[)）]")


def _drop_repeat_token(t):
    """제목 안에서 같은 지역·고유명이 두 번 나오면 뒤엣것을 뺀다.

    '파주문화재단 꿈의 오케스트라 파주 신규 단원 모집'에서 '파주'가 두 번 나온다 —
    앞은 기관명의 일부라 지울 수 없고, 뒤는 없어도 뜻이 온전하다 (2026-08-08 사용자 지시).
    앞쪽에서 이미 더 긴 낱말의 일부로 등장한 2~4자 낱말만 건드린다.
    """
    words = t.split()
    out = []
    for w in words:
        core = w.strip("(),·-–")
        if 2 <= len(core) <= 4 and re.fullmatch(r"[가-힣]+", core):
            head = " ".join(out)
            # 앞에서 '더 긴 낱말의 일부'로 이미 나왔는가 (낱말 그대로 나온 경우는 제외 —
            # 그건 원래 반복이라 손대면 뜻이 상한다)
            if core in head and not re.search(rf"(?:^|\s){re.escape(core)}(?:\s|$)", head):
                continue
        out.append(w)
    return " ".join(out)


# 제목 꼬리의 '시수 상세' 괄호 — 학년별 몇 시간인지는 상세 칸(근무시간)이 말한다.
# 카드 제목에서는 자리만 차지하고 읽는 흐름을 끊는다 (2026-08-20 사용자 지시).
#   '…모십니다((3학년 6시간, 5학년 6시간), 음악(3학년 3시간))' → '…모십니다'
# 괄호가 중첩되므로 안쪽부터 반복해 벗긴다. 학년·시간·시수 신호가 있는 괄호만 건드린다.
_HOURS_PAREN = re.compile(r"\s*\((?:[^()]|\([^()]*\))*?\d+\s*(?:시간|시수|차시)(?:[^()]|\([^()]*\))*?\)")
# 시수 괄호를 벗기면 그 바깥에 과목명만 든 껍데기가 남는다 —
# '((3학년 6시간…), 음악(3학년 3시간))' → '(음악)'. 한 겹 더 걷어낸다 (2026-08-20).
_SUBJ_ONLY_PAREN = re.compile(r"\s*[(（]\s*[가-힣]{2,6}\s*[)）]\s*$")

# 제목 앞머리의 기간 표기 — 뜻은 있지만 맨 앞에 오면 '무엇을 뽑는가'가 뒤로 밀린다.
# 뒤로 옮겨 '교과전담교사 시간강사님을 모십니다 9.21.(월)~9.23.(수)' 처럼 읽히게 한다.
_LEAD_PERIOD = re.compile(
    r"^\s*(\d{1,2}\s*\.\s*\d{1,2}\s*\.?\s*(?:\([월화수목금토일]\))?"
    r"\s*[~∼-]\s*"
    r"\d{1,2}\s*\.\s*\d{1,2}\s*\.?\s*(?:\([월화수목금토일]\))?)\s*")


def _tidy_parens(t):
    """괄호 안 내용을 지운 뒤 남는 껍데기·구분자를 치운다.

    악기 괄호·시수 괄호·마감 표기를 각각 지우다 보면 '( )', '(, )', '()' 같은 잔해가 남는다.
    지우는 규칙마다 뒷정리를 붙이면 빠뜨리는 곳이 생기므로, 마지막에 한 번 훑는다.
    """
    if not t:
        return t
    t = re.sub(r"[(\[（]\s*(?:[,·/、]\s*)+", lambda m: m.group(0)[0], t)   # 여는 괄호 뒤 구분자
    t = re.sub(r"(?:[,·/、]\s*)+\s*([)\]）])", r"\1", t)                  # 닫는 괄호 앞 구분자
    t = re.sub(r"[(（]\s*[)）]", "", t)                                    # 빈 괄호
    t = re.sub(r"\[\s*\]", "", t)
    t = re.sub(r"(?:\s*[,·/、]\s*){2,}", ", ", t)                          # 연속 구분자
    return re.sub(r"\s{2,}", " ", t).strip(" -–·,")


# 모집 표를 평탄화하면 인원 칸에 표 전체가 들어온다 —
# '성악지도자 1명 제물포구 구립 여성합창단 반주자 1명 … 단무장 1명 ▢' (제물포, 2026-08-21).
# 어느 파트를 몇 명 뽑는지는 원문 표를 봐야 하고, 카드에는 규모만 있으면 된다.
# 직무 이름은 이미 제목에 있다('…성악지도자/반주자/단무장 모집').
_HEADCOUNT = re.compile(r"(\d{1,3})\s*명")


def tidy_personnel(v):
    """인원 값 정리. 'N명'이 여럿이면 합계로 접고, 하나면 그대로 둔다."""
    if not v:
        return v
    t = re.sub(r"\s+", " ", str(v)).strip(" .,·-–▢□○●")
    # 꼬리에 붙은 고용형태는 인원이 아니다 — '보컬 1명, 기악 1명, 시간제'
    t = re.sub(r"[,·]\s*(?:시간제|전일제|기간제|계약직|정규직)\s*$", "", t).strip(" ,·")
    if re.fullmatch(r"\d{1,3}", t):     # 표에서 단위가 다음 칸으로 밀린 경우
        return t + "명"
    nums = _HEADCOUNT.findall(t)
    # 짧으면 어느 파트를 몇 명 뽑는지가 그대로 쓸모 있는 정보다('보컬 강사 1명, 기악 1명').
    # 표를 통째로 편 것만 접는다 — 기준은 사람이 한눈에 읽히는가, 즉 길이다 (2026-08-21).
    if len(nums) >= 2 and len(t) > 46:
        try:
            total = sum(int(n) for n in nums)
        except ValueError:
            return t
        return f"총 {total}명" if total else t
    # 하나뿐이어도 앞뒤에 표 부스러기가 붙어 있으면 그 부분만 남긴다
    if len(nums) == 1 and len(t) > 24:
        m = re.search(r"[가-힣]{2,12}\s*\d{1,3}\s*명", t)
        return m.group(0) if m else t
    return t


# 제목 앞머리의 사업·프로젝트 브랜드명 — '악기뱅크2.0 울림프로젝트 밴드부 강사 채용'
# (학성초, 2026-08-21). 교육청·재단이 붙이는 사업 이름은 지원자가 찾는 말이 아니다.
# 아무도 '울림프로젝트'로 검색하지 않고, 카드에서는 직무('밴드부 강사')를 가릴 뿐이다.
# 뒤에 직무 어휘가 남을 때만 뗀다 — 사업명이 제목의 전부면 그건 지울 수 없는 정보다.
_PROGRAM_LEAD = re.compile(
    r"^\s*[가-힣A-Za-z][가-힣A-Za-z0-9.\s]{0,24}?(?:프로젝트|지원\s*사업|사업단?|공모\s*사업)\s+"
    r"(?=.*(?:강사|단원|반주|지휘|교사|교원|연주자?|코치|교수|감독|지도|계약직))")


# 제목 꼬리에 붙은 과목·인원 — 카드의 모집·담당업무 행에 이미 실리는 값이라
# 제목에서 또 말할 이유가 없다 (시간강사 채용 공고: 음악 1명 — 목운중, 2026-08-25).
_TAIL_SUBJ_COUNT = re.compile(r"\s*[:：\-–]\s*[가-힣]{2,10}\s*\d{1,3}\s*명\s*$")


def compact_title(title):
    """행정 상투구를 걷어내 제목을 카드에 맞게 압축. 악기명·기관명 등 알맹이는 건드리지 않는다.

    앞머리: '2026학년도 (제2학기)', '제2026-15호', '붙임' 같은 접두 상투구
    꼬리: '… 공고(문)', '… - 2026. 7. 8. 자'(KBS식 게시일 꼬리)
    결과가 너무 짧아지면(6자 미만) 원본 유지 — 과잉 절단 방지."""
    t = _PROGRAM_LEAD.sub("", title or "")      # 사업 브랜드명 앞머리
    t = _TAIL_SUBJ_COUNT.sub("", t)             # 꼬리의 과목·인원
    t = re.sub(r"^\s*\[?(?:NEW|새글|N|오늘 ?마감|마감 ?임박|D-\d+)\]?\s+", "", t)   # 게시판 배지가 제목에 섞여온 경우 (세종교육청 새글, 경기 '오늘마감')
    # 공고번호는 앞머리뿐 아니라 대괄호 안에도 들어온다
    # ('[파주문화재단 공고 제2026-48호] …'). 자리를 가리지 않고 지운다 (2026-08-08).
    t = re.sub(r"\s*공고\s*제?\s*20\d{2}\s*[-–]\s*\d+\s*호", "", t)
    t = re.sub(r"\s*제\s*20\d{2}\s*[-–]\s*\d+\s*호", "", t)
    t = re.sub(r"^\s*(?:붙임\s*)?제?\s*20\d{2}\s*[-–]\s*\d+\s*호\s*", "", t)      # 공고번호
    # 대괄호 안에 기관명만 남았으면 껍데기를 벗긴다 — 괄호가 뜻을 더하지 않는다.
    # 단 학교 약칭 괄호('[대전선암초]')는 우리가 school_title 에서 일부러 씌운 것이므로
    # 벗기지 않는다. 최종 단계가 제목 정리를 한 번 더 돌리기 때문에, 여기서 벗기면
    # 애써 붙인 약칭 괄호가 매 크롤마다 사라진다 (2026-08-08 실제로 그랬다).
    m = re.match(r"^\s*\[\s*((?![^\[\]]{0,16}(?:초|중|고|여중|여고|예고|예중|교회|성당|채플"
                 r"|대학교|대학원)\s*\])[^\[\]]{2,20}?)\s*\]\s*(.*)$", t)
    if m:
        head, rest = m.group(1).strip(), m.group(2).strip()
        # 괄호 안 말이 뒤 문장에서 이미 하는 이야기면 껍데기째 버린다 — 안 그러면 같은 말이
        # 두 번 된다('[교회 반주자 모집] 함께 예배를 섬겨주실 반주자님을 모십니다').
        # 직무 + 모집/채용을 함께 담은 괄호는 글쓴이가 붙인 분류 딱지다. 뒤 문장이 이미 같은
        # 이야기를 하므로 버린다 — '[교회 반주자 모집] 함께 예배를 섬겨주실 반주자님을 모십니다'.
        # '[파주문화재단 공고]'처럼 직무어가 없는 것은 기관명이라 남긴다.
        label = bool(re.search(r"(?:반주자?|단원|강사|연주자|지휘자|교원|교사|성가대)", head)
                     and re.search(r"(?:모집|채용|구인|초빙)\s*$", head))
        # 게시판 딱지만 든 괄호는 벗기면 '공지'라는 낱말만 덩그러니 남는다 — 통째로 버린다
        label = label or head in {"공지", "알림", "안내", "필독", "중요", "채용공고", "모집공고",
                                  "채용", "모집", "입찰", "공고"}
        dup = sum(1 for w in head.split() if len(w) >= 2 and w in rest)
        drop = label or (dup and dup >= max(1, len(head.split()) - 1))
        t = rest if (drop and len(rest) >= 8) else f"{head} {rest}"
    t = re.sub(r"^\s*(?:붙임\s*)?20\d{2}(?:\s*[~·\-]\s*20\d{2})?\s*학?년도?\s*(?:제?\s*[12]\s*학기\s*)?", "", t)
    t = re.sub(r"\s*[-–]\s*20\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?\s*자?\s*$", "", t)
    t = re.sub(r"\s*(?:새글|NEW)\s*$", "", t)               # 꼬리에 붙은 게시판 새글 배지 (부산교육청)
    # 게시판 표의 '작성부서 · 작성일 · 조회수'가 제목 뒤에 통째로 딸려오는 곳이 있다
    # (예울마루: "…채용 공고 예술사업팀 2026-06-17 조회수 : 775").
    # 조회수를 기준점으로 삼아 그 앞의 날짜·부서명까지 함께 걷어낸다 (2026-08-08).
    t = re.sub(r"\s*[가-힣]*\s*20\d{2}[-.]\d{1,2}[-.]\d{1,2}\s*조회\s*수?\s*[:：]?\s*[\d,]+\s*$", "", t)
    t = re.sub(r"\s*조회\s*수?\s*[:：]?\s*[\d,]+\s*$", "", t)
    # 꼬리에 게시일만 붙는 곳도 있다(파주문화재단: "…모집 공고(바이올린1, 플룻1) 2026-07-28").
    # 하이픈 ISO 표기만 건다 — 제목 속 마감 표기는 '(~9.17.)' 처럼 점을 쓰므로 안 걸린다.
    t = re.sub(r"\s*20\d{2}[-.]\d{1,2}[-.]\d{1,2}\.?\s*$", "", t)
    # 홀로 선 연도는 자리를 가리지 않고 뺀다. 지금 올라와 있는 공고 목록이라 연도가 뜻을
    # 더하지 않고, 괄호를 벗기면 앞머리에 있던 연도가 문장 중간으로 밀려나기도 한다
    # ('[파주문화재단 …호] 2026 꿈의 오케스트라' → '파주문화재단 2026 꿈의 …', 2026-08-08).
    t = " ".join(w for w in t.split() if not re.fullmatch(r"20\d{2}", w))
    # 학년도도 같이 뺀다. 뜻이 없는 건 아니지만 들어가면 확인할 수 있는 정보라
    # 카드 제목에서 자리를 차지할 이유가 없다 (2026-08-08 사용자 지시).
    t = _YEAR_TERM.sub(" ", t)
    # 제목 끝의 마감 표기는 배지('접수중 (~8.28)')와 마감 행이 이미 말한다 —
    # 같은 말을 세 번 하는 셈이라 지운다 (2026-08-20 사용자 지시).
    t = re.sub(r"\s*[(（]\s*[~∼]\s*\d{1,2}\s*[./]\s*\d{1,2}\s*\.?\s*[)）]\s*$", "", t)
    t = _INST_ONLY_PAREN.sub("", t)
    # 시수 상세 괄호를 걷어낸다 (중첩이라 더 안 줄 때까지 반복)
    hit = False
    for _ in range(3):
        t2 = _tidy_parens(_HOURS_PAREN.sub("", t))
        if t2 == t:
            break
        t, hit = t2, True
    # 시수 괄호를 벗긴 자리에 과목명만 든 껍데기가 남으면 그것도 지운다 —
    # '…모십니다(음악)'. 단 지우고도 제목이 남을 때만(정보를 다 날리지 않는다).
    if hit and len(_SUBJ_ONLY_PAREN.sub("", t).strip()) >= 10:
        t = _SUBJ_ONLY_PAREN.sub("", t)
    # 앞머리 기간 표기는 뒤로 돌린다 — 학교 약칭 딱지([서울남성초])는 그대로 두고 그 뒤부터 본다
    m_lead = re.match(r"^(\s*\[[^\]]{1,20}\]\s*)?(.*)$", t, re.S)
    if m_lead:
        tag, body = m_lead.group(1) or "", m_lead.group(2)
        m_p = _LEAD_PERIOD.match(body)
        if m_p:
            rest = body[m_p.end():].strip(" -–·,")
            if len(rest) >= 6:                      # 기간을 떼고도 말이 남을 때만
                t = f"{tag}{rest} {m_p.group(1).strip()}".strip()
    t = _drop_repeat_token(t)
    # 게시판이 제목을 잘라 놓은 흔적. 목록 칸 너비에 맞춰 '…' 이나 '_' 로 끊어 준다.
    # 뒤를 되찾는 일은 상세 원문을 쥔 _repair_titles 가 하고, 여기서는 흔적만 지운다.
    # '_...' 처럼 두 가지가 겹쳐 붙기도 한다 — 한 번만 지우면 '_' 가 남는다
    t = re.sub(r"(?:\s*(?:_+|\.{2,}|…|·{2,}))+\s*$", "", t)
    t = re.sub(r"\s*_\s*공고문?\s*$", "", t)                # '…채용_공고문' 꼴
    t = re.sub(r"\s*(?:재공고|공고문|공고)\s*$", "", t)      # '채용 공고'→'채용' (의미 유지)
    t = _tidy_parens(t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–·,")
    return t if len(t) >= 6 else title

# 공고문이 '• 라벨 : 값' 꼴로 조건을 늘어놓는 곳이 많다. 값은 다음 라벨(또는 글머리표)에서
# 끊는다 — 마감일 윈도와 같은 원리다. 이걸 뽑아 두면 카드 상세가 본문 발췌 대신 항목으로 선다
# (2026-08-08 사용자 가이던스: 급여·근무기간·근무시간·담당업무·나이를 항목으로 적을 것).
_FIELD_SPECS = [
    # '보수금액 : 세전 월 550,000원' — 라벨에 금액이 붙으면 콜론이 낱말 뒤가 아니라서
    # 강·약 모드 둘 다 놓쳤다 (종로구립 PDF, 2026-08-18)
    # '강사 수당 : 1명 기준으로 시간당(40분) 40,000원' — 학교 방과후·특기적성 공고는
    # 급여를 '수당'이라 부른다. 이 낱말이 없어 시간당 4만원짜리가 페이 빈칸이었다 (2026-08-21)
    ("pay",        r"급여|보수\s*금?액?|임금|처우|사례비|근로\s*조건|급여\s*조건|보수\s*조건"
                   r"|강사\s*수당|지도\s*수당|수당|강사료|강사비|지도비|강의료"),
    ("workPeriod", r"근무\s*기간|계약\s*기간|고용\s*기간|위촉\s*기간|채용\s*기간|임용\s*기간"),
    # 교회 공고는 '예배시간'이 곧 근무시간이다 — 이 낱말이 없어 '예배시간 : 매주 일요일
    # 11시~12시'가 담당업무 칸에 딸려 들어갔다 (성은교회, 2026-08-21)
    ("workHours",  r"근무\s*시간|근무\s*일시|근무\s*형태|근무\s*요일|예배\s*시간|봉사\s*시간"),
    ("duty",       r"담당\s*업무|주요\s*업무|업무\s*내용|직무\s*내용|담당업무"),
    ("ageLimit",   r"나이|연령"),
    ("workPlace",  r"근무\s*지|근무\s*장소|근무\s*처"),
    # 연주 공고(호텔·행사 장기공연 등)는 근무가 아니라 '공연' 어휘를 쓴다
    ("perfPeriod",   r"공연\s*기간"),
    ("perfPlace",    r"공연\s*장소"),
    ("perfSchedule", r"공연\s*스케[줄쥴]|공연\s*일정"),
    ("teamComp",     r"팀\s*구성|편성"),
    ("dayOff",       r"휴일|휴무일?"),
    # 몇 명 뽑는지는 지원 여부를 가르는 정보다. 'O명'처럼 수를 안 밝히는 표기도 그대로 싣는다
    # — 한국 공고에서 그건 '정원 제한 없음'이라는 뜻이다 (2026-08-08 사용자 설명).
    # '채용 분야 및 채용 예정 인원' — '예정'이 끼면 종전 규칙이 통째로 빗나갔다 (2026-08-21)
    ("personnel",  r"모집\s*인원|채용\s*(?:예정\s*)?인원|선발\s*(?:예정\s*)?인원|모집인원"),
    # 게시한 곳이 아니라 실제로 뽑는 회사. 대학 게시판에 올라온 외부 공고에서 특히 중요하다
    # — 제주 신라호텔 공고의 고용주는 '에이디엔노뜨'이고 호텔은 공연 장소일 뿐이다.
    ("hiringOrg",  r"구인\s*회사명|회사명|모집\s*기관|채용\s*기관|구인\s*기관|업체명|기관명"),
    # 주소가 있으면 지역을 추측하지 않아도 된다 — 제목·기관명 짐작보다 훨씬 정확하다.
    ("addr",       r"주\s*소|소\s*재\s*지|근무\s*장소|사업장\s*주소"),
]

# 전화번호는 라벨 뒤에 콜론 없이 그냥 붙는 일이 많다("채용여부 진행 연락처 042-542-2224").
# 그래서 일반 '라벨 : 값' 규칙으로는 안 잡힌다 — 번호 모양을 직접 찾는다.
_PHONE = r"0\d{1,2}\s*[-)]?\s*\d{3,4}\s*-?\s*\d{4}"
# '문의 : 053-650-9107' 처럼 낱말 하나로 쓰는 곳이 많다 — 감사에서 35건이 이 꼴로 새고
# 있었다 (2026-08-11). 번호 모양을 함께 요구하므로 '문의'가 다른 뜻으로 쓰여도 안 문다.
_CONTACT_LABELED = re.compile(rf"(?:연락처|문의\s*처?|문의\s*전화|전화\s*번호|담당자)\s*[:：]?\s*({_PHONE})")
_CONTACT_ANY = re.compile(rf"\(\s*({_PHONE})\s*\)")


# 이메일도 전화처럼 라벨 없이 던져 놓는 일이 많다 — 모양을 직접 찾는다 (워크오더 08-16 §5).
# TLD 2자 이상을 요구하므로 SNS @핸들('@podium_kr')이나 hwp 부스러기는 걸리지 않는다.
_EMAIL_SHAPE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def extract_email(text):
    """공고문에서 문의 이메일. 없으면 None."""
    if not text:
        return None
    m = _EMAIL_SHAPE.search(text)
    if not m:
        return None
    e = m.group(0).strip(".")
    return e if 6 <= len(e) <= 60 else None


def extract_contact(text):
    """공고문에서 문의 전화번호. 라벨이 붙은 번호를 먼저 찾고, 없으면 괄호 안 번호를 쓴다."""
    if not text:
        return None
    # '문 의 :' 처럼 칸 맞춤으로 띄운 라벨도 받는다 — extract_fields 만 눕히고 여기는
    # 안 눕혀서 연락처 31건이 새고 있었다 (2026-08-11 감사).
    t = squash_spaced_labels(re.sub(r"\s+", " ", text))
    m = _CONTACT_LABELED.search(t) or _CONTACT_ANY.search(t)
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(1))
# 값이 끝나는 자리 — 다음 항목 라벨, 글머리표, 번호 매김.
# 번호 매김은 뒤에 한글이 와야 인정한다. 그냥 '\d\.'로 잡으면 '2026. 7. 1 ~ 2026. 12. 31'의
# 날짜 중간에서 값이 잘린다 (2026-08-08).
_FIELD_STOP = re.compile(
    # hwp 표의 항목 기호가 문장 중간에서 다음 항목을 연다 —
    # '전일제 근무 바. 후생복지: … 사. 복무: …' (2026-08-10 사용자 지적).
    # 앞이 공백일 수도, 닫는 괄호일 수도 있고 글자와 마침표 사이가 벌어지기도 한다 —
    # '…변경될 수 있음)사 . 지원자 중 전형위원회의에서…' (2026-08-11).
    # 앞 글자가 한글이면 낱말의 일부다('회사 .') — 그건 건드리지 않는다.
    r"(?:(?<=[)\]])|(?<=\s)|^)[가나다라마바사아자차카타파하]\s*\.\s"
    r"|[•▪◦○●■□▶▷※📌🔹✅☎☞⇒→]|\s\d{1,2}\)\s*(?=[가-힣])|\[|\s\d\.\s(?=[가-힣])|(?:급여|보수|임금|처우|사례비|근무\s*기간|계약\s*기간"
    r"|근무\s*시간|담당\s*업무|주요\s*업무|나이|연령|근무\s*지|자격\s*요건|우대\s*사항|전형|제출|접수"
    r"|공연\s*기간|공연\s*장소|공연\s*스케[줄쥴]|팀\s*구성|휴일|모집\s*인원|모집\s*분야|제공\s*사항"
    r"|지원\s*방법|담당자|이메일)\s*[:：]"
    )

# 라벨을 하나씩 등록하는 방식은 끝이 없다. 값 안에 콜론이 나오면 그 앞의 한글 낱말(최대 두 개)을
# 라벨로 보고 그 앞에서 자른다 — '제한 없음 교원자격증 소지자: 중등학교…' → '제한 없음'.
# 정규식 하나로 하면 왼쪽부터 매치돼 '없음'이 라벨로 잡히고 '제한'만 남는다. 그래서 콜론을
# 먼저 찾고 뒤로 되짚는다 (2026-08-11).
# 숫자 뒤 콜론(9:00 같은 시각)은 앞이 한글이 아니므로 걸리지 않는다.
# ★ 낱말 경계에서만 시작해야 한다. 경계 없이 찾으면 '50만원 주소 :' 에서 '만원 주소'가
#   라벨로 잡혀 '50'만 남고, 그마저 '잘린 값'으로 버려져 사례비가 통째로 사라졌다 (2026-08-11).
_LABEL_TAIL2 = re.compile(r"(?:^|(?<=\s))[가-힣]{1,12}\s+[가-힣]{1,12}\s*$")
_LABEL_TAIL1 = re.compile(r"(?:^|(?<=\s))[가-힣]{1,12}\s*$")


def _cut_at_next_label(v):
    for m in re.finditer(r"[:：]", v):
        head = v[:m.start()]
        # 두 낱말 라벨('교원자격증 소지자')을 먼저 본다. 단 문장 첫머리부터면 그건 라벨이
        # 아니라 값 자체다('협의 주소 :' 의 '협의'는 값) — 한 낱말로 물러난다.
        mm = _LABEL_TAIL2.search(head)
        if mm and mm.start() == 0:
            mm = _LABEL_TAIL1.search(head)
        if not mm:
            mm = _LABEL_TAIL1.search(head)
        if mm and mm.start() > 0:
            return v[:mm.start()].strip(" ,·-–")
    return v


# 한글 공고문은 라벨 칸을 맞추려고 글자 사이를 벌린다 — '사 례 비 :', '교 회 명 :', '지  역 :'.
# 눈으로는 같은 말이지만 우리 규칙에는 안 걸려서, 성은교회 공고처럼 정보가 가득한 글에서
# 사례비·자격·업무를 하나도 못 뽑았다 (2026-08-09).
# 한 글자짜리 토막이 이어질 때만 붙인다 — '모집 분야'처럼 원래 띄어 쓰는 말은 건드리지 않는다.
_SPACED_LABEL = re.compile(r"(?:[가-힣]\s+){1,5}[가-힣](?=\s*[:：])")


# 주소 칸에는 '주소는 현재 거주하는 곳을 기재하며…' 같은 지원서 작성 안내가 들어 있는 일이
# 잦다. 시도 → 시군구 → 도로명·지번 순서를 갖춘 것만 주소로 인정한다 (2026-08-09).
_ADDR_OK = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"[가-힣]{0,3}\s*[가-힣]{1,10}(?:시|군|구)\s*[가-힣\d\s.\-()]{2,40}?(?:로|길|동|가|번지)\s*[\d\-]+")


def valid_addr(v):
    """주소 모양을 갖췄는가 — 안내 문구·양식 설명을 걸러낸다."""
    return bool(v and _ADDR_OK.search(v))


def squash_spaced_labels(text):
    """'사 례 비 :' → '사례비 :' 로 눕힌다. 라벨을 찾는 모든 추출기가 이 위에서 돈다."""
    if not text:
        return text
    return _SPACED_LABEL.sub(lambda m: re.sub(r"\s+", "", m.group(0)), text)


# '위표와 같음', '붙임 참조' 처럼 다른 곳을 가리키기만 하는 값 — 읽는 사람에게 아무 정보도
# 주지 않는다. 이런 값이 첫 번째로 걸리면 뒤에 있는 진짜 값을 못 보므로, 버리고 계속 찾는다
# (2026-08-10 사용자 지적).
_REFERENCE = re.compile(r"^(?:위|상기|아래|하기|별첨|붙임|첨부|공고문|본문|해당)?\s*(?:표|문|파일)?\s*"
                        r"(?:와|과|의)?\s*(?:같음|같습니다|동일|참조|참고|확인)[\s.·…]*$"
                        # 라벨 잘림 뒤 '첨부파일'만 덩그러니 남는 꼴도 정보가 0이다
                        r"|^(?:첨부\s*파일?|붙임|별첨|상세\s*요강|공고문|파일\s*첨부)[\s.·…]*$")


# ---- 교육청 구인 게시판의 표준 메타표 (2026-08-21) ----------------------
# 시도교육청 '학교인력채용 > 구인' 게시판은 상세 위쪽에 늘 같은 표를 얹는다:
#   기관명 학성초등학교 | 채용여부 채용중 | 주소 강원…원주시 치악로 2009-9 |
#   전화번호 033-737-1470 | 팩스 | 담당자 서미순 | E-mail … | 마감일자 2026-8-27-15:00
# 라벨과 값 사이에 구분자가 없고(콜론 없음) 빈 칸(팩스·홈페이지)도 그대로 흘러서,
# 일반 '라벨 : 값' 규칙이 통째로 헛돌았다. 주소는 다음 라벨에서 못 끊겨 버려졌고
# 기관명은 읽지도 못해 공고가 전부 '○○교육청(학교 채용)'으로 뭉쳐 있었다.
# 표 자체가 고정 서식이므로 라벨 집합을 알려 주고 통째로 읽는다.
_META_LAB = (r"기관명|채용\s*여부|주\s*소|전화\s*번호|팩스|담당자|[Ee]-?[Mm]ail|이메일|연락처|홈페이지"
             # 교육청마다 칸 이름이 조금씩 다르다 — 이 목록에 없는 이름은 값을 못 끊어
             # '인천중산고등학교 모집직종 기간'처럼 다음 칸이 통째로 딸려 온다 (2026-08-21)
             r"|마감\s*일자?|등록\s*일자?|모집\s*직종|모집\s*분야|학교\s*/\s*기관|담당\s*부서"
             r"|접수\s*기간|근무\s*기간|모집\s*인원|조회수?|첨부\s*파일|작성일")
_META_ROW = re.compile(rf"({_META_LAB})\s*[:：]?\s*(.*?)(?=\s*(?:{_META_LAB})\s*[:：]?\s|$)")
_META_KEY = {"기관명": "org", "채용여부": "status", "주소": "addr", "전화번호": "contact",
             "담당자": "manager", "이메일": "email", "연락처": "contact",
             "마감일자": "deadline", "마감일": "deadline", "학교/기관": "org"}
# 기관명 칸에서 실제로 채택할 이름꼴. 이 검증이 없으면 표 머리('조회, 등록일, 마감일…')를
# 기관 이름으로 믿어 버린다 — 제주교육청 공고가 실제로 그랬다 (2026-08-21).
_ORG_SHAPE = re.compile(
    r"[가-힣A-Za-z0-9]{2,20}(?:초등학교|중학교|고등학교|중고등학교|특수학교|유치원|학교"
    r"|대학교|대학|교육청|교육지원청|교육지원센터|문화재단|재단|센터|도서관|병설유치원)")


def parse_meta_table(text):
    """교육청 구인 게시판 메타표 → dict. 표가 없으면 빈 dict."""
    if not text or "기관명" not in text:
        return {}
    t = re.sub(r"\s+", " ", text)
    i = t.find("기관명")
    win = t[i:i + 500]   # 기관명부터 마감일자까지가 붙어 있다 — 한 창만 본다
    out = {}
    for m in _META_ROW.finditer(win):
        lab = re.sub(r"\s+", "", m.group(1))
        val = m.group(2).strip(" .,·-–:：")
        key = _META_KEY.get(lab) or ("email" if "mail" in lab.lower() else None)
        if key and val and not out.get(key):
            out[key] = val
    if out.get("addr"):
        # 전북교육청 표는 우편번호를 앞에 단다 — '(54862) 전북특별자치도 전주시…'
        out["addr"] = re.sub(r"^[(（]\d{5}[)）]\s*", "", out["addr"])
        # 주소 칸은 교육청마다 서식이 제각각이라(전화·팩스가 한 칸에 뭉쳐 있기도 하다)
        # 시도명으로 시작하는 깔끔한 값만 받는다. 지역 판정에 쓰이는 값이라 반쯤 맞는 것을
        # 들이면 공고가 엉뚱한 시도로 넘어간다 — 그럴 바엔 기존 경로에 맡긴다 (2026-08-21).
        if not re.match(r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충[북남]"
                        r"|전[북남]|경[북남]|제주)[가-힣]{0,8}\s", out["addr"]):
            out.pop("addr")
    if out.get("deadline"):
        md = re.match(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", out["deadline"])   # '2026-8-27-15:00'
        out["deadline"] = f"{md.group(1)}-{int(md.group(2)):02d}-{int(md.group(3)):02d}" if md else None
    if out.get("org"):
        mo = _ORG_SHAPE.search(out["org"])
        out["org"] = mo.group(0) if mo else None   # 이름꼴이 없으면 표를 잘못 읽은 것이다
    return {k: v for k, v in out.items() if v}


# ---- 경남교육청 구인·구직포털 상세 (2026-08-23) --------------------------
# 이 포털은 목록 행에 학교 이름을 싣지 않는다. 그래서 파서가 기관을 게시판 이름
# ('경남 학교 방과후(교육청 포털)')으로 뭉쳐 두었고, 공고 카드가 전부 같은 기관으로 떴다.
# 상세엔 학교 이름이 두 군데 있다:
#   ① 머리표 '작성자 양산남부고 등록일 …'  ② 본문 '양산남부고등학교에서는 …'
# ①은 줄임 표기라 _ORG_SHAPE(정식 이름꼴)를 통과하지 못한다. ①을 실마리 삼아 ②에서
# 같은 학교의 정식 명칭을 찾아 쓰고, ②가 없을 때만 ①을 학교 약칭 규칙으로 펼친다.
# ★ _ORG_SHAPE 를 '고·중·초'까지 받도록 넓히지 말 것 — 그러면 아무 낱말이나 기관명으로
#   통과한다(사용자 지시 2026-08-23). 검증은 언제나 정식 이름꼴로 한다.
_GNE_WRITER = re.compile(r"작성자\s+([가-힣A-Za-z0-9]{2,20}?)\s+등록일")
_GNE_REGION = re.compile(r"지역\s+([가-힣]{2,8}?)\s+(?:채용상태|접수)")
# 학교 약칭 → 정식 명칭. '여고'를 '고'보다 먼저 봐야 '진주여고 → 진주여고등학교'가 안 된다.
_SCHOOL_ABBR = re.compile(r"^([가-힣]{2,12}?)(여고|여중|고|중|초)$")
_ABBR_FULL = {"고": "고등학교", "중": "중학교", "초": "초등학교",
              "여고": "여자고등학교", "여중": "여자중학교"}
_SCHOOL_SUF = r"(?:초등학교|중학교|고등학교|중고등학교|특수학교|병설유치원|유치원)"


def parse_gne_detail(text):
    """경남교육청 구인·구직포털 상세 → {"org", "region"}. 못 읽으면 빈 dict."""
    t = re.sub(r"\s+", " ", text or "")
    out = {}
    mw = _GNE_WRITER.search(t)
    if mw:
        writer = mw.group(1)
        ma = _SCHOOL_ABBR.match(writer)
        base = ma.group(1) if ma else writer
        if _ORG_SHAPE.fullmatch(writer):
            out["org"] = writer                       # 작성자가 이미 정식 명칭
        elif len(base) >= 2:
            # ② 본문에서 '작성자'와 같은 학교의 정식 명칭 — 앞 글자가 겹치는 것만 받는다.
            #    본문 전체를 _ORG_SHAPE 로 훑으면 '방과후학교강사'의 '방과후학교'를 문다.
            m = re.search(re.escape(base) + r"[가-힣]{0,6}?" + _SCHOOL_SUF, t)
            if m and _ORG_SHAPE.fullmatch(m.group(0)):
                out["org"] = m.group(0)
            elif ma:
                # ①만 있는 공고(남해정보산업고) — 약칭을 펼쳐 정식 이름꼴로 검증한다
                cand = base + _ABBR_FULL[ma.group(2)]
                if _ORG_SHAPE.fullmatch(cand):
                    out["org"] = cand
    # 지역: 상세 머리표의 '지역 양산' 칸. 시군 이름이라 시도로 못 옮겨지는 곳이 많고
    # (남해·고성·거창…), 이 게시판은 경남교육청 것이므로 못 옮기면 경남이 맞다.
    mr = _GNE_REGION.search(t)
    rg = region_from(mr.group(1)) if mr else "기타"
    out["region"] = rg if rg != "기타" else "경남"
    return out


# 보수를 '라벨 : 값'으로 못 찾는 표가 있다 — hwp 표를 평탄화하면 헤더 행과 값 행이
# 한 줄로 붙어 라벨(보수)과 값(기본급 199만원)이 멀리 떨어진다:
#   '직위 신분 보수 근무시간 위촉기간 지휘자 비상임 기본급 1,990,000원/월, 연주수당 150,000원/회'
# 그래서 '보수' 뒤 아무 금액이나 물어 **연주수당 15만원만** 실리고 기본급 월 199만원은
# 통째로 빠졌다 (양주시립교향악단 지휘자, 2026-08-23). 15만원만 보이면 오해를 부른다.
# 연락처·이메일처럼 **모양으로** 찾는다 — 급여 낱말이 금액을 직접 데리고 다니는 꼴만 받고,
# 여럿이면 모두 싣는다(기본급과 수당은 둘 다 알아야 할 조건이다).
_PAY_SHAPE = re.compile(
    r"(?:기본급|기본\s*보수|월\s*급여|월\s*보수|월\s*정액|연봉|시급|시간당|일당|일급|회당|건당"
    r"|강사료|강사비|지도비|강의료|출연료|연주\s*수당|지도\s*수당|수당)"
    r"\s*[:：]?\s*(?:금\s*)?[\d,]{3,}\s*(?:만\s*)?원(?:\s*/\s*[가-힣]{1,3}|\s*[/(]\s*[가-힣]{1,4}\s*[)]?)?")


def pay_from_shape(text):
    """급여 낱말이 금액을 직접 데리고 있는 구절을 모두 모은다. 없으면 None."""
    if not text:
        return None
    t = squash_spaced_labels(re.sub(r"\s+", " ", text))
    seen, out = set(), []
    for m in _PAY_SHAPE.finditer(t):
        v = tidy_spacing(m.group(0))
        key = re.sub(r"\D", "", v)          # 같은 금액이 되풀이되면 한 번만
        if key and key not in seen:
            seen.add(key)
            out.append(v)
        if len(out) >= 3:                   # 표 전체를 옮겨 오지 않는다
            break
    return ", ".join(out) if out else None


def extract_fields(text):
    """공고문에서 '라벨 : 값' 항목들을 뽑는다. 못 찾은 항목은 아예 넣지 않는다.

    한 라벨이 여러 번 나오면 **쓸모 있는 값이 나올 때까지** 훑는다. 예전엔 첫 번째만 보고
    끝냈는데, 그 자리가 '위표와 같음'이면 뒤에 적힌 실제 값을 영영 못 읽었다.
    """
    if not text:
        return {}
    t = squash_spaced_labels(re.sub(r"\s+", " ", text))
    out = {}
    for key, pat in _FIELD_SPECS:
        # 1차: 콜론·하이픈으로 나뉜 정상 표기. 2차: 구분자 없이 띄어쓰기만 있는 납작한 표.
        # 2차는 모양 검사(_SHAPE)가 있는 항목에만 허용한다 — 담당업무처럼 서술형인 항목은
        # 느슨하게 열면 '… 담당 업무 및 통계자료 등 자료제공을 위한 메뉴 …' 같은 산문
        # 한복판을 물어온다 (2026-08-11 감사에서 8건).
        modes = (False, True) if key in _SHAPE else (False,)
        # 모양이 안 맞는 강한 모드 값 — 버리진 않고 미뤄 둔다 (아래)
        weak = None
        for loose in modes:
            for val in _candidates(t, pat, loose=loose):
                v = _clean_field(key, val)
                if not v:
                    continue
                if key in _SHAPE and not _shape_ok(key, v):
                    # 콜론이 붙었다고 다 값은 아니다 — '근무 기간 : 상기 채용 기간 참고'
                    # (망포중, 2026-08-22)처럼 다른 데를 가리키는 안내가 흔하다. 이걸 덥석
                    # 받으면 같은 표에 '채용기간 2026/09/01~2026/09/11'이 멀쩡히 있는데도
                    # 못 읽고, QC 가 '모양 불일치'로 버려 빈칸이 된다.
                    # 그렇다고 통째로 버리면 모양 검사가 모르는 정상 표기를 잃으므로,
                    # 더 나은 값이 끝내 없을 때만 쓴다. 느슨한 모드 값은 미뤄 두지 않는다
                    # (구분자가 없어 경계가 흐린데 모양까지 안 맞으면 값이 아니다).
                    if not loose:
                        weak = weak or v
                    continue
                out[key] = v
                # 기간 칸 머리에서 떼어낸 표 앞 열의 인원은 버리지 말고 제 칸으로 돌려보낸다.
                # (같이 붙어 온 과목명은 넣을 안전한 칸이 없어 흘려보낸다 — 악기 태그는
                #  제목·모집구획에서 따로 뽑히므로 여기서 짐작해 넣으면 오염만 는다.)
                if key in ("workPeriod", "perfPeriod"):
                    _, cnt = lead_subject_count(val)
                    if cnt:
                        out.setdefault("personnel", cnt)
                break
            if key in out:
                break
        if key not in out and weak:
            out[key] = weak
    # 서울일자리포털(work.sen)은 담당업무를 '과목 (담당업무) 값 채용기간 …' 꼴 납작한 표로
    # 낸다. 구분자가 없어 강한 모드가 못 잡고, duty 는 서술형이라 느슨한 모드를 열 수 없다
    # (열면 산문 한복판을 물어온다 — 위 주석). 이 라벨은 표 머리에만 쓰는 말이라 그 꼴만
    # 따로 받는다 (2026-08-20 감사: 담당업무 미추출 8건이 전부 이 형태였다).
    if "duty" not in out:
        m = _SUBJECT_DUTY_CELL.search(t)
        if m:
            win = t[m.end():m.end() + 240]
            # 다음 라벨이 창 안에 없으면 납작한 표가 아니다 — 산문을 물어오지 않도록 포기한다
            nxt = _LABEL_WORDS.search(win)
            v = _clean_field("duty", win[:nxt.start()]) if nxt else None
            if v:
                out["duty"] = v
    # '모집분야: 플루트 파트 강사 1명'(양산남부고) — 역방향 감사와 _find_duty 는 이것도
    # 담당업무 라벨로 보는데 추출기에만 빠져 있어 아무도 안 뽑고 있었다 (2026-08-22).
    # **담당업무를 못 찾았을 때만** 본다. 같은 자격으로 두면 대개 앞에 있는 모집분야가
    # 이기는데, 그건 직무 설명이 아니라 자리 이름이라 값이 나빠진다
    # ('예배 전 찬양인도, 행정' → '전임전도사(남0명)').
    if "duty" not in out:
        for val in _candidates(t, r"모집\s*분야|모집\s*부문|채용\s*분야", loose=False):
            v = _clean_field("duty", val)
            if v:
                out["duty"] = v
                break
    return out


# 납작한 표에서 뽑을 때만 쓰는 모양 검사 — 구분자가 없어 값의 경계가 흐리기 때문이다.
_SHAPE = {
    # 기간이면 범위(~)가 있거나, 날짜를 나열하고 시수를 다는 꼴이다 —
    # '2026.9.7.(월) 3시간, 9.8.(화) 3시간, 9.9(수) 3시간' (인천중산고, 2026-08-18)
    # 물결표는 종류가 여럿이다 — 공고문에 전각(～)이 흔한데 빠져 있어서
    #   '2026.8.18.～2027.2.28' 같은 멀쩡한 기간이 모양 검사에서 떨어졌다 (2026-08-22).
    "workPeriod":   re.compile(r"\d{1,4}\s*[.\-/년]\s*\d{1,2}.*?(?:[~∼～〜-]|시간)"),
    "perfPeriod":   re.compile(r"\d{1,4}\s*[.\-/년]\s*\d{1,2}.*?[~∼～〜-]"),
    "pay":          re.compile(r"[\d,]{2,}\s*(?:만\s*)?원|시급|일당|협의"),
    # 숫자 하나만 요구하면 아무 문장이나 통과한다 — 인원 칸의 모양은 'N명'이다 (2026-08-22)
    # 숫자 하나만 요구하면 아무 문장이나 통과한다 — 인원 칸의 모양은 'N명'이다 (2026-08-22).
    # 단위 없이 숫자만 남은 칸('모집: 1', 강화중)은 tidy_personnel 이 '명'을 붙이므로 받는다.
    "personnel":    re.compile(r"\d\s*(?:명|인)|[Oo○]\s*명|^\s*\d{1,3}\s*$"),
    "workHours":    re.compile(r"전일제|시간제|주\s*\d|\d\s*시간|\d{1,2}\s*[:시]|요일|근무"),
    # 주소는 _ADDR_OK 가 곧 모양 검사다 — 이걸 빼먹어 납작한 표('- 주소 경기 부천시…')의
    # 주소 추출이 통째로 죽었었다 (2026-08-11 감사에서 19→43건 회귀로 발각)
    "addr":         _ADDR_OK,
    "ageLimit":     re.compile(r"\d|제한\s*없"),
    "contact":      re.compile(r"\d{2,}"),
}


def _shape_ok(key, v):
    pat = _SHAPE.get(key)
    return True if pat is None else bool(pat.search(v))


# 표가 납작하게 펴지면 라벨과 값 사이에 아무 기호도 없다 —
#   '채용기간 2026.09.01~2027.02.28 접수기간 2026.08.04 …'
#   '근무시간 전일제 보수/임금 접수방법 …'
# 이때는 다음 '라벨처럼 생긴 낱말'에서 값을 끊어야 한다. 콜론이 없으니 _cut_at_next_label 이
# 못 쓰인다 (2026-08-11).
_LABEL_WORDS = re.compile(
    r"(?:접수\s*기간|채용\s*기간|계약\s*기간|근무\s*기간|공고\s*기간|근무\s*시간|근무\s*조건"
    r"|보수\s*/?\s*임금|보수|급여|채용\s*인원|모집\s*인원|담당\s*업무|제출\s*서류|제출\s*장소"
    r"|제출\s*방법|접수\s*방법|상세\s*요강|채용\s*과목|채용\s*사유|과목|담당\s*업무|자격|비고|첨부|문의"
    # 교육청 구인 게시판 메타표 칸 이름 — 이게 없어 '주소 …원주시 치악로 2009-9 전화번호
    # 033-737-1470 팩스 담당자 …'가 한 덩어리로 흘러 주소 추출이 통째로 죽었다 (2026-08-21)
    r"|전화\s*번호|팩스|담당자|[Ee]-?[Mm]ail|이메일|홈페이지|마감\s*일자|채용\s*여부|기관명|연락처)")


# 목록 화면이 스스로 밝힌 총건수(예: 하이브레인 '음악학(5)'). 파서 자기검증용 —
# 수집량 baseline 은 '평소보다 적은가'만 짐작하지만, 이 수는 '다 읽었는가'를 곧바로 말한다.
# 소스 파서가 declare_total 로 적어 두면 main.py 가 소스 요약에 실어 헬스체크로 넘긴다.
DECLARED_TOTALS = {}


def declare_total(sid, n):
    """목록 화면에 적힌 총건수를 기록한다 (모르면 부르지 않는다)."""
    if isinstance(n, int) and n >= 0:
        DECLARED_TOTALS[sid] = n


# 서울일자리포털의 표 머리 '과목 (담당업무)' — 라벨이 괄호를 품고 있어 일반 라벨 규칙에
# 안 걸린다. 값은 바로 뒤 라벨 낱말에서 끊는다(값이 비어 바로 다음 라벨이면 아무것도 안 남는다).
_SUBJECT_DUTY_CELL = re.compile(r"과\s*목\s*[(（]\s*담당\s*업무\s*[)）]")


# 페이지 꼬리표(푸터) 표식 — 이 근처의 라벨은 공고 본문이 아니라 사이트 안내다
_PAGE_FOOTER = re.compile(
    r"민원실|민원기동대|대표전화|대표번호|Copyright|All Rights Reserved|무단전재|누리집|개인정보처리방침")


def _candidates(t, pat, loose=False):
    """라벨 뒤에 오는 값 후보들 — 구분자는 콜론이 흔하지만 하이픈도 쓴다.

    loose=True 면 구분자 없이 띄어쓰기만으로 이어진 것도 받는다(납작해진 표). 그 경우
    값은 다음 라벨 낱말에서 끊는다. 느슨한 만큼 호출부가 모양 검사를 함께 한다.

    ★ 값을 정규식으로 붙잡지 않고 라벨까지만 매치한 뒤 뒤를 잘라 낸다. 값을 `.{2,160}` 으로
      붙잡으면 그 160자 안에 든 다음 라벨까지 삼켜 버려서, finditer 가 두 번째 후보를 아예
      못 본다 — '가. 근무기간 : 위표와 같음 나. 근무기간 : 2026. 8. 14. ~' 에서 뒤엣것을
      영영 못 읽었다 (2026-08-10).
    """
    sep = r"(?:[:：]|[-–—]\s|\s)" if loose else r"(?:[:：]|[-–—]\s)"
    for m in re.finditer(rf"(?:{pat})\s*{sep}\s*", t):
        # 페이지 꼬리표(민원실 안내·저작권 표시)에 박힌 라벨은 공고 내용이 아니다 —
        # 인천교육청 푸터의 '근무시간 09:00~18:00(수요일…)'이 학교 근무시간으로 실렸다
        # (2026-08-17). 그럴듯해서 더 위험한 값이라 후보 단계에서 버린다.
        if _PAGE_FOOTER.search(t[max(0, m.start() - 120):m.end() + 160]):
            continue
        seg = t[m.end():m.end() + 160]
        if loose:
            nxt = _LABEL_WORDS.search(seg)
            if nxt and nxt.start() == 0:
                continue     # 라벨 바로 다음이 또 라벨 = 이 칸은 비어 있다('근무시간 보수/임금 …')
            if nxt and nxt.start() > 0:
                seg = seg[:nxt.start()]
        if len(seg.strip()) >= 1:
            yield seg


# 기간 값이 시작하는 자리 — '2026.09.07', '2026-09-07', '2026년 9월 7일', '26.9.7'
_DATE_START = re.compile(r"(?:20)?\d{2}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}")
# 표 앞 열에 딸려 온 '과목 인원' — 버리지 않고 해당 필드로 넘길 수 있게 떼어 둔다
_LEAD_SUBJ_CNT = re.compile(r"^([가-힣]{2,10})\s*(\d{1,3}\s*명)\b")
# 근무시간 값이 시작하는 자리 — 'HH:MM', '전일제', '시간제'. 요일·시수는 넣지 않는다
# (앞 열 판정에만 쓰므로 모호한 신호를 넣으면 멀쩡한 값을 자른다).
_TIME_START = re.compile(r"\d{1,2}\s*:\s*\d{2}|전일제|시간제")


def lead_subject_count(raw):
    """기간 칸 머리에 붙어 온 '음악 1명' 같은 앞 열 값 → (과목, 인원). 없으면 (None, None).

    표를 평탄화하면 데이터행의 앞 열이 뒤 칸 값에 붙어 온다. 그냥 잘라 버리면 인원 정보가
    통째로 사라지므로, 떼어낸 조각을 제 칸으로 돌려보낸다 (가운고, 워크오더 08-17 §3).
    """
    m = _LEAD_SUBJ_CNT.match((raw or "").strip())
    if not m:
        return None, None
    return m.group(1), re.sub(r"\s+", "", m.group(2))


# hwp 뷰어가 낱말마다 공백을 넣어 렌더한 값을 사람이 읽는 꼴로 되돌린다 —
# '화요일 , 목요일', '지도 ( 보컬 혹은 밴드 세션 ) 및', '강사(악기 무관)1명'
# (강원교육청 게시판, 2026-08-21). 추출 경로가 여럿이라 함수로 뺐다 — _clean_field 만
# 고쳐 놨더니 담당업무·자격처럼 전용 추출기를 쓰는 항목이 그대로 벌어진 채 나왔다.
def tidy_spacing(v):
    if not v:
        return v
    t = re.sub(r"\s+", " ", str(v))
    t = re.sub(r"\s*([()（）])\s*", r"\1", t)          # 괄호 안팎 공백 제거
    t = re.sub(r"([)\]）])(?=[가-힣\d])", r"\1 ", t)   # 닫는 괄호 뒤엔 한 칸
    # '16:00주 22시수'(대청중) · '11:001시간 주 2회'(숭신병설유치원, 2026-08-22) —
    # 시각 뒤에 낱말도 숫자도 바로 붙는다. 숫자까지 받도록 넓혔다.
    t = re.sub(r"(?<=\d:\d\d)(?=[가-힣\d])", " ", t)
    # 반대로 단위는 숫자에 붙여 준다 — '40,000 원', '1 명'. 단위 낱말만 골라야 한다:
    # 아무 한글에나 붙이면 '10:00~11:50 토요일'이 '11:50토요일'이 된다.
    t = re.sub(r"(?<=[\d,])\s+(?=(?:원|명|인|매|부)(?![가-힣]))", "", t)
    # 쉼표 앞 공백만 지운다 — 가운뎃점은 항목을 잇는 구분자로도 쓰여(' · ') 건드리면
    # 오히려 붙어 버리고, 마침표는 날짜('2026. 9.')를 망친다.
    t = re.sub(r"\s+([,、])", r"\1", t)
    # 목록 번호 접두는 괄호꼴만 뗀다 — 'N.'까지 떼면 날짜를 먹는다
    # ('9.21.(월)~9.23.(수) …' → '21.(월)~…', 서울남성초 2026-08-21)
    t = re.sub(r"^\d{1,2}\)\s*", "", t)
    # hwp 표의 항목 기호('가 . 나 . 다 .')는 다음 칸의 머리글자가 딸려 온 것이다.
    # 마침표 앞 공백을 통째로 지우면 날짜('2026. 9.')가 붙어 버리므로 이 꼴만 다룬다.
    t = re.sub(r"\s+[가나다라마바사아자차]\s*\.(?=\s|$)", "", t)
    return t.strip(" .,·-–")


def _clean_field(key, raw):
    """값 하나를 다듬고 검사한다. 쓸 수 없으면 None을 돌려 다음 후보로 넘긴다."""
    # 값이 대괄호로 시작하면 여는 괄호만 뗀다 — '[겸임 11명 / 초빙 18명]'을 _FIELD_STOP 의
    # '[' 가 통째로 잘라 빈 값이 됐다 (2026-08-11).
    # 글머리표도 마찬가지다 — '모집인원 ○ 유급단원(지도단원) 1인'의 ○ 가 다음 항목 표시로
    # 읽혀 값 전체가 지워졌다 (종로구립, 2026-08-18). 맨 앞 것만 떼고 안쪽은 그대로 둔다.
    raw = raw.lstrip("[ •▪◦○●■□▶▷※")
    val = _cut_at_next_label(_FIELD_STOP.split(raw, 1)[0])
    if "[" not in val:
        val = val.replace("]", " ")      # 여는 짝을 위에서 뗐으니 닫는 짝만 남으면 지운다
    # hwp·OCR 추출이 숫자와 단위를 벌려 놓는다 — '2,299,000 원', '만 34 세', '4 대보험'
    val = re.sub(r"(?<=\d)\s+(?=[\d,.])", "", val)
    val = re.sub(r"(?<=\d)\s+(?=[가-힣])", "", val)
    val = re.sub(r"\s*([()])\s*", r"\1", val).strip(" .,·-–")
    val = tidy_spacing(val)
    # hwp 표의 항목 기호(가.나.다.라…)가 다음 칸 머리글자로 딸려 온다
    val = re.sub(r"\s+[가나다라마바사아자차]\.?$", "", val).strip(" .,·-–")
    # 숫자 바로 뒤에 라벨이 띄어쓰기 없이 붙는다 — '2027-02-28지원서' (2026-08-12 전라중)
    val = re.sub(r"(?<=\d)(?:지원서|접수|제출|서류|첨부|공고)[가-힣]*$", "", val)
    # hwp 번호 매김 꼬리 — '…단축될 수 있음)2)' 의 2) 는 다음 항목 번호다 (한솔중)
    val = re.sub(r"\s*\d{1,2}\)\s*$", "", val).strip(" .,·-–")
    # 닫는 괄호 직후의 고아 숫자 — '…음악 문학의 이해)4' 의 4 는 표에서 딸려 온 다음 항목
    # 번호다 (강원사대부설고, 워크오더 08-16 §4)
    val = re.sub(r"(?<=[)\]])\s*\d{1,2}$", "", val).strip(" .,·-–")
    # 채용시스템 표 머리가 값 머리에 연쇄로 딸려 온다 — '과목 인원 채용기간 비고 음악 1명
    # 2026.09.07.…' (가운고). 머리만 걷어내면 실값이 살아 있으므로 버리지 않고 절단한다
    # (워크오더 08-16 §1).
    val = re.sub(r"^(?:(?:과목|인원|성명|비고|구분|학교급|근무형태|채용사유|채용기간|계약기간|근무기간)(?:\s+|$)){2,}",
                 "", val).strip(" .,·-–")
    # 기간 칸은 날짜에서 시작한다 — 헤더를 걷어내도 표의 앞 열('음악 1명')이 남아 있었다
    # (가운고, 워크오더 08-17 §3). 낱말을 하나씩 지우는 대신 날짜부터 채택한다.
    if key in ("workPeriod", "perfPeriod"):
        m_d = _DATE_START.search(val)
        if m_d and m_d.start() > 0:
            val = val[m_d.start():].strip(" .,·-–")
    # 근무시간 칸도 같은 일을 당한다 — 표를 평탄화하면 앞 열이 통째로 딸려 온다.
    # '4, 5세 학급 음악활동 협력강사 1명 2026. 9. 2.(수)~ 2026. 12. 11.(금) 10:00~11:00 1시간 주 2회'
    # (숭신병설유치원, L4#2 2026-08-22 — 직종·인원·근무기간 세 칸이 근무시간 칸에 붙었다).
    # 기간 칸과 같이 '시각부터 채택'하되, **앞부분에 인원이나 날짜가 있을 때만** 자른다 —
    # 무조건 자르면 '방과후 15:50~17:20'의 '방과후' 같은 정상 수식어까지 날아간다.
    if key == "workHours":
        m_h = _TIME_START.search(val)
        head = val[:m_h.start()] if m_h else ""
        if m_h and head and (re.search(r"\d\s*명", head) or _DATE_START.search(head)):
            # 앞머리의 요일 표기는 근무시간의 일부다 — '월,화,수 1명 17:30~22:00' 에서
            # 인원만 걷어내고 요일은 남긴다. 낱말 첫 글자('수업')를 요일로 오인하지 않도록
            # 요일 글자 뒤에 구분자가 오는 것만 인정한다.
            m_w = re.match(r"^\s*(?:[월화수목금토일](?=[\s,·/]|$)\s*[,·/]?\s*)+", head)
            days = m_w.group(0).strip(" ,·/") if m_w else ""
            val = (f"{days} " if days else "") + val[m_h.start():].strip(" .,·-–")
    # 여는 괄호만 있고 닫히지 않은 값 — 다음 라벨에서 잘린 흔적이다.
    # '09:00~18:00(수요일' → '09:00~18:00' (워크오더 08-17 §4)
    if val.count("(") > val.count(")"):
        val = val[:val.rindex("(")].strip(" .,·-–")
    # goe 채용시스템 꼬리 UI — '24시간 복리후생 근무지역 주소 지도검색' 의 복리후생 이후는
    # 화면 조각이다. 콜론 없이 붙으므로 _FIELD_STOP 이 못 자른다 (진접고, 워크오더 08-16 §1).
    val = re.split(r"\s(?:복리\s*후생|근무\s*지역|지도\s*검색)(?=\s|$)", val, 1)[0].strip(" .,·-–")
    # ice 채용란은 라벨 사이 공백이 아예 없다 — '1채용시작일 2026/09/07채용종료일 2026/09/09
    # 채용방법 병행 채용'. 첫 라벨 앞에서 끊으면 머리의 실값('1'=인원)이 남는다
    # (인천중산고, 워크오더 08-16 §2).
    val = re.split(r"(?<=[0-9가-힣])(?=채용(?:시작일|종료일|방법|공고|담당))", val, 1)[0].strip(" .,·-–")
    # '-자세한 사항은' 같은 안내 꼬리 (한솔중 근무시간)
    val = re.sub(r"\s*[-–]?\s*자세한\s*사항.*$", "", val).strip(" .,·-–")
    if not val:
        return None
    # 다른 곳을 가리키기만 하는 값 — '위표와 같음', '붙임 참조'. 정보가 0이다.
    if _REFERENCE.match(val):
        return None
    # 게시판이 값을 잘라 놓은 경우 — '접수기간 : 2026.' 처럼 연도만 남은 것
    # 게시판이 값을 잘라 놓은 경우 — '접수기간 : 2026.' 처럼 연도만 남은 것.
    # 인원은 예외다. '채용인원 1' 의 '1' 은 잘린 게 아니라 그게 값이다 (2026-08-11).
    if key != "personnel" and re.fullmatch(r"20\d{2}\.?|\d{1,2}\.?|[\d.\-/~\s]{0,7}", val):
        return None
    # hwp 추출이 깨지면 한자 부스러기가 섞인다 — '제8 捤獥 汤捯 氠瑢 기간제교원'
    if len(re.findall(r"[一-鿿]", val)) >= 2:
        return None
    if key == "pay":
        # 게시판이 단위를 빼고 적는 경우가 있다 — 서울교육일자리포털은 '보수/임금 시급 40000'
        # 처럼 '원'이 없다. 화면에 그대로 나가면 '시급 40000'이 되어 읽는 사람이 단위를
        # 짐작해야 한다 (2026-08-20). 금액이 분명하면 '원'을 붙이고 천 단위를 끊는다.
        m_bare = re.fullmatch(r"\s*((?:시급|시간당|일당|월급|월|주급|회당|연봉)?)\s*([\d,]{3,})\s*", val)
        if m_bare:
            unit, num = m_bare.group(1), m_bare.group(2).replace(",", "")
            if num.isdigit() and int(num) >= 1000:
                val = (unit + " " if unit else "") + f"{int(num):,}원"
        # 급여 자리의 법령 인용은 읽어도 얼마인지 알 수 없다
        if not re.search(r"[\d,]{2,}\s*(?:원|만|천)", val)                 and re.search(r"보수규정|예규|조례|지침|규정|법률|제\s*\d+\s*조", val):
            return None
        # 금액까지만 남긴다 — 뒤에 복무·보험 설명이 이어지면 카드에서 읽히지 않는다
        m2 = re.search(r"(?:시간당|시급|월|주|일당|회당|연간?)?\s*[\d,]{2,}\s*(?:만\s*)?원"
                       r"(?:\s*\([^)]{1,10}\))?", val)
        if m2:
            val = val[:m2.end()].strip(" ,·-–")
    if key == "addr":
        m3 = _ADDR_OK.search(val)
        if not m3:
            return None
        # 주소 부분만 남긴다. 뒤에 게시판 UI('인근전철역 근무예정지 지도보기 목록보기')가
        # 통째로 딸려 온 것이 감사에서 나왔다 (2026-08-11). 매치 끝의 짧은 꼬리
        # ('(송림동)6층' 같은 동·층 표기)까지만 붙인다.
        tail = re.match(r"[\s\d\-]*(?:\([^)]{1,14}\))?\s*[\d]*층?", val[m3.end():])
        val = (val[m3.start():m3.end()] + (tail.group(0) if tail else "")).strip(" ,·-–")
    if key == "duty" and len(val) > 80:
        # 담당업무가 길면 첫 항목 경계에서 끊는다 — 통째로 버리면('빈칸 과감히'라 해도)
        # 머리에 든 알짜('주 2회 정기연습 및 공연준비')까지 잃는다.
        cut = re.split(r"\s[-*∙•]\s|(?<=[다음됨함])\s(?=[가-힣])", val, 1)[0].strip(" ,·-–")
        val = cut if len(cut) >= 8 else val
    # 인원은 '1' 처럼 한 글자도 정상값이다
    lo = 1 if key == "personnel" else 2
    return val if lo <= len(val) <= 140 else None


# 학교 이름을 우리가 쓰는 짧은 형태로 줄인다. 게시판마다 제목이 제각각이라
# ('(고현초) 교과전담…', '안양예술고등학교 음악과…', '충암중학교 휴직 대체…')
# 카드에서 한눈에 안 들어온다. 맨 앞 [약칭]으로 통일한다 (2026-08-08 사용자 지시).
_SCHOOL_KINDS = [
    (r"여자중학교", "여중"), (r"여자고등학교", "여고"),
    (r"예술고등학교", "예고"), (r"예술중학교", "예중"),
    (r"초등학교", "초"), (r"중학교", "중"), (r"고등학교", "고"),
]
# 시도 접두어는 떼지 않는다. '대전선암초등학교'가 정식 명칭이라 '선암초'로 줄이면
# 다른 지역의 같은 이름과 헷갈리고, '서울예술고등학교'는 아예 뜻이 달라진다 (2026-08-08).


# 제목이 이미 줄여 쓴 형태('2026 서정초 동아리…', '해성국제컨벤션고 협력강사…')도 받는다.
# '고'로 끝나는 말은 학교가 아닌 경우가 많아 걸러낸다.
_NOT_SCHOOL = {"공고", "참고", "최고", "보고", "신고", "사고", "광고", "권고", "경고", "재공고"}
_SHORT_SCHOOL = re.compile(r"^([가-힣]{2,10}(?:여중|여고|예고|예중|초|중|고))(?=\s)")


# 교회·대학은 이름을 줄이지 않고 그대로 앞에 세운다 — '[인덕원꿈의교회]', '[홍익대학교]'
# (2026-08-09 사용자 지시). 학교만 약칭을 쓰는 건 이름이 길어서다.
_ORG_FULLTAG = re.compile(r"^([가-힣A-Za-z]{2,14}(?:교회|성당|채플|대학교|대학원))(?:\b|$)")


def school_short(name):
    """카드 앞에 세울 기관 딱지. 학교는 줄이고('서울고현초등학교'→'고현초'),
    교회·대학은 그대로 쓴다('인덕원꿈의교회'). 해당 없으면 None."""
    if not name:
        return None
    # 괄호 꼬리를 떼고 교회·대학인지 먼저 본다 ('교회(기독정보넷)'처럼 기관 미상인 폴백은
    # 이름이 아니므로 제외한다 — 그건 딱지로 쓸 수 없다)
    _bare = re.sub(r"\([^)]*\)", "", str(name)).strip()
    if _bare not in ("교회", "성당") and not _bare.startswith("교회("):
        m_full = _ORG_FULLTAG.match(_bare)
        if m_full:
            return m_full.group(1)
    n = re.sub(r"\([^)]*\)", "", str(name)).strip()          # '(서울시교육청)' 같은 꼬리 제거
    m = re.search(r"([가-힣]{2,12}(?:여자|예술)?(?:초등학교|중학교|고등학교))", n)
    if not m:
        # 정식 명칭이 없으면 이미 줄여 쓴 형태를 본다 (앞머리 연도는 건너뛴다)
        s = re.sub(r"^\s*20\d{2}\s*(?:학년도)?\s*", "", n)
        ms = _SHORT_SCHOOL.match(s)
        if ms and ms.group(1) not in _NOT_SCHOOL:
            return ms.group(1)
        return None
    full = m.group(1)
    for pat, short in _SCHOOL_KINDS:
        if re.search(pat + r"$", full):
            base = re.sub(pat + r"$", "", full)
            # '조선대학교여자중학교' → '조선대여중'
            base = re.sub(r"대학교$", "대", base)
            return (base + short) if len(base) >= 1 else None
    return None


def school_title(title, org):
    """학교 공고 제목을 '[약칭] 본문' 꼴로 통일. 학교가 아니면 원본 그대로."""
    # 천주교는 공고를 '광교2동 본당 …' 으로 쓰는데, 지도·검색에는 전부 '성당'으로 나온다.
    # '본당'이 교회법상 정확한 말(사목 공동체)이고 '성당'은 건물이지만, 지원자가 어디인지
    # 알아보는 게 먼저라 찾기 쉬운 쪽을 쓴다 (2026-08-09, 판단 위임받음).
    m_cath = re.match(r"^\s*([가-힣0-9]{2,10}(?:동|리|읍|면)?)\s*본당\b", title or "")
    if m_cath and "천주교" in (org or ""):
        rest = re.sub(r"\s{2,}", " ", title[m_cath.end():]).strip(" -–·,")
        return f"[천주교 {m_cath.group(1)} 성당] {rest}" if len(rest) >= 4 else title
    # 제목이 이미 다른 기관을 말하고 있으면 딱지를 붙이지 않는다. 게시판 주인을 앞에
    # 세우면 거짓이 된다 — 연세대 음대 게시판에 올라온 천안시립교향악단 공고가
    # '[연세대학교] 천안시립교향악단 예술감독 모집'이 됐다 (2026-08-09).
    # 제목 앞머리가 이 공고의 기관 자신이면 다른 기관이 아니다 — 학교 안의 동아리를
    # 남의 단체로 오인해 딱지가 안 붙었다 (성남고등학교 윈드오케스트라 클라리넷 강사
    # 채용 이 [성남고] 없이 나갔다, 2026-08-25).
    _other = re.match(r"^\s*[가-힣]{2,12}(?:\s[가-힣]{2,10})?"
                      r"(?:교향악단|필하모닉|합창단|예술단|국악단|무용단|오케스트라|문화재단|호텔)", title or "")
    if _other and not (org and _other.group(0).strip().startswith(org.strip()[:4])):
        return title
    short = school_short(org) or school_short(title)
    if not short:
        return title
    t = title
    # 제목 안에 이미 들어 있는 학교 이름(정식·약칭·괄호 표기)을 걷어낸다 — 앞에 붙일 것이므로
    t = re.sub(r"^[\[(（]\s*[^\])）]{2,12}\s*[\])）]\s*", "", t)
    t = re.sub(r"[가-힣]{2,12}(?:여자|예술)?(?:초등학교|중학교|고등학교)\s*", "", t)
    t = re.sub(rf"^\s*{re.escape(short)}\s*", "", t)     # 교회·대학 이름이 제목 앞에 또 있으면 제거
    # 괄호를 벗기면 앞머리에 있던 연도·학년도가 다시 드러난다 — 여기서도 한 번 더 훑는다
    # 연도와 그 뒤에 남는 구두점('2026. …')을 함께 걷어낸다. 점만 남으면 그다음의
    # 약칭 제거(아래)가 문자열 머리에서 걸리지 않아 '[양산남부고] . 양산남부고 …'가
    # 된다 (2026-08-23). 딱지가 이미 붙은 제목에 다시 돌려도 같은 결과가 나온다.
    t = re.sub(r"^\s*(?:20\d{2}\s*(?:학년도)?\s*)?[.,·:\-–]*\s*", "", t)
    t = _YEAR_TERM.sub(" ", t)
    t = " ".join(w for w in t.split() if not re.fullmatch(r"20\d{2}", w))
    t = re.sub(rf"^\s*{re.escape(short)}\s*", "", t)         # 이미 줄여 쓴 이름이 또 붙지 않게
    # 제목 속 괄호가 약칭의 부분문자열이면 중복이다 — '[서울중목초] …공고문(중목초)' (워크오더 D13)
    t = re.sub(r"\(([가-힣]{2,10})\)",
               lambda m: "" if m.group(1) in short else m.group(0), t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–·,")
    return f"[{short}] {t}" if len(t) >= 4 else f"[{short}] {title}"


def make_item(org, region, source, title, url, date=None, deadline=None):
    group, details = classify_insts(title)   # 악기는 원제목에서 추출(정리 전) — 악기 정보 보존
    # 음악 곁다리 판정은 반드시 '정리 전' 원제목으로 — 정리기가 타과목 시수(과학12·즐생8)를
    # 지워버리면 '(음악2)'만 남아 판정 근거가 사라진다 (2026-07-27 연천초 2차 생존 사고)
    non_music = music_minor_in_hours(title)
    clean = compact_title(music_only_title(re.sub(r"\s+", " ", title).strip()))
    # 학교 공고는 '[안양예고] …' 처럼 약칭을 앞에 세운다. 게시판마다 학교 이름을 넣는
    # 자리와 형태가 달라('(고현초) …', '충암중학교 …', 아예 없음) 카드가 들쭉날쭉했다.
    clean = school_title(clean, org)
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
