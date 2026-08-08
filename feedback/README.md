# 포디엄 피드백 수신함 (Cloudflare Worker)

방문자가 사이트에서 바로 쓰고 보내면 → Worker 가 KV 에 저장 + 텔레그램으로 알림 →
관리자는 `admin.html` 에서 지난 것까지 본다. 메일을 거치지 않는다.

## 처음 한 번만

```bash
cd C:\ohai\podium\feedback
npx wrangler login
npx wrangler kv namespace create FEEDBACK      # 출력된 id 를 wrangler.toml 에 붙여넣기
npx wrangler secret put ADMIN_KEY              # 관리자 페이지 열쇠 (아무 긴 문자열)
npx wrangler secret put TELEGRAM_BOT_TOKEN     # podium-alert 와 같은 봇 토큰
npx wrangler secret put TELEGRAM_CHAT_ID       # 알림 받을 대화방 id
npx wrangler deploy
```

배포하면 `https://podium-feedback.<계정>.workers.dev` 주소가 찍힌다.
그 주소를 `js/feedback.js` 와 `admin.html` 의 `API` 상수에 넣는다.

## 이후 고칠 때

```bash
npx wrangler deploy
```

## 경계

- **비밀값은 wrangler secret 으로만 넣는다.** wrangler.toml·소스에 적으면 커밋된다.
- 관리자 열쇠는 브라우저 localStorage 에만 남는다. 사이트 소스에는 없다.
- IP 는 원문 저장하지 않는다 — 같은 사람인지 세는 용도로만 해시를 남긴다.
- 스팸 방어 두 겹: 봇 덫(숨은 칸) + 같은 IP 시간당 5건.
