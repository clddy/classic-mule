# 명부 파이프 (§5): 후보 기관 → 채용 게시판 자동 발견 → 검증 → 자동 등록/확인 큐
# 실행: python discovery.py  → data/generic_sources.json(자동 등록) + data/source_queue.json(확인 대기)
import json, os, re, sys, time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
urllib3.disable_warnings()

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
    ("hibrain",  "하이브레인넷",        "기타", "https://www.hibrain.net"),
    # 대형교회 자체 오케스트라
    ("onnuri",   "온누리교회",          "서울", "https://www.onnuri.org"),
    ("sarang",   "사랑의교회",          "서울", "https://www.sarang.org"),
    ("fgtv",     "여의도순복음교회",    "서울", "https://www.fgtv.com"),
]

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

    with open(os.path.join(BASE, "data", "generic_sources.json"), "w", encoding="utf-8") as f:
        json.dump(registered, f, ensure_ascii=False, indent=1)
    with open(os.path.join(BASE, "data", "source_queue.json"), "w", encoding="utf-8") as f:
        json.dump({"queue": queue, "failed": failed}, f, ensure_ascii=False, indent=1)
    print(f"\n자동 등록 {len(registered)} / 확인 큐 {len(queue)} / 실패 {len(failed)}")

if __name__ == "__main__":
    run()
