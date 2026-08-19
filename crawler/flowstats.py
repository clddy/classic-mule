# 유량(flow) 기준 분포 — 소급수집(backfill)을 걷어낸 '실제 유입'만 본다.
#
# 왜 따로 두는가(2026-08-20): 아카이브 1,239건 중 712건이 8월 한 번의 소급수집이고
# 그중 692건이 cjob 하나다. 이걸 섞어 보면 "포디엄은 교회 반주 사이트"라는 착시가 생긴다.
# 실제로 7월(소급 전) cjob 비중은 6%였고, 8월 소급 제외 유량에서는 0.5%다.
# 슬러그 사전(작업 B)·수요 분석(작업 G-1)이 같은 판별을 쓰도록 함수를 한 곳에 둔다.
import json
import os
from collections import Counter
from datetime import date, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(BASE, "data", "archive.json")


def is_backfill(v):
    """이 기록이 소급수집분인가.

    ① backfill 플래그가 정직한 1차 근거다.
    ② 플래그가 없던 시절의 기록도 있어서, '처음 관측(firstSeen)이 게시일(date)보다
       한참 뒤'인 것을 2차로 본다 — 게시된 지 30일도 더 지나 처음 봤다면 그건
       그날 올라온 공고를 받은 게 아니라 과거 글을 훑어 온 것이다.
    """
    if v.get("backfill"):
        return True
    fs, d = v.get("firstSeen"), v.get("date")
    if not (fs and d):
        return False
    try:
        return (date.fromisoformat(fs[:10]) - date.fromisoformat(d[:10])).days > 30
    except ValueError:
        return False


def load(path=None):
    with open(path or ARCHIVE, encoding="utf-8") as f:
        return json.load(f)["items"]


def flow_items(items=None, days=90, today=None):
    """최근 N일 안에 '실제로 새로 들어온' 기록만."""
    items = items if items is not None else load()
    today = today or date.today()
    cut = (today - timedelta(days=days)).isoformat()
    out = []
    for iid, v in (items.items() if isinstance(items, dict) else ((x.get("id"), x) for x in items)):
        if is_backfill(v):
            continue
        if (v.get("firstSeen") or "9999")[:10] >= cut:
            out.append((iid, v))
    return out


def distribution(field, days=90, items=None):
    """유량 기준 값 빈도. field 가 리스트면 원소별로 센다(instDetails)."""
    c = Counter()
    for _, v in flow_items(items, days=days):
        val = v.get(field)
        if isinstance(val, list):
            c.update(x for x in val if x)
        elif val:
            c[val] += 1
    return c


def both_columns(field, days=90, items=None):
    """(유량, 전체) 두 열 — 착시 재발 방지용으로 항상 나란히 보여준다."""
    items = items if items is not None else load()
    total = Counter()
    for _, v in (items.items() if isinstance(items, dict) else ((x.get("id"), x) for x in items)):
        val = v.get(field)
        if isinstance(val, list):
            total.update(x for x in val if x)
        elif val:
            total[val] += 1
    return distribution(field, days=days, items=items), total


if __name__ == "__main__":
    items = load()
    n_bf = sum(1 for v in items.values() if is_backfill(v))
    fl = flow_items(items)
    print(f"아카이브 {len(items)}건 · 소급수집 {n_bf}건 · 최근 90일 유량 {len(fl)}건\n")
    for f in ("source", "tier", "kind", "instDetails", "region"):
        flow, total = both_columns(f)
        print(f"[{f}] 유량 / 전체")
        for k, n in flow.most_common(6):
            print(f"   {str(k)[:22]:24} {n:4} / {total[k]:4}")
        print()
