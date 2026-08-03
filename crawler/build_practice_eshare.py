# 공유누리 순회 결과 → 사이트 데이터 (시설 단위 묶음)
#
# 사용자 결정(2026-08-02): 방 단위 304건을 그대로 뿌리면 목록이 지저분하다 —
# **시설 단위로 묶어 카드 하나**, 카드를 누르면 **방 목록**이 열리는 구조.
# 이 스크립트가 practice_sweep.json(방 단위)을 시설로 묶어 data/practice-eshare.js 로 낸다.
#
#  · 지역 정규화: 주소 첫 토큰(경기도/경기, 전남광주통합특별시…)을 17개 시도 표기로
#    (jobs.js REGION_LIST·crawler/common.py 와 같은 체계)
#  · 시설명 추출: "합주실 B┃포천음악창작소"(포털이 방┃시설로 쓰는 표기), "군포시생활문화
#    센터 (마루연습실)", "오정생활문화센터 개인연습실 2" — 시설 접미어(센터·회관·창작소…)
#    까지를 시설로, 나머지를 방으로 가른다. 못 가르면 통째로 시설 1실.
#  · 기존 등재분(시드·yeyak)과 이름이 겹치는 시설은 뺀다 — 화면 병합의 중복 제거와 같은 규칙.
#
#   python crawler/build_practice_eshare.py
import csv
import io
import json
import os
import re
import sys
from collections import OrderedDict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWEEP = os.path.join(BASE, "data", "fullsweep", "practice_sweep.json")
SEED = os.path.join(BASE, "data", "practice_spaces_seed.csv")
OUT = os.path.join(BASE, "data", "practice-eshare.js")

# 주소 첫 토큰 → 17개 시도 (jobs.js REGION_LIST와 동일 표기)
SIDO = {}
for keys, val in [
    (("서울", "서울특별시"), "서울"), (("경기", "경기도"), "경기"),
    (("인천", "인천광역시"), "인천"), (("강원", "강원도", "강원특별자치도"), "강원"),
    (("대전", "대전광역시"), "대전"), (("세종", "세종특별자치시"), "세종"),
    (("충북", "충청북도"), "충북"), (("충남", "충청남도"), "충남"),
    (("대구", "대구광역시"), "대구"), (("경북", "경상북도"), "경북"),
    (("부산", "부산광역시"), "부산"), (("울산", "울산광역시"), "울산"),
    (("경남", "경상남도"), "경남"),
    (("광주", "광주광역시", "전남", "전라남도", "전남광주통합특별시", "광주·전남"), "광주·전남"),
    (("전북", "전라북도", "전북특별자치도"), "전북"), (("제주", "제주특별자치도"), "제주"),
]:
    for k in keys:
        SIDO[k] = val

# 시설 접미어 — 이 단어까지가 시설명이다 (긴 것 우선 매치)
FACIL = re.compile(
    r"^(.*?(?:생활문화센터|문화예술회관|문화체육센터|문화커뮤니티센터|음악창작소|공연예술연습공간"
    r"|청소년수련관|청소년문화의집|문화의집|아트센터|아트홀|아트리움|문화센터|복지회관|주민센터"
    r"|커뮤니티센터|문화공간|연습공간|스튜디오|캠퍼스|창작소|활력소|플랫폼|복합문화공간|문화재단"
    r"|문화회관|수련관|회관|센터|마당|극장|도서관))\s*(.*)$")


def split_name(nm):
    """방 이름 → (시설, 방). 포털의 '방┃시설' 표기와 '시설 (방)'/'시설 방N' 모두 처리."""
    nm = nm.strip()
    if "┃" in nm or "|" in nm:
        room, _, fac = re.sub(r"\s*[┃|]\s*", "┃", nm).partition("┃")
        return (fac.strip() or nm), room.strip()
    m = re.match(r"^(.*?)\s*\(([^)]{2,25})\)$", nm)
    if m and FACIL.match(m.group(1)):
        return m.group(1).strip(), m.group(2).strip()
    m = FACIL.match(nm)
    if m and m.group(1) != nm:
        return m.group(1).strip(), m.group(2).strip(" -·")
    return nm, ""


