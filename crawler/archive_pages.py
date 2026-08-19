# 마감된 공고의 정적 페이지 — 아카이브를 검색 착지면으로 (작업 D, 2026-08-20).
#
# 왜: official.json 은 '살아있는 공고' 스냅샷이라 마감되면 페이지가 사라진다. 그런데
# "○○중학교 음악 강사 채용"으로 검색해 들어오는 사람에게는 지난 공고도 정보다 —
# 그 기관이 어떤 조건으로 뽑았는지, 지금 진행 중인 공고는 없는지 알려줄 수 있다.
#
# 품질 게이트(중요): 알맹이 없는 페이지를 대량 생성하면 신규 도메인의 품질 신호가 상한다.
# 조립 설명(staticgen.build_description)이 빈약한 건은 **만들지 않는다** — 2026-08-20
# 실측에서 1,239건 중 611건이 빈약이었고 그중 571건이 cjob(짧은 교회 공고)이었다.
# 사용자 결정: "품질 낮은 것들은 빼고 진행" (2026-08-20).
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rawstore                                    # noqa: E402
import staticgen as SG                             # noqa: E402
from common import classify_insts, extract_fields, region_from  # noqa: E402
from slug import build as build_slug               # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_DESC = 25          # 이보다 짧은 설명이면 페이지를 만들지 않는다


def enrich(iid, v):
    """원문 보관층으로 필드를 보강한다 — archive.json 은 건드리지 않는다(읽기 전용).

    소급 수집(backfill_raw.py)으로 원문이 늦게 들어온 항목이 많아, 아카이브에 굳어 있는
    필드만 쓰면 그 원문이 통째로 낭비된다. 여기서 만들어 쓰고 버리는 파생값이다.
    """
    out = dict(v)
    t = rawstore.all_text(iid)
    if not t:
        return out
    f = extract_fields(t)
    for k, val in f.items():
        if not out.get(k) and isinstance(val, str):
            out[k] = val
    if not out.get("instDetails"):
        ins = classify_insts(v.get("title") or "")
        if ins:
            out["instDetails"] = [x for x in ins if isinstance(x, str)]
    if (out.get("region") or "기타") == "기타" and f.get("addr"):
        r = region_from(f["addr"])
        if r and r != "기타":
            out["region"] = r
    return out


def is_publishable(v):
    """설명이 알맹이를 갖췄는가 — 제목만 되풀이하거나 너무 짧으면 제외."""
    d = SG.build_description(v)
    t = (v.get("title") or "").strip()
    if len(d) < MIN_DESC:
        return False
    return not (t and d.startswith(t[:12]) and len(d) <= len(t) + 6)


def _banner(v, live_by_org, live_by_kind):
    """상단 마감 배너 + 유도 링크. 링크는 0건이면 아예 만들지 않는다."""
    dl = v.get("deadline")
    when = f" ({dl} 마감)" if dl and dl.count("-") == 2 else ""
    links = []
    org = v.get("org")
    if org and live_by_org.get(org):
        links.append('<a href="../jobs.html?org={}">이 기관의 진행 중인 공고 {}건</a>'
                     .format(SG.esc(org), live_by_org[org]))
    kind = v.get("kind")
    if kind and live_by_kind.get(kind):
        links.append('<a href="../jobs.html?kind={}">비슷한 공고 보기</a>'
                     .format(SG.esc(kind)))
    tail = (" · ".join(links)) if links else ""
    return ('<div style="background:#f3efe7;border:1px solid #ddd3c4;border-radius:8px;'
            'padding:12px 16px;margin:0 0 18px">'
            '<b>마감된 공고입니다{}</b>{}</div>'
            .format(SG.esc(when), (" · " + tail) if tail else ""))


def expected_files(base=BASE, live_ids=frozenset()):
    """이번 회차에 존재해야 할 아카이브 페이지 파일명 — staticgen 의 정리 로직이
    이것들을 지우지 않게 하려고 파일 생성 없이 이름만 계산한다."""
    with open(os.path.join(base, "data", "archive.json"), encoding="utf-8") as f:
        arc = json.load(f)["items"]
    out = set()
    for iid, v in arc.items():
        if iid in live_ids:
            continue
        v = enrich(iid, dict(v, id=iid))
        if not is_publishable(v):
            continue
        v["title"] = "[마감] " + (v.get("title") or "")
        out.add(build_slug(v) + ".html")
    return out


def generate(base=BASE, limit=None, verbose=True):
    with open(os.path.join(base, "data", "archive.json"), encoding="utf-8") as f:
        arc = json.load(f)["items"]
    with open(os.path.join(base, "data", "official.json"), encoding="utf-8") as f:
        live = json.load(f).get("items", [])
    live_ids = {j.get("id") for j in live}
    live_by_org, live_by_kind = {}, {}
    for j in live:
        if j.get("org"):
            live_by_org[j["org"]] = live_by_org.get(j["org"], 0) + 1
        if j.get("kind"):
            live_by_kind[j["kind"]] = live_by_kind.get(j["kind"], 0) + 1

    today = date.today()
    pdir = os.path.join(base, "p")
    os.makedirs(pdir, exist_ok=True)
    made = skipped = 0
    urls = []
    for iid, v in arc.items():
        if iid in live_ids:            # 아직 살아 있는 공고는 staticgen 이 만든다
            continue
        v = enrich(iid, dict(v, id=iid))
        if not is_publishable(v):
            skipped += 1
            continue
        v["title"] = "[마감] " + (v.get("title") or "")
        sl = build_slug(v)
        html = SG._detail_page(v, today)
        # 마감 배너를 본문 맨 위에 끼운다 (레이아웃은 그대로 — 배너 한 줄만 추가)
        anchor = '<main class="container"'
        i = html.find(anchor)
        j_ = html.find('>', i) + 1 if i >= 0 else -1
        if j_ > 0:
            html = html[:j_] + _banner(v, live_by_org, live_by_kind) + html[j_:]
        with open(os.path.join(pdir, sl + ".html"), "w", encoding="utf-8") as f:
            f.write(html)
        urls.append(f"{SG.SITE}/p/{sl}.html")
        made += 1
        if limit and made >= limit:
            break
    if verbose:
        print(f"[archive-pages] 생성 {made}건 · 품질 미달 제외 {skipped}건")
    return urls


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    generate(limit=a.limit)
