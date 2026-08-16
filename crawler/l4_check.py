# L4 상식 검증 — 규칙(1~5층)이 못 잡는 '문맥상 말이 안 되는 값'을 LLM으로 판정한다.
#
# 도입 계기(2026-08-16): 자유중 근무시간 '전일제 근무(1일 8시간)'. 값 자체는 모양이 멀쩡해
# 5층 검수를 통과했지만, 방과후 화·목 15:50~17:20 강사 공고와는 모순이다. 첨부 hwp에 딸려 온
# 기간제교원 공고 '양식 예시'에서 뽑힌 값이었다. 이런 건 정규식으로는 영원히 못 잡는다.
#
# 설계 원칙 세 가지 — 이걸 어기면 검증기가 오염원이 된다.
#  ① 판정만 한다. 값을 고치거나 숨기지 않는다. 사람이 읽는 브리핑으로만 나간다.
#  ② 게시 경로 밖에 있다. 크롤·배포는 이 모듈이 죽든 말든 그대로 돈다(헬스체크 안에서 실행).
#  ③ 신규·변경분만 본다. 전량 재검사는 비용만 쓰고 같은 답을 되풀이한다.
#
#   python crawler/l4_check.py --dry-run          # 대상만 세고 API 호출 안 함
#   python crawler/l4_check.py --force-id <id>    # 특정 공고를 대상에 강제 포함 (검증용)
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = DATA / "l4_state.json"
SECRETS = Path(__file__).resolve().parent / ".secrets"

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
# 판정 작업이라 최상위 모델이 필요하지 않다. 환경변수로 바꿀 수 있게 둔다.
DEFAULT_MODEL = os.environ.get("PODIUM_L4_MODEL", "claude-sonnet-5")
BATCH = 8            # 한 요청에 묶는 공고 수 — 호출 횟수를 줄이되 응답이 길어지지 않는 선
MAX_TOKENS = 4000    # 사고 블록이 출력 토큰을 함께 쓴다 — 좁게 잡으면 JSON 이 잘린다
TIMEOUT = 90

