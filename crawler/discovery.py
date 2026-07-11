# 명부 파이프 (§5): 후보 기관 → 채용 게시판 자동 발견 → 검증 → 자동 등록/확인 큐
# 실행: python discovery.py  → data/generic_sources.json(자동 등록) + data/source_queue.json(확인 대기)
# 후보는 (1) 아래 CANDIDATES 하드코딩 + (2) institutions.csv 실재검증 명부(홈페이지 보유·확정)에서 자동 로드
import json, os, re, sys, time, csv
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import urllib3
urllib3.disable_warnings()

# Windows 콘솔/리다이렉트(cp949)에서 ✔/✘ 등 유니코드 출력이 죽지 않도록 stdout 강제 utf-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import UA

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Wave 2(지역 슈퍼노드) + Wave 4(원천 공백) 후보 명부
CANDIDATES = [
    # 지역 문화재단 (산하 시향·꿈의오케·강사 공고 동시 게시)
    ("phcf",     "포항문화재단",        "경북", "https://phcf.or.kr"),
    ("cfac",     "천안문화재단",        "충남", "https://www.cfac.or.kr"),
    ("cccf",     "춘천문화재단",        "강원", "https://www.cccf.or.kr"),
    ("wonjucf",  "원주문화재단",        "강원", "https://www.wonjucf.or.kr"),
    ("ghcf",     "김해문화재단",        "경남", "https://www.ghcf.or.kr"),
    ("gumicf",   "구미문화재단",        "경북", "https://www.gumicf.or.kr"),
    ("jfac",     "제주문화예술재단",    "제주", "https://www.jfac.kr"),
    ("ansanart", "안산문화재단",        "경기", "https://www.ansanart.com"),
    ("ayac",     "안양문화예술재단",    "경기", "https://www.ayac.or.kr"),
    ("uac",      "의정부예술의전당",    "경기", "https://www.uac.or.kr"),
    ("artgy",    "고양문화재단",        "경기", "https://www.artgy.or.kr"),
    ("gfac",     "강남문화재단(강남심포니)", "서울", "https://www.gfac.or.kr"),
    ("sfac",     "서울문화재단",        "서울", "https://www.sfac.or.kr"),
    ("ifac",     "인천문화재단",        "인천", "https://www.ifac.or.kr"),
    ("bscf",     "부산문화재단",        "부산", "https://www.bscf.or.kr"),
    ("gjcf",     "광주문화재단",        "기타", "https://www.gjcf.or.kr"),
    ("sjcf",     "세종시문화재단",      "기타", "https://www.sjcf.or.kr"),
    # 시립예술단 (시청 채용/고시 게시판 — 교향악단·합창단 병설)
    ("gcart",    "고양문화재단(고양시립합창단)", "경기", "https://www.gcart.or.kr"),
    ("mokpo",    "목포시립예술단(교향악단·합창단)", "전남", "https://www.mokpo.go.kr"),
    ("yeosu",    "여수시립예술단",      "전남", "https://www.yeosu.go.kr"),
    ("wonju",    "원주시립교향악단·합창단", "강원", "https://www.wonju.go.kr"),
    ("gumi",     "구미시립예술단",      "경북", "https://www.gumi.go.kr"),
    # 국립·공연 단체 (피트/전속 수요)
    ("dgopera",  "대구오페라하우스",    "대구", "https://www.daeguoperahouse.org"),
    ("knb",      "국립발레단",          "서울", "https://www.korean-national-ballet.kr"),
    ("ubc",      "유니버설발레단",      "서울", "https://www.universalballet.com"),
    ("jeongdong","정동극장",            "서울", "https://www.jeongdong.or.kr"),
    ("lottech",  "롯데콘서트홀",        "서울", "https://www.lotteconcerthall.com"),
    # 축제 (시즌)
    ("timf",     "통영국제음악재단",    "경남", "https://www.timf.org"),
    ("gmmfs",    "평창대관령음악제",    "강원", "https://www.gmmfs.com"),
    # 도메인 노드 (Wave 3)
    ("arte",     "아르떼(문화예술교육진흥원)", "기타", "https://www.arte.or.kr"),
    # 하이브레인넷 제외: 로그인 강제 포털이라 본문·연락처 추출 불가 + 링크가 포털行(원칙 위반)
    # 대형교회 자체 오케스트라
    ("onnuri",   "온누리교회",          "서울", "https://www.onnuri.org"),
    ("sarang",   "사랑의교회",          "서울", "https://www.sarang.org"),
    ("fgtv",     "여의도순복음교회",    "서울", "https://www.fgtv.com"),
]

# ---------- institutions.csv 명부 → 후보 자동 로드 ----------
def _dom(url):
    return urlparse(url).netloc.removeprefix("www.")

def load_from_institutions():
    """실재검증 명부(institutions.csv)에서 홈페이지 보유·확정 기관을 후보로 로드.
    이미 손파서/하드코딩 후보로 커버된 도메인은 제외."""
    path = os.path.join(BASE, "crawler", "institutions.csv")
    if not os.path.exists(path):
        return []
    try:
        from sources import SOURCES
        covered = {s["domain"].removeprefix("www.") for s in SOURCES}
    except Exception:
        covered = set()
    covered |= {_dom(h) for *_, h in CANDIDATES}
    out, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].lstrip().startswith("#") or row[0] == "기관명" or len(row) < 8:
                continue
            name, region, home, real = row[0], row[3], row[4].strip(), row[7].strip()
            home = home.split("(")[0].strip()
            if not home.startswith("http") or real != "확정":
                continue
            dom = _dom(home)
            if not dom or dom in covered or dom in seen:
                continue
            seen.add(dom)
            sid = "i_" + re.sub(r"[^a-z0-9]", "", dom.replace(".", ""))[:16]
            out.append((sid, name, region or "기타", home))
    return out

