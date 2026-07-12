# 기관별 파서 — 각 함수는 make_item 리스트를 반환
import os, re, json
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from common import get, make_item, find_date, relevant, region_from

def _soup(r):
    return BeautifulSoup(r.text, "lxml")

def _row_date(el):
    """앵커가 속한 행(tr/li/div)에서 게시일 추출"""
    node = el
    for _ in range(4):
        if node.parent is None:
            break
        node = node.parent
        if node.name in ("tr", "li"):
            break
    return find_date(node.get_text(" ", strip=True))

# ---------- 1. 서울시향 (JSON API) ----------
def parse_seoulphil(s):
    items = []
    for board, label in (("orchestra", "단원 오디션"), ("staff", "직원 채용")):
        r = s.post(f"https://www.seoulphil.or.kr/recruit/{board}/selectNoticeList",
                   data={"pageIndex": 1, "pageUnit": 100}, timeout=20, verify=False)
        data = json.loads(r.text)
        for row in data.get("list", []):
            title = re.sub(r"&#\d+;", "", row.get("title", ""))
            url = f"https://www.seoulphil.or.kr/recruit/{board}/detail?postNo={row['postNo']}"
            items.append(make_item(
                "서울시립교향악단", "서울", "seoulphil.or.kr", title, url,
                date=(row.get("startDate") or "").replace(".", "-") or None,
                deadline=(row.get("endDate") or "").replace(".", "-") or None))
    return items

# ---------- 2. KBS교향악단 ----------
def parse_kbs(s):
    r = get(s, "https://www.kbssymphony.org/ko/info/recruit.php")
    items = []
    for a in _soup(r).select('a[href*="board_code=view"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        url = urljoin("https://www.kbssymphony.org/ko/info/", a["href"])
        items.append(make_item("KBS교향악단", "서울", "kbssymphony.org", title, url, date=_row_date(a)))
    return items

# ---------- 3·4. 국립심포니 / 부천필 (동일 CMS: fn_view) ----------
def _parse_mcode(s, base, board, org, region, source):
    r = get(s, f"{base}/front/{board}/article/list.do")
    items = []
    for a in _soup(r).select("a[onclick]"):
        m = re.search(r"fn_view\('(AT\d+)'\)", a.get("onclick", ""))
        if not m:
            continue
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        url = f"{base}/front/{board}/article/view.do?atcId={m.group(1)}"
        items.append(make_item(org, region, source, title, url, date=_row_date(a)))
    return items

def parse_knso(s):
    return _parse_mcode(s, "https://www.knso.or.kr", "M0000034",
                        "국립심포니오케스트라", "서울", "knso.or.kr")

def parse_bucheonphil(s):
    # list.do는 JS 렌더링이라 메인 페이지의 최신공고 위젯에서 수집
    items = _parse_mcode(s, "https://www.bucheonphil.or.kr", "M0000025",
                         "부천필하모닉(부천시립예술단)", "경기", "bucheonphil.or.kr")
    if not items:
        r = get(s, "https://www.bucheonphil.or.kr/front/M0000000/index.do")
        for a in _soup(r).select('a[href*="M0000025/article/view.do"]'):
            title = a.get_text(" ", strip=True)
            if len(title) < 6:
                continue
            items.append(make_item("부천필하모닉(부천시립예술단)", "경기", "bucheonphil.or.kr",
                                   title, urljoin(r.url, a["href"]), date=_row_date(a)))
    return items

# ---------- 5. 경기아트센터(경기필) ----------
def parse_ggac(s):
    items = []
    for url in ("https://www.ggac.or.kr/ggac/M0000217/board/list.do",
                "https://www.ggac.or.kr/?p=42"):
        try:
            r = get(s, url)
            if r.status_code != 200:
                continue
            for a in _soup(r).select('a[href*="board/view.do"]'):
                title = a.get_text(" ", strip=True)
                if len(title) < 6:
                    continue
                items.append(make_item("경기아트센터(경기필하모닉)", "경기", "ggac.or.kr",
                                       title, urljoin(r.url, a["href"]), date=_row_date(a)))
            if items:
                break
        except Exception:
            continue
    return items

# ---------- 6. 인천문화예술회관(인천시향) ----------
def parse_incheon(s):
    r = get(s, "https://www.incheon.go.kr/art/ART040102")
    items = []
    for a in _soup(r).select('a[href^="/art/ART040102/"]'):
        title = a.get_text(" ", strip=True).removeprefix("공지").strip()
        if len(title) < 6:
            continue
        items.append(make_item("인천문화예술회관(시립예술단)", "인천", "incheon.go.kr",
                               title, urljoin(r.url, a["href"]), date=_row_date(a)))
    return items

# ---------- 7. 대전시립교향악단 ----------
def parse_dpo(s):
    r = get(s, "https://dpo.artdj.kr/dpo/?a_idx=06_01", encoding="euc-kr")
    items = []
    for a in _soup(r).select('a[href*="mo=view"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 6 or "dpo_news" not in a["href"]:
            continue
        items.append(make_item("대전시립교향악단", "대전", "dpo.artdj.kr",
                               title, urljoin("https://dpo.artdj.kr/dpo/", a["href"]), date=_row_date(a)))
    return items

# ---------- 8. 대구문화예술회관(대구시향) ----------
def parse_daegu(s):
    r = get(s, "https://daeguartscenter.or.kr/index.do?menu_id=00001528")
    items = []
    for tr in re.findall(r"<tr[^>]*>[\s\S]*?</tr>", r.text):
        m = re.search(r"fn_icms_navi_common\('view','(\d+)'\)[^>]*>([^<]{6,90})</a>", tr)
        if not m:
            continue
        nid, title = m.group(1), m.group(2).strip()
        d = re.search(r"(20\d{2})-(\d{2})-(\d{2})", tr)
        url = f"https://daeguartscenter.or.kr/index.do?menu_id=00001528&nttId={nid}"
        items.append(make_item("대구문화예술회관(시립교향악단)", "대구", "daeguartscenter.or.kr",
                               title, url, date=d.group(0) if d else None))
    return items

# ---------- 9. 광주시립교향악단 ----------
def parse_gso(s):
    r = get(s, "https://gjart.gwangju.go.kr/gso/cmd.do?opencode=pg_0501")
    items = []
    for a in _soup(r).select('a[href*="boper=view"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        href = re.sub(r";jsessionid=[^?]*", "", a["href"])
        items.append(make_item("광주시립교향악단", "기타", "gjart.gwangju.go.kr",
                               title, urljoin("https://gjart.gwangju.go.kr/gso/", href), date=_row_date(a)))
    return items

# ---------- 10. 부산문화회관(부산시립예술단) ----------
def parse_bscc(s):
    r = get(s, "https://www.bscc.or.kr/05_community/?mcode=0405010000")
    items = []
    for a in _soup(r).select('a[href*="mode=2"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        items.append(make_item("부산문화회관(시립예술단)", "부산", "bscc.or.kr",
                               title, urljoin(r.url, a["href"]), date=_row_date(a)))
    return items

# ---------- 11. 수원시립예술단 ----------
def parse_artsuwon(s):
    r = get(s, "http://artsuwon.or.kr/?p=49")
    items = []
    for a in _soup(r).select('a[href*="viewMode=view"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        m = re.search(r"reqIdx=(\d{8})", a["href"])
        d = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}" if m else None
        items.append(make_item("수원시립예술단", "경기", "artsuwon.or.kr",
                               title, urljoin("http://artsuwon.or.kr/", a["href"]), date=d))
    return items

# ---------- 12. 성남문화재단 ----------
def parse_snart(s):
    r = get(s, "https://www.snart.or.kr/main/pst/list.do?pst_id=recruit")
    items = []
    for a in _soup(r).select('a[href*="view.do"]'):
        if "pst_id=recruit" not in a.get("href", ""):
            continue
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        items.append(make_item("성남문화재단(시립교향악단)", "경기", "snart.or.kr",
                               title, urljoin(r.url, a["href"]), date=_row_date(a)))
    return items

# ---------- 13. 국립오페라단 (목록만 — 상세는 JS) ----------
def parse_natopera(s):
    r = get(s, "https://www.nationalopera.org/cpage/board/notice")
    items = []
    for m in re.finditer(
            r'<td><span class="ctg">([^<]+)</span></td>\s*<td[^>]*>'
            r'<a class="viewLink" boardSeq="(\d+)"[^>]*>([^<]{6,100})</a></td>\s*'
            r'<td><span class="date">([\d.]+)</span>', r.text):
        ctg, seq, title, date = m.groups()
        url = f"https://www.nationalopera.org/cpage/board/notice?boardSeq={seq}"
        items.append(make_item("국립오페라단", "서울", "nationalopera.org",
                               title.strip(), url, date=date.replace(".", "-")))
    return items

# ---------- 14. 국립합창단 ----------
def parse_natchorus(s):
    r = get(s, "http://nationalchorus.or.kr/notice-2/",
            headers={"Referer": "http://nationalchorus.or.kr/"})
    items = []
    seen = set()
    for a in _soup(r).select('a[href*="vid="]'):
        title = a.get_text(" ", strip=True)
        m = re.search(r"vid=(\d+)", a["href"])
        if len(title) < 6 or not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        items.append(make_item("국립합창단", "서울", "nationalchorus.or.kr",
                               title, f"http://nationalchorus.or.kr/notice-2/?vid={m.group(1)}",
                               date=_row_date(a)))
    return items

# ---------- 15. 세종문화회관(서울시예술단) ----------
def parse_sejongpac(s):
    r = get(s, "https://www.sejongpac.or.kr/portal/bbs/B0000065/list.do?menuNo=200571")
    items = []
    for a in _soup(r).select('a[href*="B0000065/view.do"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        items.append(make_item("세종문화회관(서울시예술단)", "서울", "sejongpac.or.kr",
                               title, urljoin(r.url, a["href"]), date=_row_date(a)))
    return items

# ---------- 16. 창원문화재단(창원시향) ----------
def parse_cwcf(s):
    get(s, "https://www.cwcf.or.kr/main/main.asp")  # 세션 쿠키 확보
    r = get(s, "https://www.cwcf.or.kr/commu/notice_list.asp?BCATE=BD00001",
            encoding="euc-kr", headers={"Referer": "https://www.cwcf.or.kr/main/main.asp"})
    items = []
    for a in _soup(r).select('a[href*="notice_view.asp"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        items.append(make_item("창원문화재단(시립예술단)", "기타", "cwcf.or.kr",
                               title, urljoin("https://www.cwcf.or.kr/commu/", a["href"]),
                               date=_row_date(a)))
    return items

