# -*- coding: utf-8 -*-
"""practice_spaces_seed.csv → data/practice-seed.js (window.SEED_ROOMS)
개별 공간만 변환 — [포털]/[명부]/[네트워크] 메타 행은 프론트 '수집 정보' 안내용으로 별도 배열.
큐레이션(practice-public.js)과 이름 중복은 프론트에서 dedup(큐레이션 우선)."""
import csv, json, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data", "practice_spaces_seed.csv")
OUT = os.path.join(BASE, "data", "practice-seed.js")

rooms, metas = [], []
with open(SRC, encoding="utf-8") as f:
    rdr = csv.reader(f)
    hdr = None
    for row in rdr:
        if not row or row[0].lstrip().startswith("#"):
            continue
        if row[0] == "name":
            hdr = row
            continue
        d = dict(zip(hdr, row))
        name = d["name"].strip()
        price_type, price = d["price_type"].strip(), d["price"].strip()
        free = price_type == "무료" or price == "0"
        price_disp = ("무료" if free
                      else f"{int(price):,}원/{d['rental_unit'] or '회'}" if price.isdigit() and price != "0"
                      else (price_type or "요금 기관 확인"))
        src_dom = re.sub(r"^https?://(www\.)?", "", d["booking_url"]).split("/")[0]
        item = {
            "name": name, "category": "public",
            "sido": d["region"].strip(),
            "district": d["district"].strip() or None,
            "region": d["district"].strip() or d["region"].strip(),
            "addr": d["address"].strip() or None,
            "price": price_disp, "free": free,
            "selection": d["selection"].strip() or None,
            "apply_method": d["apply_method"].strip() or None,
            "apply_timing": d["apply_timing"].strip() or None,
            "eligibility": d["eligibility"].strip() or None,
            "instruments": [x for x in d["instruments"].split("|") if x],
            "booking_url": d["booking_url"].strip(),
            "src": src_dom,
            "notes": d["notes"].strip() or None,
            "verified": "2026-07-12",
        }
        item = {k: v for k, v in item.items() if v not in (None, "", [])}
        if name.startswith("["):
            metas.append({"name": name, "url": d["booking_url"].strip(),
                          "note": (d["notes"].strip()[:80] if d["notes"].strip() else "")})
        else:
            rooms.append(item)

with open(OUT, "w", encoding="utf-8") as f:
    f.write("// 자동생성: crawler/build_practice_seed.py ← data/practice_spaces_seed.csv (수정은 CSV에서)\n")
    f.write("// 신청제·공공 실재검증 시드 — 각 기관 공식정보 웹검증(2026-07-12)\n")
    f.write("window.SEED_ROOMS = ")
    json.dump(rooms, f, ensure_ascii=False, indent=1)
    f.write(";\nwindow.SEED_SOURCES = ")
    json.dump(metas, f, ensure_ascii=False, indent=1)
    f.write(";\n")

print(f"공간 {len(rooms)}곳 + 소스노드 {len(metas)}개 → {OUT}")
