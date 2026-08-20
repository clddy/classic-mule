# -*- coding: utf-8 -*-
# GA4 방문 데이터 수집기 — 하루치를 통째로 data/traffic.json 에 누적한다.
#
# 파이프라인의 위치: 사이트(js/analytics.js)가 GA4 로 쏜 이벤트를, 이 스크립트가 매일
# GA4 Data API 로 당겨와 로컬에 쌓는다. archive.json 과 같은 병합 원칙 —
# **완성된 하루치는 다시 당기지 않는다**(GA4 는 48시간이면 확정되므로 재조회해도 같은 값이다).
# 화면은 local/analytics.html 이 이 파일 하나만 읽어 그린다.
#
# ── 무엇을 담는가 (v2, 2026-08-19) ─────────────────────────────────────────
# v1 은 eventName·pagePath 두 축만 담았다. 그것만으로는 "누가 왔는가"를 못 본다 —
# 실제로 2026-08 통계의 절반이 우리 헬스체크였는데 v1 형식으로는 분간이 불가능했다.
# 그래서 방문자 차원(도시·기기·유입경로·신규재방문)과 맞춤측정기준(공고·필터)을 같이 담는다.
#
#   totals   그날 전체 — 세션·사용자·신규·참여세션·참여초·PV
#   events   이벤트별 횟수             pages    페이지별 PV·참여초
#   sources  유입경로별                audience 도시x기기xOSx브라우저x신규재방문
#   hours    시각별 세션               jobs     공고 id 별 job_view (p/<id>.html 의 그 id)
#   filters  필터 직종·결과건수         jobmeta  본 공고의 직종·지역·이동처
#
# **봇을 이름으로 걸러내지 않는다** — 대신 engagedSessions(참여세션)를 같이 받는다.
# 헬스체크도 데이터센터 스캐너도 참여세션이 0이라, '참여세션' 하나로 자동으로 갈린다.
# 목록을 손으로 관리하는 방식은 새 봇이 올 때마다 조용히 뚫린다.
#
# ── 설정 (없으면 조용히 스킵 — run_daily 에 물려도 무해) ─────────────────────────
#  crawler/.env 에 두 줄:
#    GA4_PROPERTY_ID=123456789            ← GA4 관리 → 속성 설정 → 속성 ID (G- 아님!)
#    GOOGLE_APPLICATION_CREDENTIALS=...\ga4-sa.json   ← 서비스 계정 키 파일 경로
#  준비 절차(1회):
#    1. analytics.google.com → 속성 만들기 → 데이터 스트림(웹, podiumclassical.kr)
#       → 측정 ID(G-…)를 js/analytics.js 의 PODIUM_GA_ID 에 기입
#    2. console.cloud.google.com → 프로젝트 → 'Google Analytics Data API' 사용 설정
#       → 서비스 계정 만들기 → JSON 키 다운로드
#    3. GA4 관리 → 속성 액세스 관리 → 서비스 계정 이메일을 '뷰어'로 추가
#    4. pip install google-analytics-data
#  ※ 맞춤측정기준(job_id·f_bands…)은 crawler/ga4_dimensions.py 로 등록한다.
#    등록 이전 데이터에는 소급 적용되지 않아 그 기간은 (not set) 으로 남는다.
#
#   python crawler/traffic.py                     # 어제치 + 빠진 날 자동 백필
#   python crawler/traffic.py --from 2026-08-06   # 그날부터 다시 훑기
import json
import os
import sys
from datetime import date, datetime, timedelta

# 콘솔이 cp949 면 한글 로그의 em-dash 하나에 print 가 터진다. 그 예외가 아래 수집
# try/except 에 걸리면 **성공한 날이 실패로 집계된다**(2026-08-19 실제로 13일 전부
# '실패'로 찍혔는데 데이터는 멀쩡히 저장돼 있었다). 출력은 출력대로 안전하게 만든다.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "traffic.json")
ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# 측정 시작일 — 측정 ID 오타를 고쳐 실제로 데이터가 들어오기 시작한 날(2026-08-06).
# 이 앞은 아무리 당겨도 0이라 백필 대상이 아니다.
FIRST_DAY = "2026-08-06"

SCHEMA = 4          # 이 값이 오르면 옛 형식으로 저장된 날짜는 다시 당긴다


def _load_env():
    """crawler/.env 의 키=값을 os.environ 에 보충 (이미 있는 값은 존중)"""
    try:
        with open(ENV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


def _load():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"days": {}}


