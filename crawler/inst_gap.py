# 악기 미상 큐 — 악기가 안 붙은 공고를 '왜 안 붙었나'로 갈라서 보여준다.
#
# 만든 이유(2026-08-02): 수요 지도에서 악기 미상이 68%로 나왔는데, 이걸 통째로
# '추출기가 못 잡았다'고 읽으면 엉뚱한 걸 고치게 된다. 실제로는 세 종류가 섞여 있다.
#   ① 애초에 악기가 없는 공고 (사무국 직원·평가위원·전시안내원) → 정상
#   ② 악기가 아니라 전공(subject) 축인 공고 (대학 비전임교원) → 다른 축
#   ③ 악기가 있어야 하는데 없는 공고 (시립교향악단 단원, 학교 오케스트라 강사) → 진짜 대상
# ③만 골라내야 보강 작업의 대상이 정해진다.
#
# 덤으로 ④ 범위 밖(무용·미술·행정)이 새어 들어온 것도 잡아준다 — 악기 문제가 아니라
# 음악인 필터 문제지만, 같은 큐에서 눈에 띄는 편이 낫다.
#
#   python crawler/inst_gap.py            # data/inst_gap.md 생성
#   python crawler/inst_gap.py --print
import json
import os
import re
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import classify_insts, _MUSIC_STRONG  # noqa: E402

ARC = os.path.join(BASE, "data", "archive.json")
OUT = os.path.join(BASE, "data", "inst_gap.md")

VAGUE = ("", "전체", "미상", None)
# ① 악기 개념이 없는 자리 — 이 공고에 악기가 없는 건 정상이다
NO_INST = re.compile(r"평가위원|심의위원|위원\s*공개?모집|용역|구입|물품|시설|청소|경비|주차"
                     r"|전시안내|하우스\s*매니저|사무|행정|경영|기획팀|홍보팀|회계|총무"
                     r"|인턴|기간제근로자|공무직|업무직|정규직\s*직원|본부장|관장|단장")
# ④ 포디엄 범위 밖 — README: 국악=풍류, 실용음악·무용 제외
OUT_OF_SCOPE = re.compile(r"무용|발레|한국무용|현대무용|미술관|전시장|조각|비엔날레|연극|극단"
                          r"|국악|사물놀이|판소리|가야금|해금|대금")


def bucket(it):
    t = (it.get("title") or "") + " " + (it.get("org") or "")
    kind = it.get("kind") or ""
    # '(음악, 연극영화, 종교)' 같은 혼합 표기는 음악 교원 채용이 포함된 공고라 수집이 맞다
    # (common.py _MUSIC_STRONG 주석과 같은 논리) — 범위밖으로 오판하지 않는다 (2026-08-02).
    if OUT_OF_SCOPE.search(t) and not _MUSIC_STRONG.search(it.get("title") or ""):
        return "범위밖"
    if kind in ("직원",) or NO_INST.search(t):
        return "악기무관"
    if kind == "교수":
        return "전공축"
    return "보강대상"


def main():
    items = list(json.load(open(ARC, encoding="utf-8"))["items"].values())
    miss = [i for i in items if (i.get("inst") in VAGUE)]
    buckets = {}
    for it in miss:
        buckets.setdefault(bucket(it), []).append(it)

    n, m = len(items), len(miss)
    L = ["# 악기 미상 큐", "",
         f"아카이브 {n}건 중 악기 미상 **{m}건**({m / n * 100:.0f}%). 아래처럼 갈린다.", "",
         "| 분류 | 건수 | 뜻 | 할 일 |", "|---|---:|---|---|"]
    meaning = {
        "보강대상": ("악기가 있어야 하는데 없음", "**추출기 보강 대상**"),
        "전공축": ("대학 교원 — inst 가 아니라 subject 축", "subject 추출 쪽"),
        "악기무관": ("사무·행정·위원 — 악기 개념 없음", "정상, 손대지 말 것"),
        "범위밖": ("무용·미술·국악 등 포디엄 범위 밖", "**음악인 필터 누수**"),
    }
    for k in ("보강대상", "전공축", "악기무관", "범위밖"):
        v = buckets.get(k, [])
        why, todo = meaning[k]
        L.append(f"| {k} | {len(v)} | {why} | {todo} |")

    # 제목만으로 지금 추출기를 다시 돌리면 몇 건이나 살아나는지 — 정규식 보강의 상한선
    tgt = buckets.get("보강대상", [])
    by_title = sum(1 for i in tgt if classify_insts(i.get("title") or "")[1])
    by_body = sum(1 for i in tgt
                  if not classify_insts(i.get("title") or "")[1]
                  and classify_insts(" ".join(str(i.get(f) or "") for f in
                                              ("bodyExcerpt", "qualification", "positions")))[1])
    L += ["", "## 재추출 가능성 (보강대상 %d건 기준)" % len(tgt), "",
          f"- 제목만으로 회복: **{by_title}건**", f"- 저장된 본문 발췌까지 보면 추가 회복: **{by_body}건**",
          f"- 둘 다로 안 되는 것: **{len(tgt) - by_title - by_body}건** — 정보가 첨부 공고문에만 있다는 뜻", "",
          "> 회복이 안 되는 몫이 크면 손댈 곳은 `classify_insts`(정규식)가 아니라",
          "> `attach.py`(첨부 HWP/XLSX의 모집 파트표 파싱)다. 정규식을 늘려도 안 올라간다.", ""]

    for k in ("보강대상", "범위밖", "전공축"):
        v = buckets.get(k, [])
        if not v:
            continue
        L += [f"## {k} — {len(v)}건", ""]
        if k == "보강대상":
            L += ["직종 분포: " + ", ".join(f"{a} {b}" for a, b in
                                        Counter(i.get("kind") or "미상" for i in v).most_common()), ""]
        for it in sorted(v, key=lambda x: (x.get("kind") or "", x.get("org") or ""))[:60]:
            L.append(f"- `{it.get('kind') or '?'}` {(it.get('title') or '')[:70]}  \n"
                     f"  <sub>{it.get('org')} · {it.get('source')} · {it.get('url') or '링크없음'}</sub>")
        if len(v) > 60:
            L.append(f"\n_…외 {len(v) - 60}건 (전량은 data/archive.json)_")
        L.append("")

    md = "\n".join(L)
    open(OUT, "w", encoding="utf-8").write(md)
    print(f"생성: data/inst_gap.md — 미상 {m}건 / 보강대상 {len(tgt)}건")
    for k in ("보강대상", "전공축", "악기무관", "범위밖"):
        print(f"  {k:6} {len(buckets.get(k, [])):4d}")
    if "--print" in sys.argv:
        print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
