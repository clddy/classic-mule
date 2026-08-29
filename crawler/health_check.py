# 매일 크롤 직후 도는 헬스체크 — "파서가 조용히 망가진 것"을 잡는 게 목적.
#
# 이상 없으면 침묵한다. 이상이 있을 때만 텔레그램으로 요약을 보낸다.
# 모든 실행 기록은 data/health.log, 소스별 수집량 히스토리는 data/health_history.json.
#
# 핵심은 baseline 비교다: 평소 10건 나오던 기관이 오늘 0건이면 사이트 개편으로
# 파서가 깨진 것이지 공고가 없는 게 아니다. FAIL 없이 조용히 0건이 되는 게 제일 위험하다.
#
#   python crawler/health_check.py            # 데이터 점검만 (빠름, ~1분)
#   python crawler/health_check.py --site      # 배포 사이트 점검까지 (playwright, ~2분)
#   python crawler/health_check.py --dry-run   # 텔레그램 안 보내고 히스토리도 안 쓰기
import argparse
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

import requests

# 브리핑에 이모지(🔴🟡)가 들어가는데 cp949 콘솔에서 print 가 터진다. 그 print 가
# write_log·save_history·notify 보다 앞에 있어서, 터지면 기록도 알림도 통째로 날아간다 —
# traffic.py 가 13일치를 '수집 실패'로 찍었던 것과 같은 구조다 (2026-08-19).
# run_health.ps1 은 PYTHONIOENCODING 을 박아 두지만, 손으로 돌릴 땐 그 보호가 없다.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import UA  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OFFICIAL = DATA / "official.json"
HISTORY = DATA / "health_history.json"
LOG = DATA / "health.log"
# 크롤이 GitHub Actions로 옮겨간 뒤(2026-07-25) 진실의 원천은 배포된 데이터다 —
# 로컬 official.json은 git pull 전까지 낡은 채로 남는다.
LIVE_JSON = "https://podiumclassical.kr/data/official.json"

KEEP_DAYS = 45      # 소스별 히스토리 보관 개수
MIN_SAMPLES = 5     # baseline을 신뢰하는 데 필요한 최소 '정상 관측' 수
MIN_FILL_ROWS = 4   # 채움률 급락을 말하려면 이 정도 공고는 있어야 한다 (n=1 은 0/100%뿐)
STALE_DAYS = 60     # main.py가 이보다 오래된 마감 공고를 버린다 (main.py: stale)
SENTINEL = "2000-01-01"   # 마감/상시종료 표식 — 진짜 날짜가 아니다
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 사람이 손댈 필요가 있는 등급만 텔레그램을 울린다.
ALERT_SEVS = ("HIGH", "MED")


class Report:
    """발견 사항 모음. sev: HIGH(오늘 고칠 것) / MED(이번 주) / LOW(참고)."""

    def __init__(self):
        self.items = []

    def add(self, sev, area, msg):
        self.items.append({"sev": sev, "area": area, "msg": msg})

    def by_sev(self, *sevs):
        return [f for f in self.items if f["sev"] in sevs]

    @property
    def alerting(self):
        return self.by_sev(*ALERT_SEVS)


# ---------- 히스토리 (자동생성 파일 — 반드시 병합, 통째로 덮어쓰지 않는다) ----------

def load_history():
    if HISTORY.exists():
        try:
            h = json.loads(HISTORY.read_text(encoding="utf-8"))
            h.setdefault("sources", {})
            h.setdefault("deadLinks", {})
            return h
        except Exception as e:
            print(f"[warn] health_history.json 읽기 실패({e}) — 새로 시작", file=sys.stderr)
    return {"sources": {}, "deadLinks": {}}


def save_history(hist):
    HISTORY.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- 1순위: 파서 헬스체크 ----------

def classify_error(err):
    """소스 실패 사유 → (분류, 스스로 나을 수 있는가)."""
    e = (err or "").lower()
    if "403" in e or "forbidden" in e:
        return "403 차단", False
    if "404" in e or "not found" in e:
        return "404 — URL 변경", False
    if "410" in e or "gone" in e:
        return "410 — 페이지 삭제", False
    if "timeout" in e or "timed out" in e:
        return "타임아웃", True
    if "ssl" in e or "certificate" in e:
        return "SSL 오류", True
    if "connection" in e or "resolve" in e or "dns" in e:
        return "접속 불가", True
    if "500" in e or "502" in e or "503" in e:
        return "서버 오류(5xx)", True
    return "기타 오류", True


