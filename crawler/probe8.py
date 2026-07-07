# 추가 소스 probe: 아트모아, 울산, 인천교육청, 대전교육청, 포항
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

def show_links(r, pat, n=6, keyfilter=None):
    soup = BeautifulSoup(r.text, "lxml")
    cnt = 0
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if len(t) < 8: continue
        if keyfilter and not re.search(keyfilter, t): continue
        if re.search(pat, a["href"]):
            print("  ", t[:56], "|", urljoin(r.url, a["href"])[:95])
            cnt += 1
            if cnt >= n: break
    if cnt == 0: print("  (매칭 없음)")

# 1. 아트모아 검색 (오케스트라)
sec("아트모아 search_list 오케스트라")
try:
    r = s.get("https://www.artmore.kr/sub/recruit/search_list.do", params={"sch_keyword": "오케스트라"}, timeout=15, verify=False)
    print(r.status_code, len(r.text))
    show_links(r, r"search_view", 8)
    # 파라미터 이름 확인용 폼 필드
    for m in re.findall(r'<input[^>]+name="([^"]+)"', r.text)[:15]:
        print("  input:", m)
except Exception as e: print("ERR", str(e)[:100])

# 2. 울산문화예술회관 공지/채용
sec("울산 ucac.ulsan.go.kr")
try:
    r = s.get("https://ucac.ulsan.go.kr/", timeout=15, verify=False)
    print(r.status_code, len(r.text))
    soup = BeautifulSoup(r.text, "lxml")
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if re.search(r"공지|채용|모집|알림", t) and len(t) < 30:
            print("  nav:", t, "|", urljoin(r.url, a["href"])[:90])
except Exception as e: print("ERR", str(e)[:100])

# 3. 인천교육청 채용 board (mi=10997)
sec("인천교육청 selectNttList mi=10997")
try:
    r = s.get("https://www.ice.go.kr/ice/na/ntt/selectNttList.do?mi=10997", timeout=15, verify=False)
    print(r.status_code, len(r.text))
    show_links(r, r"selectNttInfo", 6)
except Exception as e: print("ERR", str(e)[:100])

# 4. 대전교육청 joPbanc
sec("대전교육청 joPbanc list")
for u in ["https://as.dje.go.kr/prog/joPbanc/kr/sub04_01/list.do",
          "https://as.dje.go.kr/prog/joPbanc/kr/sub04_01/"]:
    try:
        r = s.get(u, timeout=15, verify=False)
        print(u[-30:], "->", r.status_code, len(r.text))
        if r.status_code == 200 and len(r.text) > 3000:
            show_links(r, r"view\.do|pbancNo", 6)
            break
    except Exception as e: print("ERR", str(e)[:100])

# 5. 포항문화재단
sec("포항문화재단 phcf.or.kr")
try:
    r = s.get("https://phcf.or.kr/", timeout=12, verify=False)
    print(r.status_code, len(r.text))
    soup = BeautifulSoup(r.text, "lxml")
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if re.search(r"채용|모집|공지", t) and len(t) < 30:
            print("  nav:", t, "|", urljoin(r.url, a["href"])[:90])
except Exception as e: print("ERR", str(e)[:100])

print("\ndone")