# 비용 추정용 단가(USD / 100만 토큰). 정확한 청구액이 아니라 '하루에 얼마 쓰나'를 보는 눈금이다.
PRICES = {
    "claude-opus":   (15.0, 75.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku":  (1.0, 5.0),
}

# 화면·브리핑에서 쓰는 한글 이름 ↔ 내부 필드 이름. LLM에는 한글로 보여 주고,
# 돌아온 판정은 내부 이름으로 되돌려 중복 보고 이력을 관리한다.
FIELD_KO = [
    ("deadline",   "마감"),
    ("pay",        "페이"),
    ("workPeriod", "근무기간"),
    ("workHours",  "근무시간"),
    ("personnel",  "모집"),
    ("certReq",    "교원자격증"),
]
KO2KEY = {ko: key for key, ko in FIELD_KO}
KO2KEY.update({key: key for key, _ in FIELD_KO})          # 모델이 영문 키로 답해도 받는다
# 분류·유형 자체를 지적할 수도 있다(관점 2) — 그때 중복 억제가 어느 값을 기준으로 할지 알려 준다
KO2KEY.update({"분류": "tier", "카테고리": "tier", "category": "tier",
               "유형": "kind", "type": "kind", "제목": "title", "title": "title"})

SYSTEM = """너는 클래식 음악 구인 공고 데이터의 검증자다. 각 공고의 추출된 필드들이 서로, 그리고 공고 제목·유형과 상식적으로 정합한지 판정하라.

점검 관점:
1. 직무-시간 정합: 방과후/시간강사 공고에 "전일제" 근무시간, 주 1-2회 수업에 주 40시간 등
2. 직무-분류 정합: 교원자격증 필요한데 취미·입문, 학교 교원인데 교수, 대학 아닌데 교육—대학
3. 마감 개연성: 마감이 근무 시작일 이후, 접수기간이 비정상적으로 긺(60일+)
4. 필드 내 이물: 페이 필드에 일정 텍스트, 근무기간 필드에 표 헤더 낱말 등 해당 필드와 무관한 내용
5. 스코프: 클래식 음악과 무관한 직무(사무·행정·무용·미술 등)로 보이는 공고

주의:
- 확실한 모순만 보고하라. 애매하면 보고하지 않는다 (오탐이 쌓이면 브리핑을 안 읽게 된다).
- 값이 비어 있는 것은 문제가 아니다 (의도된 정책). 채워진 값의 모순만 본다.
- 수정안을 제시하지 말고 무엇이 왜 이상한지만 서술하라.

출력: JSON 배열만. 마크다운·설명 금지.
[{"id": "...", "field": "근무시간", "issue": "방과후 화목 90분 수업 공고에 전일제(1일 8시간) — 모순", "confidence": "high|medium"}]
이상 없으면 []."""


# ---------- 상태 (자동생성 — 반드시 병합, 통째로 덮어쓰지 않는다) ----------

def load_state():
    if STATE.exists():
        try:
            s = json.loads(STATE.read_text(encoding="utf-8"))
            s.setdefault("seen", {})
            s.setdefault("reported", {})
            s.setdefault("runs", [])
            return s
        except Exception:
            pass
    return {"seen": {}, "reported": {}, "runs": []}


def save_state(state):
    state["runs"] = state.get("runs", [])[-30:]
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _hash(v):
    return hashlib.sha1(str(v).encode("utf-8")).hexdigest()[:12]


# ---------- 대상 고르기 ----------

def payload_of(item):
    """LLM에 보낼 최소 입력. 원문은 넣지 않는다 — 원문 대조는 C7 역방향 감사의 몫이고,
    L4는 '뽑아 놓은 값들끼리 말이 되는가'만 본다."""
    fields = {ko: item.get(key) for key, ko in FIELD_KO if item.get(key)}
    return {
        "id": item.get("id"),
        "title": (item.get("title") or "")[:80],
        "org": (item.get("org") or "")[:40],       # 관점 2(대학 아닌데 교육—대학) 판정에 필요
        "category": item.get("tier"),
        "type": item.get("kind"),
        "fields": fields,
    }


def fingerprint(p):
    """이 공고의 '검증 대상 내용'이 지난번과 같은가. 제목·분류·필드값이 그대로면 같다."""
    return _hash(json.dumps(
        {k: p[k] for k in ("title", "category", "type", "fields")}, ensure_ascii=False, sort_keys=True))


def pick_targets(items, state, force_ids=()):
    """신규 + 필드가 바뀐 공고만. 전량 재검사는 하지 않는다 (비용 통제)."""
    seen, targets = state.get("seen", {}), []
    for it in items:
        iid = it.get("id")
        if not iid:
            continue
        p = payload_of(it)
        if not p["fields"] and iid not in force_ids:
            continue                       # 볼 값이 하나도 없으면 판정할 것도 없다
        fp = fingerprint(p)
        if iid in force_ids or seen.get(iid) != fp:
            targets.append((p, fp))
    return targets


# ---------- API ----------

# 진짜 키는 ASCII 영숫자·하이픈·밑줄뿐이다. 한글이 섞인 안내 문구('sk-ant-여기에_키를…')나
# 잘못 붙여넣은 명령어를 키로 착각하면 401 만 받고 원인을 못 찾는다 (2026-08-16 실제로 겪음).
_KEY_SHAPE = re.compile(r"^sk-[A-Za-z0-9_-]{20,}$")


def _valid_key(k):
    """키 모양인가. 아니면 401 대신 조용히 스킵한다."""
    return bool(k) and bool(_KEY_SHAPE.match(k))


def load_key():
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if _valid_key(key):
        return key
    f = SECRETS / "anthropic-key.txt"      # 자격증명은 커밋하지 않는다 (.secrets/ 는 gitignore)
    if f.exists():
        # 파일에 안내 주석을 남겨 둘 수 있게 '#' 줄과 빈 줄은 건너뛴다
        for line in f.read_text(encoding="utf-8").splitlines():
            k = line.strip()
            if k and not k.startswith("#") and _valid_key(k):
                return k
    return None


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def parse_findings(text):
    """모델 응답 → 판정 목록. 파싱 실패는 예외로 올려 해당 배치만 건너뛰게 한다."""
    body = _FENCE.sub("", (text or "").strip())
    m = re.search(r"\[.*\]", body, re.S)   # 앞뒤에 설명이 붙어 와도 배열만 건진다
    data = json.loads(m.group(0) if m else body)
    if not isinstance(data, list):
        raise ValueError("배열이 아님")
    out = []
    for d in data:
        if not isinstance(d, dict) or not d.get("id") or not d.get("issue"):
            continue
        conf = str(d.get("confidence", "medium")).lower()
        out.append({
            "id": str(d["id"]),
            "field": str(d.get("field") or "").strip(),
            "issue": str(d["issue"])[:160],
            "confidence": "high" if conf.startswith("high") else "medium",
        })
    return out


def call_api(key, model, batch):
    # temperature 는 넣지 않는다 — 최신 모델에서 폐기돼 400 이 난다 (2026-08-16 실측).
    # 판정 일관성은 프롬프트가 담보한다.
    req = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": json.dumps(batch, ensure_ascii=False)}],
    }
    headers = {"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"}
    r = requests.post(API_URL, headers=headers, json=req, timeout=TIMEOUT)
    r.raise_for_status()
    doc = r.json()
    text = "".join(c.get("text", "") for c in doc.get("content", []) if c.get("type") == "text")
    u = doc.get("usage") or {}
    return text, u.get("input_tokens", 0), u.get("output_tokens", 0)


def estimate_cost(model, tok_in, tok_out):
    rate = next((v for k, v in PRICES.items() if model.startswith(k)), PRICES["claude-sonnet"])
    return (tok_in * rate[0] + tok_out * rate[1]) / 1_000_000


