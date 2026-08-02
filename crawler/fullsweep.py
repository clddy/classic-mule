# 전체 순회(fullsweep) — institutions.csv 실재 확정 명부를 전부 방문해 상태를 기록하는 서베이.
#
# 목적 (2026-08-02 사용자 지시): "604곳을 전부 한 바퀴 돌고, 기존 80개 소스 결과와 비교."
#  - 같은 스크립트를 GitHub Actions 와 로컬 양쪽에서 돌린다.
#    · Actions vs 로컬 차이 = 해외 IP 차단 지도 (국내 공공 사이트는 Actions 에 조용히 0건)
#    · 로컬 결과 vs official.json = 80개 소스 커버리지 검증 (직접 방문했으면 잡혔을 공고)
#  - 크롤(main.py)과 완전 분리 — official.json 에 아무것도 섞지 않는 관측 전용.
#
# 현실 제약: 명부 604곳 중 홈페이지 URL 이 있는 곳이 56곳뿐이다(게시판 URL 은 0).
# 그래서 이 스크립트는 "URL 이 채워질수록 대상이 늘어나는" 구조다 —
#  ① institutions.csv 의 홈페이지 → ② data/fullsweep/boards.json(발견된 게시판 캐시,
#  병합 저장·덮어쓰기 없음) → ③ 발굴 백로그(no_url)를 리포트로 남겨 URL 채우기 작업의 입력으로.
#
#   python crawler/fullsweep.py                  # 전체 (환경 자동 감지: GITHUB_ACTIONS)
#   python crawler/fullsweep.py --limit 10       # 앞 10곳만 (테스트)
#   python crawler/fullsweep.py --compare        # 로컬 vs Actions vs official.json 비교 출력
import argparse
import csv
import json
import os
import sys
import time
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests  # noqa: E402
from common import UA, relevant  # noqa: E402
from discovery import fetch, board_candidates, extract_items  # noqa: E402

CSV = os.path.join(BASE, "crawler", "institutions.csv")
DIR = os.path.join(BASE, "data", "fullsweep")
BOARDS = os.path.join(DIR, "boards.json")   # {기관명: {"board_url","label","foundAt"}} — 발견 캐시


