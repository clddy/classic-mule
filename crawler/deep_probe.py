# 게시판 깊이 탐색 — fullsweep 의 1단 탐색이 실패한 곳을 더 파고든다.
#
# fullsweep.board_candidates 는 홈페이지의 앵커 텍스트만 본다. 그래서 (1) 채용 게시판이
# 2단계 아래 있거나 (2) 메뉴가 JS 라 앵커가 없거나 (3) 링크 텍스트가 '알림마당' 같은
# 간접 표현이면 못 찾는다. 여기선 세 가지를 더 시도한다.
#   ① 관용 경로 직접 타격 (/recruit, /bbs/notice, /board/notice …)
#   ② 홈 → 1단 후보(공지·알림·소식) → 그 안의 2단 링크까지
#   ③ sitemap.xml 에서 채용성 URL 추출
#
# 대상은 인자로 준 기관명 목록(없으면 fullsweep 결과의 no_board_found 중 지정 카테고리).
# 결과는 data/fullsweep/deep_boards.json 에 병합 저장 — 사람이 보고 소스로 승격한다.
#
#   python crawler/deep_probe.py --cat 교회 민간 공공기관
#   python crawler/deep_probe.py --name 사랑의교회 소망교회
import argparse
import csv
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs4 import BeautifulSoup  # noqa: E402
from verify_urls import _fetch_either  # noqa: E402

CSV_PATH = os.path.join(BASE, "crawler", "institutions.csv")
SWEEP = os.path.join(BASE, "data", "fullsweep", "sweep-local.json")
OUT = os.path.join(BASE, "data", "fullsweep", "deep_boards.json")

# 관용 경로 — 국내 CMS 가 흔히 쓰는 채용·공지 경로
PATHS = ["/recruit", "/recruit.html", "/employ", "/job", "/jobs",
         "/bbs/board.php?bo_table=notice", "/bbs/board.php?bo_table=recruit",
         "/board/notice", "/board/recruit", "/notice", "/notice.html",
         "/community/notice", "/community/recruit", "/kor/notice",
         "/sub/notice.asp", "/html/notice.html", "/news/notice"]
# 게시글로 인정할 제목 — 음악인 채용 신호 (교회는 반주·성가대가 핵심)
ITEM_PAT = re.compile(r"(모집|채용|초빙|구인|위촉|공모|오디션|구합니다|모십니다)")
MUSIC_PAT = re.compile(r"반주|성가|찬양|지휘|오르가니스트|예배|단원|연주|악단|오케스트라|합창"
                       r"|성악|피아노|바이올린|첼로|플루트|타악|앙상블|음악")
NAV_PAT = re.compile(r"채용|구인|인재|모집|공지|알림|소식|게시판|공고|community|notice|recruit", re.I)
SKIP = re.compile(r"대관|입찰|티켓|예매|후원|기부|주차|오시는|약도|로그인|회원가입", re.I)


def get_soup(url):
    st, body, size = _fetch_either(url, timeout=12)
    if st != 200 or size < 300:
        return None, ""
    return BeautifulSoup(body, "lxml"), body


def items_in(soup, base_url):
    """모집성 게시글 추출 + 음악 신호 카운트"""
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if not (8 <= len(t) <= 90) or t in seen or not ITEM_PAT.search(t) or SKIP.search(t):
            continue
        seen.add(t)
        out.append(t)
    return out


def nav_links(soup, base_url, limit=8):
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        h = a["href"]
        if h.startswith(("javascript", "#", "mailto", "tel")) or len(t) > 20:
            continue
        if not NAV_PAT.search(t) or SKIP.search(t):
            continue
        full = urljoin(base_url, h)
        if urlparse(full).netloc != urlparse(base_url).netloc or full in seen:
            continue
        seen.add(full)
        out.append((full, t))
        if len(out) >= limit:
            break
    return out


def probe(name, home):
    """세 전략을 순서대로. 음악 신호가 있는 게시판을 최우선으로 돌려준다."""
    best = None

    def consider(url, label, titles):
        nonlocal best
        if not titles:
            return
        mus = [t for t in titles if MUSIC_PAT.search(t)]
        cand = {"board_url": url, "label": label, "rows": len(titles),
                "music": len(mus), "sample": (mus or titles)[:4]}
        if best is None or (cand["music"], cand["rows"]) > (best["music"], best["rows"]):
            best = cand

    soup, _ = get_soup(home)
    # ① 관용 경로
    for p in PATHS:
        u = home.rstrip("/") + p
        s2, _ = get_soup(u)
        if s2:
            consider(u, "관용경로" + p, items_in(s2, u))
        if best and best["music"] >= 2:
            return name, best
    # ② 홈 → 1단 → 2단
    if soup:
        for u1, lab1 in nav_links(soup, home):
            s1, _ = get_soup(u1)
            if not s1:
                continue
            consider(u1, lab1, items_in(s1, u1))
            if best and best["music"] >= 2:
                return name, best
            for u2, lab2 in nav_links(s1, u1, limit=4):
                s2, _ = get_soup(u2)
                if s2:
                    consider(u2, f"{lab1}>{lab2}", items_in(s2, u2))
                if best and best["music"] >= 2:
                    return name, best
    # ③ sitemap
    st, body, _ = _fetch_either(home.rstrip("/") + "/sitemap.xml", timeout=10)
    if st == 200 and "<loc" in body:
        for loc in re.findall(r"<loc>([^<]+)</loc>", body)[:40]:
            if re.search(r"recruit|채용|notice|공지|board", loc, re.I):
                s3, _ = get_soup(loc)
                if s3:
                    consider(loc, "sitemap", items_in(s3, loc))
                if best and best["music"] >= 2:
                    break
    return name, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", nargs="*", default=["교회", "민간", "공공기관"])
    ap.add_argument("--name", nargs="*")
    a = ap.parse_args()

    urls, cats = {}, {}
    for row in csv.reader(open(CSV_PATH, encoding="utf-8")):
        if len(row) >= 8 and row[7].strip() == "확정":
            urls[row[0]] = row[4].strip()
            cats[row[0]] = row[1]

    if a.name:
        targets = [(n, urls.get(n, "")) for n in a.name]
    else:
        sw = json.load(open(SWEEP, encoding="utf-8"))
        targets = [(r["name"], urls.get(r["name"], "")) for r in sw["results"]
                   if r.get("status") == "no_board_found" and r["cat"] in a.cat]
    targets = [(n, u) for n, u in targets if u.startswith("http")]
    print(f"깊이 탐색 {len(targets)}곳 (병렬 6)")

    found = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(probe, n, u): n for n, u in targets}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                name, best = fut.result()
            except Exception as e:
                print(f"  [{i}/{len(targets)}] ✘ {futs[fut]} {type(e).__name__}")
                continue
            if best:
                found[name] = {**best, "cat": cats.get(name, "")}
                mark = "♪" if best["music"] else " "
                print(f"  [{i}/{len(targets)}] {mark} {name} — {best['label'][:22]} "
                      f"게시글 {best['rows']} (음악 {best['music']})")
                for s in best["sample"][:2]:
                    print(f"        · {s[:62]}")
            else:
                print(f"  [{i}/{len(targets)}] △ {name} 못 찾음")

    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        old = {}
    old.update(found)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=1)
    hit = sum(1 for v in found.values() if v["music"])
    print(f"\n게시판 발견 {len(found)} (음악 신호 있는 곳 {hit}) → data/fullsweep/deep_boards.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