# ---------- 17. 전주시 (시험/채용 — 예술단 키워드만) ----------
def parse_jeonju(s):
    r = get(s, "https://www.jeonju.go.kr/index.9is?contentUid=ff8080818990c349018b041a87bd395c")
    items = []
    for a in _soup(r).select('a[href*="planweb/board/view.9is"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 6 or not re.search(r"교향악단|합창단|예술단|연주단", title):
            continue
        items.append(make_item("전주시(시립예술단)", "기타", "jeonju.go.kr",
                               title, urljoin(r.url, a["href"]), date=_row_date(a)))
    return items

# ---------- 18. 예술의전당 ----------
def parse_sac(s):
    r = get(s, "https://www.sac.or.kr/site/main/board/recruit/list")
    items = []
    for a in _soup(r).select('a[href*="/board/recruit/"]'):
        href = a["href"]
        if not re.search(r"/board/recruit/\d+", href):
            continue
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        items.append(make_item("예술의전당", "서울", "sac.or.kr",
                               title, urljoin(r.url, href), date=_row_date(a)))
    return items

# ---------- 19. 경남교육청 구인구직포털 (방과후 오케스트라 강사) ----------
GNE_URL = ("https://www.gne.go.kr/works/user/recruitment/BD_recruitmentList.do"
           "?q_searchKey=1001&q_searchVal=%EC%98%A4%EC%BC%80%EC%8A%A4%ED%8A%B8%EB%9D%BC"
           "&q_rowPerPage=15&q_currPage=1")

GNE_DETAIL = "https://www.gne.go.kr/works/user/recruitment/BD_recruitmentDetail.do?regSn="

def parse_gne(s):
    r = get(s, GNE_URL)
    items, seen = [], set()
    for a in _soup(r).select("a[onclick*=openDetail]"):
        title = a.get_text(" ", strip=True)
        m = re.search(r"openDetail\(\s*['\"]?(\d+)", a.get("onclick", ""))
        if (not m or len(title) < 10 or title in seen
                or not re.search(r"오케스트라|관현악", title)
                or not re.search(r"모집|채용|초빙|공고", title)):
            continue
        seen.add(title)
        # 개별 공고 상세 URL(regSn) — 포털 검색목록이 아니라 원문으로 링크
        items.append(make_item("경남 학교 방과후(교육청 포털)", "기타", "gne.go.kr",
                               title, GNE_DETAIL + m.group(1), date=_row_date(a)))
    return items

# ---------- 20. 아트모아 (문체부·예술경영지원센터 일자리 포털) ----------
CLASSIC_PAT = re.compile(
    r"오케스트라|교향악단|필하모닉|합창단|오페라|클래식|단원 ?모집|지휘자|반주자"
    r"|콰르텟|앙상블|성악|바이올린|비올라|첼로|더블베이스|플루트|오보에|클라리넷"
    r"|바순|호른|트럼펫|트롬본|튜바|팀파니|피아니스트")

# 집계 포털 제목에서 실제 기관명 추출 (아트인포·아트모아는 org이 없어 포털명 대신 씀)
_ORGWORD = (r"교향악단|합창단|국악관현악단|관현악단|필하모닉|예술단|오케스트라|윈드오케스트라"
            r"|앙상블|콰르텟|사중주단|중창단|합주단|아카데미|음악단|뮤지컬단|무용단|극단|문화재단|교회|성당")

def org_from_title(title, fallback):
    for m in re.finditer(r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9·\s]{1,18}?(?:" + _ORGWORD + r"))", title):
        cand = re.sub(r"^.*?[\]\)]\s*", "", m.group(1))
        cand = re.sub(r"^\s*(?:20\d\d\s*년?도?|20\d\d학년도|상반기|하반기|\d+차|신규|공개|모집|채용|지원사업)\s*", "", cand)
        cand = cand.strip(" []()")
        if 3 <= len(cand) <= 22:
            return cand
    return fallback