def master_rows():
    out = []
    with open(CSV, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].lstrip().startswith("#") or row[0] == "기관명" or len(row) < 8:
                continue
            if row[7].strip() != "확정":
                continue
            home = row[4].split("(")[0].strip()
            board = row[5].strip()
            out.append({"name": row[0], "cat": row[1], "region": row[3],
                        "home": home if home.startswith("http") else "",
                        "board": board if board.startswith("http") else ""})
    return out


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path, doc):
    os.makedirs(DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _source_domains():
    """80개 소스가 이미 파서로 커버하는 도메인 — 서베이 결과에 표시해 비교를 명확히"""
    try:
        from sources import SOURCES
        return {s["domain"].removeprefix("www.") for s in SOURCES}
    except Exception:
        return set()


def survey(env, limit=None):
    from urllib.parse import urlparse
    rows = master_rows()
    boards = _load(BOARDS, {})
    src_doms = _source_domains()
    results, n_ok = [], 0
    todo = [r for r in rows if r["board"] or r["home"] or r["name"] in boards]
    skipped = len(rows) - len(todo)
    if limit:
        todo = todo[:limit]
    print(f"명부 {len(rows)}곳 — URL 보유 {len(todo)}곳 순회, URL 없음 {skipped}곳(발굴 백로그)")

    s = requests.Session()
    s.headers.update(UA)
    for i, r in enumerate(todo, 1):
        rec = {"name": r["name"], "cat": r["cat"], "region": r["region"]}
        dom = urlparse(r["board"] or r["home"] or "").netloc.removeprefix("www.")
        if dom and dom in src_doms:
            rec["inSources"] = True   # 80개 소스가 이미 전용 파서로 커버 — 서베이는 참고용
        cached = boards.get(r["name"]) or {}
        board_url = r["board"] or cached.get("board_url")
        try:
            # 게시판 URL이 없으면 홈에서 탐색 (discovery.board_candidates 재사용)
            if not board_url:
                html = fetch(s, r["home"])
                if len(html) < 3000:
                    html = fetch(s, r["home"], use_js=True)
                if len(html) < 3000:
                    rec["status"] = "home_unreachable"
                    results.append(rec)
                    print(f"  [{i}/{len(todo)}] ✘ {r['name']} 홈 접근 실패")
                    continue
                for _score, burl, label in board_candidates(html, r["home"]):
                    bhtml = fetch(s, burl)
                    items = extract_items(bhtml, burl) if bhtml else []
                    if items:
                        board_url = burl
                        boards[r["name"]] = {"board_url": burl, "label": label,
                                             "foundAt": date.today().isoformat()}
                        break
                    time.sleep(0.4)
                if not board_url:
                    rec["status"] = "no_board_found"
                    results.append(rec)
                    print(f"  [{i}/{len(todo)}] △ {r['name']} 게시판 못 찾음")
                    continue
            # 게시판 방문 → 모집성 게시글 추출
            bhtml = fetch(s, board_url)
            if not bhtml:
                bhtml = fetch(s, board_url, use_js=True)
            items = extract_items(bhtml, board_url) if bhtml else []
            music = [it for it in items if relevant(it["title"])]
            rec.update({"status": "ok" if bhtml else "board_unreachable",
                        "board_url": board_url, "rows": len(items), "music": len(music),
                        "sample": [it["title"][:60] for it in music[:5]] or
                                  [it["title"][:60] for it in items[:3]]})
            if bhtml:
                n_ok += 1
            mark = "✔" if bhtml else "✘"
            print(f"  [{i}/{len(todo)}] {mark} {r['name']} — 게시글 {len(items)}건 (음악성 {len(music)})")
        except Exception as e:
            rec["status"] = f"error:{type(e).__name__}"
            print(f"  [{i}/{len(todo)}] ✘ {r['name']} {type(e).__name__}")
        results.append(rec)
        time.sleep(0.5)   # 정중한 순회 — 남의 서버다

    doc = {"env": env, "date": date.today().isoformat(),
           "master": len(rows), "visited": len(todo), "no_url": skipped,
           "ok": n_ok, "results": results}
    _save(os.path.join(DIR, f"sweep-{env}.json"), doc)
    _save(BOARDS, boards)
    print(f"\n저장: data/fullsweep/sweep-{env}.json — 방문 {len(todo)} · 접근 성공 {n_ok} · "
          f"게시판 캐시 {len(boards)}곳")
    print(f"URL 발굴 백로그: {skipped}곳 (명부에 홈페이지 URL 없음 — 채우면 다음 순회에 자동 포함)")
    return 0


def compare():
    lo = _load(os.path.join(DIR, "sweep-local.json"), None)
    ac = _load(os.path.join(DIR, "sweep-actions.json"), None)
    if not lo or not ac:
        print("비교하려면 sweep-local.json 과 sweep-actions.json 둘 다 필요하다", file=sys.stderr)
        return 1
    by = lambda doc: {r["name"]: r for r in doc["results"]}
    L, A = by(lo), by(ac)
    print(f"로컬({lo['date']}) {lo['ok']}/{lo['visited']} · Actions({ac['date']}) {ac['ok']}/{ac['visited']}\n")
    print("== 로컬 OK인데 Actions 실패/0건 → 해외 IP 사각 후보 ==")
    for n, r in L.items():
        a = A.get(n)
        if r.get("status") == "ok" and r.get("rows", 0) > 0 and a and (
                a.get("status") != "ok" or a.get("rows", 0) == 0):
            print(f"  {n}: 로컬 {r.get('rows')}건 / Actions {a.get('status')} {a.get('rows', 0)}건")
    # 대조 상대는 official(살아있는 것만)이 아니라 archive(전량 누적)다 — official로 대조하면
    # '수집됐다가 마감돼 빠진' 공고가 전부 공백으로 오탐된다 (2026-08-02 첫 비교에서 4건 중
    # 3건이 이 오탐이었다: 안동 첼로 강사·순천 신입단원은 정상 수집분, 밀레니엄은 270일 컷오프).
    print("\n== 순회에서 음악성 게시글이 나왔는데 아카이브에 그 기관이 전무 → 커버리지 공백 후보 ==")
    arc = _load(os.path.join(BASE, "data", "archive.json"), {"items": {}})
    orgs = {v.get("org", "") for v in arc["items"].values()}
    for n, r in L.items():
        if r.get("music", 0) > 0 and not any(n[:4] in o for o in orgs):
            print(f"  {n} ({r.get('music')}건): {'; '.join(r.get('sample', [])[:2])}")
    print("\n※ 여기 남는 것도 '옛 공고'일 수 있다 — 게시일을 확인하고 소스를 붙일 것.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=None, help="local|actions (기본: 자동 감지)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--compare", action="store_true")
    a = ap.parse_args()
    if a.compare:
        sys.exit(compare())
    env = a.env or ("actions" if os.environ.get("GITHUB_ACTIONS") else "local")
    sys.exit(survey(env, a.limit))
