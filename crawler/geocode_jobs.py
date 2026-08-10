# -*- coding: utf-8 -*-
"""공고 위치 보강 — 주소가 없으면 기관 이름으로 찾아낸다 → data/org-coords.json

왜: 공고 대부분이 주소를 안 적는다. 그런데 연주자에게 '어디인지'는 지원 여부를 가르는
정보다(악기를 들고 가야 한다). 주소가 있으면 그걸 쓰고, 없으면 기관 이름으로 지오코딩해
좌표와 정규화된 주소를 얻는다 (2026-08-09 사용자 지시).

정책: Nominatim 이용약관 준수 — 초당 1건 이하, 식별 가능한 User-Agent, 결과 캐시.
실패는 캐시하지 않는다(다음에 이름이 나아지면 다시 시도해야 하므로).

★ 반드시 지켜야 할 검증: 찾아낸 좌표의 시도가 공고의 지역과 같은지 대조한다.
   CLAUDE.md 함정 — 아르코 12곳이 전부 나주 본부 주소로 채워졌던 사고가 이 검증이
   없어서 났다. 이름만으로 찾으면 같은 이름의 다른 지역 기관이 잡히기 쉽다.
"""
import json
import os
import re
import sys
import time

import requests
import urllib3

urllib3.disable_warnings()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "org-coords.json")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".geocode-cache.json")
UA = {"User-Agent": "podium-jobs-geocoder/1.0 (podiumclassical.kr; ohmjin3141@naver.com)"}

# 장소가 아닌 이름 — 지오코딩해 봐야 엉뚱한 곳이 잡힌다
NOT_A_PLACE = re.compile(r"교육청|기독정보넷|포털|교육지원청|재단법인$|\(주\)|주식회사")

SIDO_FULL = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
             "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
             "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
             "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
             "제주": "제주특별자치도"}
# 화면 표기가 '광주·전남'인 통합 광역단체 — 질의는 둘 다 시도한다
REGION_QUERY = {"광주·전남": ["광주광역시", "전라남도"]}

cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(coords):
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)      # 쓰다 죽어도 기존 파일이 반쪽으로 남지 않게


def _clean_name(name):
    """기관명에서 괄호 주석·꼬리표를 뗀다 — '성은교회(부천 오정구 소재)' → '성은교회'."""
    n = re.sub(r"\([^)]*\)", " ", str(name or ""))
    n = re.sub(r"\s*(?:공지|채용|구인|모집|시험)\s*$", "", n)
    return re.sub(r"\s+", " ", n).strip(" ·-")


def _queries(name, region):
    """정확한 것부터 — 시도+이름, 이름 단독."""
    out = []
    for sido in REGION_QUERY.get(region, [SIDO_FULL.get(region, "")]):
        if sido:
            out.append(f"{sido} {name}")
    out.append(name)
    return [q for q in dict.fromkeys(out) if q.strip()]


def _geocode(q):
    """좌표와 함께 주소 문자열도 돌려준다 — 카드에 '어디인지'를 보여주기 위함."""
    if q in cache:
        c = cache[q]
        return None if (isinstance(c, dict) and c.get("miss")) else c
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": q, "format": "json", "limit": 1,
                                 "countrycodes": "kr", "addressdetails": 1},
                         headers=UA, timeout=15, verify=False)
        js = r.json()
        hit = None
        if js:
            a = js[0].get("address") or {}
            hit = {"lat": float(js[0]["lat"]), "lng": float(js[0]["lon"]),
                   "display": js[0].get("display_name", ""),
                   "state": a.get("state") or a.get("province") or "",
                   "city": a.get("city") or a.get("county") or a.get("town") or ""}
    except Exception:
        hit = None
    # 실패도 기록한다. 예전엔 성공만 캐시했는데, 명부 606곳 중 절반이 OSM에 없어서
    # 매 실행마다 같은 곳을 다시 물어보느라 25분을 넘겨 시간 제한에 걸렸다 (2026-08-09).
    # 못 찾은 것은 날짜와 함께 남겨, 나중에 다시 훑고 싶을 때 골라낼 수 있게 한다.
    cache[q] = hit if hit else {"miss": time.strftime("%Y-%m-%d")}
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    time.sleep(1.1)          # Nominatim: 초당 1건 이하
    return hit


def _fmt_addr(display, name=""):
    """Nominatim 표기에서 **도로명주소**만 골라 낸다.

    도로명주소는 '시도 + 시군구 + 도로명 + 건물번호'다. 동(법정동·행정동)은 들어가지 않는다.
    예전엔 통째로 뒤집어 붙였더니 동이 끼어들어 실제와 달라졌다 —
      '월촌중학교, 31, 목동서로, 목동, 목5동, 양천구, 서울특별시, 07984, 대한민국'
      전: '서울특별시 양천구 목5동 목동 목동서로 31'   (동이 둘이나 끼었다)
      후: '서울특별시 양천구 목동서로 31'              (2026-08-10 사용자 지적)
    도로명을 못 찾으면 동까지 넣은 지번식 표기로 물러난다 — 없는 것보다는 낫다.
    """
    parts = [p.strip() for p in (display or "").split(",") if p.strip()]
    parts = [p for p in parts if p != "대한민국" and not re.fullmatch(r"\d{5}", p)]
    if parts and name and parts[0].startswith(name[:3]):
        parts = parts[1:]                      # 맨 앞 기관명 — 카드에 이미 있다

    sido = next((p for p in parts if re.search(r"(특별시|광역시|특별자치시|특별자치도|도)$", p)), "")
    # 시군구는 시도를 뺀 것 중 마지막(=상위) 것. '수원시 장안구'처럼 둘이면 둘 다 쓴다.
    sgg = [p for p in parts if p != sido and re.search(r"(시|군|구)$", p)]
    road = next((p for p in parts if re.search(r"(로|길)$", p)), "")
    num = ""
    if road:
        i = parts.index(road)
        # 건물번호는 도로명 바로 앞에 온다 (Nominatim 은 좁은 것부터 나열한다)
        if i > 0 and re.fullmatch(r"\d+(-\d+)?", parts[i - 1]):
            num = parts[i - 1]
    if sido and road:
        return " ".join(x for x in [sido, *reversed(sgg[:2]), road, num] if x)
    return " ".join(reversed(parts))           # 도로명이 없으면 있는 대로


