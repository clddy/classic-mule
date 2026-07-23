// 통합 구인구직 보드 — 공식(크롤링) + 소규모(개인·팀 게시글)
// 날짜는 한국시간(KST) 기준 — toISOString은 UTC라 자정~오전9시에 하루 밀리는 문제 방지
const TODAY = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);

// 집계 포털(매개체) 도메인 — 출처로 표기하지 않고, 링크로도 내보내지 않는다
const PORTAL_RE = /artinfokorea|artmore|hibrain|jobkorea|saramin|albamon|cleaneye|gojobs|work\.go\.kr\/portal/i;
// 카드/모달에 보여줄 출처: 포털이면 감추고, 기관 원문이 있으면 그 도메인, 그마저 없으면 빈값
function sourceLabel(j) {
  if (j.source && !PORTAL_RE.test(j.source)) return j.source;
  if (j.officialUrl && !PORTAL_RE.test(j.officialUrl)) {
    try { return new URL(j.officialUrl).host.replace(/^www\./, ""); } catch (e) { return ""; }
  }
  return "";   // 포털에만 있고 기관 원문도 없음(교회·개인 직접게시) → 출처 생략
}

// ---------- 데이터 병합 ----------
const CAT2BAND = {
  "객원/대타": "객원·대체", "단원모집": "단원", "반주": "반주",
  "행사연주": "행사연주", "강사/레슨": "강사·레슨", "지휘/음악감독": "지휘"
};
const KIND2BAND = { "단원": "단원", "객원·대체": "객원·대체", "반주": "반주", "강사": "강사·레슨", "교수": "교수", "직원": "직원·스태프", "기타": "기타" };

const OFFICIAL_ITEMS = ((window.CRAWLED && window.CRAWLED.items) || []).map(j => ({
  key: "o" + j.id, src: "공식", type: "구인",
  tier: j.tier || "연주",
  band: KIND2BAND[j.kind] || "기타",
  insts: j.instDetails || [], group: j.inst,
  subject: j.subject,   // 대학 교수 초빙: 전공/과목
  courses: j.courses,   // 대학 강사: 담당 교과목(무엇을 가르치는지)
  obri: j.obri,         // 오브리(교회·행사) — 연주의 하위 필터
  certReq: j.certReq, degreeReq: j.degreeReq, careerReq: j.careerReq,   // 자격요건 필드
  verifiedAt: j.verifiedAt, verifiedNote: j.verifiedNote,   // 사람이 직접 확인한 사실 (overrides.json)
  ageGroup: j.ageGroup || "성인",   // 지원자 연령: 성인 / 미성년
  region: j.region, title: j.title, org: j.org,
  deadline: j.deadline, deadlineText: j.deadlineNote, date: j.date || j.firstSeen,
  personnel: j.personnel, qualification: j.qualification, contract: j.contract, pay: j.pay,
  auditionDate: j.auditionDate, rehearsal: j.rehearsal, concertDate: j.concertDate, program: j.program,
  positions: j.positions, recruitSummary: j.recruitSummary, bodyExcerpt: j.bodyExcerpt,
  denomination: j.denomination, documents: j.documents,
  applyEmail: j.applyEmail, applyPhone: j.applyPhone,
  url: j.url, officialUrl: j.officialUrl, isNew: j.isNew, source: j.source
}));

let COMMUNITY_ITEMS = JOBS.map(j => ({
  key: "c" + j.id, src: "소규모", type: "구인",   // v2.0: 예시 데이터는 구인만
  tier: j.tier || "연주",
  band: CAT2BAND[j.cat] || "기타",
  insts: j.instDetails || [j.instDetail], group: j.inst,
  ageGroup: "성인",
  region: j.region, title: j.title, org: j.org, pay: j.pay,
  when: j.when, program: j.program,
  personnel: j.personnel, qualification: j.qualification, contract: j.contract,
  auditionDate: j.auditionDate, rehearsal: j.rehearsal, concertDate: j.concertDate,
  positions: j.positions, recruitSummary: j.recruitSummary,
  deadline: /^\d{4}/.test(j.deadline) ? j.deadline : null, deadlineText: j.deadline,
  date: j.date, body: j.body, urgent: j.urgent, cid: j.id,
  sample: true   // data.js는 '예시' 게시글만 담음 — 카드 옅게 + '예시' 배지
}));

