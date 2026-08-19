# 수요 지도 — data/archive.json 을 읽어 "어느 악기·지역·직무에 반복 수요가 있는가"를 낸다.
#
# 쓰는 이유: 프로필 디렉토리를 나중에 열 때 어느 세그먼트부터 밀도를 만들지가 승부인데,
# 그걸 감으로 고르지 않으려고 만든다. 크롤이 이미 80개 기관을 매일 훑고 있으므로
# 이 데이터는 우리만 가진 것이다.
#
# 한계는 리포트 안에 같이 적는다 — 공고로 드러나는 건 '기관 수요'뿐이고,
# 개인(교수·단장·음악감독)이 지인에게 돌리는 수요는 여기 안 잡힌다.
#
#   python crawler/demand_map.py            # data/demand_map.md 생성
#   python crawler/demand_map.py --print     # 화면에도 출력
import csv
import json
import argparse
import os
import re
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from collections import Counter
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ARC = os.path.join(BASE, "data", "archive.json")
OUT = os.path.join(BASE, "data", "demand_map.md")
INST_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "institutions.csv")


def join_key(name):
    """조인용 정규화 — 괄호 주석·법인격·공백만 턴다.

    main.py._cov_core 를 쓰면 안 된다. 그건 말미 기관유형어(합창단·교향악단…)까지 떼서
    '국립합창단'과 '국립오페라단'을 똑같이 '국립'로 눕힌다 — haystack 부분일치 검사용이라
    그래도 되지만, 조인 키로 쓰면 604개 기관이 250개로 뭉개진다(2026-08-02에 밟음).
    """
    return re.sub(r"\([^)]*\)|재단법인|사단법인|\(재\)|\s+", "", name or "")


def master():
    """institutions.csv(실재 확정) → ({조인키: (기관명, 카테고리, 지역)}, {퍼지키: [조인키…]})"""
    from main import _cov_core
    exact, fuzzy = {}, {}
    with open(INST_CSV, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].lstrip().startswith("#") or row[0] == "기관명" or len(row) < 8:
                continue
            if row[7].strip() != "확정":
                continue
            k = join_key(row[0])
            if len(k) < 3:
                continue
            exact[k] = (row[0], row[1], row[3])
            c = _cov_core(row[0])
            if len(c) >= 3:
                fuzzy.setdefault(c, []).append(k)
    return exact, fuzzy


def match(org, exact, fuzzy):
    """정확일치 우선. 실패하면 퍼지 후보가 **딱 하나일 때만** 인정한다
    (여럿이면 '국립합창단이냐 국립오페라단이냐'를 알 수 없으므로 포기)."""
    from main import _cov_core
    k = join_key(org)
    if k in exact:
        return k
    cands = fuzzy.get(_cov_core(org or ""), [])
    return cands[0] if len(cands) == 1 else None


def load():
    with open(ARC, encoding="utf-8") as f:
        return list((json.load(f).get("items") or {}).values())


def dedupe(items):
    """url 이 같으면 같은 공고 — 원본 제목이 미세하게 바뀌면 id 가 갈리기 때문."""
    by, out = {}, []
    for it in items:
        u = it.get("url")
        if not u:
            out.append(it)
            continue
        old = by.get(u)
        if old is None:
            by[u] = it
        else:  # 더 이른 firstSeen 을 남기고 관측일수는 합산
            if (it.get("firstSeen") or "9") < (old.get("firstSeen") or "9"):
                old.update({k: v for k, v in it.items() if k not in ("days",)})
            old["days"] = max(old.get("days", 1), it.get("days", 1))
    return out + list(by.values())


# 아카이브에는 옛 태그 체계로 수집된 기록이 섞여 있다. 마감돼 사라진 공고는 다시 크롤되지
# 않으므로 영원히 옛 값으로 남는다 — 집계할 때 같은 세그먼트가 둘로 갈리지 않게 여기서 눕힌다.
# (화면 쪽 같은 처리: js/jobs.js 의 TIER_MIGRATE·REGION_MIGRATE. 옛 값은 더 늘지 않으므로
#  이 표는 한 번 고정되면 드리프트하지 않는다.)
TIER_MIGRATE = {
    "프로": "연주", "오브리": "연주", "전공·입시": "교육 — 입시·전공",
    "교육·취미": "교육 — 취미·입문", "대학·전공": "교육 — 대학",
    "예중·예고": "교육 — 입시·전공", "입문·취미": "교육 — 취미·입문",
}
# 2026-07-01 전남광주통합특별시 출범 — 통합 전 수집분 이관
REGION_MIGRATE = {"광주": "광주·전남", "전남": "광주·전남"}


