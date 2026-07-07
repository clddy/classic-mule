# Wave1/3 신규 소스 probe: 나라일터, 아트인포, 기독정보넷
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
urllib3.disable_warnings()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
s = requests.Session(); s.headers.update(UA)

def sec(t): print(f"\n{'='*58}\n{t}\n{'='*58}")

def links(r, pat, n=6):
    soup = BeautifulSoup(r.text, "lxml")
    c = 0
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if len(t) < 8: continue
        if re.search(pat, a["href"]) or re.search(pat, t):
            print("  ", t[:58], "|", urljoin(r.url, a["href"])[:90])
            c += 1
            if c >= n: break
    if c == 0: print("  (없음)")
    return c

# 1. 나라일터 — 검색 URL 후보들
sec("나라일터 gojobs 검색")
for u in [
    "https://www.gojobs.go.kr/apmList.do?searchDetailWord=&searchWord=%EC%97%B0%EC%A3%BC",   # 연주
    "https://www.gojobs.go.kr/apmList.do?searchWord=%EA%B5%B0%EC%95%85",                     # 군악
    "https://www.gojobs.go.kr/empmnInfoList.do?searchWord=%EC%97%B0%EC%A3%BC",
]:
    try:
        r = s.get(u, timeout=15, verify=False)
        print(u[30:75], "->", r.status_code, len(r.text))
        if r.status_code == 200 and len(r.text) > 5000:
            if links(r, r"apmView|empmnsn", 5): break
    except Exception as e:
        print("ERR", str(e)[:80])

# 2. 아트인포코리아
sec("아트인포 artinfokorea.com/jobs")
try:
    r = s.get("https://www.artinfokorea.com/jobs", timeout=15, verify=False)
    print(r.status_code, len(r.text))
    links(r, r"/jobs?/", 7)
    # next.js data?
    if "__NEXT_DATA__" in r.text:
        print("  [Next.js SSR — __NEXT_DATA__ 존재]")
except Exception as e:
    print("ERR", str(e)[:80])

# 3. 기독정보넷 반주자 카테고리
sec("기독정보넷 cjob 반주자(c_jikjong=2)")
try:
    r = s.get("https://www.cjob.co.kr/offerIG?c_jikjong=2&page=1&device=pc", timeout=15, verify=False)
    print(r.status_code, len(r.text))
    links(r, r"offer|view|idx", 8)
except Exception as e:
    print("ERR", str(e)[:80])

print("\ndone")