// ---------- 사용자가 직접 올린 공고 (localStorage 지속) ----------
// 이 기기에서 올린 글은 새로고침해도 유지된다. mine:true → '내 공고 관리'에서 삭제 가능.
// ※ 다른 사용자에게도 보이려면 공유 백엔드가 필요(지금은 이 기기 로컬 프로토타입).
const LS_KEY = "podium_user_posts_v2";
// 태그 체계 개편(구 4분류 → 연주/교육 3종): 이 기기에 저장된 옛 글의 tier를 새 체계로 이관
const TIER_MIGRATE = {
  "프로": "연주", "오브리": "연주", "전공·입시": "교육 — 입시·전공",
  "교육·취미": "교육 — 취미·입문", "대학·전공": "교육 — 대학",
  "예중·예고": "교육 — 입시·전공", "입문·취미": "교육 — 취미·입문"
};
function loadUserPosts() {
  try {
    const posts = JSON.parse(localStorage.getItem(LS_KEY)) || [];
    for (const p of posts) {
      if (TIER_MIGRATE[p.tier]) {
        if (p.tier === "오브리") p.obri = true;   // 오브리는 연주의 하위 필터로 승계
        p.tier = TIER_MIGRATE[p.tier];
      }
    }
    return posts;
  } catch (e) { return []; }
}
function saveUserPosts() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(USER_POSTS)); } catch (e) {}
}
let USER_POSTS = loadUserPosts();

// 연령은 필터가 아니라 '배지'로만 노출. 지금은 꺼둠 — 나중에 이 플래그만 true로 켜면 미성년 배지가 뜬다.
const SHOW_AGE_BADGE = false;

// ---------- 필터 정의 ----------
// 등급(단일 축: 연주냐 가르치냐, 가르치면 누구를). 미분류는 사람 확인 큐 → 필터 칩에는 노출 안 함.
const TIERS = ["연주", "교육 — 대학", "교육 — 입시·전공", "교육 — 취미·입문"];
const TIER_CLS = {
  "연주": "src-official", "교육 — 대학": "pos", "교육 — 입시·전공": "inst",
  "교육 — 취미·입문": "dd-open", "미분류": "dd-always"
};
const BANDS = ["단원", "객원·대체", "반주", "행사연주", "강사·레슨", "지휘", "교수", "직원·스태프", "기타"];
const INST_GROUPS = [
  ["현악", ["바이올린", "비올라", "첼로", "더블베이스"]],
  ["목관", ["플루트", "오보에", "클라리넷", "바순"]],
  ["금관", ["호른", "트럼펫", "트롬본", "튜바", "색소폰"]],
  ["그 외", ["타악", "피아노", "하프", "지휘"]],
  ["성악", ["소프라노", "메조소프라노", "알토", "테너", "바리톤", "베이스(성악)"]],
];
// 2026-07-01 전남광주통합특별시 출범 — 전남·광주가 한 광역단체가 됐다. crawler/common.py와 같은 표기.
const REGION_LIST = ["서울", "경기", "인천", "강원", "대전", "세종", "충북", "충남",
  "대구", "경북", "부산", "울산", "경남", "광주·전남", "전북", "제주", "기타"];
// 통합 전에 수집된 글은 region이 아직 '광주'·'전남'이다 — 다음 크롤 전까지 화면에서 옮겨 읽는다.
const REGION_MIGRATE = { "광주": "광주·전남", "전남": "광주·전남" };
function regionOf(j){ const r = j.region || "기타"; return REGION_MIGRATE[r] || r; }
const STATUSES = ["접수중", "마감임박", "기한 미정", "마감"];

// 기본 정렬은 마감 임박순 — '언제까지 지원 가능한가'가 이 보드의 1차 정보다 (2026-07-23)
const state = { tab: "전체", tiers: new Set(), bands: new Set(), insts: new Set(), regions: new Set(), status: new Set(), provided: new Set(), obri: false, noCert: false, noCareer: false, query: "", sort: "deadline" };
const $ = (s) => document.querySelector(s);

// 상태 어휘 통일: 사용자가 알고 싶은 건 '지금 지원 가능한가'와 '언제까지인가' 둘뿐.
//  · D-day 카운트는 임박(7일 이내)했을 때만 — D-167 같은 숫자는 정보가 아니라 소음
//  · 마감이 30일 넘게 남으면 '상시·장기'로 접음 · D-0은 '오늘 마감'으로 명시
//  · 급구·대타(마감일 없음)는 연주일이 곧 마감 → '연주일 D-n' 기준을 구분 표기
function statusOf(j) {
  let base = j.deadline, kind = "지원 마감";
  if (!base) {
    const cn = concertNum(j);                       // 연주일(YYYYMMDD 정수) — 없으면 Infinity
    if (cn !== Infinity && j.src !== "공식") {
      const s = String(cn); base = `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}`; kind = "연주일";
    } else if (j.deadlineText === "상시") {
      return { key: "접수중", label: "상시", cls: "dd-open", dday: 9000 };
    } else {
      // '확인필요'는 사용자에게 내보이지 않는다 — 크롤러가 찾을 때까지의 임시 표기만.
      return { key: "기한 미정", label: "기한 미정", cls: "dd-always", dday: 9998 };
    }
  }
  const diff = Math.round((new Date(base) - new Date(TODAY)) / 86400000);
  if (diff < 0) return { key: "마감", label: "마감", cls: "dd-closed", dday: 9999 };
  if (diff === 0) return { key: "마감임박", label: kind === "연주일" ? "오늘 연주" : "오늘 마감", cls: "dd-soon", dday: 0 };
  if (diff <= 7) return { key: "마감임박", label: `${kind} D-${diff}`, cls: "dd-soon", dday: diff };
  if (diff > 30) return { key: "접수중", label: "상시·장기", cls: "dd-open", dday: diff };
  return { key: "접수중", label: `접수중 (~${+base.slice(5,7)}.${+base.slice(8,10)})`, cls: "dd-open", dday: diff };
}