def normalize(items):
    for it in items:
        t = it.get("tier")
        if t in TIER_MIGRATE:
            if t == "오브리":
                it["obri"] = True      # 오브리는 '연주'의 하위 필터로 승계
            it["tier"] = TIER_MIGRATE[t]
        r = it.get("region")
        if r in REGION_MIGRATE:
            it["region"] = REGION_MIGRATE[r]
    return items


def txt(v, default="미상"):
    """일부 소스는 inst/instDetails 를 리스트로 준다 — 집계 키로 쓰려면 문자열로 눕힌다."""
    if isinstance(v, (list, tuple)):
        v = " ".join(str(x) for x in v if x)
    return str(v).strip() if v not in (None, "", []) else default


def month(it):
    d = it.get("date") or it.get("firstSeen") or ""
    return d[:7] if len(d) >= 7 else "미상"


def lifespan(it):
    """게시 → 마감까지 며칠. 구직자가 반응할 수 있는 창의 크기."""
    a, b = it.get("date") or it.get("firstSeen"), it.get("deadline")
    if not a or not b:
        return None
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except ValueError:
        return None


def table(counter, total, head=None, limit=None):
    rows = counter.most_common(limit)
    w = max([len(str(k)) for k, _ in rows] + [len(head or "")]) if rows else 8
    out = [f"| {(head or '항목').ljust(w)} | 건수 | 비중 |", f"|{'-' * (w + 2)}|-----:|-----:|"]
    for k, n in rows:
        out.append(f"| {str(k).ljust(w)} | {n:4d} | {n / total * 100:4.1f}% |")
    return "\n".join(out)


