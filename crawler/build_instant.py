# -*- coding: utf-8 -*-
"""local/spacecloud_mirror.json → data/practice-instant.js (즉시예약·민간)
게시 원칙: 실존 업체의 '사실 정보'만(상호·주소·전화·가격·좌표) + 출처 표기·원문 링크.
        스페이스클라우드의 마케팅 설명문은 복제하지 않는다(desc 제외).
※ 프로토타입 한정. 실서비스 시 미러링 금지 — 민간은 호스트 직접 등록 원칙.
"""
import json, os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "local", "spacecloud_mirror.json")
OUT = os.path.join(BASE, "data", "practice-instant.js")

# 스클 텍스트에서 감지한 신호 → 포디엄 악기 택소노미(사실 매핑)
SIG2INST = {
    "그랜드": "피아노있음", "피아노": "피아노있음",
    "성악": "성악·앙상블가능", "앙상블": "성악·앙상블가능", "합주": "성악·앙상블가능",
    "오케스트라": "대편성가능",
    "현악": "성악·앙상블가능", "목관": "성악·앙상블가능", "관악": "금관가능",
}
GU = re.compile(r"(서울|경기|인천|부산|대구|광주|대전|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주)"
                r"\S*\s+(\S+?[구시군])")

src = json.load(open(SRC, encoding="utf-8"))
rooms = []
for r in src["items"]:
    addr = r.get("addr") or ""
    m = GU.search(addr)
    sido = m.group(1) if m else "서울"
    sido = {"서울특별시": "서울"}.get(sido, sido)
    gu = m.group(2) if m else None
    insts = sorted({SIG2INST[s] for s in (r.get("classic_signal") or []) if s in SIG2INST})
    lo, hi = r.get("hourly_min"), r.get("hourly_max")
    # 시간 단가 상식 범위(5만원) 초과면 월정액·패키지가 잘못 잡힌 것 → 게시하지 않고 원문 확인으로
    if lo and lo > 50_000:
        lo = hi = None
    price = (f"시간 {lo:,}~{hi:,}원" if lo and hi and lo != hi
             else f"시간 {lo:,}원" if lo else "요금 원문 확인")
    rooms.append({k: v for k, v in {
        "name": r["name"].strip(),
        "category": "instant",
        "sido": sido, "district": gu, "region": gu or sido,
        "addr": addr or None,
        "phone": r.get("tel"),
        "lat": float(r["lat"]) if r.get("lat") else None,
        "lng": float(r["lng"]) if r.get("lng") else None,
        "hourlyMin": lo, "hourlyMax": hi,
        "price": price, "free": False,
        "instant": True, "minHours": 1,
        "instruments": insts,
        "booking_url": r.get("url"),
        "src": "spacecloud.kr",
        "verified": src.get("fetched"),
    }.items() if v not in (None, "", [])})

with open(OUT, "w", encoding="utf-8") as f:
    f.write("// 자동생성: crawler/build_instant.py ← local/spacecloud_mirror.json\n")
    f.write("// 즉시예약(민간) — 실존 업체의 사실 정보만 수록(상호·주소·전화·가격·좌표) + 출처·원문 링크.\n")
    f.write("// 원 플랫폼의 설명문은 복제하지 않음. 프로토타입 한정 — 실서비스 시 호스트 직접 등록으로 대체.\n")
    f.write("window.INSTANT_ROOMS = ")
    json.dump(rooms, f, ensure_ascii=False, indent=1)
    f.write(";\n")
print(f"즉시예약 {len(rooms)}곳 → {OUT}")
for r in rooms:
    print(f"  {r['name'][:26]:28} {r.get('region',''):6} {r['price']:16} {','.join(r.get('instruments',[]))}")