def check_sources(rep, doc, hist, today):
    """소스별 HTTP 상태 + 수집량 baseline 비교. 이 시스템의 핵심 기능."""
    srcs = doc.get("sources", [])
    H = hist["sources"]
    seen = set()

    for s in srcs:
        sid = s.get("id")
        if not sid:
            continue
        seen.add(sid)
        name = s.get("name", sid)
        h = H.setdefault(sid, {"name": name, "history": []})
        h["name"] = name

        # 같은 날 재실행하면 그날 기록은 갈아끼운다 (중복 관측이 median을 오염시킴)
        past = [e for e in h["history"] if e.get("date") != today]
        ok_past = [e for e in past if e.get("ok")]

        # 주기 외 승계(skipped)는 '관측'이 아니다 — 오늘 폴링하지 않고 이전 수집분을
        # 물려받은 것뿐이므로 baseline 비교도, 히스토리 적재도 하지 않는다.
        # (2026-07-21 사고: skipped 8곳의 raw=0을 실측으로 읽어 '파서 깨짐' HIGH 오탐 일제 발생.
        #  적재까지 해버리면 raw 0이 쌓여 median 자체가 오염된다.)
        if s.get("skipped"):
            h["history"] = past[-KEEP_DAYS:]
            continue

        if not s.get("ok"):
            # --- HTTP 상태 감시 ---
            kind, transient = classify_error(s.get("error"))
            streak = 1
            for e in reversed(past):
                if e.get("ok"):
                    break
                streak += 1
            detail = (s.get("error") or "")[:120]
            if not transient:
                # 403/404는 저절로 낫지 않는다 — 첫날부터 알린다
                rep.add("HIGH", "소스", f"{name}: {kind} — {detail}")
            elif streak >= 3:
                rep.add("HIGH", "소스", f"{name}: {kind} {streak}일 연속 — {detail}")
            elif streak >= 2:
                rep.add("MED", "소스", f"{name}: {kind} {streak}일 연속 — {detail}")
            else:
                # 하루짜리 타임아웃은 흔하다 — 로그에만 남기고 알리지 않는다
                rep.add("LOW", "소스", f"{name}: {kind} (1일차, 관찰 중)")
        else:
            # --- 수집량 baseline 비교 ---
            raw, kept = s.get("raw", 0), s.get("kept", 0)
            raws = [e.get("raw", 0) for e in ok_past][-KEEP_DAYS:]
            kepts = [e.get("kept", 0) for e in ok_past][-KEEP_DAYS:]

            # 목록이 스스로 건수를 밝히는 소스는 median 짐작이 필요 없다 — 사이트가 센 수와
            # 우리가 읽은 수를 바로 대조한다. 8월 하이브레인은 대학 공고 자체가 줄어 원본이
            # 12→6건이 됐는데, 45일 median 이 여름 이전 값을 붙들고 있어 '파서 -50%'가 매일
            # 떴다. 파서는 멀쩡했다(사이트 표기 5건 = 파싱 5건, 2026-08-20 실측).
            # baseline 은 '평소보다 적은가'를 짐작할 뿐이고, 이 대조는 '다 읽었는가'를 말한다.
            dec = s.get("declared")
            if dec is not None:
                if raw < dec:
                    rep.add("HIGH", "파서",
                            f"{name}: 목록 표기 {dec}건 중 {raw}건만 읽음 — 목록 파서 깨짐")
            elif len(raws) >= MIN_SAMPLES:
                mr = median(raws)
                if mr >= 3 and raw == 0:
                    rep.add("HIGH", "파서",
                            f"{name}: 원본 0건 (평소 {mr:g}건) — 목록 파서 깨짐 의심")
                elif mr >= 5 and raw <= mr * 0.5:
                    drop = round((1 - raw / mr) * 100)
                    rep.add("MED", "파서",
                            f"{name}: 원본 {raw}건, 평소 {mr:g}건 대비 -{drop}%")
                elif mr >= 3 and raw >= mr * 3:
                    rep.add("LOW", "파서",
                            f"{name}: 원본 {raw}건, 평소 {mr:g}건 대비 {raw / mr:.1f}배 급증")

            if len(kepts) >= MIN_SAMPLES:
                mk = median(kepts)
                # kept=0은 대부분 소스의 정상 상태다. 평소 꾸준히 걷히던 곳만 본다.
                if mk >= 3 and kept == 0 and raw > 0:
                    # '수집 0건'이 분류기 고장인지 만료 공고뿐인지는 짐작할 게 아니라
                    # 크롤이 세어 준 사유(drop)를 보면 된다 (2026-08-26). KBS·광주시립·
                    # 안동은 지난 채용 공고가 계속 걸려 있는 아카이브형 게시판인데,
                    # enrich 가 18일간 죽어 마감을 못 읽는 동안 '기한 미정'으로 남아 있었다.
                    # 마감을 다시 읽게 되자 전부 걷혔고, 그건 고장이 아니라 제 일을 한 것이다.
                    # baseline(평소 3~5건)은 그 18일 동안 쌓인 값이라 3주는 0을 따라가지 못한다.
                    d = s.get("drop") or {}
                    aged = d.get("만료", 0) + d.get("오래됨", 0) + d.get("지난해", 0)
                    if aged >= raw * 0.5:
                        rep.add("LOW", "분류기",
                                f"{name}: 원본 {raw}건이 전부 지난 공고 — 정상 (평소 {mk:g}건, 사유 {d})")
                    else:
                        rep.add("HIGH", "분류기",
                                f"{name}: 원본 {raw}건인데 수집 0건 (평소 {mk:g}건) — 분류·필터 깨짐 의심")

        h["history"] = (past + [{
            "date": today,
            "ok": bool(s.get("ok")),
            "raw": s.get("raw", 0),
            "kept": s.get("kept", 0),
        }])[-KEEP_DAYS:]

    # 히스토리엔 있는데 오늘 명단에서 빠진 소스 = sources.py에서 사라졌거나 이름이 바뀜
    for sid, h in H.items():
        if sid in seen or not h.get("history"):
            continue
        last = h["history"][-1]["date"]
        gap = (date.fromisoformat(today) - date.fromisoformat(last)).days
        if 1 <= gap <= 3:
            rep.add("MED", "소스", f"{h.get('name', sid)}: 이번 크롤 명단에서 빠짐 (마지막 {last})")


