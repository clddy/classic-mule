# 구글 Indexing API 통보 — 새 공고는 올리고, 내려간 공고는 내린다.
#
# 왜: 구글은 새 페이지를 언제 다시 보러 올지 자기가 정한다. 실제로 podiumclassical.kr 은
# 2026-08-03에 크롤된 뒤 닷새간 안 왔다(검색결과에 '5일 전'으로 박혀 있었다). 매일 수집이
# 이 사이트의 핵심인데 그게 검색에 닿지 않으면 의미가 없다.
#
# Indexing API 는 아무 페이지나 못 쓴다 — 구글이 채용공고(JobPosting)와 생방송에만 열어 뒀다.
# 우리 상세 페이지 p/*.html 이 정확히 JobPosting 이라 자격이 된다. 목록 페이지(jobs.html)는
# 대상이 아니므로 보내지 않는다(정책 위반).
#
# 마감된 공고를 URL_DELETED 로 알리는 쪽이 사실 더 중요하다. 안 그러면 이미 끝난 공고가
# 며칠씩 검색결과에 남아 헛걸음을 만든다.
#
# 자격증명: crawler/.secrets/gcp-indexing.json (gitignore). 서비스 계정 이메일이 Search
# Console 에 **소유자**로 등록돼 있어야 한다 — 관리자 권한으로는 403 이 난다.
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = os.path.join(BASE, "crawler", ".secrets", "gcp-indexing.json")
STATE = os.path.join(BASE, "data", "gindex_state.json")
SITE = "https://podiumclassical.kr"
ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"

DAILY_QUOTA = 200          # 구글 기본 한도
MARGIN = 10                # 여유분 — 한도를 꽉 채우면 다음 실행이 통째로 막힌다


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _token():
    """서비스 계정으로 액세스 토큰 발급. 준비가 안 됐으면 None(조용히 건너뛴다)."""
    if not os.path.exists(KEY):
        return None
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests as gr
    except ImportError:
        print("[gindex] google-auth 미설치 — pip install google-auth")
        return None
    cred = service_account.Credentials.from_service_account_file(
        KEY, scopes=["https://www.googleapis.com/auth/indexing"])
    cred.refresh(gr.Request())
    return cred.token


def notify(verbose=True):
    """official.json 과 지난 통보 기록을 견줘 바뀐 것만 구글에 알린다."""
    token = _token()
    if not token:
        if verbose:
            print("[gindex] 자격증명 없음 — 건너뜀")
        return 0

    import requests
    doc = _load(os.path.join(BASE, "data", "official.json"), {})
    items = doc.get("items") if isinstance(doc, dict) else doc
    live = {f"{SITE}/p/{i['id']}.html" for i in (items or []) if i.get("id")}
    seen = _load(STATE, {})          # url → "up" | "del"

    # 올릴 것: 이번에 새로 실렸거나, 전에 내렸다가 되살아난 것
    up = sorted(u for u in live if seen.get(u) != "up")
    # 내릴 것: 전에 올렸는데 이제 없는 것
    gone = sorted(u for u, st in seen.items() if st == "up" and u not in live)

    budget = DAILY_QUOTA - MARGIN
    # 내리는 쪽을 먼저 태운다 — 끝난 공고가 검색에 남는 게 새 공고가 늦는 것보다 해롭다
    plan = [(u, "URL_DELETED") for u in gone] + [(u, "URL_UPDATED") for u in up]
    if len(plan) > budget:
        if verbose:
            print(f"[gindex] 한도 초과 — {len(plan)}건 중 {budget}건만 보냄 "
                  f"(나머지 {len(plan) - budget}건은 다음 실행에서)")
        plan = plan[:budget]

    ok = 0
    for url, typ in plan:
        try:
            r = requests.post(ENDPOINT,
                              headers={"Authorization": "Bearer " + token,
                                       "Content-Type": "application/json"},
                              json={"url": url, "type": typ}, timeout=30)
        except Exception as e:
            print(f"[gindex] 실패 {type(e).__name__} {url}")
            continue
        if r.status_code == 200:
            seen[url] = "up" if typ == "URL_UPDATED" else "del"
            ok += 1
        elif r.status_code == 403:
            # 소유자 등록이 빠졌거나 풀렸다는 뜻 — 계속 두드려 봐야 소용없다
            print("[gindex] 403 — 서비스 계정이 Search Console 소유자인지 확인할 것. 중단")
            break
        elif r.status_code == 429:
            print("[gindex] 429 한도 소진 — 남은 건 다음 실행으로")
            break
        else:
            print(f"[gindex] {r.status_code} {url} {r.text[:120]}")

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=1)
    if verbose:
        print(f"[gindex] 통보 {ok}건 (신규·갱신 {len(up)} / 마감 {len(gone)})")
    return ok


if __name__ == "__main__":
    sys.exit(0 if notify() >= 0 else 1)
