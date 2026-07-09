# 게시판 목록의 '게시글 행' 구조 확인 (네비 제외, 상세링크 패턴만)
import re, sys
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from common import new_session, get

BOARDS = {
    "과천-채용": "https://www.gcart.or.kr/kr/commu/recruitList.do",
    "진주-채용공고": "https://www.jinju.go.kr/00130/02730/06660.web",
    "목포-채용공고": "https://www.mokpo.go.kr/www/mokpo_news/notification/incruit",
    "여수-시험채용": "https://www.yeosu.go.kr/www/govt/news/recruit",
}
DETAIL = re.compile(r"view|detail|read|articleNo|nttId|boardSeq|seq=|idx=|no=|wr_id|bod_sn|_no\b", re.I)

def dump(name, url):
    s = new_session()
    print(f"\n### {name}  {url}")
    try:
        r = get(s, url)
    except Exception as e:
        print(f"  실패 {type(e).__name__}: {str(e)[:80]}"); return
    html = r.text
    soup = BeautifulSoup(html, "lxml")
    # 1) 상세링크 href 패턴 앵커
    hits = []
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        h = a["href"]
        if 6 <= len(t) <= 90 and DETAIL.search(h) and not h.startswith(("javascript","#","mailto")):
            hits.append((t[:55], urljoin(url, h)[:75]))
    # 2) onclick 방식
    onclicks = []
    for a in soup.find_all("a", onclick=True):
        t = a.get_text(" ", strip=True)
        if 6 <= len(t) <= 90:
            onclicks.append((t[:55], a["onclick"][:55]))
    print(f"  href상세앵커 {len(hits)}개 / onclick앵커 {len(onclicks)}개")
    for t, h in hits[:8]:
        print(f"    a[href] · {t:55} → {h}")
    for t, o in onclicks[:8]:
        print(f"    onclick  · {t:55} :: {o}")
    if not hits and not onclicks:
        # 3) 테이블 tr에 뭐가 있나
        trs = re.findall(r"<tr[^>]*>[\s\S]{20,300}?</tr>", html)
        print(f"  상세앵커 0 — tr {len(trs)}개, iframe {'있음' if '<iframe' in html else '없음'}")

if __name__ == "__main__":
    only = sys.argv[1:]
    for name, url in BOARDS.items():
        if not only or any(o in name for o in only):
            dump(name, url)