def load_doc():
    """점검 대상 데이터 — 배포본이 로컬보다 최신이면 배포본을 쓴다. (반환: doc, 출처)

    크롤이 GitHub Actions로 옮겨간 뒤로 로컬 official.json은 git pull을 해야만 갱신된다.
    로컬을 기준 삼으면 (1) 크롤이 멀쩡히 돌아도 '안 돌았다' 오탐이 매일 나고
    (2) 파서 baseline·필드 점검까지 낡은 데이터로 하게 된다 (2026-07-29 실제 발생:
    Actions는 07-28까지 정상인데 로컬이 07-27이라 '2일째 크롤 안 돎' 🔴 알림).
    사용자가 실제로 보는 것은 배포된 데이터이므로 그쪽을 점검한다.
    """
    local = json.loads(OFFICIAL.read_text(encoding="utf-8")) if OFFICIAL.exists() else {}
    try:
        r = requests.get(LIVE_JSON, timeout=25, headers=UA)
        live = r.json() if r.status_code == 200 else None
    except Exception:
        live = None
    if live and (live.get("collectedAt") or "") > (local.get("collectedAt") or ""):
        return live, "배포"
    return local, "로컬"


def check_freshness(rep, doc, src="로컬"):
    """크롤 자체가 안 돌았는지. 이걸 안 보면 어제 파일을 읽고 '이상 없음'이라 답한다."""
    at = (doc.get("collectedAt") or "")[:10]
    if not at:
        rep.add("HIGH", "크롤", "official.json에 collectedAt이 없다")
        return
    gap = (date.today() - date.fromisoformat(at)).days
    if gap >= 2:
        rep.add("HIGH", "크롤", f"{src} 수집 기록이 {at} — {gap}일째 크롤이 안 돌았다")
    elif gap == 1:
        # Actions 크론(18:00 KST)은 GitHub 부하에 따라 두세 시간씩 밀린다(07-28은 20:45 완료).
        # 헬스체크 시점에 당일 크롤이 아직 안 끝난 것은 정상이므로 로그만 남긴다 —
        # 진짜 실패라면 다음 날 gap>=2로 올라와 HIGH로 잡힌다.
        rep.add("LOW", "크롤", f"{src} 수집 기록이 {at} (어제) — 오늘 크롤이 아직 안 끝났거나 지연 중")


def check_total(rep, doc, hist, today):
    """전체 수집량 급감 — 개별 소스는 멀쩡한데 합계만 무너지는 경우를 잡는다."""
    total = len(doc.get("items", []))
    tot_hist = hist.setdefault("total", [])
    past = [e for e in tot_hist if e.get("date") != today]
    vals = [e["n"] for e in past][-KEEP_DAYS:]
    if len(vals) >= MIN_SAMPLES:
        m = median(vals)
        if m >= 10 and total <= m * 0.5:
            rep.add("HIGH", "전체", f"공고 총계 {total}건, 평소 {m:g}건 대비 -{round((1 - total / m) * 100)}%")
    hist["total"] = (past + [{"date": today, "n": total}])[-KEEP_DAYS:]


# ---------- 1순위: 필수 필드 · 깨진 텍스트 ----------

def check_fields(rep, items):
    if not items:
        rep.add("HIGH", "필드", "공고가 0건 — 크롤 결과가 비었다")
        return
    for f, label in [("title", "제목"), ("org", "기관명"), ("url", "원본링크")]:
        bad = [i for i in items if not i.get(f)]
        if bad:
            ex = bad[0].get("id", "?")
            rep.add("HIGH", "필드",
                    f"{label}({f}) 비어있는 공고 {len(bad)}/{len(items)}건 (예: {ex}) — 구조 변경 신호")
    # 상시 모집(교회 반주자 등)은 원래 마감일이 없는 공고다 — 분모에 넣으면 정상인 걸
    # 추출 실패로 센다. 2026-08-08 브리핑의 '45%'가 그랬다(25건 중 7건이 상시였다).
    # 실제로 손댈 것만 세도록 상시를 양쪽에서 뺀다.
    dated = [i for i in items if not i.get("obri") and i.get("deadlineNote") != "상시"]
    nd = [i for i in dated if not i.get("deadline")]
    if dated and len(nd) / len(dated) > 0.4:
        rep.add("MED", "필드",
                f"마감일 없는 공고 {len(nd)}/{len(dated)}건 ({round(len(nd) / len(dated) * 100)}%, 상시 제외) "
                "— 마감 추출기 확인")


_BROKEN_CHARS = "�□﻿"    # 대체문자 · 흰 사각형 · BOM


def broken_ratio(t):
    """인코딩 깨짐 문자 비율. hwp 파이프라인이 깨질 때 제일 먼저 여기서 티가 난다."""
    if not t:
        return 0.0
    n = sum(1 for c in t
            if c in _BROKEN_CHARS
            or "" <= c <= ""      # 사용자영역(한글 폰트 깨짐)
            or (unicodedata.category(c) == "Cc" and c not in "\n\t\r"))
    return n / len(t)


def check_encoding(rep, items):
    bad_title, bad_body = [], []
    for i in items:
        if broken_ratio(i.get("title")) > 0:
            bad_title.append(i)
        elif broken_ratio(i.get("bodyExcerpt")) > 0.02:
            bad_body.append(i)
    if bad_title:
        rep.add("HIGH", "인코딩",
                f"제목에 깨진 문자 {len(bad_title)}건 (예: {bad_title[0].get('org')} — {bad_title[0].get('title', '')[:40]})")
    if bad_body:
        rep.add("MED", "인코딩",
                f"본문 깨짐 의심 {len(bad_body)}건 (예: {bad_body[0].get('org')}) — hwp 추출 확인")


# ---------- 2순위: 데이터 품질 ----------

def _norm(s):
    return re.sub(r"[\s\W_]+", "", (s or "")).lower()


