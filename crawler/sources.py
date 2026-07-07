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
        if len(title) < 6 or not re.search(r"교향악단|합창단|예술단|국악단|연주단", title):
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

def parse_gne(s):
    r = get(s, GNE_URL)
    items, seen = [], set()
    for a in _soup(r).select("a"):
        title = a.get_text(" ", strip=True)
        if (len(title) < 10 or title in seen
                or not re.search(r"오케스트라|관현악", title)
                or not re.search(r"모집|채용|초빙|공고", title)):
            continue
        seen.add(title)
        items.append(make_item("경남 학교 방과후(교육청 포털)", "기타", "gne.go.kr",
                               title, GNE_URL, date=_row_date(a)))
    return items

# ---------- 20. 아트모아 (문체부·예술경영지원센터 일자리 포털) ----------
CLASSIC_PAT = re.compile(
    r"오케스트라|교향악단|필하모닉|합창단|오페라|클래식|단원 ?모집|지휘자|반주자"
    r"|콰르텟|앙상블|성악|바이올린|비올라|첼로|더블베이스|플루트|오보에|클라리넷"
    r"|바순|호른|트럼펫|트롬본|튜바|팀파니|피아니스트")

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
        items.append(make_item("아트모아(예술 일자리 포털)", "기타", "artmore.kr",
                               title, urljoin("https://www.artmore.kr", a["href"]),
                               date=_row_date(a)))
    return items

# ---------- 22. 아트인포코리아 (클래식 전문 채용 포털) ----------
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
        items.append(make_item("아트인포(클래식 채용)", region_from(full), "artinfokorea.com",
                               title[:90], urljoin("https://www.artinfokorea.com", href),
                               date=_row_date(a)))
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
]

# ---------- 자동 발견 소스 (discovery.py 산출물) ----------
_GENERIC_PAT = re.compile(r"모집|채용|공고|초빙|오디션|강사")
# 자동 발견 소스는 음악 관련 글만 수집 (재단 사서·안내원·레지던시 등 잡음 차단)
MUSIC_PAT = re.compile(
    CLASSIC_PAT.pattern + r"|찬양대|성가대|음악|연주|악단|악장|수석|예술강사")

def _make_generic_parser(entry):
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
            if not MUSIC_PAT.search(t):
                continue
            if a["href"].startswith(("javascript", "#", "mailto")):
                continue
            seen.add(t)
            items.append(make_item(entry["name"], entry["region"],
                                   urlparse(entry["board_url"]).netloc.removeprefix("www."),
                                   t, urljoin(entry["board_url"], a["href"]), date=_row_date(a)))
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

# 하위 호환
PARSERS = [(s["id"], s["name"], s["fn"]) for s in SOURCES]
