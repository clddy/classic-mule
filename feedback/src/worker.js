// 포디엄 피드백 수신함 — Cloudflare Worker
//
// 왜 있나: 사이트가 GitHub Pages 정적 호스팅이라 받아 줄 서버가 없다. 그래서 피드백을
// mailto 로 떠넘기고 있었는데, 윈도우에서 메일 앱이 안 열리는 경우가 많아 사실상 막힌
// 통로였다. 방문자는 그 자리에서 쓰고 보내고, 관리자는 사이트 안 관리자 페이지에서 본다
// (2026-08-08 사용자 지시 — "메일 식이 아니라 관리자인 나만 보이게").
//
// 저장은 KV 한 곳. 받는 즉시 텔레그램으로도 밀어 주기 때문에, 관리자 페이지를 열지 않아도
// 새 피드백이 온 걸 안다. 관리자 페이지는 '지난 것 다시 보기'와 '읽음 처리'용이다.
//
// 비밀값은 전부 Worker 시크릿(wrangler secret put)에 둔다 — 사이트 소스에는 들어가지 않는다.
//   ADMIN_KEY           관리자 페이지 열쇠
//   TELEGRAM_BOT_TOKEN  알림봇 토큰 (podium-alert 와 같은 봇을 쓴다)
//   TELEGRAM_CHAT_ID    받을 대화방

const MAX_LEN = 2000;
const MIN_LEN = 5;
const RATE_MAX = 5;          // 같은 IP가 한 시간에 보낼 수 있는 수
const RATE_WINDOW = 3600;    // 초

const ALLOW_ORIGINS = [
  "https://podiumclassical.kr",
  "https://clddy.github.io",
  "http://localhost:4174",
  "http://localhost:4175",
];

function cors(origin) {
  const allow = ALLOW_ORIGINS.includes(origin) ? origin : ALLOW_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}

function json(data, status, origin) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors(origin) },
  });
}

// 열쇠 비교는 길이가 같을 때 전부 훑는다 — 앞글자부터 틀리는 위치로 열쇠를 알아내는
// 시간차 공격을 막기 위함. (짧은 문자열이라 실익은 작지만 비용도 없다)
function keyOk(given, expected) {
  if (!given || !expected || given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < given.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

// IP 원문은 저장하지 않는다. 같은 사람인지만 알면 되므로 해시로 줄여 둔다.
async function ipHash(ip) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("podium:" + ip));
  return [...new Uint8Array(buf)].slice(0, 8).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function notifyTelegram(env, item) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) return;
  const text = `📮 포디엄 피드백\n\n${item.message}\n\n— ${item.page || "?"}`;
  try {
    await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text }),
    });
  } catch (e) {
    // 텔레그램이 죽어도 피드백 저장은 이미 끝났다 — 삼키고 넘어간다
  }
}

async function submit(req, env, origin) {
  let body;
  try {
    body = await req.json();
  } catch {
    return json({ ok: false, error: "형식 오류" }, 400, origin);
  }
  // 봇 덫: 사람 눈에 안 보이는 칸이라 채워져 있으면 자동 프로그램이다.
  // 조용히 성공으로 답한다 — 막혔다는 걸 알려 주면 우회하려 든다.
  if (body.website) return json({ ok: true }, 200, origin);

  const message = String(body.message || "").trim().slice(0, MAX_LEN);
  if (message.length < MIN_LEN) {
    return json({ ok: false, error: "내용을 조금 더 적어 주세요" }, 400, origin);
  }

  const ip = req.headers.get("CF-Connecting-IP") || "0.0.0.0";
  const who = await ipHash(ip);
  const rlKey = `rl:${who}`;
  const sent = parseInt((await env.FEEDBACK.get(rlKey)) || "0", 10);
  if (sent >= RATE_MAX) {
    return json({ ok: false, error: "잠시 후 다시 보내 주세요" }, 429, origin);
  }
  await env.FEEDBACK.put(rlKey, String(sent + 1), { expirationTtl: RATE_WINDOW });

  const now = new Date().toISOString();
  const item = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    at: now,
    message,
    page: String(body.page || "").slice(0, 200),
    ua: (req.headers.get("User-Agent") || "").slice(0, 200),
    who,
    read: false,
  };
  // 키를 '역순 타임스탬프'로 만들어 KV 목록이 최신순으로 나오게 한다.
  // KV list는 키 오름차순만 주는데, 큰 수에서 뺀 값을 쓰면 최신이 앞에 온다.
  const rev = (9999999999999 - Date.now()).toString().padStart(13, "0");
  await env.FEEDBACK.put(`fb:${rev}:${item.id}`, JSON.stringify(item));

  await notifyTelegram(env, item);
  return json({ ok: true }, 200, origin);
}

async function list(url, env, origin) {
  if (!keyOk(url.searchParams.get("key"), env.ADMIN_KEY)) {
    return json({ ok: false, error: "열쇠가 맞지 않습니다" }, 401, origin);
  }
  const res = await env.FEEDBACK.list({ prefix: "fb:", limit: 200 });
  const items = [];
  for (const k of res.keys) {
    const v = await env.FEEDBACK.get(k.name);
    if (v) items.push({ ...JSON.parse(v), _key: k.name });
  }
  return json({ ok: true, items }, 200, origin);
}

async function mark(url, env, origin, read) {
  if (!keyOk(url.searchParams.get("key"), env.ADMIN_KEY)) {
    return json({ ok: false, error: "열쇠가 맞지 않습니다" }, 401, origin);
  }
  const k = url.searchParams.get("k");
  if (!k) return json({ ok: false, error: "대상 없음" }, 400, origin);
  const v = await env.FEEDBACK.get(k);
  if (!v) return json({ ok: false, error: "없는 항목" }, 404, origin);
  const item = JSON.parse(v);
  item.read = read;
  await env.FEEDBACK.put(k, JSON.stringify(item));
  return json({ ok: true }, 200, origin);
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const origin = req.headers.get("Origin") || "";
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });

    if (url.pathname === "/api/feedback" && req.method === "POST") return submit(req, env, origin);
    if (url.pathname === "/api/list" && req.method === "GET") return list(url, env, origin);
    if (url.pathname === "/api/read" && req.method === "POST") return mark(url, env, origin, true);
    if (url.pathname === "/api/unread" && req.method === "POST") return mark(url, env, origin, false);

    return json({ ok: false, error: "없는 경로" }, 404, origin);
  },
};
