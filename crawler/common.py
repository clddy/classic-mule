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
    r"(?<![\d.])(\d{1,2})\s*[./월]\s*(\d{1,2})\s*일?\s*\.?\s*(?:\([^)]{1,4}\))?[^0-9]{0,14}까지")

def _valid(y, mo, d):
    return 1 <= int(mo) <= 12 and 1 <= int(d) <= 31

def _mk(y, mo, d):
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}" if _valid(y, mo, d) else None

def _window_deadline(window, ref_year):
    """한 키워드 윈도 안에서 마감일 후보 — 신뢰도 높은 패턴 순서로"""
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
    return None

# 우선 키워드(접수기간류)에서 찾으면 즉시 확정 — 활동기간·공연일 오인 방지
# 남은기간: 기독정보넷 상세의 "남은기간 2026-05-31 23:59:59 까지" 대응
_KW_PRIORITY = re.compile(r"원서 ?접수|접수 ?기간|접수 ?기한|접수 ?마감|서류 ?접수|지원 ?기간|응시원서|남은 ?기간")
_KW_FALLBACK = re.compile(r"접수|마감|기한|제출|지원서|모집 ?기간")

def extract_deadline(text, ref_year=None):
    """본문에서 접수 마감일 추출 — '원서접수/접수기간' 윈도를 최우선으로"""
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
        c = _window_deadline(text[kw.start(): kw.start() + 300], ref_year)
        if c:
            return c
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
    r"|관람 ?해설|사진 ?공모|미술관|박물관")
# 수집 대상 (모집/채용 의도 — 교회 게시판식 "구합니다/모십니다" 포함)
INCLUDE = re.compile(r"모집|채용|오디션|공개모집|공개채용|초빙|구합니다|구인|모십니다|찾습니다|임용 ?공고|위촉")

# 구인이 아닌 '프로그램 참가자·수강생·관람객' 모집 — 이런 건 사람을 '뽑는' 게 아니라
# '참여시키는' 것이라 구인구직판 대상이 아니다 (예: 음악창작소 투어 참여자 모집 = 학생 대상).
_PARTICIPANT = re.compile(
    r"참[여가]자\s*(?:모집|신청|선착|접수|모심)|참가\s*신청|참가팀|참여\s*학생"
    r"|스튜디오\s*투어|투어\s*참[여가]|체험\s*(?:단|참[여가]|프로그램|신청|학습|교실)|견학"
    r"|관람객|관객\s*모집|수강생|수강\s*신청|교육생\s*모집|아카데미\s*(?:생|수강)"
    r"|동아리원\s*모집|모니터(?:단|링)|평가단|명예\s*기자|해설사\s*양성|양성\s*과정")
# 위 참가자 신호가 있어도 실제 '채용 직무'가 함께 있으면 구인이므로 보호(예: 체험단 강사 모집)
_HIRE_ROLE = re.compile(
    r"단원|강사|반주|지휘|교원|교수|연주자|악장|수석|성악가|객원|교습|레슨|트레이너"
    r"|사무국|직원|스태프|음악감독|코치|상근|위촉\s*(?:연주|단원)")

def relevant(title):
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
    if re.search(r"단원|악장|수석|부수석|차석|연주자|오디션|지휘자|성악가", title):
        return "단원"
    if re.search(r"직원|인턴|근로자|교육생", title):
        return "직원"
    return "기타"

# ---------- 음악인 대상 여부 (행정·홍보·시설 등 비음악 직군 차단) ----------
STAFF_EXCLUDE = re.compile(
    r"통합채용|본부장|사무국|사무직|사무단원|행정|홍보|안내원|매표|하우스|시설|미화|경비"
    r"|사서|무대 ?기술|조명|음향(?! ?감독)|공무직|기간제 ?근로자|경영지원|회계|전산|주차|보안|기획팀|마케팅"
    r"|용역|제안서|입찰|평가 ?위원|심의 ?위원|비엔날레|운송|업무직|물품|구매|납품|공사|단장 ?공개|단장 ?채용"
    r"|아역|아동 ?배우|어린이 ?배우")
_MUSIC_KEEP = re.compile(r"악기|악보|조율|지휘|반주|연주|성악|합창|오케스트라|(?<![사무])단원|수석|악장|강사")
# 타 장르(무용·미술·연극 등) 공고 — '단원'만으로는 음악 공고로 인정하지 않음
NONMUSIC_ART = re.compile(r"무용|발레|안무|댄스|연극|배우|미술|(?<!대)전시(?!립)|사진 ?(?:공모|작가)|문학|서예|디자인")
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
    r"|싱어송라이터|K-?POP|작사|디제이|일렉트로닉|세션 ?(?:기타|드럼|베이스)|어쿠스틱 ?기타")

