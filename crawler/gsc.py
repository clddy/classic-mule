# -*- coding: utf-8 -*-
# Search Console 수집기 — "구글에서 뭘 검색했을 때 우리가 뜨는가"를 data/search.json 에 쌓는다.
#
# GA4 와 보는 것이 다르다. GA4 는 **들어온 뒤**를 보고, 여기는 **들어오기 전**을 본다:
# 노출(검색결과에 뜬 횟수) · 클릭 · 순위. 검색어는 GA4 에 아예 없는 데이터라 이 경로뿐이다.
#
# ── 알아 둘 두 가지 ────────────────────────────────────────────────────────
# 1. **검색어 대부분은 익명화된다.** 구글은 소수만 검색한 질의를 개인 식별 우려로 숨긴다.
#    그래서 '검색어별 노출 합'은 언제나 '전체 노출'보다 훨씬 작다(2026-08 기준 164 중 9).
#    적게 나오는 게 고장이 아니라, 트래픽이 적을수록 더 많이 숨겨지는 것이다.
# 2. **데이터가 2~3일 늦고, 뒤늦게 정정된다.** traffic.py 처럼 '한 번 저장하면 불변'으로
#    다루면 안 된다 — 최근 구간은 매번 다시 당겨 덮어쓴다(LOOKBACK).
#
# 자격증명: crawler/.secrets/gcp-indexing.json (gindex.py 와 같은 서비스 계정).
#   · 그 계정이 Search Console 에 **소유자**로 등록돼 있어야 한다
#   · GCP 프로젝트에서 'Google Search Console API' 사용 설정 필요 (2026-08-19 켬)
#
#   python crawler/gsc.py            # 최근 30일 갱신
#   python crawler/gsc.py --days 90
import json
import os
import sys
from datetime import date, timedelta
from urllib.parse import quote

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = os.path.join(BASE, "crawler", ".secrets", "gcp-indexing.json")
OUT = os.path.join(BASE, "data", "search.json")
SITE = "https://podiumclassical.kr/"
API = "https://searchconsole.googleapis.com/webmasters/v3/sites/%s/searchAnalytics/query" % quote(SITE, safe="")

LOOKBACK = 30      # 이 구간은 매 실행 다시 당긴다 (구글이 뒤늦게 정정하므로)

# 노출·클릭이 0인 이유가 '순위가 낮아서'인지 '아예 색인이 안 돼서'인지는 이걸로만 갈린다.
#
# 하루 한도(2000건)는 넉넉하지만 **한 건에 7.5초**가 걸린다(2026-08-20 실측). 사이트맵이
# 34개인 지금도 4분이고, 공고 상세가 수백 개로 늘면 매일 크롤이 그만큼 지연된다.
# 그래서 전량이 아니라 **회전 표본**으로 본다: 주요 페이지는 매일, 공고 상세는 하루 N개씩
# 돌아가며. 지난 결과와 병합하므로 표는 늘 전체가 채워져 있고, 각 줄에 '언제 확인했는지'가 붙는다.
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
SITEMAP = os.path.join(BASE, "sitemap.xml")
DETAIL_PER_RUN = 8         # 회차당 볼 공고 상세 수 (주요 페이지는 언제나 전량)