def parse_artmore(s):
    r = get(s, "https://www.artmore.kr/sub/recruit/search_list.do")
    items = []
    for a in _soup(r).select("a.jobs_title"):
        title = a.get_text(" ", strip=True)
        state = a.select_one(".jobs_list_state")
        if state and "진행중" not in state.get_text():
            continue
        title = re.sub(r"^진행중\s*", "", title)
        if len(title) < 8 or not CLASSIC_PAT.search(title):
            continue
        it = make_item(org_from_title(title, "아트모아(예술 일자리 포털)"), "기타", "artmore.kr",
                       title, urljoin("https://www.artmore.kr", a["href"]),
                       date=_row_date(a))
        origin = _resolve_origin(s, it["url"], "artmore.kr")
        if origin:
            it["officialUrl"] = origin
        items.append(it)
    return items

# ---------- 22. 아트인포코리아 (클래식 전문 채용 포털) ----------
# 집계 사이트라 상세 페이지의 "채용 사이트 바로가기" 링크로 원본 기관 공고를 해석
_ORIGIN_TXT = re.compile(r"채용 ?사이트|바로가기|홈페이지|공식")

def _resolve_origin(s, detail_url, skip_host):
    """집계 상세 페이지에서 원본 기관 공고 URL 추출 (없으면 None)"""
    try:
        dr = get(s, detail_url)
        for a in _soup(dr).find_all("a", href=True):
            h = a["href"]
            if h.startswith("http") and skip_host not in h \
                    and not re.search(r"facebook|instagram|youtube|kakao|blog\.naver", h) \
                    and _ORIGIN_TXT.search(a.get_text(" ", strip=True)):
                # 경로 없는 맨 홈페이지(예: 학원 브랜드사이트)는 공고 원문이 아님 →
                # 스킵해 집계 직접게시글이 연락처 지원(_extract_contact)으로 유도되게 한다
                if len(urlparse(h).path.strip("/")) < 2:
                    continue
                return h
    except Exception:
        pass
    return None

def parse_artinfo(s):
    r = get(s, "https://www.artinfokorea.com/jobs")
    items, seen = [], set()
    for a in _soup(r).select('a[href^="/jobs/"]'):
        href = a["href"]
        if not re.match(r"^/jobs/\d+", href) or href in seen:
            continue
        seen.add(href)
        full = a.get_text(" ", strip=True)
        if len(full) < 10:
            continue
        # 카드 앵커가 제목+지역+악기+기관명을 통째로 담고 있어 첫 텍스트 노드만 제목으로
        first = next((t.strip() for t in a.stripped_strings), "")
        title = first if len(first) >= 10 else full[:90]
        it = make_item(org_from_title(title, "아트인포(클래식 채용)"), region_from(full), "artinfokorea.com",
                       title[:90], urljoin("https://www.artinfokorea.com", href),
                       date=_row_date(a))
        origin = _resolve_origin(s, it["url"], "artinfokorea.com")
        if origin:
            it["officialUrl"] = origin
        items.append(it)
    return items

# ---------- 23. 기독정보넷 (교회 반주자·연주자) ----------
CJOB_INCLUDE = re.compile(r"피아노|오르간|반주|성악|솔리스트|바이올린|비올라|첼로|플루트|오케스트라|지휘|콰르텟|앙상블|소프라노|알토|테너|베이스")
CJOB_EXCLUDE = re.compile(r"드럼|일렉|기타리스트|베이스 ?기타|신디|미디|보컬 ?트레이너")

def parse_cjob(s):
    r = get(s, "https://www.cjob.co.kr/offerIG?c_jikjong=2&page=1&device=pc")
    items = []
    for a in _soup(r).select('a[href*="bo_table=offerIG"]'):
        if "wr_id=" not in a["href"]:
            continue
        title = a.get_text(" ", strip=True)
        if len(title) < 8 or not CJOB_INCLUDE.search(title) or CJOB_EXCLUDE.search(title):
            continue
        m = re.search(r"([가-힣A-Za-z0-9]{2,15}(?:교회|성당|채플))", title)
        org = m.group(1) if m else "교회(기독정보넷)"
        items.append(make_item(org, region_from(title), "cjob.co.kr",
                               title, urljoin("https://www.cjob.co.kr/", a["href"]),
                               date=_row_date(a)))
    return items

