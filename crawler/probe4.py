# 4단계: 까다로운 사이트 정밀 분석 (onclick 패턴, 403 우회, 게시판 위치)
import re, time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
urllib3.disable_warnings()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "ko-KR,ko;q=0.9"}

def sec(t): print(f"\n{'='*60}\n{t}\n{'='*60}")

s = requests.Session()
s.headers.update(UA)

# --- 1. 서울시향 오디션 목록 구조 ---
sec("서울시향 /recruit/orchestra/list")
r = s.get("https://www.seoulphil.or.kr/recruit/orchestra/list", timeout=15, verify=False)
m = re.findall(r'(postNo[=\'"]?\d+)', r.text)[:10]
print("postNo 패턴:", m)
soup = BeautifulSoup(r.text, "lxml")
for tag in soup.find_all(["td", "li", "dt", "strong"], string=re.compile(r"모집|오디션|채용"))[:5]:
    print("ITEM:", tag.get_text(" ", strip=True)[:80], "| parent:", str(tag.parent)[:200])

# --- 2. KNSO 목록 onclick ---
sec("KNSO list.do onclick")
r = s.get("https://www.knso.or.kr/front/M0000034/article/list.do", timeout=15, verify=False)
for m in re.findall(r'<a[^>]{0,200}onclick="([^"]+)"[^>]*>([^<]{10,80})</a>', r.text)[:5]:
    print(m)

# --- 3. 국립오페라단 notice onclick ---
sec("국립오페라단 notice onclick")
r = s.get("https://www.nationalopera.org/cpage/board/notice", timeout=15, verify=False)
for m in re.findall(r'onclick="([^"]{5,120})"[^>]*>\s*([^<]{10,80})', r.text)[:6]:
    print(m)

# --- 4. 대구콘서트하우스 onclick ---
sec("대구콘서트하우스 notice onclick")
r = s.get("https://www.daeguconcerthouse.or.kr/index.do?menu_id=00000024", timeout=15, verify=False)
for m in re.findall(r'<a[^>]{0,250}(?:onclick|href)="(javascript:[^"]{5,150}|[^"]*seq[^"]{0,80})"[^>]*>([\s\S]{0,120}?)</a>', r.text)[:6]:
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m[1])).strip()
    if txt: print(m[0][:100], "|", txt[:60])

# --- 5. 대전시향 artdj 게시판 찾기 ---
sec("대전시향 dpo.artdj.kr 내부 링크")
r = s.get("https://dpo.artdj.kr/dpo/", timeout=15, verify=False)
found = set()
for m in re.findall(r'href="([^"]*a_idx=[^"]*)"[^>]*>([^<]{2,30})', r.text):
    if m not in found:
        found.add(m)
        print(urljoin(r.url, m[0])[:100], "|", m[1].strip())

# --- 6. 예술의전당 채용 게시판 ---
sec("예술의전당 recruit 시도")
for u in ["https://www.sac.or.kr/site/main/board/recruit/list", "https://www.sac.or.kr/site/main/content/recruit"]:
    try:
        r = s.get(u, timeout=15, verify=False)
        print(u, "->", r.status_code, len(r.text))
        if r.status_code == 200 and len(r.text) > 5000:
            for m in re.findall(r'href="(/site/main/board/recruit/\d+[^"]*)"[^>]*>', r.text)[:3]:
                print("  detail:", m)
            for m in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([^<]*(?:채용|모집)[^<]*)</a>', r.text)[:5]:
                print("  item:", m[1][:60], "|", m[0][:90])
    except Exception as e:
        print(u, "ERR", str(e)[:80])

# --- 7. 창원 cwcf 403 우회 (세션+리퍼러) ---
sec("창원 cwcf 세션 재시도")
r = s.get("https://www.cwcf.or.kr/main/main.asp", timeout=15, verify=False)
print("main:", r.status_code)
r = s.get("https://www.cwcf.or.kr/commu/notice_list.asp?BCATE=BD00001", timeout=15, verify=False,
          headers={"Referer": "https://www.cwcf.or.kr/main/main.asp"})
print("board:", r.status_code, len(r.text))
if r.status_code == 200:
    for m in re.findall(r'<a[^>]+href="([^"]*notice_view[^"]*)"[^>]*>([^<]{8,80})</a>', r.text)[:5]:
        print("  ", m[1].strip()[:60], "|", m[0][:90])

# --- 8. 대구문화예술회관 ---
sec("대구문화예술회관 daeguartscenter")
r = s.get("https://daeguartscenter.or.kr/", timeout=15, verify=False)
print("main:", r.status_code, len(r.text))
soup = BeautifulSoup(r.text, "lxml")
for a in soup.find_all("a", href=True):
    t = a.get_text(" ", strip=True)
    if re.search(r"채용|공고|공지", t) and len(t) < 30:
        print("  nav:", t, "|", urljoin(r.url, a["href"])[:100])

# --- 9. 대전시청 문화예술과 공지 board ---
sec("대전시청 문화예술과 board")
u = "https://www.daejeon.go.kr/drh/depart/board/boardNormalList.do?boardId=normal_0189&menuSeq=1632"
r = s.get(u, timeout=15, verify=False)
print(r.status_code, len(r.text))
if r.status_code == 200:
    for m in re.findall(r'<a[^>]+href="([^"]*boardNormalView[^"]*)"[^>]*>\s*([^<]{8,80})', r.text)[:5]:
        print("  ", m[1].strip()[:60], "|", m[0][:100])

print("\ndone")