// ---------- 칩 렌더 ----------
// '기타'는 클래식 사이트에서 악기 기타(guitar)로 읽힌다 — 화면 표기만 '그 외'로 (데이터 값은 유지)
const bandLabel = b => b === "기타" ? "그 외" : b;
function renderChips(sel, items, set) {
  const el = $(sel);
  el.innerHTML = items.map(v => `<button class="chip${set.has(v) ? " on" : ""}" data-v="${v}">${bandLabel(v)}</button>`).join("");
  el.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => {
    const v = c.dataset.v;
    set.has(v) ? set.delete(v) : set.add(v);
    renderAll();
  }));
}

function renderInstChips() {
  const el = $("#filter-inst");
  el.innerHTML = INST_GROUPS.map(([g, list]) => `
    <div class="inst-group"><span class="inst-group-label">${g}</span>
      ${list.map(v => `<button class="chip${state.insts.has(v) ? " on" : ""}" data-v="${v}">${v}</button>`).join("")}
    </div>`).join("");
  el.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => {
    const v = c.dataset.v;
    state.insts.has(v) ? state.insts.delete(v) : state.insts.add(v);
    renderAll();
  }));
}

// ---------- 필터링 ----------
// 예시 카드(COMMUNITY_ITEMS)는 피드에서 제외 — 실공고 사이에 섞이면 밀도를 부풀리고
// 지원 시도를 유발한다. 예시의 용도는 '이렇게 올리면 좋다' 템플릿 → 빈 결과 화면에서만 노출.
function filtered() {
  const all = [...OFFICIAL_ITEMS, ...USER_POSTS];
  return all.filter(j => {
    if (j.type === "구직") return false;   // v2.0: 구직 게시판 종료 — 저장 데이터는 유지, 표시만 안 함 (Layer 3 프로필이 자리를 물려받을 예정)
    if (state.tiers.size && !state.tiers.has(j.tier)) return false;
    if (state.obri && !j.obri) return false;                       // 오브리(교회·행사)만
    if (state.noCert && j.certReq === "예") return false;          // 교원자격증 불필요한 자리만
    if (state.noCareer && j.careerReq !== "무관") return false;    // 경력 무관인 자리만
    if (state.bands.size && !state.bands.has(j.band)) return false;
    if (state.insts.size) {
      if (!j.insts.length || ![...state.insts].some(v => j.insts.includes(v))) return false;
    }
    if (state.regions.size && !state.regions.has(regionOf(j))) return false;
    if (state.status.size && !state.status.has(statusOf(j).key)) return false;
    if (state.provided.size && !/제공/.test(j.instProvided || "")) return false;
    if (state.query) {
      const q = state.query.toLowerCase();
      if (!`${j.title} ${j.org} ${j.insts.join(" ")} ${j.body || ""}`.toLowerCase().includes(q)) return false;
    }
    return true;
  }).sort(sortFns[state.sort] || sortFns.deadline);
}

// ---------- 정렬 ----------
function payNum(j) {
  const nums = [...String(j.pay || "").matchAll(/(\d[\d,]*)\s*만/g)].map(m => +m[1].replace(/,/g, ""));
  return nums.length ? Math.max(...nums) : -1;
}
function concertNum(j) {
  const s = j.concertDate || j.when || "";
  let m = s.match(/(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})/);
  if (m) return (+m[1]) * 10000 + (+m[2]) * 100 + (+m[3]);
  m = s.match(/(\d{1,2})\s*[/.]\s*(\d{1,2})/);
  if (m) return 20260000 + (+m[1]) * 100 + (+m[2]);
  return Infinity;
}
// 연주(단원·객원·반주) 공고가 교육 공고에 묻히지 않도록 상단 노출 — 마감 안 된 연주는 최상단으로.
const playRank = (j) => (j.tier === "연주" && statusOf(j).key !== "마감") ? 0 : 1;
const byDeadline = (a, b) => {
  if (playRank(a) !== playRank(b)) return playRank(a) - playRank(b);   // 연주 우선
  const sa = statusOf(a), sb = statusOf(b);
  if (sa.dday !== sb.dday) return sa.dday - sb.dday;
  return (b.date || "").localeCompare(a.date || "");
};
const sortFns = {
  // 재방문자의 기본 행동은 '새로 뭐 올라왔나' — 최신순이 기본 (연주 우선 부스트 유지)
  latest: (a, b) => playRank(a) - playRank(b) || (b.date || "").localeCompare(a.date || ""),
  deadline: byDeadline,
  pay: (a, b) => (payNum(b) - payNum(a)) || byDeadline(a, b),
  concert: (a, b) => (concertNum(a) - concertNum(b)) || byDeadline(a, b),
};

