# GA4 맞춤 측정기준 등록 — 이벤트 파라미터를 리포트에서 쪼개 볼 수 있게 만든다.
#
# 왜 필요한가(2026-08-06): GA4는 이벤트 파라미터를 **맞춤 측정기준으로 등록해야만**
# 리포트·Data API에서 조회할 수 있다. 등록 전엔 "job_view 37회"까지만 보이고
# "비올라 공고 12회"는 못 본다. 게다가 **등록 이전 데이터에는 소급 적용되지 않는다** —
# 늦게 등록할수록 그만큼의 기간이 통째로 분석 불가가 된다.
#
# 파라미터 이름은 세 곳이 일치해야 한다: js/jobs.js(jobParams·reportFilter) +
# practice.html(spaceParams·reportSpaceFilter) + crawler/staticgen.py(_detail_page).
# 여기 목록이 그 계약서다 — 한쪽만 바꾸면 그 값은 영원히 (not set)으로 남는다.
#
# 무료 GA4 한도: 이벤트 범위 맞춤 측정기준 50개.
#
#   python crawler/ga4_dimensions.py            # 현황만
#   python crawler/ga4_dimensions.py --apply     # 없는 것 등록
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from traffic import _load_env  # noqa: E402

# (파라미터명, 표시이름, 설명)
# ⚠ display_name 은 영숫자·밑줄·공백만 허용 — 하이픈·슬래시·중점을 넣으면 400 (2026-08-06)
DIMENSIONS = [
    # ── 공고 컨텍스트 (job_view / job_outbound / contact_click) ──
    ("job_id",      "공고 ID",        "공고 식별자 — archive.json과 조인해 공급·반응을 붙이는 열쇠"),
    ("job_tier",    "공고 직무군",     "연주 / 교육—대학 / 교육—입시·전공 / 교육—취미·입문"),
    ("job_kind",    "공고 직종",       "단원·객원·반주·솔리스트·강사·지휘·교수 등"),
    ("job_inst",    "공고 대표악기",   "공고의 첫 악기 — 악기별 관심도의 기본 축"),
    ("job_insts",   "공고 악기 전체",  "복수 악기 공고의 전체 목록(| 구분)"),
    ("job_region",  "공고 지역",       "17개 시도 — 지역 수요 밀도"),
    ("job_org",     "공고 기관",       "게시 기관명 — 어느 기관 공고가 읽히나"),
    ("job_source",  "공고 수집원천",   "어느 채널로 들어온 공고가 실제로 읽히나"),
    ("job_status",  "공고 상태",       "접수중·마감임박·기한 미정·마감"),
    ("job_dday",    "마감 임박도",     "D0-3/D4-7/D8-30/D30+/상시/미정 — 알림 발송 타이밍의 근거"),
    ("job_cert",    "교원자격증 요건", "자격 요건이 관심도를 깎는지(진입장벽 분석)"),
    ("job_career",  "경력 요건",       "경력 무관 공고가 더 읽히는지"),
    ("job_degree",  "학위 요건",       "학위 요건별 반응 차이"),
    ("job_age",     "지원자 연령대",   "성인 / 미성년(청소년 단원 모집)"),
    ("job_subject", "전공",            "대학 교원 초빙의 전공 — 악기와 다른 축"),
    ("job_obri",    "객원 여부",       "객원·대체 공고의 반응 — 신뢰 시장 수요의 유일한 관측창"),
    ("job_new",     "신규 공고 여부",  "NEW 배지가 클릭을 끌어올리는지"),
    ("dest",        "이동 대상",       "official(기관 원문)·url·mail·tel — 지원 경로 분포"),
    ("page_area",   "페이지 영역",     "list(목록) / detail(정적 상세) — 유입 지점 구분"),

    # ── 공고 필터 (filter_use / filter_empty) — 수요 신호 ──
    ("f_tiers",   "필터 직무군",   "사용자가 고른 직무군"),
    ("f_bands",   "필터 직종",     "사용자가 고른 직종"),
    ("f_insts",   "필터 악기",     "**찾는 악기** — 공급(크롤)과 대조할 수요의 핵심"),
    ("f_regions", "필터 지역",     "찾는 지역 — 지역 미스매치 발견"),
    ("f_status",  "필터 상태",     "접수중만 보는지 등"),
    ("f_query",   "검색어",        "필터로 표현 못 한 요구가 드러나는 자리"),
    ("f_sort",    "정렬 기준",     "마감순/최신순 — 무엇이 급한가"),
    ("f_toggles", "필터 토글",     "NEW·교회·무자격·경력무관 — 진입장벽 수요"),
    ("f_results", "결과 건수",     "0이면 filter_empty — 채워야 할 칸"),

    # ── 연습실 (space_view / space_filter / space_empty / practice_outbound) ──
    ("sp_name",     "시설명",        "어느 연습 공간이 열람되나"),
    ("sp_region",   "시설 지역",     "연습실 수요의 지역 분포"),
    ("sp_free",     "요금 구분",     "가격이 선택을 가르는지"),
    ("sp_rooms",    "방 개수",       "다실 시설이 더 선호되는지"),
    ("sp_cat",      "대여 방식",     "public(신청제·공공) / instant(외부 예약)"),
    ("sp_src",      "시설 출처",     "공유누리·yeyak·시드 중 어디서 온 데이터가 쓰이나"),
    ("sp_room",     "방 이름",       "시설 안에서 어느 방이 선택되나"),
    ("sp_dest",     "연습실 이동처", "apply/book/modal/room — 예약 동선"),
    ("sp_allow",    "필터 연주허용", "타악·금관 허용 수요 — 확인된 페인포인트"),
    ("sp_equip",    "필터 비치악기", "마림바·팀파니 등 '들고 못 다니는 악기' 수요"),
    ("sp_regions",  "필터 연습실지역", "찾는 지역"),
    ("sp_price",    "필터 가격",     "무료만 찾는 비율"),
    ("sp_results",  "연습실 결과수", "0이면 space_empty"),

    # ── 공통 ──
    ("label", "이벤트 라벨", "단순 라벨형 이벤트(텔레그램 배너 등)의 위치 정보"),
]


