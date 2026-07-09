# 새올 게시판 실경로 발견: 홈/채용페이지 렌더 → HTML에서 saeol/gosi URL 추출 → data-action 확인
import re, sys
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from jsfetch import render
from common import new_session, get

CITIES = {
 "익산": "https://www.iksan.go.kr",
 "청주": "https://www.cheongju.go.kr",
 "강릉": "https://www.gn.go.kr",
 "김천": "https://www.gimcheon.go.kr",
 "춘천": "https://www.chuncheon.go.kr",
}
SAEOL = re.compile(r'["\'/]([\w/]*saeol/gosi/list\.do[^"\'>\s]*)')

def find_saeol_path(home):
    # 1) 홈 렌더 HTML에서 saeol URL 직접 탐색
    try:
        html = render(home, wait_ms=3000)
    except Exception as e:
        return None, f"홈렌더실패 {type(e).__name__}"
    hits = set(SAEOL.findall(html))
    return hits, None

def check_board(url):
    try:
        html = render(url, wait_ms=3000)
    except Exception as e:
        return f"렌더실패 {type(e).__name__}"
    soup = BeautifulSoup(html, "lxml")
    da = [a.get_text(" ",strip=True)[:40] for a in soup.find_all("a")
          if a.get("data-action") and "view.do" in a.get("data-action","")
          and 6 <= len(a.get_text(" ",strip=True)) <= 90]
    return f"data-action 게시글 {len(da)}건" + (f" 예:{da[0]}" if da else "")

if __name__ == "__main__":
    only = sys.argv[1:]
    for city, home in CITIES.items():
        if only and not any(o in city for o in only):
            continue
        print(f"\n### {city}  {home}")
        hits, err = find_saeol_path(home)
        if err:
            print(f"  {err}"); continue
        if not hits:
            print("  홈에 saeol/gosi 경로 없음 (다른 CMS이거나 딥링크)"); continue
        for path in list(hits)[:4]:
            u = urljoin(home, "/" + path.lstrip("/"))
            print(f"  {path[:55]} → {check_board(u)}")