// 원천 기관명 태그 — [공식] 대신 어느 기관에서 수집했는지를 그대로 보여준다 (커버리지가 곧 제품)
const SRC_ORG = {
  "sejongpac.or.kr": "세종문화회관", "gojobs.go.kr": "나라일터", "goe.go.kr": "경기도교육청",
  "work.sen.go.kr": "서울시교육청", "kbssymphony.org": "KBS교향악단",
  "cjob.co.kr": "기독정보넷",
  "ice.go.kr": "인천교육청", "pen.go.kr": "부산교육청", "gwe.go.kr": "강원교육청",
  "jbe.go.kr": "전북교육청", "jje.go.kr": "제주교육청", "sje.go.kr": "세종교육청",
  "jne.go.kr": "전남교육청", "gbe.kr": "경북교육청", "cbe.go.kr": "충북교육청",
  "gne.go.kr": "경남교육청", "dje.go.kr": "대전교육청", "bscc.or.kr": "부산문화회관",
  "cwcf.or.kr": "창원문화재단", "gunsan.go.kr": "군산시", "music.snu.ac.kr": "서울대 음대",
  "seoulphil.or.kr": "서울시향", "artsuwon.or.kr": "수원시립예술단",
};
const srcOrgTag = j => SRC_ORG[j.source] || sourceLabel(j) || "";

function cardHTML(j) {
  const st = statusOf(j);
  const tags = `
    ${j.sample ? `<span class="tag sample">예시</span>` : ""}
    <span class="tag ${TIER_CLS[j.tier] || "cat"}">${j.tier}</span>
    ${SHOW_AGE_BADGE && j.ageGroup === "미성년" ? `<span class="tag pos">미성년</span>` : ""}
    ${j.verifiedNote ? `<span class="tag ok">✓ 모집 확인 ${j.verifiedAt || ""}</span>` : ""}
    <span class="tag cat">${bandLabel(j.band)}</span>
    ${j.subject && !j.insts.includes(j.subject) ? `<span class="tag inst">${j.subject}</span>` : ""}
    ${j.insts.map(i => `<span class="tag inst">${i}</span>`).join("")}
    ${(j.positions || []).filter(p => /수석|악장|차석/.test(p)).map(p => `<span class="tag pos">${p}</span>`).join("")}
    <span class="tag ${st.cls}">${st.label}</span>
    ${/제공/.test(j.instProvided || "") ? `<span class="tag provided">악기 제공</span>` : ""}
    ${j.isNew ? `<span class="tag urgent">NEW</span>` : ""}`;
  const region = regionOf(j) !== "기타" ? `<span>${regionOf(j)}</span>` : "";
  const pay = okPay(j.pay) ? `<span class="pay">${cleanVal(j.pay)}</span>` : "";
  const meta = `
    <span>${j.org}</span>
    ${region}
    ${j.when ? `<span>${j.when}</span>` : ""}
    ${pay}
    ${j.rehearsalCount ? `<span>리허설 ${j.rehearsalCount}회</span>` : ""}
    ${j.deadline ? `<span>마감 ${j.deadline}</span>` : ""}`;
  // 객원·대체는 프로그램(연주곡)을 카드에 노출 (동생 피드백)
  const program = j.program
    ? `<div class="program-line"><b>연주곡</b>${j.program}</div>` : "";
  if (j.src === "공식") {
    const orgTag = srcOrgTag(j);
    return `
    <article class="job-card${st.key === "마감" ? " closed" : ""}" data-okey="${j.key}">
      <div class="top-row">${orgTag ? `<span class="tag src-official">${orgTag}</span>` : ""}${tags}</div>
      <h3>${j.title}</h3>
      ${program}
      <div class="meta">${meta}</div>
      <div class="source-line"><span>${srcLine(j)}</span><span>눌러서 상세보기</span></div>
    </article>`;
  }
  return `
    <article class="job-card${st.key === "마감" ? " closed" : ""}${j.sample ? " is-sample" : ""}${j.mine ? " mine" : ""}" data-cid="${j.cid}">
      <div class="top-row">${j.mine ? `<span class="tag pos">포디엄 등록</span>` : ""}${tags}</div>
      <h3>${j.title}</h3>
      ${program}
      <div class="meta">${meta}</div>
    </article>`;
}

