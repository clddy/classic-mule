# 게시판 과거 글 소급 수집 — 수요 분석용 (사이트 게시와 무관)
#
# 왜: official.json은 '지금 지원 가능한 공고'만 담고, archive.json은 포디엄이 켜진 뒤
# 관측한 것만 쌓인다. "어느 악기가 언제 얼마나 뽑히는가" 같은 계절성은 과거 1~2년치가
# 있어야 보인다 — 그건 각 게시판의 뒤 페이지에 그대로 남아 있다 (2026-08-07 사용자 제안).
#
# 원칙:
#  · 수집물은 **archive.json에만** 넣는다. 사이트에는 지금 지원 가능한 것만 떠야 한다.
#  · 마감이 지난 글도 그대로 보존한다 — 그게 이 수집의 목적이다.
#  · 목록만 읽는다(제목·링크·게시일). 상세는 열지 않는다 — 과거 글 수백 건의 상세를
#    두드리면 상대 서버에 부담이고, 수요 분석엔 제목·시기·기관이면 충분하다.
#
# 사용: python crawler/backfill_past.py [--pages 20] [--source cjob]
import argparse
import datetime as dt
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs4 import BeautifulSoup

import archive
from common import new_session, get, make_item, relevant, musician_relevant, region_from, find_date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 페이지를 뒤로 넘길 수 있는 게시판만 등록한다. 파서가 목록 URL을 하드코딩하고 있어
# 기존 sources.py를 그대로 재사용할 수 없으므로, 여기서 '목록 URL + 링크 규칙'만 다시 적는다.
BOARDS = [
    {
        "id": "cjob",
        "name": "기독정보넷(교회 반주)",
        "url": "https://www.cjob.co.kr/offerIG?c_jikjong=2&page={p}&device=pc",
        "sel": 'a[href*="bo_table=offerIG"]',
        "source": "cjob.co.kr",
        "base": "https://www.cjob.co.kr/",
        "org_pat": r"([가-힣A-Za-z0-9]{2,15}(?:교회|성당|채플))",
        "org_fallback": "교회(기독정보넷)",
    },
]

# 등록하지 못한 게시판과 이유 (다시 시도할 때 같은 길을 헤매지 않도록):
#  · 아트인포(artinfokorea.com) — ?page=N 을 서버가 무시하고 늘 같은 10건을 준다.
#    1·2페이지 글 ID가 완전히 동일함을 확인(2026-08-07). 더보기를 JS로 붙이는 방식이라
#    소급 수집하려면 헤드리스 렌더가 필요하다.


def sweep_board(s, board, pages, sleep=1.2):
    """한 게시판의 1~pages 페이지를 훑어 아이템 목록을 반환."""
    items, seen_url = [], set()
    empty_streak = 0
    for p in range(1, pages + 1):
        try:
            r = get(s, board["url"].format(p=p))
            if r.status_code != 200:
                break
        except Exception as e:
            print(f"    page {p}: {type(e).__name__} — 중단")
            break
        soup = BeautifulSoup(r.text, "lxml")
        found = 0
        for a in soup.select(board["sel"]):
            href = a.get("href") or ""
            title = a.get_text(" ", strip=True)
            if len(title) < 8:
                continue
            url = href if href.startswith("http") else board["base"].rstrip("/") + "/" + href.lstrip("/")
            if url in seen_url:
                continue
            seen_url.add(url)
            # 음악인 공고만 — 여기서 거르지 않으면 아카이브가 잡음으로 부푼다
            if not relevant(title):
                continue
            m = re.search(board["org_pat"], title)
            org = m.group(1) if m else board["org_fallback"]
            it = make_item(org, region_from(title), board["source"], title, url,
                           date=find_date(a.parent.get_text(" ", strip=True) if a.parent else ""))
            if it.get("nonMusic") or not musician_relevant(it["title"], it.get("kind", ""), org):
                continue
            it["backfill"] = True          # 소급 수집분 표식 — 관측 시점이 아니라 게시 시점 기준
            items.append(it)
            found += 1
        print(f"    page {p:3d}: {found}건")
        empty_streak = empty_streak + 1 if found == 0 else 0
        if empty_streak >= 3:              # 연속 3페이지 빈손이면 끝에 닿은 것
            print("    (연속 3페이지 수확 없음 — 종료)")
            break
        time.sleep(sleep)                  # 상대 서버 예의
    return items


def _wrid(url):
    m = re.search(r"wr_id=(\d+)", url or "")
    return int(m.group(1)) if m else None