def _region_ok(hit, region):
    """찾아낸 곳의 시도가 공고 지역과 맞는가 — 안 맞으면 동명이인 기관이다."""
    if not region or region == "기타":
        return True          # 우리도 지역을 모르면 대조할 기준이 없다
    want = REGION_QUERY.get(region, [SIDO_FULL.get(region, "")])
    state = (hit.get("state") or "") + " " + (hit.get("display") or "")
    return any(w and (w in state or w[:2] in state) for w in want)


def _from_master():
    """기관 명부(crawler/institutions.csv) 전체 — 미리 찾아 두면 새 공고가 즉시 위치를 갖는다."""
    import csv
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "institutions.csv")
    out = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("#") or row[0] == "기관명":
                    continue
                name = _clean_name(row[0])
                region = row[3].strip() if len(row) > 3 else ""
                if name and len(name) >= 3 and not NOT_A_PLACE.search(name):
                    out.append((name, region))
    except FileNotFoundError:
        pass
    return out


def reformat(verbose=True):
    """이미 찾아 둔 곳의 주소 표기만 다시 만든다 — 재조회 없이 캐시의 원본으로.

    표기 규칙을 고쳤을 때 220곳을 다시 물어보면 4시간이 걸린다. 원본(display)은 캐시에
    남아 있으므로 그것으로 다시 찍어 낸다 (2026-08-10).
    """
    coords = _load(OUT, {})
    disp = {}
    for q, v in cache.items():
        if isinstance(v, dict) and v.get("display"):
            # 질의는 '서울특별시 월촌중학교' 처럼 시도가 붙어 있다 — 이름만 남겨 대조한다
            disp.setdefault(q.split(" ")[-1], v["display"])
            disp.setdefault(q, v["display"])
    n = 0
    for name, rec in coords.items():
        d = disp.get(name)
        if not d:
            continue
        new = _fmt_addr(d, name)
        if new and new != rec.get("addr"):
            rec["addr"] = new
            n += 1
    _save(coords)
    if verbose:
        print(f"[geocode_jobs] 주소 표기 재정리 {n}곳 / 전체 {len(coords)}곳")
    return n


def run(limit=40, verbose=True, items=None, master=False):
    """items 를 넘기면 그 목록에서, 안 넘기면 official.json 에서 대상을 고른다.
    master=True 면 기관 명부 전체를 훑는다(초벌 채우기용)."""
    if items is None:
        doc = _load(os.path.join(BASE, "data", "official.json"), {})
        items = doc.get("items") if isinstance(doc, dict) else doc
    coords = _load(OUT, {})

    if master:
        todo = [(n, r) for n, r in _from_master() if n not in coords][:limit]
        if verbose:
            print(f"[geocode_jobs] 명부에서 {len(todo)}곳 조회 (이미 찾은 {len(coords)}곳 제외)")
        return _sweep(todo, coords, verbose)

    todo = []
    for it in (items or []):
        key = _clean_name(it.get("org"))
        if not key or len(key) < 3 or NOT_A_PLACE.search(key):
            continue
        if it.get("addr") or key in coords:
            continue
        todo.append((key, it.get("region") or ""))
    # 같은 기관이 여러 공고에 걸쳐 있으면 한 번만 찾는다
    todo = list(dict.fromkeys(todo))[:limit]
    if not todo:
        if verbose:
            print("[geocode_jobs] 찾을 대상 없음")
        return 0
    return _sweep(todo, coords, verbose)


def _sweep(todo, coords, verbose):
    if not todo:
        return 0
    found = 0
    for name, region in todo:
        hit = None
        for q in _queries(name, region):
            h = _geocode(q)
            if h and _region_ok(h, region):
                hit = h
                break
            if h and verbose:
                print(f"    [건너뜀] {name}: 찾은 곳이 {h.get('state','?')} — 공고 지역 {region} 과 불일치")
        if hit:
            coords[name] = {"lat": hit["lat"], "lng": hit["lng"],
                            "addr": _fmt_addr(hit["display"], name),
                            "at": time.strftime("%Y-%m-%d")}
            found += 1
            if verbose:
                print(f"    {name} → {hit['display'][:60]}", flush=True)
            # 찾는 대로 바로 저장한다. 명부 606곳을 훑다 시간 제한에 걸려 죽었을 때
            # 마지막에 한 번만 쓰는 구조라 그때까지 찾은 것이 통째로 날아갔다 (2026-08-09).
            if found % 10 == 0:
                _save(coords)
    _save(coords)
    if verbose:
        print(f"[geocode_jobs] {found}/{len(todo)}건 위치 확보 · 누적 {len(coords)}곳")
    return found


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", action="store_true", help="기관 명부 전체를 훑는다(초벌 채우기)")
    ap.add_argument("--limit", type=int, default=40, help="이번 실행에서 조회할 최대 곳 수")
    ap.add_argument("--reformat", action="store_true", help="재조회 없이 주소 표기만 다시 만든다")
    a = ap.parse_args()
    if a.reformat:
        sys.exit(0 if reformat() >= 0 else 1)
    sys.exit(0 if run(limit=a.limit, master=a.master) >= 0 else 1)
