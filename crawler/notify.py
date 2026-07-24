"""텔레그램 알림 — 포디엄 저장소에 번들된 판(표준 라이브러리만, 의존성 0).

왜 번들하는가: 원본은 C:\\ohai\\telegram-notify\\notify.py(로컬 공유 허브)에 있지만,
GitHub Actions(리눅스) 컨테이너에는 그 경로가 없다. 크롤 코드가 어디서 돌든
`from notify import send`가 되도록 저장소 안에 같은 모듈을 둔다.

토큰 우선순위:
  1) 환경변수 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  ← Actions는 Secrets가 여기로 주입
  2) 로컬 공유 허브 config.json (C:\\ohai\\telegram-notify\\config.json)  ← 내 PC 실행
자격증명은 코드·커밋에 절대 넣지 않는다 — 값은 Secrets(원격)와 gitignore된 config.json(로컬)에만.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
# 로컬 실행 시 공유 허브의 config.json을 그대로 재사용 (리눅스엔 이 경로가 없어 자동 무시)
_CONFIG_CANDIDATES = [
    os.path.join(_HERE, "config.json"),
    r"C:\ohai\telegram-notify\config.json",
]


def _load_config():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return token, chat_id
    for path in _CONFIG_CANDIDATES:
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("bot_token", ""), str(cfg.get("chat_id", ""))
        except (FileNotFoundError, OSError):
            continue
    return "", ""


def send(text, *, silent=False, parse_mode=None, timeout=15):
    """텔레그램으로 메시지 전송. 성공 True, 실패 False (예외를 던지지 않음)."""
    token, chat_id = _load_config()
    if not token or not chat_id:
        print("[telegram] 토큰/chat_id 없음 (Secrets 또는 config.json 확인)", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_notification": silent}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    data = urllib.parse.urlencode(payload).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=data, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                print(f"[telegram] API 오류: {body}", file=sys.stderr)
                return False
            return True
    except Exception as e:
        print(f"[telegram] 전송 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "포디엄 telegram 번들 테스트 ✅"
    ok = send(msg)
    print("전송 성공" if ok else "전송 실패")
    sys.exit(0 if ok else 1)
