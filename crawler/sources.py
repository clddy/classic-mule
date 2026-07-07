# 기관별 파서 — 각 함수는 make_item 리스트를 반환
import re, json
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from common import get, make_item, find_date, relevant

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

PARSERS = [
    ("seoulphil",   "서울시립교향악단",        parse_seoulphil),
    ("kbs",         "KBS교향악단",             parse_kbs),
    ("knso",        "국립심포니오케스트라",     parse_knso),
    ("ggac",        "경기아트센터(경기필)",     parse_ggac),
    ("bucheonphil", "부천필하모닉",            parse_bucheonphil),
    ("incheon",     "인천문화예술회관",         parse_incheon),
    ("dpo",         "대전시립교향악단",         parse_dpo),
    ("daegu",       "대구문화예술회관(시향)",   parse_daegu),
    ("gso",         "광주시립교향악단",         parse_gso),
    ("bscc",        "부산문화회관(시립예술단)", parse_bscc),
    ("artsuwon",    "수원시립예술단",           parse_artsuwon),
    ("snart",       "성남문화재단",             parse_snart),
    ("natopera",    "국립오페라단",             parse_natopera),
    ("natchorus",   "국립합창단",               parse_natchorus),
    ("sejongpac",   "세종문화회관(서울시예술단)", parse_sejongpac),
    ("cwcf",        "창원문화재단",             parse_cwcf),
    ("jeonju",      "전주시(시립예술단)",       parse_jeonju),
    ("sac",         "예술의전당",               parse_sac),
]