// 출처 표기 규칙: 기관 원문(officialUrl)이 있는 공고만 출처를 표기한다.
// 집계 포털(아트인포 등) 이름은 링크는 물론 텍스트로도 내보이지 않는다 (2026-07-23 지시).
function srcLine(j) {
  const s = sourceLabel(j);
  return s ? `출처 <span class="src">${s}</span>` : "";
}

function renderList() {
  const list = filtered();
  // 직접 올린 공고(내 기기)를 최상단 고정 — 급구 먼저, 그다음 최신순
  const mine = list.filter(x => x.mine)
    .sort((a, b) => b.cid - a.cid);
  const rest = list.filter(x => !x.mine);
  const oc = rest.filter(x => x.src === "공식").length;
  $("#result-count").innerHTML = `총 <strong>${list.length}</strong>건 (공식 ${oc} · 소규모 ${list.length - oc}) — 카드를 누르면 상세가 열립니다`;
  const el = $("#job-list");
  if (!list.length) {
    // 빈 결과 = 예시 카드의 자리: '이렇게 올리면 좋다' 템플릿으로만 노출 (피드에는 섞지 않음)
    el.innerHTML = `<div class="empty">조건에 맞는 공고가 없습니다.<br>필터를 조정하거나, 직접 올려보세요.</div>
      <div class="pinned-sep">작성 예시 — 이런 정보가 들어가면 지원이 빨라져요</div>`
      + COMMUNITY_ITEMS.map(cardHTML).join("");
    return;
  }
  let html = "";
  if (mine.length) {
    html += `<div class="pinned-head">📌 직접 올린 공고 <span>${mine.length}</span></div>`;
    html += mine.map(cardHTML).join("");
    if (rest.length) html += `<div class="pinned-sep">전체 공고</div>`;
  }
  html += rest.map(cardHTML).join("");
  el.innerHTML = html;
  el.querySelectorAll(".job-card[data-cid]").forEach(card => {
    card.addEventListener("click", () => openDetail(+card.dataset.cid));
  });
  el.querySelectorAll(".job-card[data-okey]").forEach(card => {
    card.addEventListener("click", () => openOfficial(card.dataset.okey));
  });
}


// 단일 토글 필터 (오브리·교원자격증) — 다중선택 칩과 달리 boolean state
function renderToggle(sel, label, key) {
  const el = $(sel);
  if (!el) return;
  el.innerHTML = `<button class="chip${state[key] ? " on" : ""}">${label}</button>`;
  el.querySelector(".chip").addEventListener("click", () => { state[key] = !state[key]; renderAll(); });
}

function renderAll() {
  renderChips("#filter-tier", TIERS, state.tiers);
  renderToggle("#filter-obri", "교회 공고만", "obri");   // 크롤 필드명(obri)은 유지 — 크롤러 무수정
  renderToggle("#filter-cert", "교원자격증 불필요만", "noCert");
  renderToggle("#filter-career", "경력 무관만", "noCareer");
  // 교원자격증·학위는 교육 공고에만 해당 — 교육 구분을 골랐을 때만 노출 (연주 찾는 사람에겐 소음)
  const eduOn = [...state.tiers].some(t => t.startsWith("교육"));
  const fgCert = $("#fg-cert");
  if (fgCert) {
    fgCert.style.display = eduOn ? "" : "none";
    if (!eduOn && (state.noCert || state.noCareer)) { state.noCert = false; state.noCareer = false; }
  }
  renderChips("#filter-band", BANDS, state.bands);
  renderInstChips();
  renderChips("#filter-region", REGION_LIST, state.regions);
  renderChips("#filter-status", STATUSES, state.status);
  renderChips("#filter-provided", ["제공됨"], state.provided);
  renderList();
}