def main():
    # 작업 G-1 — 소급수집(backfill)을 걷어낸 '유량' 기준으로도 볼 수 있어야 한다.
    # 아카이브 1,239건 중 712건이 8월 한 번의 소급수집이고 그중 692건이 cjob 하나라,
    # 섞어 보면 "포디엄은 교회 반주 사이트"라는 착시가 생긴다 (2026-08-19 규명).
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude-backfill", action="store_true",
                    help="소급수집분을 빼고 실제 유입(유량)만 집계")
    args, _ = ap.parse_known_args()
    if not os.path.exists(ARC):
        print("data/archive.json 이 없다 — crawler/backfill_archive.py 를 먼저 돌릴 것", file=sys.stderr)
        return 1
    items = normalize(dedupe(load()))
    n_all = len(items)
    if args.exclude_backfill:
        from flowstats import is_backfill
        items = [i for i in items if not is_backfill(i)]
    n = len(items)
    if not n:
        print("아카이브가 비어 있다", file=sys.stderr)
        return 1

    days = sorted(it.get("firstSeen") for it in items if it.get("firstSeen"))
    from flowstats import is_backfill
    n_bf = sum(1 for i in normalize(dedupe(load())) if is_backfill(i))
    scope = "유량(소급수집 제외)" if args.exclude_backfill else "전체(소급수집 포함)"
    L = [f"# 포디엄 수요 지도", "",
         f"생성 {date.today().isoformat()} · 집계 범위 **{scope}** · 공고 **{n}건**"
         + (f" (전체 {n_all}건 중 소급수집 {n_bf}건 제외)" if args.exclude_backfill
            else f" · 이 중 소급수집 {n_bf}건")
         + f" · 관측 {days[0]} ~ {days[-1]}", "",
         "> ⚠ 소급수집분은 과거 글을 한 번에 훑어 온 것이라 '지금 들어오는 수요'가 아니다.",
         "> 분포를 판단할 때는 `--exclude-backfill` 로 유량 기준을 함께 볼 것 —",
         "> 전체 기준으로는 cjob(교회 반주)이 58%지만 유량 기준으로는 1% 미만이다.", "",
         "> 공고에 드러나는 것은 **기관 수요**뿐이다. 개인(교수·단장·교회 음악감독)이 지인에게",
         "> 바로 돌리는 수요는 여기 잡히지 않는다 — 그쪽이 오히려 더 클 수 있다는 걸 전제로 읽을 것.", ""]

    # 1. 월별 유입 — 계절성. 채용은 학기·시즌을 탄다.
    L += ["## 1. 월별 신규 공고", "", table(Counter(month(i) for i in items), n, "월"), ""]

    # 2. 직무군 — 포디엄이 실제로 어떤 시장을 덮고 있는지
    n_obri = sum(1 for i in items if i.get("obri"))
    L += ["## 2. 직무군(tier)", "", table(Counter(txt(i.get("tier"), "미분류") for i in items), n, "직무군"), "",
          f"이 중 객원·대체(obri) 표시 **{n_obri}건**({n_obri / n * 100:.0f}%). "
          "공고로 나오는 객원 수요의 규모 — 지인 소개로 도는 몫은 여기 안 잡힌다.", "",
          "## 3. 직종(kind)", "", table(Counter(txt(i.get("kind")) for i in items), n, "직종"), ""]

    # 3. 악기 — 디렉토리 세그먼트를 고르는 축. 여기가 비면 축 자체가 안 선다.
    inst = Counter(txt(i.get("inst")) for i in items)
    vague = inst.get("전체", 0) + inst.get("미상", 0)
    L += ["## 4. 악기 분류(inst)", "", table(inst, n, "악기"), "",
          f"**데이터 품질 경고:** 악기가 특정되지 않은 공고가 {vague}건({vague / n * 100:.0f}%)이다. "
          "이 비율이 높으면 '악기별 수요'는 아직 신뢰할 수 없고, 추출기 보강이 선행돼야 한다.", ""]
    det = Counter(txt(i["instDetails"]) for i in items if i.get("instDetails"))
    if det:
        L += ["### 세부 악기 표기(instDetails, 채워진 것만)", "",
              table(det, sum(det.values()), "표기", limit=25), ""]

    # 4. 지역 — 밀도는 전국이 아니라 지역 단위로 생긴다
    L += ["## 5. 지역", "", table(Counter(txt(i.get("region")) for i in items), n, "지역"), ""]

    # 5. 교차 — 실제 세그먼트. "서울 × 연주" 같은 칸이 첫 타깃 후보다.
    cross = Counter((txt(i.get("region")), txt(i.get("tier"), "미분류")) for i in items)
    L += ["## 6. 세그먼트 (지역 × 직무군) 상위 20", "",
          "| 지역 | 직무군 | 건수 |", "|------|--------|-----:|"]
    for (r, t), c in cross.most_common(20):
        L.append(f"| {r} | {t} | {c} |")
    L += ["", "> 디렉토리를 열 때 프로필 밀도를 먼저 만들 칸이 여기 위쪽에 있다.",
          "> 단, 한 칸의 공고 건수가 두 자리는 돼야 '반복 수요'라고 부를 수 있다.", ""]

    # 6. 반복 게시 기관 — 미래 디렉토리의 '돌아다닐 사람' 후보 명부
    org = Counter(txt(i.get("org")) for i in items)
    repeat = Counter({k: v for k, v in org.items() if v >= 2})
    L += ["## 7. 반복 게시 기관 (2건 이상)", "",
          f"전체 {len(org)}개 기관 중 **{len(repeat)}개**가 두 번 이상 공고를 냈다.", "",
          table(repeat, n, "기관", limit=30) if repeat else "_아직 없음 — 관측 기간이 짧다._", "",
          "> 이 명단이 중요한 이유: 반복해서 사람을 구한다는 건 상시 수요가 있다는 뜻이고,",
          "> 나중에 프로필 디렉토리를 열었을 때 **먼저 알려야 할 수요측**이 바로 여기다.", ""]

    # 7. 공고 수명 — 구직자가 반응할 수 있는 창
    spans = sorted(x for x in (lifespan(i) for i in items) if x is not None and 0 <= x <= 365)
    if spans:
        mid = spans[len(spans) // 2]
        L += ["## 8. 공고 수명 (게시 → 마감)", "",
              f"측정 가능 {len(spans)}건 · 중앙값 **{mid}일** · 최단 {spans[0]}일 · 최장 {spans[-1]}일", "",
              f"> 중앙값이 {mid}일이면, 알림이 하루만 늦어도 지원 기회의 상당분이 날아간다.", ""]

    # 8. 소스 기여 — 어느 원천이 실제로 데이터를 만들고 있나
    L += ["## 9. 수집 원천별 기여", "", table(Counter(txt(i.get("source")) for i in items), n, "원천", limit=25), ""]

    # 9. 기관 명부 결합 — 아카이브(실제 게시)와 institutions.csv(실재 확정 명부)를 붙인다.
    #    프로필 디렉토리를 열 때 '먼저 알릴 수요측'이 여기서 나온다.
    try:
        mst, fuz = master()
    except Exception as e:
        mst = None
        L += [f"_기관 명부 결합 실패: {type(e).__name__}: {e}_", ""]
    if mst:
        hit = {}              # 조인키 → 게시 건수
        unknown = Counter()   # 명부에 없는 게시 기관
        for it in items:
            org = txt(it.get("org"), "")
            if not org:
                continue
            k = match(org, mst, fuz)
            if k:
                hit[k] = hit.get(k, 0) + 1
            else:
                unknown[org] += 1
        active = sorted(hit.items(), key=lambda kv: -kv[1])
        L += ["## 10. 기관 명부 결합 (institutions.csv 실재 확정본)", "",
              f"명부 **{len(mst)}개** 기관 중 관측 기간에 실제로 공고를 낸 곳 **{len(hit)}개** "
              f"({len(hit) / len(mst) * 100:.0f}%). 나머지는 이 26일간 조용했거나 파서가 못 잡은 것이다.", ""]

        # ① 상시 수요 기관 — 명부에 있고 2건 이상. 디렉토리를 열 때 1순위 통보 대상.
        L += ["### 상시 수요 기관 (명부 등재 + 2건 이상 게시)", "",
              "| 기관 | 카테고리 | 지역 | 건수 |", "|---|---|---|---:|"]
        n_std = 0
        for core, c in active:
            if c < 2:
                continue
            name, cat, region = mst[core]
            L.append(f"| {name} | {cat} | {region} | {c} |")
            n_std += 1
        L += ["", f"**{n_std}개.** 프로필 디렉토리를 열었을 때 가장 먼저 알려야 할 명단이 이것이다 — "
                  "반복해서 사람을 구한다는 건 상시 수요가 있다는 뜻이니까.", ""]

        # ② 명부에 없는데 공고를 낸 곳 → 명부 보강 후보 (집계 포털명은 원래 명부에 없다)
        if unknown:
            L += ["### 명부에 없는 게시 기관 (명부 보강 후보 상위 25)", "",
                  table(unknown, sum(unknown.values()), "기관", limit=25), "",
                  "> 집계 포털(아트인포·아트모아·hibrain)과 교회는 원래 명부 대상이 아니다. "
                  "그 밖의 이름이 보이면 institutions.csv 누락이다.", ""]

        # ③ 명부에 있는데 조용한 곳 — 수요가 없는 건지 파서가 못 잡는 건지 구분이 필요
        silent = [v for k, v in mst.items() if k not in hit]
        by_cat = Counter(c for _, c, _ in silent)
        L += ["### 관측 기간에 조용했던 명부 기관", "",
              f"{len(silent)}개. 카테고리별: " + ", ".join(f"{k} {v}" for k, v in by_cat.most_common()), "",
              "> 여기엔 '진짜 채용이 없었던 곳'과 '파서가 못 잡는 곳'이 섞여 있다. "
              "헬스체크 baseline과 달리 이건 **한 번도 안 잡힌** 기관이라 baseline이 안 서는 사각지대다.", ""]

    md = "\n".join(L)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"생성: data/demand_map.md ({n}건 기준)")
    if "--print" in sys.argv:
        print()
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
