# 교육청 방과후/강사 채용 게시판 구조 확인
import re
import requests
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
s = requests.Session(); s.headers.update(UA)

def sec(t): print(f"\n{'='*60}\n{t}\n{'='*60}")

# 1. 경남 구인구직포털 (오케스트라 검색)
sec("경남 gne.go.kr works 오케스트라 검색")
u = "https://www.gne.go.kr/works/user/recruitment/BD_recruitmentList.do?q_searchKey=1001&q_searchVal=%EC%98%A4%EC%BC%80%EC%8A%A4%ED%8A%B8%EB%9D%BC&q_rowPerPage=10&q_currPage=1"
try:
    r = s.get(u, timeout=15, verify=False)
    print(r.status_code, len(r.text))
    soup = BeautifulSoup(r.text, "lxml")
    for a in soup.find_all("a", href=True)[:60]:
        t = a.get_text(" ", strip=True)
        if len(t) > 8 and re.search(r"모집|채용|강사|공고", t):
            print("  ", t[:60], "|", a["href"][:80])
except Exception as e:
    print("ERR", str(e)[:100])

# 2. 경기교육청 채용 목록
sec("경기 goe.go.kr hnfpPbancList")
u = "https://www.goe.go.kr/recruit/ad/func/pb/hnfpPbancList.do"
try:
    r = s.get(u, timeout=15, verify=False)
    print(r.status_code, len(r.text))
    # 목록 아이템 패턴 추정
    for m in re.findall(r'<a[^>]+href="([^"]{5,120})"[^>]*>([\s\S]{0,120}?)</a>', r.text):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m[1])).strip()
        if len(t) > 8 and re.search(r"모집|채용|강사|공고", t):
            print("  ", t[:60], "|", m[0][:80])
    # onclick 패턴
    for m in re.findall(r'onclick="([^"]{5,80})"[^>]*>([^<]{10,80})<', r.text)[:5]:
        print("  onclick:", m[0][:60], "|", m[1][:50])
except Exception as e:
    print("ERR", str(e)[:100])

print("\ndone")
