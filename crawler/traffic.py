# GA4 방문 데이터 수집기 — 어제치 이벤트·페이지뷰를 data/traffic.json 에 누적한다.
#
# 파이프라인의 위치: 사이트(js/analytics.js)가 GA4 로 쏜 이벤트를, 이 스크립트가 매일
# GA4 Data API 로 당겨와 로컬에 쌓는다. archive.json 과 같은 병합 원칙(덮어쓰기 없음) —
# 하루치가 한 번 저장되면 불변이다. 수요 지도가 나중에 이걸 job id 로 조인한다
# (p/<id>.html 경로가 곧 공고 id 라서 페이지뷰만으로도 공고별 열람 수가 나온다).
#
# ── 설정 (없으면 조용히 스킵 — run_daily 에 물려도 무해) ─────────────────────────
#  crawler/.env 에 두 줄:
#    GA4_PROPERTY_ID=123456789            ← GA4 관리 → 속성 설정 → 속성 ID (G- 아님!)
#    GOOGLE_APPLICATION_CREDENTIALS=C:\...\ga4-sa.json   ← 서비스 계정 키 파일 경로
#  준비 절차(1회):
#    1. analytics.google.com → 속성 만들기 → 데이터 스트림(웹, podiumclassical.kr)
#       → 측정 ID(G-…)를 js/analytics.js 의 PODIUM_GA_ID 에 기입
#    2. console.cloud.google.com → 프로젝트 → 'Google Analytics Data API' 사용 설정
#       → 서비스 계정 만들기 → JSON 키 다운로드
#    3. GA4 관리 → 속성 액세스 관리 → 서비스 계정 이메일을 '뷰어'로 추가
#    4. pip install google-analytics-data
#  ※ 이벤트 파라미터(job_id·tier 등)를 API 로 뽑으려면 GA4 관리 → 맞춤 정의에서
#    맞춤 측정기준으로 등록해야 한다. 등록 전엔 이벤트 이름·페이지 경로만 나온다 —
#    v1 은 그것만으로 충분하다(공고별 열람은 pagePath 로 잡힌다).
import json
import os
import sys
from datetime import date, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "traffic.json")
ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


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
    """GA4 Data API 에서 day(YYYY-MM-DD) 하루치를 당긴다 → {"events":{}, "pages":{}}"""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    prop = f"properties/{os.environ['GA4_PROPERTY_ID']}"
    client = BetaAnalyticsDataClient()

    def run(dims):
        req = RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date=day, end_date=day)],
            dimensions=[Dimension(name=d) for d in dims],
            metrics=[Metric(name="eventCount")],
            limit=5000,
        )
        return client.run_report(req)

    events = {}
    for row in run(["eventName"]).rows:
        events[row.dimension_values[0].value] = int(row.metric_values[0].value)
    pages = {}
    for row in run(["pagePath"]).rows:
        pages[row.dimension_values[0].value] = int(row.metric_values[0].value)
    return {"events": events, "pages": pages}


def main():
    _load_env()
    if not os.environ.get("GA4_PROPERTY_ID"):
        print("traffic: GA4_PROPERTY_ID 미설정 — 스킵 (crawler/traffic.py 머리말 참고)")
        return 0
    doc = _load()
    yday = (date.today() - timedelta(days=1)).isoformat()
    # 덮어쓰기 금지: 이미 저장된 날은 다시 당기지 않는다 (GA 무료 쿼터 절약 겸)
    if yday in doc["days"]:
        print(f"traffic: {yday} 이미 저장됨 — 스킵")
        return 0
    try:
        doc["days"][yday] = pull(yday)
    except ImportError:
        print("traffic: google-analytics-data 미설치 — pip install google-analytics-data", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"traffic: 수집 실패 {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    doc["updatedAt"] = date.today().isoformat()
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    ev = doc["days"][yday]["events"]
    print(f"traffic: {yday} 저장 — 이벤트 {sum(ev.values())}건 ({len(ev)}종), 페이지 {len(doc['days'][yday]['pages'])}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
