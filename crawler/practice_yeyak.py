# -*- coding: utf-8 -*-
"""서울시 공공서비스예약(yeyak.seoul.go.kr) — 음악 연습 가능 공간 수집.

신청제·공공 연습공간의 최대 노드. 검색 AJAX(selectPageListSvcMoreAjax.do)로
연습 관련 키워드를 훑고, 상세(selectReservView.do)에서 요금·예약방법·선정방법·
대상·접수기간을 파싱해 data/practice-yeyak.js 로 내보낸다.

사용: python crawler/practice_yeyak.py
"""
import json, os, re, sys, time
import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "practice-yeyak.js")

PORTAL = "https://yeyak.seoul.go.kr"
AJAX = PORTAL + "/web/search/selectPageListSvcMoreAjax.do?currentPage={page}"
VIEW = PORTAL + "/web/reservation/selectReservView.do?rsv_svc_id={sid}"

# 음악 연습에 쓸 수 있는 공간을 넓게 검색 → 이름으로 정밀 필터
KEYWORDS = ["연습실", "합주", "음악실", "음악연습", "공연연습", "피아노", "밴드실", "다목적실"]
# 이름 필터: 음악 연습 가능 신호 (다목적실은 '연습' 동반 시만 — 회의용 다목적실 배제)
MUSIC_OK = re.compile(r"연습실|합주|음악|피아노|밴드|공연연습")
MUSIC_NO = re.compile(r"댄스|무용|발레|골프|스크린|체육|운동|요가|필라테스|회의|세미나|강의|스터디|녹음실 ?전용")

SEOUL_GU = re.compile(r"(종로|중구|용산|성동|광진|동대문|중랑|성북|강북|도봉|노원|은평|서대문|마포"
                      r"|양천|강서|구로|금천|영등포|동작|관악|서초|강남|송파|강동)구?")


def _session():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    s.get(PORTAL + "/web/main.do", timeout=20, verify=False)
    return s


def search(s, kw):
    """키워드로 서비스 목록 수집 (페이지네이션)."""
    out, page = [], 1
    while page <= 10:
        try:
            r = s.post(AJAX.format(page=page),
                       data={"sch_text": kw, "sch_row_per_page": "50"},
                       timeout=20, verify=False,
                       headers={"X-Requested-With": "XMLHttpRequest",
                                "Referer": PORTAL + "/web/search/selectPageListTotalSearch.do"})
            d = r.json()
        except Exception:
            break
        lst = d.get("resultList") or []
        out += lst
        total = (d.get("param") or {}).get("svcTotCount") or 0
        if len(out) >= total or not lst:
            break
        page += 1
        time.sleep(0.4)
    return out


_LBL = {
    "fee": r"이용요금\s*([^ ]{1,20}(?:\s?원)?)",
    "method": r"예약방법\s*([가-힣]{2,6})",   # 인터넷/방문/전화 한 단어 — 뒤따르는 '문의전화…' 오포획 방지
    "phone": r"문의전화\s*([^ ]{2,30}(?:\s*/\s*[\d\-]{9,13})?)",
    "select": r"선정방법\s*([가-힣]{2,8})",
    "target": r"이용대상\s*(.{2,40}?)\s*(?:장소|서비스|이용기간)",
    "place": r"장소\s*(.{2,50}?)\s*지도보기",
    "use": r"이용기간\s*([\d.:~\s]{8,40})",
    "apply": r"접수기간\s*([\d.:~\s]{8,45})",
}

def detail(s, sid):
    try:
        r = s.get(VIEW.format(sid=sid), timeout=20, verify=False)
        if r.status_code != 200:
            return {}
    except Exception:
        return {}
    txt = re.sub(r"\s+", " ", BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
    out = {}
    for k, pat in _LBL.items():
        m = re.search(pat, txt)
        if m:
            out[k] = m.group(1).strip()
    return out


# 다목적실(주민센터·청년센터)은 이름만으론 음악 가능 여부를 모름 → 상세 설명에서 판별
_DETAIL_MUSIC = re.compile(r"악기|음악|합주|연주|공연 ?연습|밴드|피아노|보면대")

def main():
    s = _session()
    seen, rows, cands = set(), [], []
    for kw in KEYWORDS:
        for it in search(s, kw):
            sid, name = it.get("SVC_ID"), (it.get("SVC_NM") or "").strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            if MUSIC_NO.search(name):
                continue
            rec = {"sid": sid, "name": name, "free": it.get("PCHRG_YN") == "N"}
            if MUSIC_OK.search(name):
                rows.append(rec)          # 이름부터 음악 신호 → 바로 포함
            else:
                cands.append(rec)         # 다목적실류 → 상세 설명으로 판별
    print(f"[yeyak] 이름 확정 {len(rows)}건 + 후보(다목적실류) {len(cands)}건 — 상세 판별")
    for c in cands:
        try:
            r = s.get(VIEW.format(sid=c["sid"]), timeout=20, verify=False)
            txt = re.sub(r"\s+", " ", BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
            # 상세 본문 중 '서비스 소개' 근처에서 음악 신호 (페이지 공통 문구 오탐 방지: 이름+소개부만)
            body = txt[txt.find("서비스"):txt.find("주의사항")] if "서비스" in txt else txt
            if _DETAIL_MUSIC.search(body):
                rows.append(c)
                print(f"  [상세판별 포함] {c['name'][:40]}")
        except Exception:
            pass
        time.sleep(0.4)
    items = []
    for r_ in rows:
        d = detail(s, r_["sid"])
        time.sleep(0.5)
        gu = SEOUL_GU.search(f"{r_['name']} {d.get('place','')}")
        items.append({
            "name": r_["name"],
            "category": "public",
            "region": (gu.group(1) + "구") if gu else "서울",
            "addr": d.get("place") or "",
            "price": d.get("fee") or ("무료" if r_["free"] else "유료(상세 참조)"),
            "selection": d.get("select") or "",
            "apply_method": d.get("method") or "인터넷",
            "apply_timing": d.get("apply") or "",
            "eligibility": d.get("target") or "",
            "hours": d.get("use") or "",
            "phone": d.get("phone") or "",
            "booking_url": VIEW.format(sid=r_["sid"]),
            "src": "yeyak.seoul.go.kr",
        })
        print(f"  · {r_['name'][:36]} | {items[-1]['price']} | {items[-1]['selection']}")
    from datetime import date
    payload = {"fetched": date.today().isoformat(), "items": items}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.YEYAK_ROOMS = ")
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write(";\n")
    print(f"[yeyak] {len(items)}건 저장 → {OUT}")


if __name__ == "__main__":
    main()