# ---------- 실행 ----------

def run(items, state, force_ids=(), dry_run=False, model=None):
    """(findings, note) 반환. note는 헬스체크 로그에 남길 한 줄 요약.

    어떤 실패도 예외로 새어 나가지 않는다 — L4가 헬스체크 나머지를 막으면 안 된다."""
    model = model or DEFAULT_MODEL
    targets = pick_targets(items, state, force_ids)
    if not targets:
        return [], "L4 대상 0건 — 호출 없음"
    if dry_run:
        return [], f"L4 [dry-run] 대상 {len(targets)}건 (호출 안 함)"

    key = load_key()
    if not key:
        return [], "L4 스킵됨 — ANTHROPIC_API_KEY 없음"

    findings, tok_in, tok_out, failed = [], 0, 0, 0
    for i in range(0, len(targets), BATCH):
        chunk = targets[i:i + BATCH]
        try:
            text, ti, to = call_api(key, model, [p for p, _ in chunk])
            tok_in, tok_out = tok_in + ti, tok_out + to
            findings.extend(parse_findings(text))
        except Exception as e:
            failed += 1
            print(f"[warn] L4 배치 {i // BATCH + 1} 실패: {type(e).__name__}: {str(e)[:120]}",
                  file=sys.stderr)
            continue
        # 성공한 배치의 공고만 '검사 완료'로 표시한다 — 실패분은 다음 실행에서 다시 대상이 된다
        for p, fp in chunk:
            state.setdefault("seen", {})[p["id"]] = fp

    if failed and not findings and failed * BATCH >= len(targets):
        return [], f"L4 스킵됨 — API 호출 {failed}배치 전부 실패 (대상 {len(targets)}건)"

    fresh = dedupe(findings, items, state)
    cost = estimate_cost(model, tok_in, tok_out)
    state.setdefault("runs", []).append({
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"), "model": model,
        "targets": len(targets), "in": tok_in, "out": tok_out,
        "usd": round(cost, 4), "findings": len(fresh), "failedBatches": failed,
    })
    note = (f"L4 대상 {len(targets)}건 · 판정 {len(fresh)}건 · {model} "
            f"토큰 {tok_in}+{tok_out} · 약 ${cost:.4f}"
            + (f" · 실패 배치 {failed}" if failed else ""))
    return fresh, note


def dedupe(findings, items, state):
    """같은 (공고, 필드)는 값이 바뀌기 전까지 다시 보고하지 않는다.
    한 번 읽고 넘긴 지적이 매일 다시 뜨면 브리핑을 안 읽게 된다."""
    by_id = {i.get("id"): i for i in items}
    rep, fresh = state.setdefault("reported", {}), []
    for f in findings:
        it = by_id.get(f["id"])
        if not it:
            continue                        # 이미 사라진 공고 — 보고할 대상이 없다
        key = KO2KEY.get(f["field"], f["field"])
        # 아는 필드면 그 값이 바뀌었는지로 판단하고, 모르는 이름이면 지적 문구 자체를 기준으로
        # 삼는다 — 안 그러면 같은 필드의 서로 다른 지적이 한 덩어리로 묶여 조용히 사라진다.
        vh = _hash(it.get(key)) if key in it else _hash(f["issue"])
        slot = f"{f['id']}|{key}"
        if rep.get(slot) == vh:
            continue                        # 값이 그대로 = 이미 보고한 그 문제
        rep[slot] = vh
        f["title"] = (it.get("title") or "")[:30]
        fresh.append(f)
    # 사라진 공고의 이력은 흘려보낸다 (상태 파일이 무한히 자라지 않도록)
    alive = set(by_id)
    for slot in [s for s in rep if s.split("|")[0] not in alive]:
        rep.pop(slot, None)
    return fresh


def format_findings(findings):
    """(본문 줄 목록, 부록 텍스트) — high는 브리핑 본문에, medium은 접힌 부록에."""
    high = [f for f in findings if f["confidence"] == "high"]
    med = [f for f in findings if f["confidence"] != "high"]
    lines = [f"[L4] {f['title']} {f['field']} — {f['issue']} (high)" for f in high]
    appendix = ""
    if med:
        appendix = "L4 참고(medium, 확인만):\n" + "\n".join(
            f"  · {f['title']} {f['field']} — {f['issue']}" for f in med)
    return lines, appendix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="대상만 세고 API 호출·상태 저장 안 함")
    ap.add_argument("--force-id", action="append", default=[], help="이 공고를 대상에 강제 포함")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    doc = json.loads((DATA / "official.json").read_text(encoding="utf-8"))
    items = doc.get("items", [])
    state = load_state()
    findings, note = run(items, state, force_ids=tuple(args.force_id),
                         dry_run=args.dry_run, model=args.model)
    print(note)
    lines, appendix = format_findings(findings)
    for ln in lines:
        print(ln)
    if appendix:
        print(appendix)
    if not args.dry_run:
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