// ---------- 유형별 요약 필드 (단원 vs 객원 구분) ----------
// 단원(정규): 모집인원·자격·계약기간·오디션 (프로그램 없음)
// 객원·대체: 모집인원·자격·리허설·연주일·페이·프로그램
// 필드 값 정제: OCR 띄어쓰기·공유버튼 꼬리·잡음 제거
function cleanVal(v) {
  return String(v || "").replace(/\s+/g, " ")
    .replace(/(\d)\s+([가-힣])/g, "$1$2")          // OCR: "30 명"→"30명", "2011 년"→"2011년"
    .replace(/\s*[(（][^)）]*$/, "")                // 닫히지 않은 괄호 이하 제거 (OCR 잘림)
    .replace(/(?:\s+(?:URL|주소 ?복사|복사|인쇄|스크랩|공유|보내기|관심기관\S*|목록|메뉴|홈|top))+\s*$/gi, "")
    .replace(/\s+\d{1,2}$/, "")                    // 꼬리에 붙은 낱개 숫자 제거 ("1명 2"→"1명")
    .replace(/[·|,\s~]+$/, "").trim();
}
function okPay(v) { return v && /원|만|협의|규정|시급|일당|사례/.test(v) && !/보내기|스북|URL|복사|인쇄/.test(v); }
// 총 보수를 (리허설 N회 + 공연 1회)로 나눈 회당 환산 — 이미 회당/시간당이면 생략
function payPerSession(j) {
  if (!j.rehearsalCount || j.rehearsalCount < 1) return null;
  if (/회당|시간당|일당|시급/.test(j.pay || "")) return null;
  const m = String(j.pay || "").match(/([\d,]+)\s*만/);
  if (!m) return null;
  const total = Number(m[1].replace(/,/g, ""));
  if (!total) return null;
  const per = Math.round(total / (j.rehearsalCount + 1) * 10) / 10;
  return `약 ${per}만원 (총 ${total}만 ÷ 리허설 ${j.rehearsalCount}+공연)`;
}