def pull(day):
    """GA4 Data API 에서 day(YYYY-MM-DD) 하루치를 통째로 당긴다."""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    prop = "properties/%s" % os.environ["GA4_PROPERTY_ID"]
    client = BetaAnalyticsDataClient()

    def run(dims, mets, limit=5000):
        req = RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date=day, end_date=day)],
            dimensions=[Dimension(name=d) for d in dims],
            metrics=[Metric(name=m) for m in mets],
            limit=limit,
        )
        r = client.run_report(req)
        return [([v.value for v in row.dimension_values],
                 [v.value for v in row.metric_values]) for row in r.rows]

    def counts(dim, metric="eventCount"):
        """단일 차원 → {값: 수}. 맞춤측정기준 미등록 기간은 (not set) 뿐이라 빈 dict 가 된다."""
        try:
            return {d[0]: int(m[0]) for d, m in run([dim], [metric])
                    if d[0] not in ("", "(not set)")}
        except Exception as e:
            print("  (%s 스킵: %s)" % (dim, type(e).__name__), file=sys.stderr)
            return {}

    def rows(dims, mets):
        try:
            return [d + [int(float(x)) for x in m] for d, m in run(dims, mets)]
        except Exception as e:
            print("  (%s 스킵: %s)" % ("/".join(dims) or "totals", type(e).__name__),
                  file=sys.stderr)
            return []

    # 세션 계열 지표 묶음 — 어느 차원으로 쪼개든 같은 다섯 개를 본다.
    S = ["sessions", "totalUsers", "engagedSessions", "userEngagementDuration", "screenPageViews"]
    rec = {"v": SCHEMA}

    keys = ["sessions", "users", "newUsers", "engaged", "engagementSec", "pv"]
    tot = rows([], ["sessions", "totalUsers", "newUsers", "engagedSessions",
                    "userEngagementDuration", "screenPageViews"])
    rec["totals"] = dict(zip(keys, tot[0][-6:])) if tot else dict.fromkeys(keys, 0)

    rec["events"] = counts("eventName")
    rec["pages"] = {d[0]: [int(m[0]), int(float(m[1]))]
                    for d, m in run(["pagePath"], ["screenPageViews", "userEngagementDuration"])}
    # 채널 그룹(자연검색/직접/추천/소셜)까지 같이 — source 문자열만으로는 분류가 애매하다
    rec["sources"] = rows(["sessionSource", "sessionMedium",
                           "sessionDefaultChannelGroup"], S)
    # 어느 페이지로 들어왔나 (출처별) — 검색 유입이 목록으로 오는지 상세로 오는지
    rec["landing"] = rows(["sessionSource", "landingPage"],
                          ["sessions", "engagedSessions", "screenPageViews"])
    # 실제 참조 URL — 'blog.naver.com' 이 아니라 '어느 글'인지가 여기 있다
    rec["referrers"] = rows(["pageReferrer"], ["sessions", "engagedSessions"])
    rec["audience"] = rows(["city", "deviceCategory", "operatingSystem", "browser",
                            "newVsReturning"], S)
    # [세션, 참여세션] — 참여 쪽만 보면 헬스체크·스캐너가 빠진 '사람의 시각'이 된다
    rec["hours"] = {d[0]: [int(m[0]), int(m[1])]
                    for d, m in run(["hour"], ["sessions", "engagedSessions"])}

    rec["jobs"] = counts("customEvent:job_id")
    rec["filters"] = {"bands": counts("customEvent:f_bands"),
                      "results": counts("customEvent:f_results"),
                      "insts": counts("customEvent:f_insts"),
                      "regions": counts("customEvent:f_regions")}
    # 축별 집계(filters)는 "무엇을 많이 걸렀나"까지만 답한다. "**무엇을 켰을 때** 결과가
    # 없었나"는 축을 쪼갠 순간 사라지는 정보라, 조합을 통째로 한 줄로 받아 둔다.
    rec["filterCombos"] = rows(["customEvent:f_bands", "customEvent:f_insts",
                                "customEvent:f_regions", "customEvent:f_toggles",
                                "customEvent:f_query", "customEvent:f_results"],
                               ["eventCount"])
    # 열린 공고의 '성격' — 무엇이 열렸나(제목)보다 어떤 종류가 열렸나가 수요 신호다
    rec["jobmeta"] = {"kind": counts("customEvent:job_kind"),
                      "tier": counts("customEvent:job_tier"),
                      "inst": counts("customEvent:job_inst"),
                      "dday": counts("customEvent:job_dday"),
                      "region": counts("customEvent:job_region"),
                      "cert": counts("customEvent:job_cert"),
                      "career": counts("customEvent:job_career"),
                      "dest": counts("customEvent:dest")}
    return rec


def _targets(doc, start):
    """당겨야 할 날짜들 — 아직 없거나 옛 형식(v<SCHEMA)인 날. 오늘은 제외(미완성이라)."""
    out, d = [], datetime.strptime(start, "%Y-%m-%d").date()
    end = date.today() - timedelta(days=1)
    while d <= end:
        k = d.isoformat()
        if doc["days"].get(k, {}).get("v", 0) < SCHEMA:
            out.append(k)
        d += timedelta(days=1)
    return out


def main(argv):
    _load_env()
    if not os.environ.get("GA4_PROPERTY_ID"):
        print("traffic: GA4_PROPERTY_ID 미설정 — 스킵 (crawler/traffic.py 머리말 참고)")
        return 0
    start = FIRST_DAY
    if "--from" in argv:
        start = argv[argv.index("--from") + 1]
    doc = _load()
    days = _targets(doc, start)
    if not days:
        print("traffic: 새로 당길 날 없음 (최신 %s)" % max(doc["days"], default="-"))
        return 0

    ok, fail = 0, 0
    for day in days:
        try:
            rec = pull(day)
        except ImportError:
            print("traffic: google-analytics-data 미설치 — pip install google-analytics-data",
                  file=sys.stderr)
            return 1
        except Exception as e:
            fail += 1
            print("traffic: %s 수집 실패 %s: %s" % (day, type(e).__name__, e), file=sys.stderr)
            continue
        # 저장·출력은 수집 밖에서 — 여기서 나는 예외를 '수집 실패'로 세지 않는다.
        doc["days"][day] = rec
        ok += 1
        t = rec["totals"]
        print("traffic: %s 세션 %s(참여 %s) 사용자 %s PV %s"
              % (day, t["sessions"], t["engaged"], t["users"], t["pv"]))

    if not ok:
        return 1
    doc["updatedAt"] = date.today().isoformat()
    doc["schema"] = SCHEMA
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print("traffic: %d일 저장%s" % (ok, (", %d일 실패" % fail) if fail else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
