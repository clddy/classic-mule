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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import UA  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OFFICIAL = DATA / "official.json"
HISTORY = DATA / "health_history.json"
LOG = DATA / "health.log"

KEEP_DAYS = 45      # 소스별 히스토리 보관 개수
MIN_SAMPLES = 5     # baseline을 신뢰하는 데 필요한 최소 '정상 관측' 수
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

            if len(raws) >= MIN_SAMPLES:
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


def check_freshness(rep, doc):
    """크롤 자체가 안 돌았는지. 이걸 안 보면 어제 파일을 읽고 '이상 없음'이라 답한다."""
    at = (doc.get("collectedAt") or "")[:10]
    if not at:
        rep.add("HIGH", "크롤", "official.json에 collectedAt이 없다")
        return
    gap = (date.today() - date.fromisoformat(at)).days
    if gap >= 2:
        rep.add("HIGH", "크롤", f"수집 기록이 {at} — {gap}일째 크롤이 안 돌았다")
    elif gap == 1:
        # 자정 직후 실행 등으로 하루 차이는 날 수 있다
        rep.add("MED", "크롤", f"수집 기록이 {at} (어제) — 오늘 크롤이 실패했는지 확인")


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
    nd = [i for i in items if not i.get("deadline")]
    if len(nd) / len(items) > 0.4:
        rep.add("MED", "필드",
                f"마감일 없는 공고 {len(nd)}/{len(items)}건 ({round(len(nd) / len(items) * 100)}%) — 마감 추출기 확인")


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


def check_links(rep, items, hist, today):
    """유저가 실제로 누를 링크(접수중)만 찔러본다. 404면 신뢰가 바로 깨진다.

    한 번의 네트워크 블립으로 알리지 않도록 2회 연속 404부터 보고한다.
    (실패를 캐시해서 재시도를 막지는 않는다 — 매 실행 전부 새로 확인)
    """
    t = date.fromisoformat(today)
    live = []
    for i in items:
        d = i.get("deadline")
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
    """HEAD → 막히면 GET. 상태코드만 돌려준다."""
    r = requests.head(url, headers=UA, timeout=15, allow_redirects=True)
    if r.status_code in (403, 405, 501):     # HEAD를 안 받는 서버 → GET으로 재확인
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
    sys.path.insert(0, r"C:\ohai\telegram-notify")
    try:
        from notify import send
        send(text)
        return True
    except Exception as e:
        print(f"[warn] 텔레그램 전송 실패: {e}", file=sys.stderr)
        return False


# ---------- 진입점 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", action="store_true", help="배포 사이트까지 점검 (playwright)")
    ap.add_argument("--dry-run", action="store_true", help="텔레그램·히스토리 쓰기 없이 출력만")
    ap.add_argument("--no-links", action="store_true", help="죽은 링크 확인 건너뛰기")
    args = ap.parse_args()

    if not OFFICIAL.exists():
        print("official.json이 없다 — 크롤을 먼저 돌릴 것", file=sys.stderr)
        return 2
    doc = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    items = doc.get("items", [])
    # collectedAt은 "2026-07-15 03:01" 형태 — 날짜만 쓴다
    today = (doc.get("collectedAt") or "")[:10] or date.today().isoformat()

    rep = Report()
    hist = load_history()

    # 1순위 — 파서
    check_freshness(rep, doc)
    check_sources(rep, doc, hist, today)
    check_total(rep, doc, hist, today)
    check_fields(rep, items)
    check_encoding(rep, items)
    # 2순위 — 데이터 품질
    check_dupes(rep, items)
    check_dates(rep, items, today)
    if not args.no_links:
        check_links(rep, items, hist, today)
    # 3·4순위 — 배포 사이트·제출 플로우
    if args.site:
        try:
            from health_site import check_site
            check_site(rep, doc)
        except Exception as e:
            rep.add("MED", "사이트", f"사이트 점검 자체가 실패: {type(e).__name__}: {e}")

    text = render(rep, today, args.site)
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
