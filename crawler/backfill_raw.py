# 원문 보관층 소급 채우기 — 과거 수집분의 '본문'을 뒤늦게 받아온다.
#
# 왜 필요한가(2026-08-20): backfill_past.py 가 게시판 목록에서 제목·날짜만 긁어 아카이브를
# 채웠던 탓에, 소급 수집분 712건 중 691건은 raw 층에 원문이 아예 없다. 원문이 없으면
#  · 추출기를 고쳐도 소급 적용할 것이 없고 (3층 구조의 자기치유가 안 먹는다)
#  · 상세 페이지를 만들어도 알맹이가 없다 (작업 D 게이트가 여기서 막혔다)
# 게시판이 아직 살아 있는 동안 본문을 받아 두는 것이 데이터 자산으로도 남는다.
#
# 원칙
#  · raw 는 불변 누적 — 이미 있는 항목은 건드리지 않는다 (stash/flush 가 보장)
#  · archive.json 은 읽기 전용. 여기서 절대 쓰지 않는다
#  · 로그인 벽에 막힌 소스는 몇 건 시도해 보고 통째로 건너뛴다 (무의미한 요청 반복 방지)
#  · 회차당 상한을 둬 며칠에 걸쳐 수렴시킨다 — 남의 서버를 두들기지 않는다
#
#   python crawler/backfill_raw.py --limit 200          # 200건만
#   python crawler/backfill_raw.py --source cjob        # 특정 소스만
#   python crawler/backfill_raw.py --dry-run            # 대상만 세기
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as M          # noqa: E402  (get/new_session/body_text 재사용)
import rawstore           # noqa: E402
import attach                          # noqa: E402
from bs4 import BeautifulSoup          # noqa: E402
from common import body_text, tls_blocked, curl_get  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(BASE, "data", "archive.json")
STATE = os.path.join(BASE, "data", "backfill_raw_state.json")

# 본문 대신 로그인 안내만 돌려주는 페이지 — 받아 봐야 쓰레기다
_LOGIN_WALL = re.compile(r"로그인후에 이용|회원전용|로그인 후 이용|권한이 없|회원만 열람")
MIN_BODY = 300            # 이보다 짧으면 껍데기로 본다
MAX_ATTACH = 3            # 공고당 첨부 상한 — 알맹이는 보통 공고문 한 장이다
WALL_GIVEUP = 5           # 한 소스에서 연속 이만큼 벽에 막히면 그 소스는 포기


def _load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("done", [])      # 성공적으로 받은 id
    s.setdefault("dead", [])      # 죽었거나 벽에 막힌 id
    s.setdefault("skipSources", [])
    return s


def _save_state(s):
    s["done"], s["dead"] = sorted(set(s["done"])), sorted(set(s["dead"]))
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def targets(source=None):
    with open(ARCHIVE, encoding="utf-8") as f:
        arc = json.load(f)["items"]
    st = _load_state()
    seen = set(st["done"]) | set(st["dead"])
    out = []
    for iid, v in arc.items():
        if iid in seen or not v.get("url"):
            continue
        src = (v.get("source") or "")
        if src.split(".")[0] in st["skipSources"]:
            continue
        if source and source not in src:
            continue
        if rawstore.all_text(iid):        # 이미 원문이 있으면 대상 아님
            continue
        out.append((iid, v))
    return out, st


def run(limit=200, source=None, dry_run=False, verbose=True):
    todo, st = targets(source)
    if verbose:
        import collections
        c = collections.Counter((v.get("source") or "?").split(".")[0] for _, v in todo)
        print(f"[backfill-raw] 대상 {len(todo)}건 · 소스별 {dict(c.most_common(8))}")
    if dry_run or not todo:
        return 0
    s = M.new_session()
    got = wall = dead = 0
    wall_streak = {}
    batch = todo[:limit]
    # 하이브레인은 requests 쿠키로는 안 열린다 — 크롤러와 같은 Playwright 프로필 세션
    # (hibrain_auth.fetch_many)을 태워야 본문이 나온다 (2026-08-20 실측: 쿠키 이식 0/6).
    hb_html = {}
    hb = [(i, v) for i, v in batch if "hibrain" in (v.get("source") or "")]
    if hb:
        try:
            import hibrain_auth
            hb_html = hibrain_auth.fetch_many([v["url"] for _, v in hb]) or {}
            if verbose:
                print(f"  하이브레인 세션으로 {len(hb_html)}/{len(hb)}건 수신")
        except Exception as e:
            if verbose:
                print(f"  [warn] 하이브레인 세션 실패: {type(e).__name__}")
    for iid, v in batch:
        src = (v.get("source") or "?").split(".")[0]
        if src == "hibrain":
            html = hb_html.get(v["url"])
            t = body_text(html) if html else ""
            if not t or _LOGIN_WALL.search(t[:2000]) or len(t) < MIN_BODY:
                st["dead"].append(iid); wall += 1
                continue
            rawstore.stash(iid, "page", t, url=v["url"], title=v.get("title"))
            st["done"].append(iid); got += 1
            continue
        try:
            r = M.get(s, v["url"])
        except Exception:
            st["dead"].append(iid); dead += 1; continue
        if r.status_code != 200:
            st["dead"].append(iid); dead += 1; continue
        t = body_text(r.text)
        if _LOGIN_WALL.search(t[:2000]) or len(t) < MIN_BODY:
            st["dead"].append(iid); wall += 1
            wall_streak[src] = wall_streak.get(src, 0) + 1
            if wall_streak[src] >= WALL_GIVEUP and src not in st["skipSources"]:
                st["skipSources"].append(src)
                if verbose:
                    print(f"  [{src}] 연속 {WALL_GIVEUP}건 벽/빈본문 — 이 소스는 이후 건너뜀")
            continue
        wall_streak[src] = 0
        rawstore.stash(iid, "page", t, url=v["url"], title=v.get("title"))
        # 본문이 메뉴뿐이고 알맹이가 첨부 공고문에 있는 사이트가 많다 — 문화재단·교육청이
        # 대부분 그렇다. 본문만 받으면 발췌 생성률이 2% 였다 (2026-08-20 실측).
        try:
            for furl, fname in (M.find_attachments(BeautifulSoup(r.text, "lxml"), r.url) or [])[:MAX_ATTACH]:
                try:
                    fr = (curl_get(furl, referer=v["url"], timeout=40) if tls_blocked(furl)
                          else s.get(furl, timeout=40, verify=False, headers={"Referer": v["url"]}))
                    if fr.status_code == 200 and 1_000 < len(fr.content) < 20_000_000:
                        rawstore.stash(iid, "attach", attach.extract_any(fname or furl, fr.content),
                                       name=(fname or furl)[:60])
                except Exception:
                    continue
        except Exception:
            pass
        st["done"].append(iid); got += 1
        if got % 25 == 0:                 # 중간 저장 — 오래 도는 작업이라 끊겨도 이어간다
            rawstore.flush(); _save_state(st)
            if verbose:
                print(f"  … {got}건 저장")
    rawstore.flush()
    _save_state(st)
    if verbose:
        print(f"[backfill-raw] 본문 확보 {got}건 · 벽/빈본문 {wall}건 · 실패 {dead}건 "
              f"· 남은 대상 {max(0, len(todo) - limit)}건")
    return got


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--source", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sys.exit(0 if run(a.limit, a.source, a.dry_run) >= 0 else 1)
