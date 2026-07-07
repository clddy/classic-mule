# JS 렌더링 필요 사이트 probe (Playwright)
import re, sys
sys.path.insert(0, r"C:\ohai\classic-mule\crawler")
from jsfetch import render
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def scan(name, url, **kw):
    print(f"\n{'='*58}\n{name} : {url[:80]}\n{'='*58}")
    try:
        html = render(url, **kw)
        print("rendered size:", len(html))
        soup = BeautifulSoup(html, "lxml")
        n = 0
        for a in soup.find_all("a", href=True):
            t = a.get_text(" ", strip=True)
            if 8 <= len(t) <= 90 and re.search(r"모집|채용|강사|공고|단원", t):
                oc = (a.get("onclick") or "")[:50]
                print("  ", t[:56], "|", urljoin(url, a["href"])[:80], ("| oc:" + oc if oc else ""))
                n += 1
                if n >= 7: break
        if n == 0:
            # onclick 행 기반 탐색
            for m in re.findall(r'onclick="([^"]{5,90})"[^>]*>([^<]{10,80})<', html):
                if re.search(r"모집|채용|강사|공고", m[1]):
                    print("  oc:", m[0][:60], "|", m[1][:50])
                    n += 1
                    if n >= 7: break
        if n == 0: print("  (없음)")
    except Exception as e:
        print("ERR", type(e).__name__, str(e)[:120])

scan("경기교육청 초중등시간강사", "https://www.goe.go.kr/recruit/ad/func/pb/hnfpPbancList.do", selector="a", click="a[href='#tab2']")
scan("인천교육청 채용", "https://www.ice.go.kr/ice/na/ntt/selectNttList.do?mi=10997", selector="a")
scan("대전교육청 joPbanc", "https://as.dje.go.kr/prog/joPbanc/kr/sub04_01/list.do", selector="a")
scan("울산문화예술회관", "https://ucac.ulsan.go.kr/", selector="a")
scan("대구문화예술진흥원 공고", "https://dgfca.or.kr/article/NOTICE", selector="a")
print("\ndone")