def main():
    apply = "--apply" in sys.argv
    _load_env()
    pid = os.environ.get("GA4_PROPERTY_ID")
    if not pid:
        print("GA4_PROPERTY_ID 미설정", file=sys.stderr)
        return 1
    # 클라이언트와 타입을 같은 모듈에서 가져와야 한다 — google.analytics.admin 은
    # v1alpha 로 해석되는데 타입만 v1beta 에서 가져오면 TypeError 가 난다 (2026-08-06).
    from google.analytics.admin_v1beta import AnalyticsAdminServiceClient, CustomDimension
    c = AnalyticsAdminServiceClient()
    prop = f"properties/{pid}"

    have = {}
    for d in c.list_custom_dimensions(parent=prop):
        have[d.parameter_name] = d.display_name
    todo = [d for d in DIMENSIONS if d[0] not in have]
    print(f"설계 {len(DIMENSIONS)}개 · 이미 등록 {len(have)}개 · 신규 {len(todo)}개")
    if len(have) + len(todo) > 50:
        print("⚠ 무료 한도(50) 초과 — 목록을 줄일 것", file=sys.stderr)
        return 1
    if not apply:
        for p, n, _ in todo:
            print(f"  + {n} ({p})")
        print("\n--apply 를 주면 등록한다")
        return 0

    ok, fail = 0, 0
    for param, name, desc in todo:
        try:
            c.create_custom_dimension(parent=prop, custom_dimension=CustomDimension(
                parameter_name=param, display_name=name, description=desc[:150],
                scope=CustomDimension.DimensionScope.EVENT))
            print(f"  ✔ {name} ({param})")
            ok += 1
        except Exception as e:
            print(f"  ✘ {name} ({param}) — {type(e).__name__}: {str(e)[:110]}")
            fail += 1
    print(f"\n등록 성공 {ok} · 실패 {fail} · 총 {len(have) + ok}개")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