# ---------- 21. 울산문화예술회관(시립예술단) ----------
# ucac.ulsan.go.kr은 JS 스텁 — www.ulsan.go.kr/ucac/art 경로가 SSR이고 링크도 이쪽만 정상 (클릭 추적으로 확인)
def parse_ulsan(s):
    r = get(s, "https://www.ulsan.go.kr/ucac/art/page.do?mnu_code=mnu003001")
    items = []
    for a in _soup(r).select('a[href*="bod_sn"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 8:
            continue
        m = re.search(r"bod_sn=(\d+)", a["href"])
        if not m:
            continue
        url = f"https://www.ulsan.go.kr/ucac/art/page.do?mnu_code=mnu003001&bod_sn={m.group(1)}&cmd=2"
        items.append(make_item("울산문화예술회관(시립예술단)", "기타", "ulsan.go.kr",
                               title, url, date=_row_date(a)))
    return items

# ---------- 24. 포항문화재단(포항시립교향악단·합창단) — JS 렌더 + onclick moveDetail ----------
def parse_phcf(s):
    from jsfetch import render
    html = render("https://www.phcf.or.kr/phcf/recruitment/view.do", wait_ms=3000)
    items, seen = [], set()
    for a in BeautifulSoup(html, "lxml").find_all("a", onclick=re.compile(r"moveDetail")):
        m = re.search(r"moveDetail\((\d+)\)", a.get("onclick", ""))
        raw = a.get_text(" ", strip=True)
        if not m or not (8 <= len(raw) <= 120):
            continue
        # "<제목> <팀명> | <날짜>" 꼬리 제거
        title = re.split(r"\s*\|\s*20\d\d", raw)[0]
        title = re.sub(r"\s*[A-Za-z]?-?[가-힣A-Za-z·]{2,12}(팀|과|부|센터)\s*$", "", title).strip()
        # '예술단체'·'지원사업 코디' 등 행정 오탐 방지 — 앙상블명사+채용동사 인접만
        if not STRICT_ENSEMBLE_PAT.search(title):
            continue
        if m.group(1) in seen:
            continue
        seen.add(m.group(1))
        url = f"https://www.phcf.or.kr/phcf/recruitment/detail.do?BRD_SEQ={m.group(1)}"
        items.append(make_item("포항문화재단(시립교향악단·합창단)", "경북", "phcf.or.kr",
                               title, url, date=None))
    return items

# ---------- 25. 클린아이 잡+ (행안부 지방공공기관 통합채용 = 문화재단·시설공단·출연기관) ----------
# 목록이 JSON API(pubEndDate=마감까지 포함) → 상세파싱 불필요. 상세(POST)에서 기관 원문 홈페이지 해석.
# 시립예술단·문화재단 단원/연주 채용의 법정 발행 채널 — 미커버 '나머지' 공공기관을 통째로 포착.
CLEANEYE_LIST = "https://job.cleaneye.go.kr/user/selectYpRecruitment.do"
CLEANEYE_DETAIL = "https://job.cleaneye.go.kr/user/ypCareersData.do"
CLEANEYE_MUSIC = re.compile(
    r"교향악단|필하모닉|합창단|오케스트라|관현악|국악관현악|예술단|연주단|윈드 ?오케스트라"
    r"|반주자|성악|악장|수석 ?단원|상임 ?단원|객원 ?단원|비상임 ?단원|단원 ?(?:모집|채용|충원|위촉|공개)")

def _cleaneye_origin(s, x):
    """클린아이 상세(POST)에서 기관 원문 홈페이지/공고 링크 추출 (없으면 None)."""
    try:
        r = s.post(CLEANEYE_DETAIL, timeout=15, verify=False,
                   data={"empyear": x.get("empyear"), "entSeq": x.get("entSeq"), "ypEntId": x.get("ypEntId")})
        for m in re.finditer(r'https?://[^"\'<>\s)]+', r.text):
            u = m.group(0)
            if not re.search(r"cleaneye|w3\.org|hrdb\.go|worktogether|matchingbank|gojobs|"
                             r"moel\.go|work24|work\.go|alio\.go|saramin|jobkorea|incruit|albamon|"
                             r"\.(?:css|js|png|jpe?g|gif|woff2?|ico)", u, re.I):
                return u
    except Exception:
        pass
    return None

def parse_cleaneye(s):
    items = []
    for page in range(1, 9):   # 최근 800건(게시일 역순) 스캔 → 음악 공고만
        try:
            r = s.post(CLEANEYE_LIST, timeout=20, verify=False,
                       data={"pageIndex": page, "recordCountPerPage": 100})
            rows = json.loads(r.text).get("list", [])
        except Exception:
            break
        if not rows:
            break
        for x in rows:
            title = re.sub(r"\s+", " ", x.get("entTitle", "")).strip()
            org = re.sub(r"^\(재\)\s*|^재단법인\s*", "", x.get("entName", "")).strip()
            if not (CLEANEYE_MUSIC.search(title) or re.search(r"교향악|필하모닉|합창단|예술단", org)):
                continue
            origin = _cleaneye_origin(s, x)
            it = make_item(org, region_from(f"{org} {title}"), "job.cleaneye.go.kr", title,
                           origin or CLEANEYE_LIST,
                           date=(x.get("pubDate") or None), deadline=(x.get("pubEndDate") or None))
            if origin:
                it["officialUrl"] = origin
            items.append(it)
    return items

# ---------- 25b. 나라일터(인사혁신처 gojobs) — 공공기관·지자체·군악대 채용 공식 발행채널 ----------
# 공고명 검색(searchKeyword) GET → 행 tr[번호|공고명|기관|게시일|마감일|조회] → 상세 apmView.do GET.
# 시립예술단·학교 오케스트라·군악대 등 '나머지' 공공 채용의 원천(문서: 나라일터=원천 취급).
GOJOBS_LIST = "https://www.gojobs.go.kr/apmList.do"
GOJOBS_VIEW = "https://www.gojobs.go.kr/apmView.do?empmnsn={sn}&empmnsecode={ec}&menuNo=401"
GOJOBS_KWS = ["오케스트라", "관현악", "교향악단", "합창단", "관악부", "국악관현악단", "예술단", "군악"]

def parse_gojobs(s):
    items, seen = [], set()
    for kw in GOJOBS_KWS:
        try:
            r = get(s, GOJOBS_LIST, params={"menuNo": "401", "searchKeyword": kw})
            if r.status_code != 200:
                continue
        except Exception:
            continue
        for tr in re.findall(r"<tr[^>]*>[\s\S]*?</tr>", r.text):
            m = re.search(r"fn_apmView\('(\d+)',\s*'(\d+)'\)", tr)
            if not m or m.group(2) in seen:
                continue
            cells = [re.sub(r"\s+", " ", c).strip()
                     for c in re.sub(r"<[^>]+>", "\n", tr).split("\n") if c.strip()]
            # cells 대략 [번호, 공고명, 기관경로, 게시일, 마감일, 조회수]
            title = next((c for c in cells if len(c) >= 8 and re.search(r"모집|채용|공고|강사|단원", c)), None)
            if not title or not MUSIC_PAT.search(title):
                continue
            dates = [c for c in cells if re.match(r"20\d\d-\d\d-\d\d$", c)]
            # 기관 셀: '○○교육청 ○○지원청 ○○학교' 경로 → 말단 기관명. 공고명/숫자 셀 제외.
            org_c = next((c for c in cells
                          if c != title and not re.match(r"20\d\d|^\d+$", c)
                          and re.search(r"학교|유치원|교육청|교육지원청|재단|시청|도청|구청|군청"
                                        r"|예술단|회관|공사|공단|대학|병원|연구원|진흥원|센터|청$", c)), "")
            org = re.sub(r".*\s", "", org_c.strip()) if org_c else "공공기관"
            if org in ("공고", "채용", "") or len(org) < 2:
                org = org_c.strip().split()[-1] if org_c.strip() else "공공기관"
            seen.add(m.group(2))
            items.append(make_item(f"{org}(나라일터)", region_from(org_c), "gojobs.go.kr", title,
                                   GOJOBS_VIEW.format(sn=m.group(2), ec=m.group(1)),
                                   date=(dates[0] if dates else None),
                                   deadline=(dates[-1] if len(dates) >= 2 else None)))
    return items

# ---------- 26. 시도교육청 방과후/강사 채용 포털 (개별 파서, config 파라미터화) ----------
# 각 교육청 구인구직 포털은 시스템이 제각각 → 포털별 config(검색URL 템플릿 + 상세 id 패턴)로 파라미터화.
# 방과후 오케스트라·관악부·1인1악기 등 음악 강사 공고를 키워드로 검색해 수집.
from urllib.parse import quote as _q
EDU_KWS = ["오케스트라", "관현악", "관악부", "바이올린", "첼로", "플루트", "성악", "합창"]
EDU_MUSIC = re.compile(
    r"오케스트라|관현악|관악|현악|합주|바이올린|비올라|첼로|더블 ?베이스|콘트라베이스"
    r"|플루트|오보에|클라리넷|바순|호른|트럼펫|트롬본|튜바|색소폰|타악|팀파니"
    r"|피아노|성악|합창|음악|악기")

def _make_edu_parser(cfg):
    """교육청 포털 config → 파서.
    mode 'search': kws 루프하며 list.format(kw=)를 검색 / 'board': 단일 URL을 EDU_MUSIC로 필터.
    공통: sel(상세앵커) → idpat(href/onclick에서 id) → detail.format(id=)."""
    urls = ([cfg["list"].format(kw=_q(kw)) for kw in cfg.get("kws", EDU_KWS)]
            if cfg.get("mode", "search") == "search" else [cfg["list"]])
    def parse(s):
        items, seen = [], set()
        for url in urls:
            try:
                r = get(s, url, encoding=cfg.get("enc"))
                if r.status_code != 200:
                    continue
            except Exception:
                continue
            for a in _soup(r).select(cfg["sel"]):
                title = a.get_text(" ", strip=True)
                if len(title) < 6 or title in seen or not EDU_MUSIC.search(title):
                    continue
                blob = (a.get("href") or "") + " " + (a.get("onclick") or "")
                m = re.search(cfg["idpat"], blob)
                if not m:
                    continue
                seen.add(title)
                items.append(make_item(cfg["name"], cfg["region"], cfg["source"],
                                       title, cfg["detail"].format(id=m.group(1))))
        return items
    return parse

# ---- 경기교육청 구인구직(hnfp) — 목록 POST + 상세 GET (2026-07 리버스엔지니어링) ----
# 키워드 검색은 서버에서 무시됨 → 목록 페이지 순회 후 제목(EDU_MUSIC) 클라이언트 필터.
# 경기 상세: hnfpPbancInfoView.do GET이 쿠키 없이도 열림(2026-07 재검증, 94KB 정상)
# — 과거 타임아웃은 일시 장애였음. 특정 공고 딥링크로 연결한다.
GOE_VIEW = "https://www.goe.go.kr/recruit/ad/func/pb/hnfpPbancInfoView.do?mi=10502&pbancSn={id}"

def parse_goe(s):
    items, seen = [], set()
    for ocpt in ("", "A", "B"):        # 전체·기간제/사립교원·교육공무직(방과후 포함)
        for page in (1, 2):
            try:
                r = s.post("https://www.goe.go.kr/recruit/ad/func/pb/hnfpPbancList.do?mi=10502",
                           timeout=20, verify=False,
                           data={"currPage": page, "pageIndex": 50, "mi": "10502",
                                 "srchEcptDl": "Y", "srchOcptCd": ocpt})
                if r.status_code != 200:
                    continue
            except Exception:
                continue
            for a in _soup(r).select('a[href*="goView"]'):
                m = re.search(r"goView\('(\d+)'\)", a.get("href", ""))
                tit_el = a.select_one("p.cont_tit")
                if not m or not tit_el:
                    continue
                title = re.sub(r"^\s*(?:마감임박|신규|NEW|D-\d+)\s*", "",
                               tit_el.get_text(" ", strip=True))
                if len(title) < 8 or not EDU_MUSIC.search(title):
                    continue
                if m.group(1) in seen:
                    continue
                seen.add(m.group(1))
                org_el = a.select_one(".cont_top span")
                org = org_el.get_text(strip=True) if org_el else "경기 학교"
                d = find_date(a.get_text(" ", strip=True))
                items.append(make_item(f"{org}(경기교육청)", "경기", "goe.go.kr", title,
                                       GOE_VIEW.format(id=m.group(1)), date=d))
    return items

# ---- na/ntt CMS 교육청 채용게시판 (인천·전남·경북·세종 공통 벤더) ----
# 목록 GET → 행 .nttInfoBtn[data-id] → 상세 GET selectNttInfo.do?nttSn=&mi=
NA_NTT_BOARDS = [
    {"id": "edu_ice", "name": "인천교육청(학교 채용)", "region": "인천", "dom": "ice.go.kr",
     "base": "https://www.ice.go.kr/ice", "mi": "10997", "bbsId": "1981", "extra": ""},
    {"id": "edu_jne", "name": "전남교육청(학교 채용)", "region": "기타", "dom": "jne.go.kr",
     "base": "https://www.jne.go.kr/main", "mi": "265", "bbsId": "117", "extra": "&searchCate1=1"},
    {"id": "edu_gbe", "name": "경북교육청(학교 채용)", "region": "기타", "dom": "gbe.kr",
     "base": "https://www.gbe.kr/main", "mi": "3636", "bbsId": "1890", "extra": ""},
    {"id": "edu_sje", "name": "세종교육청(학교 채용)", "region": "기타", "dom": "sje.go.kr",
     "base": "https://www.sje.go.kr/sje", "mi": "52132", "bbsId": "108", "extra": ""},
    # 대구 — 같은 na/ntt CMS인데 requests 차단 → Playwright 렌더(js) 경유
    {"id": "edu_dge", "name": "대구교육청(모집공고)", "region": "대구", "dom": "dge.go.kr",
     "base": "https://www.dge.go.kr/main", "mi": "5211", "bbsId": "1793", "extra": "", "js": True},
    # 부산 — 홈만 리다이렉트 스텁, 목록은 http+Referer로 열림
    {"id": "edu_pen", "name": "부산교육청(학교인력채용)", "region": "부산", "dom": "pen.go.kr",
     "base": "http://www.pen.go.kr/main", "mi": "30367", "bbsId": "2364", "extra": "",
     "referer": "https://www.pen.go.kr/"},
    # 충북 — home/main.php는 열리고 구인정보 게시판도 na/ntt 공통
    {"id": "edu_cbe", "name": "충북교육청(구인정보)", "region": "기타", "dom": "cbe.go.kr",
     "base": "https://www.cbe.go.kr/cbe", "mi": "11716", "bbsId": "1798", "extra": ""},
]

def _make_nantt_parser(cfg):
    def parse(s):
        items = []
        for page in (1, 2, 3):
            url = (f"{cfg['base']}/na/ntt/selectNttList.do?mi={cfg['mi']}"
                   f"&bbsId={cfg['bbsId']}&currPage={page}{cfg['extra']}")
            try:
                if cfg.get("js"):
                    from jsfetch import render
                    html = render(url, wait_ms=2500)
                else:
                    hdr = {"Referer": cfg["referer"]} if cfg.get("referer") else None
                    r = get(s, url, headers=hdr) if hdr else get(s, url)
                    if r.status_code != 200:
                        break
                    html = r.text
            except Exception:
                break
            rows = BeautifulSoup(html, "lxml").select(".nttInfoBtn[data-id]")
            if not rows:
                break
            for a in rows:
                title = a.get_text(" ", strip=True)
                if len(title) < 8 or not EDU_MUSIC.search(title):
                    continue
                url = (f"{cfg['base']}/na/ntt/selectNttInfo.do?nttSn={a['data-id']}"
                       f"&mi={cfg['mi']}&bbsId={cfg['bbsId']}")
                items.append(make_item(cfg["name"], cfg["region"], cfg["dom"], title, url,
                                       date=_row_date(a)))
        return items
    return parse

# ---- 강원교육청 구인 게시판 — 목록 GET(sub.do) + 상세 GET(bbs/view.do?bbsSn=) ----
GWE_LIST = "https://www.gwe.go.kr/main/sub.do?key=bTIzMDcyMTA1ODUxNTU%3D"
GWE_VIEW = "https://www.gwe.go.kr/main/bbs/view.do?key=bTIzMDcyMTA1ODU2MzM%3D&bbsSn={id}"

def parse_gwe(s):
    items, seen = [], set()
    try:
        r = get(s, GWE_LIST)
    except Exception:
        return items
    for a in _soup(r).find_all("a", onclick=re.compile(r"goView\('\d+'")):
        m = re.search(r"goView\('(\d+)'", a.get("onclick", ""))
        title = a.get("title") or a.get_text(" ", strip=True)
        title = re.sub(r"^\s*NEW\s*|\s*\[[가-힣]{2,8}\]\s*", " ", title).strip()
        if not m or m.group(1) in seen or len(title) < 8 or not EDU_MUSIC.search(title):
            continue
        seen.add(m.group(1))
        items.append(make_item("강원교육청(학교 채용)", "기타", "gwe.go.kr",
                               title, GWE_VIEW.format(id=m.group(1)), date=_row_date(a)))
    return items

# ---- 전북교육청 학교/기관별 채용공고 — 과목이 제목이 아닌 행(tr) 셀에 표기 ----
# 행 전체 텍스트로 음악 필터 (제목 셀만으론 학교명뿐이라 판별 불가)
JBE_LIST = ("https://www.jbe.go.kr/board/list.jbe?boardId=BBS_0000130"
            "&menuCd=DOM_000000103004006000&startPage={page}")

def parse_jbe(s):
    from urllib.parse import urljoin as _uj
    items = []
    for page in (1, 2, 3):
        try:
            r = get(s, JBE_LIST.format(page=page))
            if r.status_code != 200:
                break
        except Exception:
            break
        rows = _soup(r).select("table tbody tr")
        if not rows:
            break
        for tr in rows:
            # 셀 구조: [번호, 학교급, 학교명(=앵커), 과목/제목, 모집기간(시작~마감)]
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            a = tr.find("a", href=re.compile(r"view\.jbe"))
            if not a or len(cells) < 5:
                continue
            org, subject, period = cells[2], cells[3], cells[4]
            if not EDU_MUSIC.search(subject):     # 과목 셀로만 필터 (학교명 오탐 방지)
                continue
            dl = None
            m = re.search(r"~\s*(20\d{2})-(\d{2})-(\d{2})", period)
            if m:
                dl = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            items.append(make_item(f"{org}(전북교육청)", "기타", "jbe.go.kr",
                                   f"{org} {subject} 채용",
                                   _uj("https://www.jbe.go.kr/", a["href"]),
                                   date=find_date(period), deadline=dl))
    return items

# ---- 대전교육청 구인·구직(boardCnts CMS) — goView(boardID, boardSeq, lev …) → GET view.do ----
DJE_LIST = "https://www.dje.go.kr/boardCnts/list.do?boardID={bid}&m={m}&s=dje&page={page}"
DJE_BOARDS = [("10539", "030201"), ("54", "030202")]   # 구인·구직 / 학교인력 채용공고

def parse_dje(s):
    items, seen = [], set()
    for bid, menu in DJE_BOARDS:
        for page in (1, 2):
            try:
                r = get(s, DJE_LIST.format(bid=bid, m=menu, page=page))
                if r.status_code != 200:
                    break
            except Exception:
                break
            for a in _soup(r).find_all(["a", "td"], onclick=re.compile(r"goView\(")):
                m = re.search(r"goView\('(\d+)',\s*'(\d+)',\s*'(\d+)'", a.get("onclick", ""))
                title = a.get_text(" ", strip=True)
                if not m or len(title) < 8 or title in seen or not EDU_MUSIC.search(title):
                    continue
                seen.add(title)
                url = (f"https://www.dje.go.kr/boardCnts/view.do?boardID={m.group(1)}"
                       f"&boardSeq={m.group(2)}&lev={m.group(3)}&s=dje&m={menu}")
                items.append(make_item("대전교육청(학교 채용)", "대전", "dje.go.kr",
                                       title, url, date=_row_date(a)))
    return items

# mode: "search"(키워드 루프, list에 {kw}) / "board"(단일 게시판, 제목 EDU_MUSIC 필터)
EDU_PORTALS = [
    # 서울 — 서울교육일자리포털(제목검색형, 공개). 확인·수집됨.
    {"id": "edu_seoul", "name": "서울시교육청(방과후 강사)", "region": "서울", "source": "work.sen.go.kr",
     "mode": "search",
     "list": "https://work.sen.go.kr/work/search/recInfo/BD_selectSrchRecInfo.do"
             "?q_srchType=rcrtTtl&q_srchText={kw}&q_currPage=1&q_rowPerPage=30&q_sortBy=regDt",
     "sel": 'a[href*="BD_selectRecDetail.do"]', "idpat": r"q_rcrtSn=(\d+)",
     "detail": "https://work.sen.go.kr/work/search/recInfo/BD_selectRecDetail.do?q_rcrtSn={id}"},
    # 경남 — 별도 손파서 parse_gne(works 시스템)로 이미 수집 중.
    #
    # ── 커버 현황: 시도교육청 17/17 전곳 개통 ──
    #  서울(검색형)·경남(works)·경기(POST)·강원(bbs)·전북(행필터)·대전(boardCnts)
    #  na/ntt 공통: 인천·전남·경북·세종·대구(js)·부산(http+Referer)·충북
    #  generic(GET게시판): 광주·제주·울산 / 충남(needs_js)
]

# ---------- 소스 레지스트리 ----------
# layer: A 전국집계 / B 지역슈퍼노드 / C 도메인집계 / D 원천
# poll:  daily / weekly(days=요일 0=월) / seasonal(months=[..], 시즌엔 daily)
def S(sid, name, fn, domain, layer, poll="weekly", days=(0, 2, 4), months=None):
    return {"id": sid, "name": name, "fn": fn, "domain": domain,
            "layer": layer, "poll": poll, "days": tuple(days),
            "months": tuple(months) if months else None}

SOURCES = [
    # A. 전국 집계 노드 — 매일
    S("artmore",   "아트모아(일자리 포털)",  parse_artmore,  "artmore.kr",        "A", "daily"),
    S("artinfo",   "아트인포(클래식 채용)",  parse_artinfo,  "artinfokorea.com",  "A", "daily"),
    S("cleaneye",  "클린아이 잡+(지방공공기관)", parse_cleaneye, "job.cleaneye.go.kr", "A", "daily"),
    S("gojobs",    "나라일터(공공·군악대)",  parse_gojobs,   "gojobs.go.kr",      "A", "daily"),
    # C. 도메인 집계 노드 — 매일
    S("cjob",      "기독정보넷(교회 반주)",  parse_cjob,     "cjob.co.kr",        "C", "daily"),
    S("gne",       "경남교육청 방과후강사",  parse_gne,      "gne.go.kr",         "C", "daily"),
    # B. 지역 슈퍼노드 — 주 2~3회
    S("ggac",      "경기아트센터(경기필)",   parse_ggac,     "ggac.or.kr",        "B", "weekly", (1, 4)),
    S("incheon",   "인천문화예술회관",       parse_incheon,  "incheon.go.kr",     "B", "weekly", (0, 3)),
    S("daegu",     "대구문화예술회관(시향)", parse_daegu,    "daeguartscenter.or.kr", "B", "weekly", (0, 3)),
    S("bscc",      "부산문화회관(시립예술단)", parse_bscc,   "bscc.or.kr",        "B", "weekly", (0, 3)),
    S("artsuwon",  "수원시립예술단",         parse_artsuwon, "artsuwon.or.kr",    "B", "weekly", (1, 4)),
    S("snart",     "성남문화재단",           parse_snart,    "snart.or.kr",       "B", "weekly", (0, 3)),
    S("sejongpac", "세종문화회관(서울시예술단)", parse_sejongpac, "sejongpac.or.kr", "B", "weekly", (1, 4)),
    S("cwcf",      "창원문화재단",           parse_cwcf,     "cwcf.or.kr",        "B", "weekly", (0, 3)),
    S("ulsan",     "울산문화예술회관",       parse_ulsan,    "ucac.ulsan.go.kr",  "B", "weekly", (1, 4)),
    # D. 원천 — 주 2~3회
    S("seoulphil", "서울시립교향악단",       parse_seoulphil, "seoulphil.or.kr",  "D", "weekly", (0, 2, 4)),
    S("kbs",       "KBS교향악단",            parse_kbs,      "kbssymphony.org",   "D", "weekly", (0, 2, 4)),
    S("knso",      "국립심포니오케스트라",    parse_knso,     "knso.or.kr",        "D", "weekly", (0, 2, 4)),
    S("bucheonphil", "부천필하모닉",         parse_bucheonphil, "bucheonphil.or.kr", "D", "weekly", (1, 4)),
    S("dpo",       "대전시립교향악단",       parse_dpo,      "dpo.artdj.kr",      "D", "weekly", (1, 4)),
    S("gso",       "광주시립교향악단",       parse_gso,      "gjart.gwangju.go.kr", "D", "weekly", (1, 4)),
    S("natopera",  "국립오페라단",           parse_natopera, "nationalopera.org", "D", "weekly", (1, 4)),
    S("natchorus", "국립합창단",             parse_natchorus, "nationalchorus.or.kr", "D", "weekly", (0, 3)),
    S("jeonju",    "전주시(시립예술단)",     parse_jeonju,   "jeonju.go.kr",      "D", "weekly", (2,)),
    S("sac",       "예술의전당",             parse_sac,      "sac.or.kr",         "D", "weekly", (2,)),
    S("phcf",      "포항문화재단(시립교향악단)", parse_phcf,   "phcf.or.kr",        "D", "weekly", (1, 4)),
]

# 시도교육청 방과후/강사 포털 (config 기반) — 도메인 집계 노드, 주 2회
for _ep in EDU_PORTALS:
    SOURCES.append(S(_ep["id"], _ep["name"], _make_edu_parser(_ep), _ep["source"], "C", "weekly", (1, 4)))
# 경기(POST)·강원·전북·대전 교육청 손파서
SOURCES.append(S("edu_goe", "경기교육청(방과후·강사)", parse_goe, "goe.go.kr", "C", "weekly", (1, 4)))
SOURCES.append(S("edu_gwe", "강원교육청(학교 채용)", parse_gwe, "gwe.go.kr", "C", "weekly", (1, 4)))
SOURCES.append(S("edu_jbe", "전북교육청(학교 채용)", parse_jbe, "jbe.go.kr", "C", "weekly", (1, 4)))
SOURCES.append(S("edu_dje", "대전교육청(학교 채용)", parse_dje, "dje.go.kr", "C", "weekly", (1, 4)))
# na/ntt 공통 벤더 교육청 (인천·전남·경북·세종)
for _nb in NA_NTT_BOARDS:
    SOURCES.append(S(_nb["id"], _nb["name"], _make_nantt_parser(_nb), _nb["dom"], "C", "weekly", (1, 4)))

# ---------- 자동 발견 소스 (discovery.py 산출물) ----------
_GENERIC_PAT = re.compile(r"모집|채용|공고|초빙|오디션|강사")
# 자동 발견 소스는 음악 관련 글만 수집 (재단 사서·안내원·레지던시 등 잡음 차단)
MUSIC_PAT = re.compile(
    CLASSIC_PAT.pattern + r"|찬양대|성가대|음악|연주|악단|악장|수석|예술강사")

# city-wide 통합게시판용 엄격 필터 — 광범위한 MUSIC_PAT(음악/수석/연주) 오포착 방지.
# 앙상블 명사 + 채용 동사 인접 or (상임/객원)단원 표기만 통과.
STRICT_ENSEMBLE_PAT = re.compile(
    r"(교향악단|합창단|예술단|연주단|오케스트라|국악관현악단|관현악단|필하모닉|무용단|오페라단)"
    r".{0,10}(단원|모집|채용|오디션|위촉|충원|초빙|상근)"
    r"|(상임|비상임|객원|시간제)\s*단원")

def _make_generic_parser(entry):
    music_pat = (re.compile(entry["title_pat"]) if entry.get("title_pat")
                 else STRICT_ENSEMBLE_PAT if entry.get("strict") else MUSIC_PAT)
    def parse(s):
        if entry.get("needs_js"):
            from jsfetch import render
            html = render(entry["board_url"], wait_ms=2500)
        else:
            html = get(s, entry["board_url"]).text
        soup = BeautifulSoup(html, "lxml")
        items, seen = [], set()
        for a in soup.find_all("a", href=True):
            t = a.get_text(" ", strip=True)
            if not (10 <= len(t) <= 90) or t in seen or not _GENERIC_PAT.search(t):
                continue
            if not music_pat.search(t):
                continue
            href = a["href"]
            if href.startswith(("javascript", "#", "mailto")):
                # 새올(표준 지자체 게시판) 등: 실제 permalink가 data-action에 있음
                href = a.get("data-action") or ""
                if not href or href.startswith(("javascript", "#", "mailto")):
                    continue
            seen.add(t)
            items.append(make_item(entry["name"], entry["region"],
                                   urlparse(entry["board_url"]).netloc.removeprefix("www."),
                                   t, urljoin(entry["board_url"], href), date=_row_date(a)))
        return items
    return parse

_GS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "generic_sources.json")
if os.path.exists(_GS_PATH):
    try:
        with open(_GS_PATH, encoding="utf-8") as _f:
            for _e in json.load(_f):
                SOURCES.append(S("g_" + _e["id"], _e["name"], _make_generic_parser(_e),
                                 urlparse(_e["board_url"]).netloc, "B", "weekly", (1, 4)))
    except Exception:
        pass

# 하이브레인넷(대학 음악 채용) — 로그인 세션 필요(hibrain_auth). 주간 폴링.
try:
    from sources_hibrain import parse_hibrain
    SOURCES.append(S("hibrain", "하이브레인넷(대학 음악채용)", parse_hibrain,
                     "hibrain.net", "B", "weekly", (1, 4)))
except Exception:
    pass

# 하위 호환
PARSERS = [(s["id"], s["name"], s["fn"]) for s in SOURCES]