def check_dupes(rep, items):
    """같은 공고가 여러 소스로 들어와 중복 노출되는지. main.py의 dedup을 빠져나간 것들."""
    groups = {}
    for i in items:
        k = (_norm(i.get("title")), _norm(i.get("org")))
        if not k[0]:
            continue
        groups.setdefault(k, []).append(i)
    dupes = [v for v in groups.values() if len({x["id"] for x in v}) >= 2]
    if dupes:
        ex = dupes[0]
        srcs = "·".join(sorted({x.get("channel", "?") for x in ex}))
        rep.add("MED", "중복",
                f"중복 노출 {len(dupes)}건 (예: {ex[0].get('title', '')[:35]} — {srcs})")


def check_dates(rep, items, today):
    t = date.fromisoformat(today)
    bad_fmt, far, too_old = [], [], []
    for i in items:
        d = i.get("deadline")
        if not d:
            continue
        if not DATE_RE.match(d):
            bad_fmt.append(i)
            continue
        if d == SENTINEL:      # 마감/상시종료 표식 — 날짜로 검증하지 않는다
            continue
        try:
            dd = date.fromisoformat(d)
        except ValueError:
            bad_fmt.append(i)
            continue
        if dd > t + timedelta(days=365):
            far.append(i)
        elif dd < t - timedelta(days=STALE_DAYS):
            too_old.append(i)
    if bad_fmt:
        rep.add("HIGH", "날짜",
                f"마감일 형식 이상 {len(bad_fmt)}건 (예: {bad_fmt[0].get('deadline')!r} — {bad_fmt[0].get('org')})")
    if far:
        rep.add("MED", "날짜",
                f"마감일이 1년 이상 미래 {len(far)}건 (예: {far[0].get('deadline')} — {far[0].get('org')}) — 연도 파싱 오류 의심")
    if too_old:
        rep.add("MED", "날짜",
                f"마감 {STALE_DAYS}일 초과 경과분이 남아있음 {len(too_old)}건 — stale 컷오프 확인")

    # 마감 공고가 board를 채우고 있는지 (설계상 '마감' 배지로 남기지만, 너무 많으면 죽은 게시판)
    dated = [i for i in items if i.get("deadline") and i["deadline"] != SENTINEL and DATE_RE.match(i["deadline"])]
    closed = [i for i in dated if date.fromisoformat(i["deadline"]) < t]
    if dated and len(closed) / len(items) > 0.6:
        rep.add("LOW", "품질",
                f"마감 지난 공고가 {len(closed)}/{len(items)}건 ({round(len(closed) / len(items) * 100)}%) — 접수중 공고가 거의 없음")


