# 2단계: 작동 사이트의 채용 게시판 URL 정밀 탐색 + 리다이렉트 추적
import json, re, sys, time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
urllib3.disable_warnings()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "ko-KR,ko;q=0.9"}

def fetch(url):
    r = requests.get(url, headers=UA, timeout=12, verify=False)
    return r

# href 패턴으로 채용 게시판 후보 추출
HREF_PAT = re.compile(r"recruit|채용|job|emplmnt|audition|notice|bbs|board|pst_id", re.I)
TEXT_PAT = re.compile(r"채용|모집|오디션|단원|공지|공고")

def scan(name, url):
    print(f"\n=== {name} : {url}")
    try:
        r = fetch(url)
        print(f"  status={r.status_code} size={len(r.text)} final={r.url}")
        if len(r.text) < 2000:
            # 리다이렉트 페이지 — meta/js 이동 대상 출력
            print("  BODY:", r.text[:500].replace("\n", " "))
            return
        soup = BeautifulSoup(r.text, "lxml")
        found = {}
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)[:50]
            href = a["href"]
            if href.startswith("javascript"): continue
            if (TEXT_PAT.search(text) and HREF_PAT.search(href)) or re.search(r"recruit|audition|emplmnt", href, re.I):
                full = urljoin(r.url, href)
                if full not in found:
                    found[full] = text
        for u, t in list(found.items())[:12]:
            print(f"  [{t}] {u}")
    except Exception as e:
        print(f"  ERR {type(e).__name__}: {str(e)[:100]}")

TARGETS = [
    ("서울시향", "https://www.seoulphil.or.kr"),
    ("국립심포니", "https://www.knso.or.kr"),
    ("인천예술회관 채용/공모", "https://www.incheon.go.kr/art/ART040102"),
    ("성남문화재단 채용", "https://www.snart.or.kr/main/pst/list.do?pst_id=recruit"),
    ("국립오페라단 오디션", "https://www.nationalopera.org/cpage/program/knoAuditions"),
    ("세종문화회관 공지", "https://www.sejongpac.or.kr/portal/bbs/B0000058/list.do?menuNo=200568"),
    ("창원문화재단", "https://www.cwcf.or.kr/main/main.asp"),
    ("경기아트센터 main.do", "https://www.ggac.or.kr/main.do"),
    ("부천필 redirect", "https://www.bucheonphil.or.kr"),
    ("부산문화회관 redirect", "https://www.bscc.or.kr"),
    ("청주 cjcf redirect", "https://www.cjcf.or.kr"),
    ("국립합창단 (헤더보강)", "https://www.nationalchorus.or.kr"),
]

for name, url in TARGETS:
    scan(name, url)
    time.sleep(1)
print("\ndone")