// 상단 메타 = 사실(기관·지역·마감) + 구조화 필드(형태·모집·자격·일정 …)
function metaRows(j) {
  const st = statusOf(j);
  const dl = j.deadline
    ? `${j.deadline} <span style="color:var(--ink-soft)">(${st.label})</span>`
    : (j.deadlineText === "상시" ? "상시 모집" : (j.src === "공식" ? "기한 미정" : (j.deadlineText || "협의")));
  const rows = [["기관", j.org], ["지역", regionOf(j)], ["마감", dl]];
  const insts = (j.insts || []).join("·");
  const senior = (j.positions || []).filter(p => /수석|악장|차석/.test(p)).join("·");
  if (j.band && j.band !== "기타") rows.push(["형태", j.band]);
  if (j.subject) rows.push(["전공", cleanVal(j.subject)]);   // 대학 교수: 어떤 과목/전공인지
  if (j.courses && j.courses.length) rows.push(["교과목", j.courses.join(", ")]);   // 대학 강사: 담당 과목
  if (j.verifiedNote) rows.push(["✓ 직접 확인", `${cleanVal(j.verifiedNote)}${j.verifiedAt ? ` <span style="color:var(--ink-soft)">(${j.verifiedAt})</span>` : ""}`]);
  if (j.certReq && j.certReq !== "무관") rows.push(["교원자격증", j.certReq === "예" ? "필요" : "불필요"]);
  if (j.degreeReq && j.degreeReq !== "무관") rows.push(["학위 요건", j.degreeReq + " 이상"]);
  if (j.careerReq && j.careerReq !== "미기재") rows.push(["경력", j.careerReq]);
  if (j.recruitSummary) rows.push(["모집", cleanVal(j.recruitSummary)]);
  else if (j.personnel) rows.push(["모집", cleanVal((insts ? insts + " " : "") + j.personnel)]);
  else if (insts) rows.push(["모집", insts + (senior ? " " + senior : "")]);
  // 원문에서 '…경험이 있는 (자)'처럼 관형형에서 잘려온 자격 문구는 '자'를 붙여 문장을 닫는다
  let q = cleanVal(j.qualification);
  if (/(있는|없는|준하는|가능한|갖춘|마친|수료한|졸업한|이수한|전공한|취득한|소지한)$/.test(q)) q += " 자";
  if (q && q.length >= 4) rows.push(["자격", q]);
  const reh = cleanVal(j.rehearsal || j.when);
  if (!j.rehearsalCount && reh && /\d/.test(reh)) rows.push(["리허설", reh]);
  const con = cleanVal(j.concertDate);
  if (con && /\d/.test(con)) rows.push(["연주일", con]);
  if (j.auditionDate) rows.push(["오디션", cleanVal(j.auditionDate)]);
  if (j.contract) rows.push(["계약", cleanVal(j.contract)]);
  if (okPay(j.pay)) rows.push(["페이", cleanVal(j.pay)]);
  // 리허설 횟수 + 회당 환산 (연주자가 시간당 효율로 판단)
  if (j.rehearsalCount) {
    const rw = cleanVal(j.rehearsalWhen || j.when);
    rows.push(["리허설", `${j.rehearsalCount}회${rw ? " · " + rw : ""}`]);
    const pps = payPerSession(j);
    if (pps) rows.push(["회당 환산", pps]);
  }
  // 악기 제공 — 포디엄만의 필드 (특히 타악·건반)
  if (j.instProvided) {
    rows.push(["악기 제공", j.instProvided + (j.instProvidedDetail ? ` — ${cleanVal(j.instProvidedDetail)}` : "")]);
  }
  if (j.setup) rows.push(["셋업/운반", j.setup]);
  if (j.keyboard) rows.push(["건반", j.keyboard]);
  if (j.phone) rows.push(["연락처", `<a href="tel:${j.phone.replace(/-/g, "")}">${j.phone}</a>`]);
  if (j.denomination) rows.push(["교단", cleanVal(j.denomination)]);
  if (j.documents) rows.push(["제출 서류", cleanVal(j.documents)]);
  if (j.program) rows.push(["프로그램", cleanVal(j.program)]);
  // 포털 직접게시글: 지원 연락처를 카드 안에서 바로 노출 (포털로 내보내지 않음)
  if (j.applyEmail) rows.push(["지원 이메일", `<a href="mailto:${j.applyEmail}">${j.applyEmail}</a>`]);
  if (j.applyPhone) rows.push(["지원 전화", `<a href="tel:${j.applyPhone.replace(/-/g, "")}">${j.applyPhone}</a>`]);
  return rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

// 하단 간단 요약: 자유서술 발췌에서 잡음 제거 후 최대 3줄
const EXCERPT_NOISE = /채용 ?비리|비리 ?신고|신고 ?센터|공공기관 채용|청탁|개인정보|저작권|이용약관|고객센터|자주 ?묻는|FAQ|바로가기|로그인|회원가입|단장 ?공개|용역|평가위원|입찰|\.(?:pdf|hwpx?|jpe?g|png|zip)/i;
function shortSummary(j) {
  const tp = (j.title || "").replace(/\s+/g, "").slice(0, 14);
  const segs = (j.bodyExcerpt || "").split(/\s*·\s*/)
    .map(s => cleanVal(s))
    .filter(s => s && s.length >= 6 && !EXCERPT_NOISE.test(s)
      && s.replace(/\s+/g, "").slice(0, 14) !== tp);   // 제목 반복 줄 제거
  return segs.slice(0, 3).join("\n");
}

// ---------- 공식 공고 상세 모달 (요약 + 원문 바로가기) ----------
function openOfficial(key) {
  const j = OFFICIAL_ITEMS.find(x => x.key === key);
  if (!j) return;
  const st = statusOf(j);
  $("#detail-tags").innerHTML = `
    <span class="tag ${TIER_CLS[j.tier] || "cat"}">${j.tier}</span>
    <span class="tag cat">${bandLabel(j.band)}</span>
    ${j.subject && !j.insts.includes(j.subject) ? `<span class="tag inst">${j.subject}</span>` : ""}
    ${j.insts.map(i => `<span class="tag inst">${i}</span>`).join("")}
    ${(j.positions || []).filter(p => /수석|악장|차석/.test(p)).map(p => `<span class="tag pos">${p}</span>`).join("")}
    <span class="tag ${st.cls}">${st.label}</span>
    ${j.isNew ? `<span class="tag urgent">NEW</span>` : ""}`;
  $("#detail-title").textContent = j.title;
  $("#detail-meta").innerHTML = metaRows(j);
  // 하단: 간단한 요약(최대 3줄) — 없으면 비움
  $("#detail-body").textContent = shortSummary(j);
  const act = $("#detail-action");
  // 링크 원칙: 집계 포털(아트인포·아트모아)로는 절대 내보내지 않는다.
  //  - 기관 원문(officialUrl)이 있으면 그 페이지로 이동
  //  - 포털 직접게시글(원문 없음)이면 지원 연락처로 바로 지원 (이메일/전화)
  //  - 그 외 자체 게시판 소스는 수집 URL이 곧 원문이므로 그대로 이동
  // 포털 도메인이면(source든 officialUrl이든) 절대 링크로 내보내지 않는다
  const isAggregator = PORTAL_RE.test(j.source || "");
  const officialOk = j.officialUrl && !PORTAL_RE.test(j.officialUrl);
  if (officialOk) {
    act.textContent = "공식 공고 페이지 바로가기 ↗";
    act.onclick = () => window.open(j.officialUrl, "_blank", "noopener");
    act.style.display = "";
  } else if (isAggregator) {
    // 포털 직접게시글 — 포털로 보내지 않고 연락처로 지원
    if (j.applyEmail) {
      act.textContent = "이메일로 지원 ✉";
      act.onclick = () => window.open(`mailto:${j.applyEmail}`, "_blank");
      act.style.display = "";
    } else if (j.applyPhone) {
      act.textContent = `전화 지원 ☎ ${j.applyPhone}`;
      act.onclick = () => window.open(`tel:${j.applyPhone.replace(/-/g, "")}`, "_blank");
      act.style.display = "";
    } else {
      // 연락처도 원문도 없는 드문 경우 — 포털(수집 URL)로는 절대 내보내지 않는다 (2026-07-23).
      // 링크 없이 검색 안내만 남긴다.
      act.textContent = "기관명으로 검색해 지원하세요";
      act.onclick = null;
      act.style.display = "";
    }
  } else {
    act.textContent = "공고 보러가기 ↗";
    act.onclick = () => window.open(j.url, "_blank", "noopener");
    act.style.display = "";
  }
  $("#detail-modal").classList.add("open");
}

// ---------- 소규모 글 상세 모달 ----------
function openDetail(cid) {
  const j = USER_POSTS.find(x => x.cid === cid) || COMMUNITY_ITEMS.find(x => x.cid === cid);
  if (!j) return;
  if (j.type !== "구인") return;   // v2.0: 종료된 게시판의 레거시 글은 열지 않음 (데이터는 보존)
  $("#detail-tags").innerHTML = `
    ${j.sample ? `<span class="tag sample">예시</span>` : ""}
    ${j.mine ? `<span class="tag mine">내 공고</span>` : ""}
    <span class="tag ${TIER_CLS[j.tier] || "cat"}">${j.tier}</span>
    <span class="tag ${j.type === "구인" ? "type-offer" : "type-seek"}">${j.type}</span>
    <span class="tag cat">${bandLabel(j.band)}</span>
    ${j.insts.map(i => `<span class="tag inst">${i}</span>`).join("")}`;
  $("#detail-title").textContent = j.title;
  $("#detail-meta").innerHTML = metaRows(j) + `<dt>등록일</dt><dd>${j.date}</dd>`;
  $("#detail-body").textContent = j.body || shortSummary(j) || "";
  const act = $("#detail-action");
  // 내가 올린 글이면 삭제 버튼, 연락처 있으면 바로 전화, 아니면 안내
  if (j.mine) {
    act.style.display = "";
    act.textContent = "이 공고 삭제 🗑";
    act.onclick = () => deleteMyPost(j.cid);
  } else if (j.phone) {
    act.style.display = "";
    act.textContent = `전화 연락 ☎ ${j.phone}`;
    act.onclick = () => window.open(`tel:${j.phone.replace(/-/g, "")}`, "_blank");
  } else {
    act.style.display = "";
    act.textContent = "지원하기 / 연락하기";
    act.onclick = () => alert("이 예시 글은 연락처가 없습니다. '＋ 글 올리기'로 직접 등록해 보세요.");
  }
  $("#detail-modal").classList.add("open");
}

// ---------- 글쓰기 ----------
// 글 등록은 스펙 v1 엔진(js/write.js)이 담당 — 스텝 폼·매트릭스·제목 제안·완료 화면

// 내 공고(이 기기에서 올린 것) 삭제
function deleteMyPost(cid) {
  const i = USER_POSTS.findIndex(p => p.cid === cid);
  if (i < 0) return;
  if (!confirm("이 공고를 삭제할까요? (이 기기에서 올린 공고)")) return;
  USER_POSTS.splice(i, 1);
  saveUserPosts();
  $("#detail-modal").classList.remove("open");
  renderAll();
}

// ---------- 초기화 ----------
document.addEventListener("DOMContentLoaded", () => {
  renderAll();
  // 딥링크: 과외 페이지 등에서 jobs.html#post=o<id> 로 진입하면 해당 공고 모달을 바로 연다
  const hm = location.hash.match(/^#post=(.+)$/);
  if (hm) {
    const key = decodeURIComponent(hm[1]);
    if (OFFICIAL_ITEMS.some(j => j.key === key)) openOfficial(key);
    else if (/^c\d+$/.test(key)) openDetail(+key.slice(1));   // 직접 등록 글 공유 링크
  }
  $("#search-input").addEventListener("input", (e) => { state.query = e.target.value.trim(); renderList(); });
  $("#sort-sel").addEventListener("change", (e) => { state.sort = e.target.value; renderList(); });
  $("#filter-reset").addEventListener("click", () => {
    state.tiers.clear(); state.bands.clear(); state.insts.clear(); state.regions.clear(); state.status.clear(); state.provided.clear(); state.obri = false; state.noCert = false; state.noCareer = false;
    state.query = ""; $("#search-input").value = "";
    renderAll();
  });
  $("#btn-write").addEventListener("click", () => {
    $("#write-modal").classList.add("open");
    if (window.PodiumWrite) PodiumWrite.reset();   // 유형 선택부터
  });
  if (sessionStorage.getItem("podium_open_write")) {   // 홈 '공고 올리기' 진입
    sessionStorage.removeItem("podium_open_write");
    $("#btn-write").click();
  }
  document.querySelectorAll(".modal-backdrop").forEach(bd => {
    bd.addEventListener("click", (e) => { if (e.target === bd) bd.classList.remove("open"); });
    bd.querySelector(".modal-close").addEventListener("click", () => bd.classList.remove("open"));
  });
});