def check_description(rep, items, hist):
    """상세 페이지 description 결함 — 약관 혼입·본문 공백·제목 중복 (작업 A-3, 판정만).

    description 을 필드 조립으로 바꿔 오염원은 구조적으로 없앴지만, 조립 재료인
    필드가 비면 문장이 앙상해진다. 무엇이 얼마나 비는지는 계속 봐야 한다.
    bodyExcerpt 는 화면에 안 쓰이지만 아카이브·분석에 남으므로 함께 센다.

    **공백률은 절대값이 아니라 baseline 으로 본다** (2026-08-22). 10% 넘으면 알리던
    규칙은 발췌기가 헐거웠고 소스 구성이 달랐을 때 정한 것이다. 지금 주력 소스인
    교육청 구인포털(work.sen·goe)은 상세 페이지에 산문 본문이 아예 없다 — 내용은
    납작한 표(이미 필드로 뽑힌다)와 첨부 hwp 에 있고, 첨부 폴백은 안내문이 딸려 와
    2026-08-21 에 일부러 철회했다. 그래서 공백 73%는 고장이 아니라 그 소스들의 정상
    상태이고, 그걸 매일 🟡 로 올리면 진짜 회귀가 묻힌다.
    이 시스템의 다른 점검과 같은 원리로 간다 — 수준이 아니라 '어제까지와 달라졌는가'.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from staticgen import build_description
    except Exception:
        return
    terms = re.compile(r"개인정보|동의를? ?거부|보유 ?및 ?이용 ?기간|필수 ?항목|구직활동 ?서비스"
                       r"|제공 ?목적|고유식별정보")
    clause, blank, dup, thin = 0, 0, 0, 0
    for j in items:
        ex = (j.get("bodyExcerpt") or "").strip()
        if ex and terms.search(ex):
            clause += 1
        elif not ex:
            blank += 1
        d = build_description(j)
        t = (j.get("title") or "").strip()
        if t and t[:12] and t[:12] in d and len(d) <= len(t) + 4:
            dup += 1                       # 제목만 되풀이 = 조립 재료가 없다는 뜻
        if len(d) < 30:
            thin += 1
    n = max(len(items), 1)
    if clause:
        rep.add("MED", "설명", f"약관 시그니처 검출 {clause}건 — 본문 발췌 추출 규칙 보강 필요")

    ratio = blank * 100 // n
    past = (hist.get("excerptBlank") or [])[-KEEP_DAYS:]
    if len(past) >= MIN_SAMPLES and ratio >= median(past) + 20:
        rep.add("MED", "설명",
                f"본문 발췌 공백 {blank}건 ({ratio}%) — 평소 {median(past):g}% 대비 급등")
    else:
        rep.add("LOW", "설명", f"본문 발췌 공백 {blank}건 ({ratio}%)")
    hist["excerptBlank"] = (past + [ratio])[-KEEP_DAYS:]

    if dup or thin:
        rep.add("LOW", "설명", f"설명 빈약: 제목 반복 {dup}건 · 30자 미만 {thin}건")


def check_apply_path(rep, items):
    """지원 경로가 아예 없는 카드 — 링크도 연락처도 없으면 방문자는 막다른 골목이다.

    화면 버튼 규칙(staticgen._apply)을 그대로 재사용한다 — 판정 규칙을 여기 복제하면
    화면과 표류한다. 송곡여고(나라일터)가 화면 PORTAL_RE 와 크롤러 목록의 어긋남으로
    버튼 없이 나갔고, 사용자가 발견했다 (2026-08-30) — 다음부터는 이 검사가 먼저 운다.
    """
    try:
        from staticgen import _apply
    except Exception:
        return
    dead = []
    for j in items:
        label, href = _apply(j)
        if not label or not href:
            dead.append(j.get("title", "")[:26])
    if dead:
        rep.add("MED", "지원경로",
                f"링크도 연락처도 없는 카드 {len(dead)}건 — 예: {'; '.join(dead[:3])}")


def check_sitemap(rep):
    """구글 서치콘솔에 사이트맵이 등록돼 있고 정상 처리되는가.

    사이트맵 제출은 한 번 하면 끝인 줄 알기 쉽지만, 조용히 깨지는 축에 속한다 —
    파일이 404가 되거나, 구글이 읽다 오류를 내거나, 속성에서 등록이 빠져도 아무 신호가 없다.
    색인이 안 되는 이유를 몇 주 뒤에야 알게 되는 게 제일 나쁘다 (2026-08-19 최초 제출).
    서비스 계정(인덱싱 API용)이 속성 소유자라 조회까지 자동으로 된다.
    """
    key = Path(__file__).resolve().parent / ".secrets" / "gcp-indexing.json"
    if not key.exists():
        return
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests as gt
        import urllib.parse
        cred = service_account.Credentials.from_service_account_file(
            str(key), scopes=["https://www.googleapis.com/auth/webmasters"])
        cred.refresh(gt.Request())
        site = urllib.parse.quote("https://podiumclassical.kr/", safe="")
        r = requests.get(f"https://www.googleapis.com/webmasters/v3/sites/{site}/sitemaps",
                         headers={"Authorization": f"Bearer {cred.token}"}, timeout=30)
        if r.status_code != 200:
            rep.add("MED", "사이트맵", f"서치콘솔 조회 실패 (HTTP {r.status_code})")
            return
        maps = r.json().get("sitemap", [])
        if not maps:
            rep.add("HIGH", "사이트맵", "서치콘솔에 등록된 사이트맵이 없다 — 재제출 필요")
            return
        for m in maps:
            errs, warns = int(m.get("errors", 0)), int(m.get("warnings", 0))
            submitted = sum(int(c.get("submitted", 0)) for c in m.get("contents", []))
            if errs:
                rep.add("HIGH", "사이트맵", f"구글이 사이트맵에서 오류 {errs}건 — {m.get('path')}")
            elif warns:
                rep.add("MED", "사이트맵", f"사이트맵 경고 {warns}건 — {m.get('path')}")
            else:
                rep.add("LOW", "사이트맵", f"정상 (URL {submitted}건, 마지막 처리 "
                                           f"{(m.get('lastDownloaded') or '?')[:10]})")
    except Exception as e:
        rep.add("LOW", "사이트맵", f"점검 건너뜀 — {type(e).__name__}")


def check_links(rep, items, hist, today):
    """유저가 실제로 누를 링크(접수중)만 찔러본다. 404면 신뢰가 바로 깨진다.

    한 번의 네트워크 블립으로 알리지 않도록 2회 연속 404부터 보고한다.
    (실패를 캐시해서 재시도를 막지는 않는다 — 매 실행 전부 새로 확인)
    """
    t = date.fromisoformat(today)
    live = []
    for i in items:
        d = i.get("deadline")
        # 사용자가 실제로 누르는 링크는 officialUrl(기관 원문)이 우선이다 — 한양대 겸임교수
        # 공고가 원문 소멸 후에도 노출됐다(워크오더 E16). 그쪽을 점검 대상으로 삼는다.
        if i.get("officialUrl"):
            i = dict(i, url=i["officialUrl"])
        if not i.get("url"):
            continue
        if d and d != SENTINEL and DATE_RE.match(d):
            try:
                if date.fromisoformat(d) < t:
                    continue     # 마감된 건 이미 '마감' 표시 — 링크 죽어도 급하지 않다
            except ValueError:
                pass
        live.append(i)

    def probe(it):
        url = it["url"]
        try:
            r = requests_head(url)
            return it, r
        except Exception:
            return it, None      # 네트워크 오류는 죽은 링크로 치지 않는다

    results = []
    if live:
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(probe, live))

    streaks = hist["deadLinks"]
    dead_now = []
    for it, code in results:
        url = it["url"]
        if code in (404, 410):
            streaks[url] = {"n": streaks.get(url, {}).get("n", 0) + 1, "last": today,
                            "org": it.get("org"), "title": (it.get("title") or "")[:60]}
            if streaks[url]["n"] >= 2:
                dead_now.append((it, code))
        elif code is not None:
            streaks.pop(url, None)   # 살아났으면 기록 삭제

    # 이제 official.json에 없는 URL의 streak은 정리 (히스토리 무한 증식 방지)
    cur = {i.get("url") for i in items}
    for url in [u for u in streaks if u not in cur]:
        streaks.pop(url)

    if dead_now:
        it, code = dead_now[0]
        rep.add("MED", "링크",
                f"죽은 원본링크 {len(dead_now)}건 (예: {code} — {it.get('org')} / {(it.get('title') or '')[:35]})")


def requests_head(url):
    """HEAD → 실패하면 GET으로 재확인. 상태코드만 돌려준다.

    **4xx는 전부 GET으로 다시 본다.** HEAD에만 404를 주는 서버가 실제로 있다 —
    기독정보넷(cjob)이 그렇다(HEAD 404 / GET 200). 404를 곧이곧대로 믿었더니 멀쩡한
    교회 공고 전부가 '죽은 링크'로 기록됐고, 크롤러가 그 기록을 보고 교회 카테고리를
    통째로 지웠다 (2026-08-08). 링크가 죽었다는 판정은 GET으로 확인된 것만 인정한다.
    """
    r = requests.head(url, headers=UA, timeout=15, allow_redirects=True)
    if r.status_code >= 400:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True, stream=True)
        r.close()
    return r.status_code


# ---------- 보고 ----------

SEV_MARK = {"HIGH": "🔴", "MED": "🟡", "LOW": "⚪"}


def render(rep, today, ran_site):
    lines = []
    for sev in ("HIGH", "MED", "LOW"):
        for f in rep.by_sev(sev):
            lines.append(f"{SEV_MARK[sev]} [{f['area']}] {f['msg']}")
    if not lines:
        lines.append("이상 없음")
    scope = "데이터+사이트" if ran_site else "데이터"
    head = f"포디엄 헬스체크 {today} ({scope})"
    return head + "\n" + "\n".join(lines)


def write_log(text):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n===== [{stamp}] =====\n{text}\n")


def notify(text):
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # 번들 crawler/notify.py
    try:
        from notify import send
        send(text)
        return True
    except Exception as e:
        print(f"[warn] 텔레그램 전송 실패: {e}", file=sys.stderr)
        return False


# ---------- 진입점 ----------

# ---------- 역방향 감사 + 소스별 채움률 (2026-08-15 워크오더 C7·C8) ----------
# 판정만 하고 수정하지 않는다 — 자동 수정은 오염을 만들 수 있어 사람 확인 큐로만 보낸다.
_SIG2FIELD = [
    (re.compile(r"접수\s*기간|원서\s*접수|접수\s*마감|제출\s*기한"), "deadline", "마감"),
    # 낱말만으로 찾으면 워크넷류 사이트 UI('육아휴직급여·최저임금위원회')가 걸려 숙지고처럼
    # 원문에 보수 표기가 없는 공고까지 [미추출]로 오탐한다 (2026-08-19) — 라벨 꼴만 인정
    (re.compile(r"(?:보수|급여|임금|사례비)\s*[:：/]|보수\s*금?액|시\s*급\s*[:：]?\s*[\d,]"),  "pay", "급여"),
    (re.compile(r"근무\s*기간|채용\s*기간|계약\s*기간"),             "workPeriod", "근무기간"),
    (re.compile(r"모집\s*분야|담당\s*업무"),                          "duty",     "분야"),
]
_FILL_FIELDS = ("deadline", "pay", "workPeriod", "workHours", "personnel", "contact", "email", "addr", "qualification")

# 라벨에 조사가 **바로 붙으면** 항목이 아니라 산문이다 —
# '경력증명서 상 근무기간과 담당업무가 명시된 경우'. '별'은 사이트 메뉴('담당업무별전화').
# 조사 뒤에 공백을 요구하는 것이 핵심이다. 안 그러면 '급여: 이백만원'의 '이'를 조사로 읽어
# 멀쩡한 값을 산문으로 몰아낸다.
_PROSE_TAIL = re.compile(r"^(?:(?:과|와|이|가|은|는|을|를|에|의|도|만)\s|별[가-힣])")
# 칸 이름만 적힌 자리 — 경남교육청은 접수기간이 비어 있어도 '접수기간 시작일 - 종료일'
# 처럼 칸 이름을 그대로 그린다 (2026-08-22). 칸 이름은 값이 아니다.
_PLACEHOLDER_VAL = re.compile(
    r"^(?:시작일?|종료일?|구분|비고|기간|일자|날짜|미정|활동영역|프로그램명|활동방법|영역|명칭|인원)"
    r"(?:\s*[-~/·]?\s*(?:시작일?|종료일?|구분|비고|기간|일자|날짜|미정|활동영역|프로그램명|활동방법|영역|명칭|인원))*$")
# 라벨이 겹쳐 적히는 자리 — '보수/임금', '과목 (담당업무)'. 겹친 라벨은 값이 아니다.
_LABEL_ECHO = re.compile(r"^(?:임금|보수|급여|담당\s*업무|모집\s*분야|과목)\s*[)）]?\s*")
# 보수 자리에 법령·조례 인용만 있으면 금액이 없는 것이다. QC 가 일부러 버리는 값이라
# (common._LAW_CITE) 감사가 '미추출'로 셀 이유가 없다.
# '보수 : 시간당 강사 수당 지급기준에 준한다'(망포중, 2026-08-22)처럼 다른 기준을
# 가리키기만 하는 것도 금액이 없는 것이다 — 원문에 없는 값을 매일 내놓으라고 조를 뿐이다.
_PAY_NO_AMOUNT = re.compile(r"보수\s*규정|보수규정|조례|시행\s*규칙|지침|호봉|산정"
                            r"|지급\s*기준|기준에\s*준|기준에\s*따|내부\s*규정")
_PAY_AMOUNT = re.compile(r"[\d,]{2,}\s*(?:만\s*)?원|시급|일당|월급|협의")
# 지원자가 채울 서식(응시원서·이력서·경력증명서)의 흔적. 앞은 서식 이름, 뒤는 hwp 표 머리로
# 글자마다 벌어진 칸 이름이다 — '자격증'처럼 붙여 쓴 낱말은 지원자격 산문에도 흔해서
# 붙은 꼴까지 받으면 멀쩡한 미추출(악기뱅크 담당업무)까지 덮는다 (2026-08-20).
_FORM_CTX = re.compile(r"응시\s?원서|이력서|경력\s?증명서|재직\s?증명서|자기\s?소개서|별지|서식"
                       r"|경\s력\s사\s항|자\s격\s증|근\s무\s기\s간|직\s장\s명|학\s력\s사\s항")


def _value_after(t, end):
    """라벨 뒤에 실제로 값이 오는가 — 다음 라벨 전까지의 알맹이. 없으면 ''.

    서울일자리포털은 값이 없는 칸에도 라벨을 찍는다('근무시간 보수/임금 접수방법').
    그런 자리를 [미추출]로 세면 원문에 없는 값을 매일 내놓으라고 조르는 셈이 된다
    (2026-08-20). 라벨은 라벨일 뿐이고, 감사가 찾는 것은 '값이 있는데 못 뽑은' 자리다.
    """
    import common
    win = re.sub(r"^[\s:：/·\-–]+", "", t[end:end + 140])
    for _ in range(3):
        w2 = _LABEL_ECHO.sub("", win)
        if w2 == win:
            break
        win = w2
    nxt = common._LABEL_WORDS.search(win)
    return (win[:nxt.start()] if nxt else win).strip(" :：/·-–()（）")


def _really_missing(t, pat, field):
    """이 원문에 '뽑을 수 있었는데 안 뽑힌 값'이 정말 있는가."""
    for m in pat.finditer(t):
        if _PROSE_TAIL.match(t[m.end():m.end() + 8]):
            continue                      # 산문·사이트 메뉴
        win = t[m.end():m.end() + 140]
        if field == "pay" and _PAY_NO_AMOUNT.search(win[:60]) and not _PAY_AMOUNT.search(win[:60]):
            continue                      # 법령 인용뿐 — 금액이 없다
        # 첨부에 딸려 온 응시원서·이력서 서식에도 '근무기간 / 담당업무' 칸이 있다.
        # 그건 지원자가 채울 빈 칸이지 이 공고의 값이 아니다 (2026-08-20 양주·양현고).
        # 마감·급여는 '응시원서 접수' 옆이 제자리라 이 규칙에서 뺀다.
        if field in ("duty", "workPeriod") and _FORM_CTX.search(t[max(0, m.start() - 140):m.end() + 140]):
            continue
        val = _value_after(t, m.end())
        if len(val) < 2 or _PLACEHOLDER_VAL.match(val):
            continue                      # 라벨만 있거나 칸 이름만 있는 자리
        return True
    return False


def check_unextracted(rep, items):
    """원문에 시그널 라벨이 있는데 대응 필드가 빈 공고 → [미추출] 보고 (수정 없음)."""
    import rawstore
    miss = []
    for i in items:
        t = re.sub(r"\s+", " ", rawstore.all_text(i.get("id")) or "")
        if len(t) < 200:
            continue
        for pat, field, label in _SIG2FIELD:
            if i.get(field) or i.get("deadlineNote") == "상시":
                continue
            if _really_missing(t, pat, field):
                miss.append((label, i.get("title", "")[:24]))
    if miss:
        import collections
        cnt = collections.Counter(l for l, _ in miss)
        ex = "; ".join(f"{l}:{t}" for l, t in miss[:4])
        rep.add("MED", "미추출",
                f"라벨은 있는데 필드가 빈 공고 {len(miss)}건 ({dict(cnt)}) — 예: {ex}")


def fill_rate_table(items, hist):
    """소스×필드 채움률 표 + 전일 대비 급락 검출. (표 텍스트, 급락 경고 목록) 반환."""
    import collections
    by = collections.defaultdict(list)
    for i in items:
        by[(i.get("source") or "?")[:18]].append(i)
    lines = ["소스별 채움률 (마감/급여/기간/연락처/이메일):"]
    warns = []
    today_rates = {}
    for src in sorted(by):
        rows = by[src]
        rates = {f: sum(1 for i in rows if i.get(f)) * 100 // len(rows)
                 for f in ("deadline", "pay", "workPeriod", "contact", "email")}
        rates["n"] = len(rows)
        today_rates[src] = rates
        lines.append(f"  {src:20s} {len(rows):2d}건  "
                     + " ".join(f"{rates[f]:3d}%" for f in ("deadline", "pay", "workPeriod", "contact", "email")))
        prev = (hist.get("fill_rates") or {}).get(src)
        # 공고가 몇 건 없는 소스는 한 건이 들고 나는 것만으로 채움률이 100%p 씩 튄다 —
        # 연세대 음대 게시판이 2건에서 1건(오디션 공고, 근무기간이 원래 없다)이 되자
        # 'workPeriod 50%→0%'가 떴다 (2026-08-22). 표에는 그대로 싣되 경고는 내지 않는다.
        # 옛 기록엔 n 이 없다 — 그 경우는 오늘 건수만 보고 판단한다.
        if prev and len(rows) >= MIN_FILL_ROWS and prev.get("n", MIN_FILL_ROWS) >= MIN_FILL_ROWS:
            for f in ("deadline", "workPeriod"):
                if prev.get(f, 0) >= 50 and rates[f] <= prev[f] - 40:
                    warns.append(f"{src} {f} {prev[f]}%→{rates[f]}%")
    hist["fill_rates"] = today_rates
    return chr(10).join(lines), warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", action="store_true", help="배포 사이트까지 점검 (playwright)")
    ap.add_argument("--dry-run", action="store_true", help="텔레그램·히스토리 쓰기 없이 출력만")
    ap.add_argument("--no-links", action="store_true", help="죽은 링크 확인 건너뛰기")
    ap.add_argument("--l4-dry", action="store_true", help="L4 상식 검증을 API 호출 없이 대상만 세기")
    ap.add_argument("--l4-force", action="append", default=[],
                    help="L4 대상에 이 공고 id를 강제 포함 (검증용)")
    args = ap.parse_args()

    if not OFFICIAL.exists():
        print("official.json이 없다 — 크롤을 먼저 돌릴 것", file=sys.stderr)
        return 2
    doc, doc_src = load_doc()   # 배포본이 더 최신이면 그걸 점검한다 (Actions 시대)
    items = doc.get("items", [])
    # collectedAt은 "2026-07-15 03:01" 형태 — 날짜만 쓴다
    today = (doc.get("collectedAt") or "")[:10] or date.today().isoformat()

    rep = Report()
    hist = load_history()

    # 1순위 — 파서
    check_freshness(rep, doc, doc_src)
    check_sitemap(rep)
    check_sources(rep, doc, hist, today)
    check_total(rep, doc, hist, today)
    check_fields(rep, items)
    check_encoding(rep, items)
    check_description(rep, items, hist)
    check_apply_path(rep, items)
    # 2순위 — 데이터 품질
    check_dupes(rep, items)
    check_dates(rep, items, today)
    # B5(워크오더): 마감이 게시일+60일을 넘으면 오추출 의심 — 자동 수정 없이 플래그만
    for i in items:
        # 상시모집은 기한이 사람 구해질 때까지다 — 게시일과 멀어도 오추출이 아니다
        # (남양교회·의왕소만교회가 매일 같은 알림을 냈다, 워크오더 08-17 §1)
        if i.get("deadlineNote") == "상시":
            continue
        d, g = i.get("deadline"), i.get("date")
        if d and g and DATE_RE.match(d) and DATE_RE.match(g):
            try:
                if (date.fromisoformat(d) - date.fromisoformat(g)).days > 60:
                    rep.add("MED", "의심",
                            f"마감({d})이 게시({g})+60일 초과 — {i.get('title','')[:26]}")
            except ValueError:
                pass
    # 원출처를 못 찾아 게시를 보류한 집계본 (워크오더 08-17 §6) — 역추적 규칙 보강 재료다.
    # 같은 건수가 매일 반복되면 새 정보가 아니다 — 건수가 변한 날만 알림(MED), 그대로면 로그만
    held = doc.get("heldNoOrigin") or 0
    if held:
        sev = "MED" if held != hist.get("heldNoOrigin") else "LOW"
        rep.add(sev, "보류", f"원출처 미확인 {held}건 — 아카이브만 남기고 게시 보류")
    hist["heldNoOrigin"] = held
    # C7(워크오더): 역방향 감사 — 라벨은 있는데 필드가 빈 공고 (판정만, 수정 없음)
    try:
        check_unextracted(rep, items)
    except Exception as e:
        rep.add("LOW", "미추출", f"역방향 감사 실패: {type(e).__name__}")
    if not args.no_links:
        check_links(rep, items, hist, today)
    # 3·4순위 — 배포 사이트·제출 플로우
    if args.site:
        try:
            from health_site import check_site
            check_site(rep, doc)
        except Exception as e:
            rep.add("MED", "사이트", f"사이트 점검 자체가 실패: {type(e).__name__}: {e}")

    # C8(워크오더): 소스×필드 채움률 표 + 전일 대비 급락 알림
    try:
        table, warns = fill_rate_table(items, hist)
        for w in warns:
            rep.add("MED", "채움률", f"채움률 급락: {w}")
    except Exception:
        table = ""

    # L4(워크오더 08-16 2차): 규칙이 못 잡는 '문맥상 말이 안 되는 값'을 LLM이 판정한다.
    # 판정만 하고 고치지 않으며, 여기서 무슨 일이 나도 나머지 헬스체크는 그대로 나간다.
    l4_appendix = ""
    try:
        import l4_check
        l4_state = l4_check.load_state()
        # --dry-run 은 기본적으로 API를 부르지 않는다. 상태를 저장하지 않으므로 돌릴 때마다
        # 전량이 다시 대상이 되어 토큰만 태우기 때문이다. 단 --l4-force 는 '이 건을 일부러
        # 검사하라'는 명시적 지시이므로 그때는 부른다 (검증용 경로).
        l4_dry = args.l4_dry or (args.dry_run and not args.l4_force)
        findings, l4_note = l4_check.run(items, l4_state,
                                         force_ids=tuple(args.l4_force or ()),
                                         dry_run=l4_dry)
        # 열린 판정 전부(도장 찍기 전까지)가 본문에 남는다 — format 은 state 기준 (워크오더 08-19)
        lines, l4_appendix = l4_check.format_findings(l4_state)
        for ln in lines:
            rep.add("MED", "L4", ln[5:] if ln.startswith("[L4] ") else ln)
        rep.add("LOW", "L4", l4_note)
        if not args.dry_run and not args.l4_dry:
            l4_check.save_state(l4_state)
    except Exception as e:
        rep.add("LOW", "L4", f"L4 스킵됨 — {type(e).__name__}: {str(e)[:80]}")

    text = render(rep, today, args.site)
    if table:
        text = text + chr(10)*2 + table
    if l4_appendix:
        text = text + chr(10)*2 + l4_appendix
    print(text)

    if args.dry_run:
        print("\n[dry-run] 텔레그램·히스토리 쓰기 생략")
        return 0

    write_log(text)
    save_history(hist)

    if rep.alerting:
        notify(text)
    return 1 if rep.by_sev("HIGH") else 0


if __name__ == "__main__":
    sys.exit(main())
