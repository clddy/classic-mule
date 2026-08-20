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
  name: 40, intro: 100, career: 500, contact: 200, phone: 20, video: 300,
  rateMax: 3, rateWindow: 3600,     // 같은 IP 시간당 3회 (공개 폼 최소 방어)
};

// 연주 영상 — 연주자에게는 이력서보다 이게 실체다 (2026-08-20 사용자 지시:
// "자신이 얼만큼 칠 수 있는지 퍼포먼스가 중요하기 때문에").
// 링크는 임베드가 되는 곳만 받는다. 아무 URL이나 받으면 공개 페이지가 낚시 링크의 통로가 된다.
const VIDEO_HOSTS = /^https?:\/\/(?:www\.)?(?:youtube\.com\/(?:watch\?v=|shorts\/|embed\/)|youtu\.be\/|vimeo\.com\/|naver\.me\/|tv\.naver\.com\/)/i;

export function videoId(url) {
  // 유튜브·비메오 주소에서 임베드용 식별자. 못 읽으면 null.
  const u = String(url || "");
  let m = u.match(/(?:youtube\.com\/(?:watch\?v=|shorts\/|embed\/)|youtu\.be\/)([A-Za-z0-9_-]{6,})/i);
  if (m) return { host: "youtube", id: m[1] };
  m = u.match(/vimeo\.com\/(?:video\/)?(\d{6,})/i);
  if (m) return { host: "vimeo", id: m[1] };
  return null;
}

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

// 공개 연락 수단 — 이메일은 필수, 전화번호는 선택 (2026-08-20 사용자 지시로 두 칸으로 나눔).
// ⚠ 공개 페이지의 전화번호는 스팸 수집의 표적이 된다. 그래도 받기로 한 것은 연주 일감이
//   전화로 오가는 일이 많기 때문이다 — 대신 '선택'으로 두어 본인이 고르게 한다.
const EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/;
const URL_RE = /^https?:\/\/[^\s<>"']{4,}$/i;
// 국내 번호만. 하이픈이 있든 없든 받고 저장할 때 하이픈 꼴로 맞춘다.
const PHONE_RE = /^0\d{1,2}-?\d{3,4}-?\d{4}$/;

function fmtPhone(v) {
  const d = String(v || "").replace(/[^0-9]/g, "");
  if (d.length === 11) return d.slice(0, 3) + "-" + d.slice(3, 7) + "-" + d.slice(7);
  if (d.length === 10) {
    return d.startsWith("02")
      ? d.slice(0, 2) + "-" + d.slice(2, 6) + "-" + d.slice(6)
      : d.slice(0, 3) + "-" + d.slice(3, 6) + "-" + d.slice(6);
  }
  if (d.length === 9 && d.startsWith("02")) return "02-" + d.slice(2, 5) + "-" + d.slice(5);
  return String(v || "").trim();
}

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
    err.push("이메일을 정확히 적어 주세요");
  }

  out.phone = s(body.phone, LIMITS.phone);
  if (out.phone) {
    const norm = fmtPhone(out.phone);
    if (!PHONE_RE.test(norm.replace(/-/g, "").replace(/^(0\d{1,2})(\d{3,4})(\d{4})$/, "$1-$2-$3"))
        && !PHONE_RE.test(norm)) {
      err.push("전화번호 형식을 확인해 주세요 (예: 010-1234-5678)");
    } else {
      out.phone = norm;
    }
  }

  // 영상 링크 (선택) — 임베드 가능한 곳만
  out.video = s(body.video, LIMITS.video);
  if (out.video && !VIDEO_HOSTS.test(out.video)) {
    err.push("영상 링크는 유튜브·비메오 주소만 넣을 수 있습니다");
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
    intro: p.intro, career: p.career, contact: p.contact, phone: p.phone || "", at: p.at,
    video: p.video || "", videoFile: p.videoFile || "",
  };
}
