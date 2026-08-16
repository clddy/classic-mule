# 공고 아카이브 — 마감돼 사라진 공고까지 누적 보관.
#
# official.json 은 '지금 살아있는 공고' 스냅샷이다. 마감·삭제된 공고는 다음 크롤에서
# 그냥 사라진다. 그런데 "어느 악기·지역·직무에 반복 수요가 있는가"(수요 지도)를 알려면
# 사라진 공고까지 포함한 전량이 필요하다 — 그래서 여기 따로 쌓는다.
#
# 원칙 두 가지:
#  ① 절대 덮어쓰지 않는다. 한 번 들어온 id 는 지워지지 않는다.
#     (CLAUDE.md 함정 — discovery.py·geocode_practice.py 가 통째로 덮어써 사고 냈던 것)
#  ② 분류 필드(kind/tier/inst…)는 최신값으로 갱신한다. 분류기가 좋아지면 과거 기록도
#     같이 좋아져야 한다. 대신 firstSeen 은 항상 '더 이른 쪽'을 남긴다.
import json
import os
from datetime import date

# 보관 필드.
# bodyExcerpt·qualification 을 넣는 이유(2026-08-02): 마감된 공고는 원문이 죽어 재크롤이
# 불가능하다. 추출기를 고쳤을 때 과거분에 재적용할 수 있는 유일한 원문 흔적이 이 발췌다.
# (길이는 200자 안팎이라 파일 비대화 걱정보다 재추출 가능성이 크다)
KEEP = (
    "id", "org", "region", "source", "channel", "layer",
    "title", "url", "officialUrl",
    "date", "deadline", "deadlineFrom",
    "kind", "tier", "inst", "instDetails", "subject",
    "ageGroup", "obri", "certReq", "degreeReq", "careerReq", "personnel",
    "bodyExcerpt", "qualification", "positions",
    # 공고문에서 뽑은 근무 조건 (common.extract_fields) — 마감돼 원문이 죽어도 남는다
    "pay", "workPeriod", "workHours", "duty", "ageLimit", "workPlace",
    "perfPeriod", "perfPlace", "perfSchedule", "teamComp", "dayOff", "hiringOrg", "contact", "email", "addr", "lat", "lng", "addrFrom", "orgAffil",
    # 게시판 뒤 페이지에서 소급 수집한 과거 글(backfill_past.py)임을 표시한다.
    # 관측 시점(firstSeen)이 실제 게시 시점과 무관하므로, 계절성·추이를 볼 때
    # 이 표식으로 갈라 봐야 한다 (2026-08-07).
    "backfill",
    # 위 date 가 실측이 아니라 wr_id 보간값임을 뜻한다(backfill_past.fill_dates).
    # 월 단위 추세용이지 개별 공고의 정확한 게시일이 아니다.
    "dateApprox",
)


def _path(base):
    return os.path.join(base, "data", "archive.json")


def load(base):
    try:
        with open(_path(base), encoding="utf-8") as f:
            doc = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return doc.get("items") or {}


def merge(base, items, seen_on=None, arc=None, save=True):
    """items(이번 크롤의 final)를 아카이브에 병합. 새로 들어온 건수를 돌려준다.

    seen_on: 관측일(YYYY-MM-DD). 과거 복원(backfill_archive.py)에서 커밋 날짜를 넣는다.
    arc:     이미 메모리에 든 아카이브. 여러 스냅샷을 연속 병합할 때 넘긴다
             (안 넘기면 매번 디스크에서 다시 읽어 앞선 병합이 날아간다).
    """
    seen_on = seen_on or date.today().isoformat()
    if arc is None:
        arc = load(base)
    added = 0
    for it in items:
        iid = it.get("id")
        if not iid:
            continue
        rec = arc.get(iid)
        new = {k: it.get(k) for k in KEEP if it.get(k) not in (None, "")}
        if rec is None:
            new["firstSeen"] = min(x for x in (it.get("firstSeen"), seen_on) if x)
            new["lastSeen"] = seen_on
            new["days"] = 1
            arc[iid] = new
            added += 1
            continue
        # 이미 있는 기록: 분류 필드는 최신값으로 갱신하되 관측 이력은 보존
        first = min(x for x in (rec.get("firstSeen"), it.get("firstSeen"), seen_on) if x)
        last = max(x for x in (rec.get("lastSeen"), seen_on) if x)
        days = rec.get("days", 1) + (1 if seen_on > (rec.get("lastSeen") or "") else 0)
        rec.update(new)
        rec["firstSeen"], rec["lastSeen"], rec["days"] = first, last, days
    if save:
        write(base, arc)
    return added


def write(base, arc):
    payload = {
        "updatedAt": date.today().isoformat(),
        "count": len(arc),
        "items": arc,
    }
    p = _path(base)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)   # 쓰다 죽어도 기존 아카이브가 반쪽으로 남지 않게
