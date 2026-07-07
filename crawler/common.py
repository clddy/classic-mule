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
    r"|[1-3] ?차 ?(?:심사|전형|시험|발표|합격|서류|면접|실기|안내)"
    r"|워크숍|워크샵|수강생 ?모집")
# 수집 대상 (모집/채용 의도 — 교회 게시판식 "구합니다/모십니다" 포함)
INCLUDE = re.compile(r"모집|채용|오디션|공개모집|공개채용|초빙|구합니다|구인|모십니다|찾습니다")

def relevant(title):
    return bool(INCLUDE.search(title)) and not EXCLUDE.search(title)

def classify_kind(title):
    """단원(상임) / 객원·대체(비상임·기간제) / 반주 / 직원 / 기타"""
    if re.search(r"사무단원|기획운영단원|사무국|행정|안내원|매니저|팀장|본부장|시설|미화|보안", title):
        return "직원"
    if re.search(r"객원|비상임|대체(?:근로|인력|연주)?|기간제.*단원|단원.*기간제", title):
        return "객원·대체"
    if re.search(r"반주자|반주 ?단원", title):
        return "반주"
    if re.search(r"단원|악장|수석|부수석|차석|연주자|오디션|지휘자|성악가", title):
        return "단원"
    if re.search(r"직원|인턴|근로자|교육생|강사", title):
        return "직원"
    return "기타"

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
    if not details:
        if re.search(r"현악", title): return "현악", []
        if re.search(r"목관|관악", title): return "목관", []
        if re.search(r"금관", title): return "금관", []
        if re.search(r"성악|합창", title): return "성악", []
        return "전체", []
    return groups[0], details

def classify_tier(title, org=""):
    """프로(국공립·직업) / 전공·입시 / 교육·취미 / 오브리(행사·교회)"""
    t = f"{title} {org}"
    if re.search(r"방과후|초등학교|중학교|고등학교|취미|시민|문화센터|동아리", t):
        return "교육·취미"
    if re.search(r"유스|청소년|소년소녀|교육단원|아카데미|영재|콩쿠르 ?준비", t):
        return "전공·입시"
    if re.search(r"교회|성당|성가대|웨딩|예식|축가|기업 ?행사|송년|찬양|주일|예배|전례", t):
        return "오브리"
    return "프로"

# 텍스트에서 시도 단위 지역 추출 (집계 노드용)
_REGION_TOKENS = [
    ("서울", "서울"), ("경기", "경기"), ("인천", "인천"), ("대전", "대전"),
    ("대구", "대구"), ("부산", "부산"),
    ("김포", "경기"), ("성남", "경기"), ("수원", "경기"), ("고양", "경기"),
    ("부천", "경기"), ("평택", "경기"), ("안양", "경기"), ("안산", "경기"),
    ("용인", "경기"), ("의정부", "경기"),
]

def region_from(text, default="기타"):
    for token, region in _REGION_TOKENS:
        if token in text:
            return region
    return default

def item_id(url, title):
    return hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:16]

def make_item(org, region, source, title, url, date=None, deadline=None):
    group, details = classify_insts(title)
    return {
        "id": item_id(url, title),
        "org": org, "region": region, "source": source,
        "title": re.sub(r"\s+", " ", title).strip(),
        "url": url,
        "date": date,          # 게시일 (모르면 None)
        "deadline": deadline,  # 접수 마감 (모르면 None)
        "kind": classify_kind(title),
        "tier": classify_tier(title, org),
        "inst": group,
        "instDetails": details,  # 세부 악기 (복수 가능: "비올라, 오보에")
    }