def _norm(s):
    return re.sub(r"[\s()\[\]·┃|,-]", "", s or "")


def existing_names():
    have = set()
    for line in io.open(SEED, encoding="utf-8", newline=""):
        raw = line.rstrip("\r\n")
        if not raw or raw.lstrip().startswith("#") or raw.startswith("name,"):
            continue
        row = next(csv.reader([raw]), [])
        if row and row[0].strip():
            have.add(_norm(row[0]))
    try:
        t = io.open(os.path.join(BASE, "data", "practice-yeyak.js"), encoding="utf-8").read()
        for it in json.loads(t[t.find("{"):t.rfind(";")])["items"]:
            have.add(_norm(it["name"]))
    except Exception:
        pass
    return have


# 공유누리엔 시설뿐 아니라 물품·강좌도 있다 — '브로드밴드 혼 안테나'(전기/전자 장비)와
# '성인피아노A_봄학기'(문화강좌)가 키워드에 걸려 들어왔다(2026-08-02). 자원분류(cls)
# 화이트리스트로 **공간만** 남긴다. 이름의 강좌 패턴도 이중으로 거른다.
CLS_OK = {"공방·공작실·공연연습실", "일반강의실", "다목적실", "주민편의시설 등",
          "기타연습창작공간", "기타"}
LECTURE = re.compile(r"학기|사회교육|\d\s*기\]|제\d+기|교실$|클래스|아카데미|과정[\])]?$")


def main():
    sw = json.load(open(SWEEP, encoding="utf-8"))
    have = existing_names()
    facs = OrderedDict()
    for v in sw["items"].values():
        if (v.get("cls") or "") not in CLS_OK or LECTURE.search(v["name"]):
            continue
        fac, room = split_name(v["name"])
        sido = SIDO.get(v.get("sido") or "", "기타")
        # 같은 시설명이 다른 도시에 있을 수 있다 — 주소 앞 두 토큰으로 구분
        key = (_norm(fac), " ".join((v.get("addr") or "").split()[:2]))
        f = facs.setdefault(key, {"name": fac, "region": sido,
                                  "addr": v.get("addr") or "", "rooms": []})
        f["rooms"].append({"name": room or "연습실", "free": bool(v.get("free")),
                           "bookTo": v.get("bookTo") or ""})

    items, skipped = [], 0
    for f in facs.values():
        if _norm(f["name"]) in have or any(
                _norm(f["name"])[:8] in h or h[:8] in _norm(f["name"]) for h in have if len(h) >= 6):
            skipped += 1
            continue
        rooms = f["rooms"]
        n_free = sum(1 for r in rooms if r["free"])
        price = "무료" if n_free == len(rooms) else ("일부 무료" if n_free else None)
        items.append({
            "name": f["name"], "category": "public", "region": f["region"],
            "addr": f["addr"],
            "price": price, "free": n_free == len(rooms),
            "spaces": f"연습실 {len(rooms)}실" if len(rooms) > 1 else (rooms[0]["name"] if rooms[0]["name"] != "연습실" else ""),
            "booking_url": rooms[0]["bookTo"],
            "rooms": rooms if len(rooms) > 1 else None,
            "apply_method": "온라인 예약",
            "src": "공공개방자원(공유누리 경유)",
            "verified": sw.get("date"),
        })
    items.sort(key=lambda x: (x["region"], x["name"]))
    payload = {"fetched": sw.get("date"), "items": items}
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("window.ESHARE_ROOMS = ")
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write(";\n")
    from collections import Counter
    n_rooms = sum(len(f["rooms"]) for f in facs.values())
    print(f"방 {n_rooms}실 → 시설 {len(facs)}곳 (기존 겹침 {skipped} 제외) → 게시 {len(items)}곳")
    print("시도별:", Counter(i["region"] for i in items).most_common())
    print(f"저장: data/practice-eshare.js")
    return 0


if __name__ == "__main__":
    sys.exit(main())