def musician_relevant(title, kind, org=""):
    """음악인(연주·지휘·반주·강사)이 대상인 공고인지 — 행정직·스태프는 제외.
    기관명 속 '오케스트라/합창단'이 음악 키워드로 오인되지 않도록 기관명을 제거 후 판정.
    ※ 무용은 NONMUSIC_ART 약필터로 처리 — 순수 무용(무용수·안무가)은 빼되
      '무용단 반주자'처럼 클래식 연주 역할은 살린다(고객=클래식 음악인)."""
    if GUGAK_EXCLUDE.search(f"{title} {org}"):
        return False
    if POP_EXCLUDE.search(f"{title} {org}"):   # 실용음악(대중·재즈 전공) 전면 제외
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
    r"|초등학교|중학교|고등학교|특수학교|유치원|어린이집|정교사|기간제교사|기간제교원")
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
REGION_ORDER = ["서울", "경기", "인천", "강원", "대전", "세종", "충북", "충남",
                "대구", "경북", "부산", "울산", "경남", "광주", "전북", "전남", "제주"]
_REGION_TOKENS = [
    # 광역시·특별시
    ("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"),
    ("대전", "대전"), ("울산", "울산"), ("세종", "세종"), ("광주광역", "광주"),
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
    # 전남
    ("전라남", "전남"), ("전남", "전남"), ("목포", "전남"), ("여수", "전남"),
    ("순천", "전남"), ("광양", "전남"), ("나주", "전남"),
    # 제주
    ("제주", "제주"), ("서귀포", "제주"),
    # 광주(광역시) — '경기 광주시'보다 예술기관은 광주광역시가 절대다수라 광주로
    ("광주", "광주"),
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
    r"(?<![가-힣])(?:영어|수학|국어|사회|과학|생명과학|생물|지구과학|지학|물리|화학|한국사|국사|세계사|역사|지리|도덕|윤리|한문|중국어|일본어|스페인어|프랑스어|독일어|베트남어"
    r"|상업|공업|농업|수산|가사|회계|무역|관광|조경|토목|건축|전기|전자|기계|자동차|미용|이용|축산"
    r"|정보|컴퓨터|코딩|소프트웨어|로봇|드론|바둑|장기|체스|주산|한자|속독|논술|독서|글쓰기|웅변|스피치|토론|리더십"
    r"|미술|서예|캘리그라피|공예|도예|만들기|그리기|웹툰|애니메이션|카툰|디자인|사진|영상|미디어"
    r"|체육|축구|농구|배구|야구|탁구|배드민턴|테니스|줄넘기|태권도|검도|유도|합기도|스포츠|요가|필라테스|수영"
    r"|무용|댄스|발레|치어리딩|방송댄스|스트릿댄스"
    r"|조리|요리|제빵|베이킹|바리스타|플로리스트|원예|텃밭|보드게임|마술|연극|연기|진로|상담|심리|과학실험|생태|환경|숲해설"
    r"|실과|기술가정|가정|기술|보건|간호|유아|특수교육|특수)(?![가-힣])")

def music_only_title(title):
    """다과목 나열 공고에서 음악 외 과목명 제거. 음악 신호가 없으면 원본 유지(악기명은 항상 보존)."""
    if not title or not _MUSIC_STRONG.search(title):
        return title
    t = _OTHER_SUBJECT.sub("", title)
    if t == title:
        return title
    t = re.sub(r"(?:\s*[,·/、]\s*){2,}", ", ", t)          # 연속 구분자 → 하나로
    t = re.sub(r"[(\[（]\s*(?:[,·/、]\s*)+", lambda m: m.group(0)[0], t)   # 여는 괄호 뒤 구분자
    t = re.sub(r"(?:[,·/、]\s*)+\s*([)\]）])", r"\1", t)     # 닫는 괄호 앞 구분자
    t = re.sub(r"[(\[（]\s*[)\]）]", "", t)                  # 빈 괄호 제거
    t = re.sub(r"^[\s,·/、]+|[\s,·/、]+$", "", re.sub(r"\s{2,}", " ", t))
    return t.strip() or title

def make_item(org, region, source, title, url, date=None, deadline=None):
    group, details = classify_insts(title)   # 악기는 원제목에서 추출(정리 전) — 악기 정보 보존
    clean = music_only_title(re.sub(r"\s+", " ", title).strip())
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
