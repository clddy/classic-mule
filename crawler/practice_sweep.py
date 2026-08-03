# 연습실 전수 순회 — 공유누리(eshare.go.kr) 전국 공공자원 통합검색.
#
# 공고 쪽 fullsweep 과 같은 자리(2026-08-02 이식): 개별 시설을 돌지 않고 **채널**을 돈다.
# 공유누리 = 행안부 운영, 전국 11만 공유자원 통합 — 연습실 검색만으로 287건(서울 yeyak 5건의
# 57배). 각 항목의 osdScrUrl 이 지자체 원문 예약처 딥링크라 포디엄 링크 원칙(원문으로
# 딥링크, 집계 포털로 내보내지 않음)과 구조가 맞는다.
#
# 관측 전용: data/fullsweep/practice_sweep.json 에 기록하고, --compare 로 기존
# 시드(practice_spaces_seed.csv)·yeyak 수집분 대비 공백을 낸다. 사이트 게시는 별도 결정.
#
#   python crawler/practice_sweep.py             # 순회
#   python crawler/practice_sweep.py --compare   # 기존 등재분 대비 공백 리포트
import csv
import io
import json
import os
import re
import sys
import time
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
import urllib3
urllib3.disable_warnings()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "fullsweep", "practice_sweep.json")
SEED = os.path.join(BASE, "data", "practice_spaces_seed.csv")

PORTAL = "https://www.eshare.go.kr"
PAGE = PORTAL + "/UserPortal/Upc/UpcMapSrchResult/index.do"
API = PORTAL + "/UserPortal/Upc/UpcMapSrchResult/indexSrchResult.do"

# 음악 연습에 닿는 검색어 — 넓게 긁고 이름으로 거른다 (practice_yeyak.py 와 같은 2단 구조)
KEYWORDS = ["연습실", "합주실", "음악연습", "음악실", "밴드", "피아노", "공연연습", "음악창작소"]
# yeyak 과 같은 필터 — 무용·체육·회의실류 배제
MUSIC_OK = re.compile(r"연습실|합주|음악|피아노|밴드|공연연습|창작소")
MUSIC_NO = re.compile(r"댄스|무용|발레|골프|스크린|체육|운동|요가|필라테스|회의|세미나|강의실$"
                      r"|스터디|미술|공예|도예|목공|요리|바둑")


def sweep():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126"})
    r0 = s.get(PAGE, params={"rsrc_nm": "연습실"}, timeout=25, verify=False)  # 세션 쿠키
    found, dropped = {}, 0
    for kw in KEYWORDS:
        first, total, got = 0, None, 0
        while True:
            try:
                r = s.post(API, json={"searchKeyword": kw, "searchCondition": "",
                                      "rsrcClsCd": "", "sido": "", "sigungu": "",
                                      "firstIndex": first, "recordCountPerPage": "100"},
                           headers={"Referer": r0.url}, timeout=25, verify=False)
                d = r.json()["resultList"]
            except Exception as e:
                print(f"  [{kw}] 페이지 {first} 실패: {type(e).__name__}")
                break
            items = d.get("resultList") or []
            total = d.get("totalCnt", 0)
            for it in items:
                no, nm = it.get("rsrcNo"), (it.get("rsrcNm") or "").strip()
                if not no or no in found or not nm:
                    continue
                if MUSIC_NO.search(nm) or not MUSIC_OK.search(nm):
                    dropped += 1
                    continue
                addr = (it.get("addr") or "").strip()
                sido = addr.split()[0] if addr else ""
                found[no] = {
                    "name": nm, "addr": addr, "sido": sido,
                    "free": it.get("freeYnNm") == "Y",
                    "cls": it.get("rsrcClsNm") or "",
                    "bookTo": it.get("osdScrUrl") or "",   # 지자체 원문 예약처 딥링크
                    "kw": kw,
                }
            got += len(items)
            if not items or got >= total:
                break
            first += len(items)
            time.sleep(0.5)
        print(f"  [{kw}] 검색 {total}건 → 누적 채택 {len(found)}")
        time.sleep(0.5)

    payload = {"date": date.today().isoformat(), "src": "eshare.go.kr",
               "count": len(found), "dropped": dropped, "items": found}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    from collections import Counter
    print(f"\n채택 {len(found)}곳 (비음악 제외 {dropped}) → data/fullsweep/practice_sweep.json")
    print("시도별:", Counter(v["sido"] for v in found.values()).most_common())
    return 0


def _norm(s):
    return re.sub(r"[\s()\[\]·┃|,-]", "", s or "")


def compare():
    sw = json.load(open(OUT, encoding="utf-8"))
    have = set()
    for row in csv.DictReader(open(SEED, encoding="utf-8")):
        n = (row.get("name") or "").strip()
        if n and not n.startswith("#"):
            have.add(_norm(n))
    try:
        t = io.open(os.path.join(BASE, "data", "practice-yeyak.js"), encoding="utf-8").read()
        for it in json.loads(t[t.find("{"):t.rfind(";")])["items"]:
            have.add(_norm(it["name"]))
    except Exception:
        pass
    gaps = [v for v in sw["items"].values()
            if not any(_norm(v["name"])[:8] in h or h[:8] in _norm(v["name"]) for h in have if len(h) >= 6)]
    from collections import Counter
    print(f"공유누리 {sw['count']}곳 중 기존 미등재 {len(gaps)}곳")
    print("시도별 공백:", Counter(g["sido"] for g in gaps).most_common())
    for g in sorted(gaps, key=lambda x: x["sido"])[:40]:
        print(f"  [{g['sido']:3}] {g['name'][:40]} — {'무료' if g['free'] else '유료'}")
    if len(gaps) > 40:
        print(f"  … 외 {len(gaps) - 40}곳 (전량은 practice_sweep.json 대조)")
    return 0


if __name__ == "__main__":
    sys.exit(compare() if "--compare" in sys.argv else sweep())
