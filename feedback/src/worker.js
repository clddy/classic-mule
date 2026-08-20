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

import * as PF from "./profiles.js";

const MAX_LEN = 2000;
const MIN_LEN = 5;
const RATE_MAX = 5;          // 같은 IP가 한 시간에 보낼 수 있는 수
const RATE_WINDOW = 3600;    // 초

const ALLOW_ORIGINS = [
  "https://podiumclassical.kr",
  "https://clddy.github.io",
  "http://localhost:4174",
  "http://localhost:4175",
  "http://localhost:8791",   // 대시보드 로컬 확인용 (podium-static)
  "http://localhost:4173",
];

function cors(origin) {
  const allow = ALLOW_ORIGINS.includes(origin) ? origin : ALLOW_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Admin-Key",
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

// 보낸 결과를 짧은 문자열로 돌려준다. 예전엔 실패를 통째로 삼켰는데, 그러면 알림이
// 안 올 때 원인을 볼 방법이 없다 — 토큰이 틀린 건지 대화방 id가 틀린 건지, 아니면
// 애초에 호출조차 안 된 건지 구분이 안 됐다 (2026-08-08).
// 피드백 저장은 이미 끝난 뒤라 여기서 실패해도 흐름은 막지 않는다.
// 붙여넣을 때 따옴표·쉼표·줄바꿈이 딸려 들어가는 일이 잦다. 그대로 두면 텔레그램이
// 'Not Found'를 돌려주는데, 그 메시지만 봐서는 토큰이 틀린 건지 알 길이 없다.
const clean = v => String(v || "").trim().replace(/^["'`]|["',`]+$/g, "").trim();


async function notifyTelegram(env, item) {
  const TOKEN = clean(env.TELEGRAM_BOT_TOKEN);
  const CHAT = clean(env.TELEGRAM_CHAT_ID);
  if (!TOKEN) return "토큰 없음";
  if (!CHAT) return "대화방 id 없음";
  const text = `📮 포디엄 피드백\n\n${item.message}\n\n— ${item.page || "?"}`;
  try {
    const r = await fetch(`https://api.telegram.org/bot${TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: CHAT, text }),
    });
    const d = await r.json().catch(() => ({}));
    if (d && d.ok) return "ok";
    // 텔레그램이 돌려주는 사유를 그대로 남긴다("chat not found", "Unauthorized" 등).
    // 토큰 자체는 여기 안 실린다.
    return `실패: ${d.description || r.status}`;
  } catch (e) {
    return `실패: ${e.name}`;
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
  // 알림 결과를 항목에 함께 적어 둔다 — 관리자 페이지에서 '텔레그램이 안 갔다'를 볼 수 있게.
  item.tg = await notifyTelegram(env, item);
  await env.FEEDBACK.put(`fb:${rev}:${item.id}`, JSON.stringify(item));
  return json({ ok: true }, 200, origin);
}

// 열쇠는 헤더로 받는다. 주소창(쿼리스트링)에 실으면 브라우저 기록·중간 로그에 그대로 남는다.
function adminKey(req, url) {
  return req.headers.get("X-Admin-Key") || url.searchParams.get("key") || "";
}


async function diag(req, url, env, origin) {
  if (!keyOk(adminKey(req, url), env.ADMIN_KEY)) {
    return json({ ok: false, error: "열쇠가 맞지 않습니다" }, 401, origin);
  }
  const out = { hasToken: !!env.TELEGRAM_BOT_TOKEN, hasChatId: !!env.TELEGRAM_CHAT_ID };
  if (env.TELEGRAM_BOT_TOKEN) {
    // 어느 봇인지 확인 — 토큰이 다른 봇의 것이면 여기서 이름이 다르게 나온다
    try {
      const r = await fetch(`https://api.telegram.org/bot${clean(env.TELEGRAM_BOT_TOKEN)}/getMe`);
      const d = await r.json();
      out.bot = d.ok ? `@${d.result.username}` : `실패: ${d.description}`;
    } catch (e) { out.bot = `실패: ${e.name}`; }
  }
  out.send = await notifyTelegram(env, { message: "진단 발송 — 이 메시지가 보이면 알림 경로 정상", page: "/diag" });
  return json({ ok: true, ...out }, 200, origin);
}


async function list(req, url, env, origin) {
  if (!keyOk(adminKey(req, url), env.ADMIN_KEY)) {
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

async function mark(req, url, env, origin, read) {
  if (!keyOk(adminKey(req, url), env.ADMIN_KEY)) {
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

// ── 방문 대시보드 데이터 (2026-08-19) ────────────────────────────────────────
// 왜 여기 있나: 사이트 저장소가 public 이라 data/traffic.json 을 커밋하면 방문자 수·
// 검색 유입·어떤 공고가 읽히는지가 통째로 공개된다(.gitignore 가 그래서 막고 있다).
// 그렇다고 로컬 서버를 띄워야만 보이면 실제로 안 보게 된다 — 화면(analytics.html)은
// 공개 사이트에 두고 **데이터만** 열쇠로 여기서 받아 간다. 피드백 수신함과 같은 구조다.
//
// PC 가 매일(crawler/dash_upload.py) 올리고, 브라우저가 열쇠로 받아 간다.
// KV 값 1MB 제한이 있어 traffic+search 합본만 둔다 — 지금 30KB 남짓이라 여유가 크다.
const DASH_KEY = "dash:latest";
const DASH_MAX = 900 * 1024;

async function dashPut(req, url, env, origin) {
  if (!keyOk(adminKey(req, url), env.ADMIN_KEY)) {
    return json({ ok: false, error: "열쇠가 맞지 않습니다" }, 401, origin);
  }
  const body = await req.text();
  if (body.length > DASH_MAX) {
    return json({ ok: false, error: "너무 큼 " + body.length }, 413, origin);
  }
  try { JSON.parse(body); } catch (e) {
    return json({ ok: false, error: "JSON 아님" }, 400, origin);
  }
  await env.FEEDBACK.put(DASH_KEY, body);
  return json({ ok: true, bytes: body.length }, 200, origin);
}

async function dashGet(req, url, env, origin) {
  if (!keyOk(adminKey(req, url), env.ADMIN_KEY)) {
    return json({ ok: false, error: "열쇠가 맞지 않습니다" }, 401, origin);
  }
  const v = await env.FEEDBACK.get(DASH_KEY);
  if (!v) return json({ ok: false, error: "아직 올라온 데이터가 없습니다" }, 404, origin);
  return new Response(v, {
    status: 200,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors(origin) },
  });
}


// ---------- 프로필 디렉토리 (작업 H, 2026-08-20) ----------
// 토큰은 조회·수정·삭제 전부 POST body 로 받는다 — URL 쿼리에 실으면 브라우저 히스토리와
// 엣지 로그에 삭제 권한이 그대로 남는다.

async function pfSubmit(req, env, origin) {
  let body;
  try { body = await req.json(); } catch { return json({ ok: false, error: "형식 오류" }, 400, origin); }
  // 봇 덫 — 사람 눈에 안 보이는 칸이 채워져 오면 조용히 성공으로 답하고 버린다
  if (body.website) return json({ ok: true, silent: true }, 200, origin);

  const { data, err } = PF.validate(body);
  if (err.length) return json({ ok: false, error: err[0], errors: err }, 400, origin);

  const ip = req.headers.get("CF-Connecting-IP") || "0.0.0.0";
  const who = await ipHash(ip);
  const rlKey = `pfrl:${who}`;
  const sent = parseInt((await env.PROFILES.get(rlKey)) || "0", 10);
  if (sent >= PF.LIMITS.rateMax) {
    return json({ ok: false, error: "잠시 후 다시 시도해 주세요" }, 429, origin);
  }
  await env.PROFILES.put(rlKey, String(sent + 1), { expirationTtl: PF.LIMITS.rateWindow });

  const token = PF.newToken();
  const rec = {
    ...data,
    id: PF.newId(),
    at: new Date().toISOString(),
    status: "pending",              // 자동 게시 금지 — 사람이 승인해야 published 가 된다
    tokenHash: await PF.hashToken(token),   // 원문은 저장하지 않는다
    who,
  };
  await env.PROFILES.put(PF.KEY(rec.id), JSON.stringify(rec));
  await pfNotifyPending(env).catch(() => {});   // 알림 실패가 제출을 막지 않는다
  // 토큰은 여기서 한 번만 돌려준다. 다시 볼 방법이 없다고 화면에서 분명히 알린다.
  return json({ ok: true, id: rec.id, token }, 200, origin);
}

async function pfLoad(env, id) {
  const raw = id ? await env.PROFILES.get(PF.KEY(id)) : null;
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

// 토큰으로 본인 확인 — 맞으면 레코드를, 아니면 null. 존재/부재를 구분해 알리지 않는다.
async function pfAuth(env, body) {
  const rec = await pfLoad(env, String(body.id || "").slice(0, 32));
  if (!rec) return null;
  const h = await PF.hashToken(body.token);
  return PF.hashEq(h, rec.tokenHash || "") ? rec : null;
}

async function pfView(req, env, origin) {
  let body;
  try { body = await req.json(); } catch { return json({ ok: false }, 400, origin); }
  const rec = await pfAuth(env, body);
  if (!rec) return json({ ok: false, error: "확인 코드가 맞지 않습니다" }, 403, origin);
  return json({ ok: true, profile: PF.publicView(rec), status: rec.status }, 200, origin);
}

async function pfUpdate(req, env, origin) {
  let body;
  try { body = await req.json(); } catch { return json({ ok: false }, 400, origin); }
  const rec = await pfAuth(env, body);
  if (!rec) return json({ ok: false, error: "확인 코드가 맞지 않습니다" }, 403, origin);
  const { data, err } = PF.validate({ ...body, consent: true });
  if (err.length) return json({ ok: false, error: err[0] }, 400, origin);
  // 고친 내용은 다시 승인을 받는다 — 승인 뒤 내용을 바꿔치기하는 경로를 막는다
  const next = { ...rec, ...data, status: "pending", editedAt: new Date().toISOString() };
  await env.PROFILES.put(PF.KEY(rec.id), JSON.stringify(next));
  return json({ ok: true, status: next.status }, 200, origin);
}

async function pfDelete(req, env, origin) {
  let body;
  try { body = await req.json(); } catch { return json({ ok: false }, 400, origin); }
  const rec = await pfAuth(env, body);
  if (!rec) return json({ ok: false, error: "확인 코드가 맞지 않습니다" }, 403, origin);
  await env.PROFILES.delete(PF.KEY(rec.id));   // 실삭제 — 표시만 바꾸지 않는다
  return json({ ok: true, deleted: true }, 200, origin);
}


// --- 승인 파이프라인 (H-2) — 자동 게시 금지. 사람이 승인해야 published 가 된다. ---

// 알림은 건당이 아니라 '대기 N건' 묶음으로 보낸다 — 봇이 폼을 두들기면 건당 알림은
// 그대로 알림 폭탄이 된다 (2026-08-20 승인 사항). 같은 시간대에는 한 번만 보낸다.
async function pfNotifyPending(env) {
  const TOKEN = clean(env.TELEGRAM_BOT_TOKEN);
  const CHAT = clean(env.TELEGRAM_CHAT_ID);
  if (!TOKEN || !CHAT) return "설정 없음";
  const mark = new Date().toISOString().slice(0, 13);   // 시간 단위 묶음 (YYYY-MM-DDTHH)
  if (await env.PROFILES.get("pfnotify:" + mark)) return "이미 보냄";
  const { keys } = await env.PROFILES.list({ prefix: "pf:" });
  let pending = 0;
  for (const k of keys) {
    const raw = await env.PROFILES.get(k.name);
    try { if (JSON.parse(raw).status === "pending") pending++; } catch { /* 건너뜀 */ }
  }
  if (!pending) return "대기 없음";
  await env.PROFILES.put("pfnotify:" + mark, "1", { expirationTtl: 3600 });
  const text = `👤 포디엄 프로필 승인 대기 ${pending}건

관리자 페이지에서 확인하세요.`;
  try {
    const r = await fetch(`https://api.telegram.org/bot${TOKEN}/sendMessage`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: CHAT, text }),
    });
    const d = await r.json().catch(() => ({}));
    return d && d.ok ? "ok" : `실패: ${d.description || r.status}`;
  } catch (e) { return `실패: ${e.name}`; }
}

// 관리자 목록 — 열쇠가 있어야 본다. 여기서는 내부값(토큰 해시)을 절대 내보내지 않는다.
async function pfAdminList(req, url, env, origin) {
  if (!keyOk(req.headers.get("X-Admin-Key"), env.ADMIN_KEY)) {
    return json({ ok: false, error: "열쇠가 맞지 않습니다" }, 401, origin);
  }
  const want = url.searchParams.get("status") || "";
  const { keys } = await env.PROFILES.list({ prefix: "pf:" });
  const items = [];
  for (const k of keys) {
    const raw = await env.PROFILES.get(k.name);
    if (!raw) continue;
    let p;
    try { p = JSON.parse(raw); } catch { continue; }
    if (want && p.status !== want) continue;
    items.push({ ...PF.publicView(p), status: p.status, editedAt: p.editedAt || null });
  }
  items.sort((a, b) => String(b.at).localeCompare(String(a.at)));
  return json({ ok: true, items }, 200, origin);
}

// 승인·반려. 반려는 지우지 않고 표시만 바꾼다 — 본인이 토큰으로 지울 수 있어야 하고,
// 관리자가 실수로 지웠을 때 되돌릴 방법이 없으면 곤란하다.
async function pfAdminSet(req, env, origin) {
  if (!keyOk(req.headers.get("X-Admin-Key"), env.ADMIN_KEY)) {
    return json({ ok: false, error: "열쇠가 맞지 않습니다" }, 401, origin);
  }
  let body;
  try { body = await req.json(); } catch { return json({ ok: false }, 400, origin); }
  const status = String(body.status || "");
  if (!["published", "rejected", "pending"].includes(status)) {
    return json({ ok: false, error: "상태값이 올바르지 않습니다" }, 400, origin);
  }
  const rec = await pfLoad(env, String(body.id || "").slice(0, 32));
  if (!rec) return json({ ok: false, error: "없는 프로필" }, 404, origin);
  rec.status = status;
  rec.reviewedAt = new Date().toISOString();
  await env.PROFILES.put(PF.KEY(rec.id), JSON.stringify(rec));
  return json({ ok: true, id: rec.id, status }, 200, origin);
}

// 관리자 삭제 — 사칭·스팸을 즉시 걷어낼 수단. 실삭제다.
async function pfAdminDelete(req, env, origin) {
  if (!keyOk(req.headers.get("X-Admin-Key"), env.ADMIN_KEY)) {
    return json({ ok: false, error: "열쇠가 맞지 않습니다" }, 401, origin);
  }
  let body;
  try { body = await req.json(); } catch { return json({ ok: false }, 400, origin); }
  const id = String(body.id || "").slice(0, 32);
  if (!(await pfLoad(env, id))) return json({ ok: false, error: "없는 프로필" }, 404, origin);
  await env.PROFILES.delete(PF.KEY(id));
  return json({ ok: true, deleted: true }, 200, origin);
}

// 공개 목록 — published 만. 열쇠 없이 누구나 본다(그게 디렉토리의 목적).
async function pfPublic(req, env, origin) {
  const { keys } = await env.PROFILES.list({ prefix: "pf:" });
  const items = [];
  for (const k of keys) {
    const raw = await env.PROFILES.get(k.name);
    if (!raw) continue;
    try {
      const p = JSON.parse(raw);
      if (p.status === "published") items.push(PF.publicView(p));
    } catch { /* 건너뜀 */ }
  }
  items.sort((a, b) => String(b.at).localeCompare(String(a.at)));
  return json({ ok: true, items }, 200, origin);
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const origin = req.headers.get("Origin") || "";
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });

    if (url.pathname === "/api/feedback" && req.method === "POST") return submit(req, env, origin);
    if (url.pathname === "/api/profile" && req.method === "POST") return pfSubmit(req, env, origin);
    if (url.pathname === "/api/profile/view" && req.method === "POST") return pfView(req, env, origin);
    if (url.pathname === "/api/profile/update" && req.method === "POST") return pfUpdate(req, env, origin);
    if (url.pathname === "/api/profile/delete" && req.method === "POST") return pfDelete(req, env, origin);
    if (url.pathname === "/api/profiles" && req.method === "GET") return pfPublic(req, env, origin);
    if (url.pathname === "/api/profile/admin" && req.method === "GET") return pfAdminList(req, url, env, origin);
    if (url.pathname === "/api/profile/admin" && req.method === "POST") return pfAdminSet(req, env, origin);
    if (url.pathname === "/api/profile/admin/delete" && req.method === "POST") return pfAdminDelete(req, env, origin);
    if (url.pathname === "/api/list" && req.method === "GET") return list(req, url, env, origin);
    if (url.pathname === "/api/diag" && req.method === "GET") return diag(req, url, env, origin);
    if (url.pathname === "/api/read" && req.method === "POST") return mark(req, url, env, origin, true);
    if (url.pathname === "/api/unread" && req.method === "POST") return mark(req, url, env, origin, false);
    if (url.pathname === "/api/dash" && req.method === "PUT") return dashPut(req, url, env, origin);
    if (url.pathname === "/api/dash" && req.method === "GET") return dashGet(req, url, env, origin);

    return json({ ok: false, error: "없는 경로" }, 404, origin);
  },
};
