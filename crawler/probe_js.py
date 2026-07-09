# JS 홈페이지 렌더 → 채용/모집/공고 게시판 링크 추출
import re, sys
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from jsfetch import render

BOARD = re.compile(r"채용|모집|공고|오디션|구인|알림마당|공지|고시|소식|게시판")
SKIP = re.compile(r"입찰|낙찰|재정|예산|보도|영상|포토|사진|정책|규제|민원|의견|설문|안전|재난")

SITES = {
 "포항문화재단": "https://www.phcf.or.kr",
 "원주시": "https://www.wonju.go.kr",
 "익산시": "https://www.iksan.go.kr",
 "청주시": "https://www.cheongju.go.kr",
 "강릉시": "https://www.gn.go.kr",
 "김천시": "https://www.gimcheon.go.kr",
}

def scan(name, home):
    print(f"\n### {name}  {home}")
    try:
        html = render(home, wait_ms=3000)
    except Exception as e:
        print(f"  렌더실패 {type(e).__name__}: {str(e)[:80]}"); return
    soup = BeautifulSoup(html, "lxml")
    seen = {}
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        h = a["href"]
        if h.startswith(("javascript","#","mailto")) or not (2 <= len(t) <= 22):
            continue
        if BOARD.search(t) and not SKIP.search(t):
            full = urljoin(home, h)
            if full not in seen:
                seen[full] = t
    print(f"  게시판후보 {len(seen)}개")
    for full, t in list(seen.items())[:18]:
        print(f"    · {t:16} {full[:88]}")

if __name__ == "__main__":
    only = sys.argv[1:]
    for name, home in SITES.items():
        if not only or any(o in name for o in only):
            scan(name, home)