def fill_dates(s, step=10, sleep=1.0):
    """소급 수집분의 게시일을 채운다 — 표본 + 보간.

    cjob 목록에는 날짜 열이 아예 없다(교회명·제목·조회수뿐). 상세에는 '등록일'이
    로그인 게이트 뒤에서도 노출되지만, 712건을 전부 두드리는 건 이 스크립트의 원칙
    ('목록만 읽는다')에 어긋난다.

    대신 wr_id가 게시 순번이라는 점을 쓴다 — step건마다 하나씩만 실제로 열어 (wr_id, 등록일)
    앵커를 만들고, 사이는 선형 보간한다. 앵커가 양쪽에서 조여 주므로 월 단위 계절성을 보는
    데는 충분하고, 요청 수는 1/step로 줄어든다. 보간값은 dateApprox=True로 구분한다
    — 개별 공고의 정확한 날짜로 쓰면 안 된다 (2026-08-07).
    """
    arc = archive.load(BASE)
    rows = sorted(
        ((_wrid(v.get("url")), k, v) for k, v in arc.items()
         if v.get("backfill") and _wrid(v.get("url"))),
        key=lambda x: x[0],
    )
    if not rows:
        print("소급 수집분이 없다")
        return 0

    idx = list(range(0, len(rows), step))
    if idx[-1] != len(rows) - 1:
        idx.append(len(rows) - 1)     # 양 끝은 반드시 앵커로 — 바깥은 보간할 수 없다
    print(f"소급 {len(rows)}건 · 앵커 {len(idx)}건 조회")

    anchors = []
    for n, i in enumerate(idx, 1):
        wr, _, it = rows[i]
        try:
            r = get(s, it["url"])
            m = re.search(r"(?:등록일|작성일|게시일)\s*[:\s]*(20\d{2}[-.]\d{1,2}[-.]\d{1,2})",
                          BeautifulSoup(r.text, "lxml").get_text(" ", strip=True))
        except Exception as e:
            print(f"    wr_id={wr}: {type(e).__name__}")
            m = None
        if m:
            d = m.group(1).replace(".", "-")
            y, mo, dd = d.split("-")
            anchors.append((wr, f"{y}-{int(mo):02d}-{int(dd):02d}"))
        if n % 10 == 0:
            print(f"    {n}/{len(idx)}")
        time.sleep(sleep)

    anchors.sort()
    if len(anchors) < 2:
        print("앵커가 2개 미만 — 보간 불가")
        return 0
    print(f"  앵커 {len(anchors)}건: {anchors[0][1]} ~ {anchors[-1][1]}")

    def to_ord(ds):
        y, m, d = (int(x) for x in ds.split("-"))
        return dt.date(y, m, d).toordinal()

    filled = 0
    for wr, key, it in rows:
        if it.get("date") and not it.get("dateApprox"):
            continue
        lo = max((a for a in anchors if a[0] <= wr), default=None)
        hi = min((a for a in anchors if a[0] >= wr), default=None)
        if not lo or not hi:
            continue
        if lo[0] == hi[0]:
            o = to_ord(lo[1])
        else:                          # wr_id 순번 대비 선형 보간
            f = (wr - lo[0]) / (hi[0] - lo[0])
            o = round(to_ord(lo[1]) + f * (to_ord(hi[1]) - to_ord(lo[1])))
        it["date"] = dt.date.fromordinal(o).isoformat()
        it["dateApprox"] = True
        filled += 1

    archive.write(BASE, arc)
    print(f"게시일 채움: {filled}건 (보간값은 dateApprox 표시)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=20, help="게시판당 훑을 페이지 수")
    ap.add_argument("--source", help="특정 게시판만 (id)")
    ap.add_argument("--dry-run", action="store_true", help="아카이브에 쓰지 않고 집계만")
    ap.add_argument("--fill-dates", action="store_true",
                    help="수집 대신, 이미 쌓인 소급분의 게시일을 표본+보간으로 채운다")
    ap.add_argument("--step", type=int, default=10, help="--fill-dates 의 앵커 간격")
    args = ap.parse_args()

    s = new_session()
    if args.fill_dates:
        return fill_dates(s, step=args.step)
    total = []
    for b in BOARDS:
        if args.source and b["id"] != args.source:
            continue
        print(f"[{b['name']}] 최대 {args.pages}페이지")
        got = sweep_board(s, b, args.pages)
        print(f"  → {len(got)}건 수확")
        total.extend(got)

    print(f"\n합계 {len(total)}건")
    if args.dry_run:
        print("[dry-run] 아카이브 기록 생략")
        return 0
    n = archive.merge(BASE, total)
    print(f"아카이브 병합: 신규 {n}건 · 누적 {len(archive.load(BASE))}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
