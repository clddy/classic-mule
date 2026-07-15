# -*- coding: utf-8 -*-
"""연습실 좌표 보강 — OSM Nominatim 지오코딩 → data/practice-coords.js
정책: Nominatim 이용약관 준수(초당 1건 이하, 식별 가능한 User-Agent). 결과는 캐시해 재요청 최소화.
좌표 없는 곳은 프론트가 구/시 중심 근사치로 폴백한다.
"""
import json, os, re, sys, time
import requests, urllib3
urllib3.disable_warnings()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "practice-coords.js")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".geocode-cache.json")

UA = {"User-Agent": "podium-practice-geocoder/1.0 (classic-mule prototype; ohmjin3141@naver.com)"}
cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}


def targets():
    """data/practice-*.js 는 손으로 쓴 JS(주석·비따옴표 키)라 node로 로드해 추출한다."""
    import subprocess, tempfile
    d = os.path.join(BASE, "data").replace("\\", "/")
    js = f"""
    global.window = {{}};
    const fs = require('fs');
    for (const f of ['practice-seed.js','practice-public.js','practice-yeyak.js']) {{
      const p = '{d}/' + f;
      if (fs.existsSync(p)) eval(fs.readFileSync(p, 'utf8'));
    }}
    const w = global.window;
    const out = [...(w.SEED_ROOMS||[]), ...(w.PUBLIC_ROOMS||[]), ...((w.YEYAK_ROOMS||{{}}).items||[])];
    process.stdout.write(JSON.stringify(out));
    """
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js); tmp = f.name
    try:
        r = subprocess.run(["node", tmp], capture_output=True, text=True, encoding="utf-8")
        return json.loads(r.stdout) if r.stdout.strip() else []
    finally:
        os.unlink(tmp)


def clean_addr(a):
    """'서울 마포구 양화로 72, 효성해링턴타워 B1~B2 (서교동)' → '서울 마포구 양화로 72'
    Nominatim은 건물명·층·괄호주석이 붙으면 매칭을 실패한다."""
    a = re.sub(r"\(.*?\)", " ", a or "")          # 괄호 주석
    a = a.split(",")[0]                            # 콤마 뒤 건물명
    a = re.sub(r"\s*(지하\s*\d*|B\d+|\d+층|\d+호|[가-힣A-Za-z]*빌딩|[가-힣]*타워).*$", "", a)
    return re.sub(r"\s+", " ", a).strip(" ·-")


def queries_for(r):
    """정확한 것부터 순서대로 시도 — 도로명주소 > 시도+구+주소 > 시도+구+이름"""
    sido = r.get("sido") or ""
    dist = r.get("district") or (r.get("region") if re.search(r"구$|시$|군$", r.get("region", "")) else "")
    addr = clean_addr(r.get("addr") or "")
    name = r.get("name", "")
    qs = []
    if re.search(r"(로|길)\s*\d", addr):           # 도로명+번지 = 최상
        qs.append(addr if re.match(r"^(서울|경기|인천|부산|대구|광주|대전|울산|세종|강원|충|전|경|제주)", addr)
                  else f"{sido} {addr}")
    if addr and addr not in qs:
        qs.append(" ".join(x for x in [sido, dist, addr] if x))
    if name:
        qs.append(" ".join(x for x in [sido, dist, name] if x))
        qs.append(name)                            # 기관명 단독 (우진문화공간 등)
    return [q.strip() for q in dict.fromkeys(qs) if q.strip()]


def geocode(q):
    if q in cache:
        return cache[q]
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": q, "format": "json", "limit": 1, "countrycodes": "kr"},
                         headers=UA, timeout=15, verify=False)
        js = r.json()
        hit = [float(js[0]["lat"]), float(js[0]["lon"])] if js else None
    except Exception:
        hit = None
    cache[q] = hit
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    time.sleep(1.1)          # Nominatim: 초당 1건 이하
    return hit


def main():
    rooms = targets()
    coords, ok = {}, 0
    for r in rooms:
        name = r.get("name")
        if not name:
            continue
        hit, used = None, ""
        for q in queries_for(r):
            hit = geocode(q)
            if hit:
                used = q; break
        if hit:
            coords[name] = [round(hit[0], 6), round(hit[1], 6)]
            ok += 1
        print(f"  {'OK ' if hit else '·  '}{name[:30]:32} ← {(used or '(전부 실패)')[:44]}")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// 자동생성: crawler/geocode_practice.py (OSM Nominatim)\n")
        f.write("// 공간명 → [위도, 경도]. 없는 곳은 프론트가 구/시 중심 근사치로 폴백.\n")
        f.write("window.ROOM_COORDS = ")
        json.dump(coords, f, ensure_ascii=False, indent=1)
        f.write(";\n")
    print(f"\n지오코딩 {ok}/{len(rooms)}곳 → {OUT}")


if __name__ == "__main__":
    main()
