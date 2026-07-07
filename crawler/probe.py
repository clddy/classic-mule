# 1단계: 후보 도메인 연결 확인 + 채용/공지 게시판 링크 자동 탐색
import json, re, sys, time
import requests
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

CANDIDATES = [
    ("seoulphil",   "서울시립교향악단",   "https://www.seoulphil.or.kr"),
    ("kbssymphony", "KBS교향악단",        "https://www.kbssymphony.org"),
    ("knso",        "국립심포니오케스트라", "https://www.knso.or.kr"),
    ("ggac",        "경기필하모닉",       "https://www.ggac.or.kr"),
    ("bucheonphil", "부천필하모닉",       "https://www.bucheonphil.or.kr"),
    ("incheonart",  "인천시립교향악단",   "https://www.incheon.go.kr/art/index"),
    ("dpo",         "대전시립교향악단",   "https://www.daejeon.go.kr/dpo/index.do"),
    ("daegu",       "대구시립교향악단",   "https://www.daegufca.or.kr"),
    ("gso",         "광주시립교향악단",   "https://gso.gwangju.go.kr"),
    ("bscc",        "부산시립교향악단",   "https://www.bscc.or.kr"),
    ("suwon",       "수원시립교향악단",   "https://www.artsuwon.or.kr"),
    ("snart",       "성남시립교향악단",   "https://www.snart.or.kr"),
    ("natopera",    "국립오페라단",       "https://www.nationalopera.org"),
    ("natchorus",   "국립합창단",         "https://www.nationalchorus.or.kr"),
    ("sejongpac",   "세종문화회관(서울시예술단)", "https://www.sejongpac.or.kr"),
    ("wonju",       "원주시립교향악단",   "https://www.wjcf.or.kr"),
    ("changwon",    "창원시립교향악단",   "https://www.cwcf.or.kr"),
    ("jeonju",      "전주시립교향악단",   "https://www.jeonju.go.kr"),
    ("cheongju",    "청주시립교향악단",   "https://www.cjcf.or.kr"),
    ("primephil",   "프라임필하모닉",     "http://www.primephil.co.kr"),
]

KEYWORDS = re.compile(r"채용|모집|단원|오디션|공고|인사")

results = []
for sid, name, url in CANDIDATES:
    row = {"id": sid, "name": name, "url": url, "status": None, "size": 0, "links": []}
    try:
        r = requests.get(url, headers=UA, timeout=12, verify=False)
        row["status"] = r.status_code
        row["size"] = len(r.text)
        row["final_url"] = r.url
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            seen = set()
            for a in soup.find_all("a", href=True):
                text = a.get_text(" ", strip=True)
                if text and KEYWORDS.search(text) and len(text) < 40:
                    href = a["href"]
                    key = (text, href)
                    if key not in seen:
                        seen.add(key)
                        row["links"].append({"text": text, "href": href})
            row["links"] = row["links"][:8]
    except Exception as e:
        row["status"] = f"ERR: {type(e).__name__}: {str(e)[:80]}"
    results.append(row)
    print(f"[{row['status']}] {name} ({row['size']}b) links={len(row['links'])}", flush=True)
    time.sleep(1)

with open(sys.argv[1] if len(sys.argv) > 1 else "probe_result.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
print("done")