def _session():
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    cred = service_account.Credentials.from_service_account_file(
        KEY, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return AuthorizedSession(cred)


def _query(s, start, end, dims, limit=1000):
    r = s.post(API, json={"startDate": start, "endDate": end, "dimensions": dims,
                          "rowLimit": limit, "type": "web"})
    if not r.ok:
        raise RuntimeError("%s %s" % (r.status_code, r.text[:300]))
    return r.json().get("rows") or []


def _pack(rows, ndims):
    """[keys..., 노출, 클릭, 순위] 형태로 눕힌다 (순위는 소수 한 자리)"""
    return [row["keys"][:ndims] + [row["impressions"], row["clicks"],
                                   round(row["position"], 1)] for row in rows]


def _sitemap_urls():
    """sitemap.xml 의 <loc> 전부. 사이트맵이 곧 '구글에 보이길 원하는 주소' 목록이다."""
    import re
    try:
        with open(SITEMAP, encoding="utf-8") as f:
            return re.findall(r"<loc>(.*?)</loc>", f.read())
    except FileNotFoundError:
        return []


def _pick(urls, prev):
    """이번 회차에 검사할 주소 — 주요 페이지 전부 + 공고 상세는 '가장 오래 안 본' 순 N개."""
    main = [u for u in urls if "/p/" not in u]
    detail = [u for u in urls if "/p/" in u]
    seen = {r[0]: (r[4] if len(r) > 4 else "") for r in prev}   # 주소 → 마지막 확인일
    detail.sort(key=lambda u: (seen.get(u, ""), u))             # 확인 안 한 것이 맨 앞
    return main + detail[:DETAIL_PER_RUN]


def inspect_all(s, urls, prev, today):
    """URL 별 색인 상태 → [주소, 판정, 상태문구, 마지막크롤, 확인일]. 지난 결과와 병합한다."""
    merged = {r[0]: list(r) for r in prev}
    for u in _pick(urls, prev):
        try:
            r = s.post(INSPECT, json={"inspectionUrl": u, "siteUrl": SITE}, timeout=30)
            if not r.ok:
                merged[u] = [u, "ERROR", "HTTP %s" % r.status_code, "", today]
                continue
            ix = (r.json().get("inspectionResult") or {}).get("indexStatusResult") or {}
            merged[u] = [u, ix.get("verdict") or "?", ix.get("coverageState") or "?",
                         (ix.get("lastCrawlTime") or "")[:10], today]
        except Exception as e:
            merged[u] = [u, "ERROR", type(e).__name__, "", today]
    # 사이트맵에서 빠진 주소(마감돼 사라진 공고)는 표에서도 지운다
    live = set(urls)
    return [v for k, v in merged.items() if k in live]


def main(argv):
    days = LOOKBACK
    if "--days" in argv:
        days = int(argv[argv.index("--days") + 1])
    if not os.path.exists(KEY):
        print("gsc: 자격증명 없음 (%s) — 스킵" % KEY)
        return 0
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    try:
        s = _session()
        doc = {
            "site": SITE, "from": start, "to": end,
            "updatedAt": date.today().isoformat(),
            # 검색어는 익명화가 심해 기간 합계로만 본다(하루씩 쪼개면 거의 다 사라진다)
            "queries": _pack(_query(s, start, end, ["query"]), 1),
            "queryPages": _pack(_query(s, start, end, ["query", "page"]), 2),
            "pages": _pack(_query(s, start, end, ["page"]), 1),
            "days": _pack(_query(s, start, end, ["date"]), 1),
            "devices": _pack(_query(s, start, end, ["device"]), 1),
        }
        # 색인 상태 — 노출 0이 '순위가 낮아서'인지 '색인 자체가 안 돼서'인지 가른다.
        # 지난 회차 결과를 물려받아 병합한다(표본 회전이라 매 회차 일부만 새로 본다).
        try:
            with open(OUT, encoding="utf-8") as f:
                prev = (json.load(f).get("index") or [])
        except (FileNotFoundError, json.JSONDecodeError):
            prev = []
        _urls = _sitemap_urls()
        # 사이트맵 전체 규모 — index 는 회전 표본이라 그 길이를 전체로 착각하면 안 된다
        doc["sitemapTotal"] = len(_urls)
        doc["index"] = inspect_all(s, _urls, prev, date.today().isoformat())
    except ImportError:
        print("gsc: google-auth 미설치 — pip install google-auth requests", file=sys.stderr)
        return 1
    except Exception as e:
        print("gsc: 수집 실패 %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1

    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    imp = sum(r[-3] for r in doc["days"])
    clk = sum(r[-2] for r in doc["days"])
    named = sum(r[-3] for r in doc["queries"])
    ix = doc.get("index") or []
    ok = sum(1 for r in ix if r[1] == "PASS")
    print("gsc: %s~%s 노출 %d 클릭 %d · 검색어 %d종(노출 %d, 나머지 %d는 구글이 익명화)"
          % (start, end, imp, clk, len(doc["queries"]), named, imp - named))
    if ix:
        today = date.today().isoformat()
        fresh = sum(1 for r in ix if len(r) > 4 and r[4] == today)
        print("gsc: 색인 %d/%d (이번 회차 %d개 확인, 나머지는 지난 결과 유지)"
              % (ok, len(ix), fresh))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
