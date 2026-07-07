# 3단계: 확정 후보 게시판에서 공고 아이템이 실제로 뽑히는지 확인
import re, time, sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
urllib3.disable_warnings()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
      "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
      "Referer": "https://www.google.com/"}

KEY = re.compile(r"모집|채용|공고|오디션|단원")

BOARDS = [
    ("seoulphil-audition", "https://www.seoulphil.or.kr/recruit/orchestra/list"),
    ("kbs-recruit", "https://www.kbssymphony.org/ko/info/recruit.php"),
    ("knso-notice", "https://www.knso.or.kr/front/M0000034/article/list.do"),
    ("ggac-notice", "https://www.ggac.or.kr/?p=42"),
    ("bucheonphil-main", "https://www.bucheonphil.or.kr/front/M0000000/index.do"),
    ("incheon-art", "https://www.incheon.go.kr/art/ART040102"),
    ("dpo-artdj", "https://dpo.artdj.kr/dpo/"),
    ("dgfca-notice", "https://dgfca.or.kr/article/NOTICE"),
    ("gso-notice", "https://gjart.gwangju.go.kr/gso/cmd.do?opencode=pg_0501"),
    ("bscc-recruit", "https://www.bscc.or.kr/05_community/?mcode=0405010000"),
    ("artsuwon", "http://artsuwon.or.kr/?p=49"),
    ("natopera-notice", "https://www.nationalopera.org/cpage/board/notice"),
    ("natchorus", "http://nationalchorus.or.kr/notice-2/"),
    ("cwcf-recruit", "http://www.cwcf.or.kr/commu/notice_list.asp?BCATE=BD00001"),
    ("jeonju-exam", "https://www.jeonju.go.kr/index.9is?contentUid=ff8080818990c349018b041a87bd395c"),
    ("cjcf-new", "https://cjcf.or.kr/new"),
    ("dch-notice", "https://www.daeguconcerthouse.or.kr/index.do?menu_id=00000024"),
    ("sac-main", "https://www.sac.or.kr"),
]

for sid, url in BOARDS:
    print(f"\n=== {sid} : {url}")
    try:
        r = requests.get(url, headers=UA, timeout=15, verify=False)
        print(f"  status={r.status_code} size={len(r.text)}")
        if r.status_code != 200 or len(r.text) < 500:
            print("  BODY:", r.text[:300].replace("\n", " "))
            continue
        soup = BeautifulSoup(r.text, "lxml")
        n = 0
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            if 8 <= len(text) <= 90 and KEY.search(text):
                full = urljoin(r.url, a["href"])
                print(f"  * {text[:70]} | {full[:110]}")
                n += 1
                if n >= 6: break
        if n == 0:
            print("  (키워드 매칭 항목 없음 — JS 렌더링이거나 다른 URL 필요)")
    except Exception as e:
        print(f"  ERR {type(e).__name__}: {str(e)[:100]}")
    time.sleep(1)
print("\ndone")
