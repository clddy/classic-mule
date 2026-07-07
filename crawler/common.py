# 공통 유틸: 세션, 날짜/분류 추출
import re, hashlib, time
import requests
import urllib3
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

def get(s, url, encoding=None, **kw):
    r = s.get(url, timeout=20, verify=False, **kw)
    if encoding:
        r.encoding = encoding
    elif r.encoding in (None, "ISO-8859-1"):
        r.encoding = r.apparent_encoding
    time.sleep(0.8)  # 예의상 간격
    return r

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

def _valid(y, mo, d):
    return 1 <= int(mo) <= 12 and 1 <= int(d) <= 31

def extract_deadline(text):
    """본문에서 접수 마감일 추출 — 접수/마감 키워드 근처의 기간 종료일 우선"""
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    best = None
    for kw in re.finditer(r"(접수|마감|기한|제출|응시원서|지원서|모집 ?기간)", text):
        window = text[kw.start(): kw.start() + 300]
        # 1순위: 기간 표기(~)의 종료일
        for m in RANGE_PAT.finditer(window):
            y = m.group(4) or m.group(1)
            if _valid(y, m.group(5), m.group(6)):
                cand = f"{y}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"
                if best is None or cand > best:
                    best = cand
        if best:
            continue
        # 2순위: 키워드 근처의 마지막 날짜
        dates = [norm_date(m) for m in DATE_PAT.finditer(window) if _valid(m.group(1), m.group(2), m.group(3))]
        if dates:
            cand = max(dates)
            if best is None or cand > best:
                best = cand
    return best

# 제외: 지원자에게만 해당하는 진행 공지 (심사일정·실기전형·악보·합격자 등)
# — 우리는 "언제까지 / 누구를 / 몇 명 뽑는지"가 담긴 모집 공고 자체만 수집한다
EXCLUDE = re.compile(
    r"합격자|합격 ?자|결과|최종 ?발표|선정|취소 ?공고|발표 및"
    r"|심사|실기 ?전형|서류 ?전형|면접|오디션 ?안내|오디션 ?일정"
    r"|악보|과제곡|지정곡|전형 ?일정|일정 ?안내|세부 ?안내|응시표|수험표"
    r"|[1-3] ?차|워크숍|워크샵|수강생 ?모집")
# 수집 대상 (모집/채용 의도)
INCLUDE = re.compile(r"모집|채용|오디션|공개모집|공개채용|초빙")

def relevant(title):
    return bool(INCLUDE.search(title)) and not EXCLUDE.search(title)

def classify_kind(title):
    if re.search(r"단원|악장|수석|부수석|차석|연주자|오디션|지휘자|지휘|반주|성악가|협연", title):
        if re.search(r"사무단원|기획운영단원|사무국", title):
            return "직원"
        return "단원"
    if re.search(r"직원|사무|행정|인턴|근로자|안내원|매니저|팀장|본부장|교육생|강사", title):
        return "직원"
    return "기타"

def classify_inst(title):
    t = title
    if re.search(r"더블 ?베이스|콘트라베이스", t): return "현악"
    if re.search(r"바이올린|비올라|첼로|하프|현악", t): return "현악"
    if re.search(r"플루트|오보에|클라리넷|바순|파곳|목관|피콜로", t): return "목관"
    if re.search(r"호른|트럼펫|트롬본|튜바|금관", t): return "금관"
    if re.search(r"타악|팀파니|퍼커션", t): return "타악"
    if re.search(r"피아노|오르간|건반|반주", t): return "건반"
    if re.search(r"소프라노|알토|테너|베이스(?!기타)|바리톤|성악|합창", t): return "성악"
    if re.search(r"지휘", t): return "지휘"
    return "전체"

def item_id(url, title):
    return hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:16]

def make_item(org, region, source, title, url, date=None, deadline=None):
    return {
        "id": item_id(url, title),
        "org": org, "region": region, "source": source,
        "title": re.sub(r"\s+", " ", title).strip(),
        "url": url,
        "date": date,          # 게시일 (모르면 None)
        "deadline": deadline,  # 접수 마감 (모르면 None)
        "kind": classify_kind(title),
        "inst": classify_inst(title),
    }
