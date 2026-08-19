# -*- coding: utf-8 -*-
# 방문 대시보드 데이터 업로드 — traffic.json + search.json 을 Worker(KV)로 올린다.
#
# 왜: 사이트 저장소가 public 이라 방문 통계를 커밋할 수 없다(.gitignore). 그렇다고 로컬
# 서버를 띄워야만 보이면 실제로는 안 보게 된다. 그래서 화면(analytics.html)만 공개
# 사이트에 두고, 데이터는 여기서 열쇠로 올려 브라우저가 열쇠로 받아 가게 한다.
# 피드백 수신함(admin.html)과 완전히 같은 구조다.
#
# 열쇠: crawler/.secrets/admin-key.txt (gitignore) 또는 환경변수 PODIUM_ADMIN_KEY.
#       Worker 쪽 시크릿 ADMIN_KEY 와 같은 값이어야 한다.
#
#   python crawler/dash_upload.py
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://podium-feedback.ohmjin314.workers.dev/api/dash"
KEYFILE = os.path.join(BASE, "crawler", ".secrets", "admin-key.txt")


def _key():
    k = os.environ.get("PODIUM_ADMIN_KEY")
    if k:
        return k.strip()
    try:
        with open(KEYFILE, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _read(name):
    try:
        with open(os.path.join(BASE, "data", name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main():
    import requests
    key = _key()
    if not key:
        print("dash_upload: 열쇠 없음 (%s 또는 PODIUM_ADMIN_KEY) — 스킵" % KEYFILE)
        return 0
    traffic = _read("traffic.json")
    if not traffic:
        print("dash_upload: data/traffic.json 없음 — 스킵 (crawler/traffic.py 먼저)")
        return 0
    payload = json.dumps({"traffic": traffic, "search": _read("search.json")},
                         ensure_ascii=False, separators=(",", ":"))
    r = requests.put(API, data=payload.encode("utf-8"), timeout=30,
                     headers={"Content-Type": "application/json", "X-Admin-Key": key})
    if not r.ok:
        print("dash_upload: 실패 HTTP %s %s" % (r.status_code, r.text[:200]), file=sys.stderr)
        return 1
    print("dash_upload: 올림 %.1fKB (%s)" % (len(payload.encode("utf-8")) / 1024, r.text[:80]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
