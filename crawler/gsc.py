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
    print("gsc: %s~%s 노출 %d 클릭 %d · 검색어 %d종(노출 %d, 나머지 %d는 구글이 익명화)"
          % (start, end, imp, clk, len(doc["queries"]), named, imp - named))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