CANDIDATES = CANDIDATES + load_from_institutions()

NAV_PAT = re.compile(r"채용|인재|구인|모집공고|공지사항|공고|알림")
ITEM_PAT = re.compile(r"모집|채용|공고|초빙|오디션|강사")
EXCLUDE_NAV = re.compile(r"대관|입찰|결과|당첨|티켓|예매")

def fetch(s, url, use_js=False):
    if use_js:
        try:
            from jsfetch import render
            return render(url, wait_ms=2500)
        except Exception:
            return ""
    try:
        r = s.get(url, timeout=12, verify=False)
        r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""

def board_candidates(html, base_url):
    """홈페이지에서 채용/공지 게시판 링크 후보 추출"""
    soup = BeautifulSoup(html, "lxml")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        h = a["href"]
        if h.startswith(("javascript", "#", "mailto")) or len(t) > 20:
            continue
        if NAV_PAT.search(t) and not EXCLUDE_NAV.search(t):
            full = urljoin(base_url, h)
            if full not in seen:
                seen.add(full)
                # 채용 명시 > 공지 순으로 정렬 점수
                score = 2 if re.search(r"채용|인재|구인|모집", t) else 1
                out.append((score, full, t))
    out.sort(key=lambda x: -x[0])
    return out[:4]

def extract_items(html, base_url):
    """게시판 페이지에서 모집성 게시글 추출 (범용 휴리스틱)"""
    soup = BeautifulSoup(html, "lxml")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if not (10 <= len(t) <= 90) or not ITEM_PAT.search(t) or t in seen:
            continue
        h = a["href"]
        if h.startswith(("javascript", "#", "mailto")):
            continue
        seen.add(t)
        items.append({"title": t, "url": urljoin(base_url, h)})
        if len(items) >= 6:
            break
    return items

def run():
    s = requests.Session()
    s.headers.update(UA)
    registered, queue, failed = [], [], []

    for sid, name, region, home in CANDIDATES:
        print(f"--- {name} ({home})", flush=True)
        html = fetch(s, home)
        used_js = False
        if len(html) < 3000:  # JS 스텁 → 렌더링
            html = fetch(s, home, use_js=True)
            used_js = True
        if len(html) < 3000:
            failed.append({"id": sid, "name": name, "reason": "홈페이지 접근 실패"})
            print("    접근 실패")
            continue

        best = None
        for score, board_url, label in board_candidates(html, home):
            bhtml = fetch(s, board_url)
            bjs = False
            if len(bhtml) < 3000:
                bhtml = fetch(s, board_url, use_js=True)
                bjs = True
            items = extract_items(bhtml, board_url) if bhtml else []
            if not items and not bjs:  # 정적 0건 → JS 렌더 재시도 (saeol·재단 게시판 다수 JS)
                bhtml2 = fetch(s, board_url, use_js=True)
                items2 = extract_items(bhtml2, board_url) if bhtml2 else []
                if items2:
                    items, bjs = items2, True
            print(f"    [{label}] {board_url[:70]} → {len(items)}건")
            if items and (best is None or len(items) > len(best["sample"])):
                best = {"id": sid, "name": name, "region": region,
                        "board_url": board_url, "board_label": label,
                        "needs_js": used_js or bjs,
                        "sample": items}
            if best and len(best["sample"]) >= 3:
                break
            time.sleep(0.6)

        if best and len(best["sample"]) >= 2:
            registered.append(best)
            print(f"    ✔ 자동 등록 ({len(best['sample'])}건 확인)")
        elif best:
            queue.append(best)
            print(f"    ? 확인 큐 (1건만 확인)")
        else:
            failed.append({"id": sid, "name": name, "reason": "게시판 미발견/항목 없음"})
            print("    ✘ 미발견")
        time.sleep(0.8)

    # 머지: 이번 실행에서 테스트하지 않은 기존 등록 소스는 보존(통째 덮어쓰기로 인한 회귀 방지).
    # 테스트한 후보는 이번 결과(registered)로 갱신 — 검증 실패 시 자연 드랍.
    gs_path = os.path.join(BASE, "data", "generic_sources.json")
    tested_ids = {sid for sid, *_ in CANDIDATES}
    prev_registered = []
    if os.path.exists(gs_path):
        try:
            with open(gs_path, encoding="utf-8") as f:
                prev_registered = json.load(f)
        except Exception:
            pass
    preserved = [e for e in prev_registered if e.get("id") not in tested_ids]
    merged = preserved + registered
    with open(gs_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    if preserved:
        print(f"(미테스트 기존 소스 {len(preserved)}개 보존)")
    with open(os.path.join(BASE, "data", "source_queue.json"), "w", encoding="utf-8") as f:
        json.dump({"queue": queue, "failed": failed}, f, ensure_ascii=False, indent=1)
    print(f"\n자동 등록 {len(registered)} / 확인 큐 {len(queue)} / 실패 {len(failed)}")

if __name__ == "__main__":
    run()
