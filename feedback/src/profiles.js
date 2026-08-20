// 프로필 디렉토리 — 저장·검증·삭제 (작업 H, 2026-08-20)
//
// 원칙 (지시서 v3 + 2026-08-20 승인 사항)
//  · 개인정보는 public 저장소에 1바이트도 넣지 않는다 — 전부 KV 안에서만 산다.
//  · **삭제 경로가 게시 기능보다 먼저다.** 지울 방법이 없는 상태로 공개 폼을 열면
//    잘못 올라온 개인정보를 뺄 수단이 없다.
//  · 수정·삭제 토큰은 **해시로만 저장한다.** 토큰이 곧 타인 프로필 삭제 권한이라,
//    평문으로 두면 KV 열람 권한이 삭제 권한이 된다. 비밀번호와 같은 취급이다.
//  · 토큰은 crypto.getRandomValues 기반 128비트. Math.random 계열 금지(예측 가능).
//  · 토큰은 URL 쿼리에 싣지 않는다 — 브라우저 히스토리·엣지 로그에 남는다.
//    조회·수정·삭제 전부 POST body 로 받는다.
//  · 자동 게시 금지 — 제출은 pending 으로만 들어가고 사람이 승인해야 published 가 된다.

export const LIMITS = {
  name: 40, intro: 100, career: 500, contact: 200,
  rateMax: 3, rateWindow: 3600,     // 같은 IP 시간당 3회 (공개 폼 최소 방어)
};

// 토큰: 16바이트(128비트) → base32 유사 표기. 사람이 옮겨 적을 수 있게 소문자+숫자만.
const T_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789";   // 헷갈리는 글자(i,l,o,0,1) 제외
export function newToken() {
  const buf = new Uint8Array(16);
  crypto.getRandomValues(buf);
  let out = "";
  for (const b of buf) out += T_ALPHABET[b % T_ALPHABET.length];
  return out.replace(/(.{4})(?=.)/g, "$1-");   // pxk2-9mfa-… 옮겨 적기 쉽게 끊는다
}

export async function hashToken(token) {
  const norm = String(token || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
  if (!norm) return "";
  const buf = await crypto.subtle.digest("SHA-256",
    new TextEncoder().encode("podium:profile:" + norm));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

// 해시 비교도 시간차를 남기지 않는다 (worker.js keyOk 와 같은 이유)
export function hashEq(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

const REGIONS = new Set(["서울", "부산", "대구", "인천", "대전", "울산", "세종", "경기",
  "강원", "충북", "충남", "전북", "광주·전남", "경북", "경남", "제주"]);

// 공개 연락 수단 — 이메일 또는 http(s) 주소만. 전화번호는 v0 에서 받지 않는다
// (공개 페이지에 전화번호가 박히면 스팸 수집의 표적이 된다).
const EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/;
const URL_RE = /^https?:\/\/[^\s<>"']{4,}$/i;

export function validate(body) {
  const out = {}, err = [];
  const s = (v, n) => String(v == null ? "" : v).trim().replace(/\s+/g, " ").slice(0, n);

  out.name = s(body.name, LIMITS.name);
  if (out.name.length < 2) err.push("이름 또는 활동명을 적어 주세요");

  out.inst = s(body.inst, 40);
  if (!out.inst) err.push("악기 또는 전공을 적어 주세요");

  out.region = s(body.region, 12);
  if (!REGIONS.has(out.region)) err.push("활동 지역을 골라 주세요");

  out.intro = s(body.intro, LIMITS.intro);
  if (out.intro.length < 5) err.push("한 줄 소개를 적어 주세요");

  out.career = s(body.career, LIMITS.career);   // 선택

  out.contact = s(body.contact, LIMITS.contact);
  if (!(EMAIL_RE.test(out.contact) || URL_RE.test(out.contact))) {
    err.push("공개 연락 수단은 이메일 또는 링크로 적어 주세요");
  }

  if (body.consent !== true && body.consent !== "true") {
    err.push("공개 게시 동의가 필요합니다");
  }
  return { data: out, err };
}

export const KEY = (id) => `pf:${id}`;

export function newId() {
  const buf = new Uint8Array(8);
  crypto.getRandomValues(buf);
  return [...buf].map(b => b.toString(16).padStart(2, "0")).join("");
}

// 공개 화면에 내보내는 모양 — 토큰 해시·IP 해시 같은 내부 값은 절대 싣지 않는다.
export function publicView(p) {
  return {
    id: p.id, name: p.name, inst: p.inst, region: p.region,
    intro: p.intro, career: p.career, contact: p.contact, at: p.at,
  };
}
