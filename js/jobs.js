// 통합 구인구직 보드 — 공식(크롤링) + 소규모(개인·팀 게시글)
// 날짜는 한국시간(KST) 기준 — toISOString은 UTC라 자정~오전9시에 하루 밀리는 문제 방지
const TODAY = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);

// ---------- 데이터 병합 ----------
const CAT2BAND = {
  "객원/대타": "객원·대체", "단원모집": "단원", "반주": "반주",
  "행사연주": "행사연주", "강사/레슨": "강사·레슨", "지휘/음악감독": "지휘"
};
const KIND2BAND = { "단원": "단원", "객원·대체": "객원·대체", "반주": "반주", "강사": "강사·레슨", "직원": "직원·스태프", "기타": "기타" };

const OFFICIAL_ITEMS = ((window.CRAWLED && window.CRAWLED.items) || []).map(j => ({
  key: "o" + j.id, src: "공식", type: "구인",
  tier: j.tier || "프로",
  band: KIND2BAND[j.kind] || "기타",
  insts: j.instDetails || [], group: j.inst,
  region: j.region, title: j.title, org: j.org,
  deadline: j.deadline, deadlineText: j.deadlineNote, date: j.date || j.firstSeen,
  personnel: j.personnel, qualification: j.qualification, contract: j.contract, pay: j.pay,
  auditionDate: j.auditionDate, rehearsal: j.rehearsal, concertDate: j.concertDate, program: j.program,
  positions: j.positions, recruitSummary: j.recruitSummary, bodyExcerpt: j.bodyExcerpt,
  url: j.url, officialUrl: j.officialUrl, isNew: j.isNew, source: j.source
}));

let COMMUNITY_ITEMS = JOBS.map(j => ({
  key: "c" + j.id, src: "소규모", type: j.type === "offer" ? "구인" : "구직",
  tier: j.tier || "프로",
  band: CAT2BAND[j.cat] || "기타",
  insts: j.instDetails || [j.instDetail], group: j.inst,
  region: j.region, title: j.title, org: j.org, pay: j.pay,
  when: j.when, program: j.program,
  personnel: j.personnel, qualification: j.qualification, contract: j.contract,
  auditionDate: j.auditionDate, rehearsal: j.rehearsal, concertDate: j.concertDate,
  positions: j.positions, recruitSummary: j.recruitSummary,
  deadline: /^\d{4}/.test(j.deadline) ? j.deadline : null, deadlineText: j.deadline,
  date: j.date, body: j.body, urgent: j.urgent, cid: j.id
}));

// ---------- 필터 정의 ----------
// 구분: 프로(국공립·직업) / 전공·입시(유스·입시레슨) / 교육·취미(방과후·취미레슨) / 오브리(교회·웨딩·행사)
const TIERS = ["프로", "전공·입시", "교육·취미", "오브리"];
const TIER_CLS = { "프로": "src-official", "전공·입시": "pos", "교육·취미": "dd-open", "오브리": "inst" };
const BANDS = ["단원", "객원·대체", "반주", "행사연주", "강사·레슨", "지휘", "직원·스태프", "기타"];
const INST_GROUPS = [
  ["현악", ["바이올린", "비올라", "첼로", "더블베이스"]],
  ["목관", ["플루트", "오보에", "클라리넷", "바순"]],
  ["금관", ["호른", "트럼펫", "트롬본", "튜바"]],
  ["기타", ["타악", "피아노", "하프", "지휘"]],
  ["성악", ["소프라노", "메조소프라노", "알토", "테너", "바리톤", "베이스(성악)"]],
];
const REGION_LIST = ["서울", "경기", "인천", "대전", "대구", "부산", "기타"];
const STATUSES = ["접수중", "마감임박", "확인필요", "마감"];

const state = { tab: "전체", tiers: new Set(), bands: new Set(), insts: new Set(), regions: new Set(), status: new Set(), query: "", sort: "deadline" };
const $ = (s) => document.querySelector(s);

function statusOf(j) {
  if (!j.deadline) {
    if (j.deadlineText === "상시") return { key: "접수중", label: "상시", cls: "dd-open", dday: 9000 };
    return { key: "확인필요", label: "기한 확인필요", cls: "dd-always", dday: 9998 };
  }
  const diff = Math.round((new Date(j.deadline) - new Date(TODAY)) / 86400000);
  if (diff < 0) return { key: "마감", label: "마감", cls: "dd-closed", dday: 9999 };
  if (diff <= 7) return { key: "마감임박", label: `마감임박 D-${diff}`, cls: "dd-soon", dday: diff };
  return { key: "접수중", label: `접수중 D-${diff}`, cls: "dd-open", dday: diff };
}

// ---------- 칩 렌더 ----------
function renderChips(sel, items, set) {
  const el = $(sel);
  el.innerHTML = items.map(v => `<button class="chip${set.has(v) ? " on" : ""}" data-v="${v}">${v}</button>`).join("");
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
function filtered() {
  const all = [...OFFICIAL_ITEMS, ...COMMUNITY_ITEMS];
  return all.filter(j => {
    if (state.tab !== "전체" && j.type !== state.tab) return false;
    if (state.tiers.size && !state.tiers.has(j.tier)) return false;
    if (state.bands.size && !state.bands.has(j.band)) return false;
    if (state.insts.size) {
      if (!j.insts.length || ![...state.insts].some(v => j.insts.includes(v))) return false;
    }
    if (state.regions.size && !state.regions.has(j.region)) return false;
    if (state.status.size && !state.status.has(statusOf(j).key)) return false;
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
const byDeadline = (a, b) => {
  const sa = statusOf(a), sb = statusOf(b);
  if (sa.dday !== sb.dday) return sa.dday - sb.dday;
  return (b.date || "").localeCompare(a.date || "");
};
const sortFns = {
  deadline: byDeadline,
  pay: (a, b) => (payNum(b) - payNum(a)) || byDeadline(a, b),
  concert: (a, b) => (concertNum(a) - concertNum(b)) || byDeadline(a, b),
};

function cardHTML(j) {
  const st = statusOf(j);
  const tags = `
    <span class="tag ${TIER_CLS[j.tier] || "cat"}">${j.tier}</span>
    ${j.type === "구직" ? `<span class="tag type-seek">구직</span>` : ""}
    <span class="tag cat">${j.band}</span>
    ${j.insts.map(i => `<span class="tag inst">${i}</span>`).join("")}
    ${(j.positions || []).filter(p => /수석|악장|차석/.test(p)).map(p => `<span class="tag pos">${p}</span>`).join("")}
    <span class="tag ${st.cls}">${st.label}</span>
    ${j.urgent ? `<span class="tag urgent">급구</span>` : ""}
    ${j.isNew ? `<span class="tag urgent">NEW</span>` : ""}`;
  const meta = `
    <span>${j.org}</span>
    <span>${j.region}</span>
    ${j.when ? `<span>${j.when}</span>` : ""}
    ${j.pay ? `<span class="pay">${j.pay}</span>` : ""}
    ${j.deadline ? `<span>마감 ${j.deadline}</span>` : ""}`;
  // 객원·대체는 프로그램(연주곡)을 카드에 노출 (동생 피드백)
  const program = j.program
    ? `<div class="program-line"><b>연주곡</b>${j.program}</div>` : "";
  if (j.src === "공식") {
    return `
    <article class="job-card${st.key === "마감" ? " closed" : ""}" data-okey="${j.key}">
      <div class="top-row">${tags}</div>
      <h3>${j.title}</h3>
      ${program}
      <div class="meta">${meta}</div>
      <div class="source-line"><span>출처 <span class="src">${j.source}</span></span><span>눌러서 상세 · 원문 보기</span></div>
    </article>`;
  }
  return `
    <article class="job-card${st.key === "마감" ? " closed" : ""}" data-cid="${j.cid}">
      <div class="top-row">${tags}</div>
      <h3>${j.title}</h3>
      ${program}
      <div class="meta">${meta}</div>
    </article>`;
}

function renderList() {
  const list = filtered();
  const oc = list.filter(x => x.src === "공식").length;
  $("#result-count").innerHTML = `총 <strong>${list.length}</strong>건 (공식 ${oc} · 소규모 ${list.length - oc}) — 카드를 누르면 요약과 원문 링크가 열립니다`;
  const el = $("#job-list");
  if (!list.length) {
    el.innerHTML = `<div class="empty">조건에 맞는 공고가 없습니다.<br>필터를 조정해 보세요.</div>`;
    return;
  }
  el.innerHTML = list.map(cardHTML).join("");
  el.querySelectorAll(".job-card[data-cid]").forEach(card => {
    card.addEventListener("click", () => openDetail(+card.dataset.cid));
  });
  el.querySelectorAll(".job-card[data-okey]").forEach(card => {
    card.addEventListener("click", () => openOfficial(card.dataset.okey));
  });
}

function renderTabs() {
  ["전체", "구인", "구직"].forEach(t => {
    $(`#tab-${t}`).classList.toggle("active", state.tab === t);
  });
  const all = [...OFFICIAL_ITEMS, ...COMMUNITY_ITEMS];
  $("#tab-전체").innerHTML = `전체 <span class="count">${all.length}</span>`;
  $("#tab-구인").innerHTML = `구인 <span class="count">${all.filter(x => x.type === "구인").length}</span>`;
  $("#tab-구직").innerHTML = `구직 <span class="count">${all.filter(x => x.type === "구직").length}</span>`;
}

function renderAll() {
  renderTabs();
  renderChips("#filter-tier", TIERS, state.tiers);
  renderChips("#filter-band", BANDS, state.bands);
  renderInstChips();
  renderChips("#filter-region", REGION_LIST, state.regions);
  renderChips("#filter-status", STATUSES, state.status);
  renderList();
}

// ---------- 유형별 요약 필드 (단원 vs 객원 구분) ----------
// 단원(정규): 모집인원·자격·계약기간·오디션 (프로그램 없음)
// 객원·대체: 모집인원·자격·리허설·연주일·페이·프로그램
function metaRows(j) {
  const st = statusOf(j);
  const rows = [];
  rows.push(["기관", j.org]);
  rows.push(["지역", j.region]);
  const dl = j.deadline
    ? `${j.deadline} <span style="color:var(--ink-soft)">(${st.label})</span>`
    : (j.deadlineText === "상시" ? "상시 모집" : (j.src === "공식" ? "원문에서 확인" : (j.deadlineText || "협의")));
  rows.push(["마감", dl]);
  // 모집 인원 (표 요약이 있으면 직책·인원이 함께 담김)
  if (j.recruitSummary) rows.push(["모집 인원", j.recruitSummary]);
  else if (j.personnel) rows.push(["모집 인원", j.personnel]);
  // 직책 — 수석류(수석·부수석·차석·악장)만 표기, 일반 단원·튜티는 생략
  if (j.positions && j.positions.length && !j.recruitSummary) {
    const senior = j.positions.filter(p => /수석|악장|차석/.test(p));
    if (senior.length) rows.push(["직책", senior.join(" · ")]);
  }
  if (j.qualification) rows.push(["자격", j.qualification]);
  if (j.band === "객원·대체") {
    if (j.rehearsal || j.when) rows.push(["리허설", j.rehearsal || j.when]);
    if (j.concertDate) rows.push(["연주일", j.concertDate]);
    if (j.pay) rows.push(["페이", j.pay]);
    if (j.program) rows.push(["프로그램", j.program]);
  } else if (j.band === "단원") {
    if (j.contract) rows.push(["계약기간", j.contract]);
    if (j.auditionDate) rows.push(["오디션", j.auditionDate]);
    if (j.pay && j.src !== "공식") rows.push(["보수", j.pay]);
  } else {
    if (j.when) rows.push(["일시", j.when]);
    if (j.pay) rows.push(["보수", j.pay]);
    if (j.program) rows.push(["프로그램", j.program]);
  }
  return rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

// 기관 페이지 배너·타 게시물 잡음 (요약에서 제거)
const EXCERPT_NOISE = /채용 ?비리|비리 ?신고|신고 ?센터|공공기관 채용|청탁|개인정보|저작권|이용약관|고객센터|자주 ?묻는|FAQ|바로가기|로그인|회원가입|단장 ?공개|용역|평가위원|입찰/;

// 요약 발췌를 '리드 문장 + · 불릿' 형태로 정리 (줄줄이 나열·잡음 제거)
function fmtExcerpt(ex) {
  const segs = (ex || "").split(/\s*·\s*/)
    .map(s => s.trim()).filter(s => s && !EXCERPT_NOISE.test(s));
  if (!segs.length) return "";
  if (segs.length === 1) return segs[0];
  const [lead, ...rest] = segs;
  return lead + "\n\n" + rest.map(s => "· " + s).join("\n");
}

// ---------- 공식 공고 상세 모달 (요약 + 원문 바로가기) ----------
function openOfficial(key) {
  const j = OFFICIAL_ITEMS.find(x => x.key === key);
  if (!j) return;
  const st = statusOf(j);
  $("#detail-tags").innerHTML = `
    <span class="tag ${TIER_CLS[j.tier] || "cat"}">${j.tier}</span>
    <span class="tag cat">${j.band}</span>
    ${j.insts.map(i => `<span class="tag inst">${i}</span>`).join("")}
    ${(j.positions || []).filter(p => /수석|악장|차석/.test(p)).map(p => `<span class="tag pos">${p}</span>`).join("")}
    <span class="tag ${st.cls}">${st.label}</span>
    ${j.isNew ? `<span class="tag urgent">NEW</span>` : ""}`;
  $("#detail-title").textContent = j.title;
  // 포털(아트모아·아트인포) 항목은 원문(officialUrl)으로만 연결 — 포털로는 절대 링크하지 않음
  const isPortal = /artmore\.kr|artinfokorea\.com/.test(j.source || "");
  const target = j.officialUrl || (isPortal ? null : j.url);
  let host = "";
  try { if (target) host = new URL(target).hostname.replace(/^www\./, ""); } catch (e) {}
  $("#detail-meta").innerHTML = metaRows(j) +
    `<dt>수집 출처</dt><dd>${j.source}${j.officialUrl ? ` → 원문: <b>${host}</b>` : ""}</dd>`;
  // 본문 요약 (잡음 제거 후) + 항상 동일한 안내 문구로 통일
  const ex = fmtExcerpt(j.bodyExcerpt);
  $("#detail-body").textContent = ex
    ? ex + "\n\n— 상세 요강은 원문에서 확인하세요."
    : "상세 요강은 원문에서 확인하세요.";
  const act = $("#detail-action");
  if (target) {
    act.textContent = j.officialUrl ? "공식 공고 페이지 바로가기 ↗" : "공고 원문 바로가기 ↗";
    act.onclick = () => window.open(target, "_blank", "noopener");
    act.style.display = "";
  } else {
    // 포털 항목인데 원문 링크를 못 찾음 → 포털로 보내지 않음
    act.style.display = "none";
    $("#detail-body").textContent = "이 공고는 포털에서 수집됐고 원문 링크를 확인 중입니다. 기관명으로 검색해 공식 공고를 확인해 주세요.";
  }
  $("#detail-modal").classList.add("open");
}

// ---------- 소규모 글 상세 모달 ----------
function openDetail(cid) {
  const j = COMMUNITY_ITEMS.find(x => x.cid === cid);
  if (!j) return;
  $("#detail-tags").innerHTML = `
    <span class="tag ${TIER_CLS[j.tier] || "cat"}">${j.tier}</span>
    <span class="tag ${j.type === "구인" ? "type-offer" : "type-seek"}">${j.type}</span>
    <span class="tag cat">${j.band}</span>
    ${j.insts.map(i => `<span class="tag inst">${i}</span>`).join("")}
    ${j.urgent ? `<span class="tag urgent">급구</span>` : ""}`;
  $("#detail-title").textContent = j.title;
  $("#detail-meta").innerHTML = metaRows(j) + `<dt>등록일</dt><dd>${j.date}</dd>`;
  $("#detail-body").textContent = j.body || "";
  const act = $("#detail-action");
  act.style.display = "";
  act.textContent = "지원하기 / 연락하기";
  act.onclick = () => alert("지원/연락 기능은 프로토타입에서 제공되지 않습니다.");
  $("#detail-modal").classList.add("open");
}

// ---------- 글쓰기 ----------
function submitWrite(e) {
  e.preventDefault();
  const f = e.target;
  const cid = Math.max(0, ...COMMUNITY_ITEMS.map(j => j.cid)) + 1;
  const inst = f.elements["w-instDetail"].value.trim() || f.elements["w-inst"].value;
  const item = {
    key: "c" + cid, cid, src: "소규모",
    type: f.elements["w-type"].value === "offer" ? "구인" : "구직",
    tier: f.elements["w-tier"].value,
    band: CAT2BAND[f.elements["w-cat"].value] || "기타",
    insts: [inst], group: f.elements["w-inst"].value,
    when: f.elements["w-when"].value || null,
    program: f.elements["w-program"].value || null,
    personnel: f.elements["w-personnel"].value || null,
    qualification: f.elements["w-qual"].value || null,
    region: f.elements["w-region"].value,
    title: f.elements["w-title"].value,
    org: f.elements["w-org"].value,
    pay: f.elements["w-pay"].value || "협의",
    deadline: f.elements["w-deadline"].value || null,
    deadlineText: f.elements["w-deadline"].value || "상시",
    date: TODAY, body: f.elements["w-body"].value,
    urgent: f.elements["w-urgent"].checked
  };
  COMMUNITY_ITEMS.unshift(item);
  f.reset();
  $("#write-modal").classList.remove("open");
  state.tab = item.type;
  renderAll();
  openDetail(cid);
}

// ---------- 초기화 ----------
document.addEventListener("DOMContentLoaded", () => {
  renderAll();
  ["전체", "구인", "구직"].forEach(t => {
    $(`#tab-${t}`).addEventListener("click", () => { state.tab = t; renderAll(); });
  });
  $("#search-input").addEventListener("input", (e) => { state.query = e.target.value.trim(); renderList(); });
  $("#sort-sel").addEventListener("change", (e) => { state.sort = e.target.value; renderList(); });
  $("#filter-reset").addEventListener("click", () => {
    state.tiers.clear(); state.bands.clear(); state.insts.clear(); state.regions.clear(); state.status.clear();
    state.query = ""; $("#search-input").value = "";
    renderAll();
  });
  $("#btn-write").addEventListener("click", () => $("#write-modal").classList.add("open"));
  $("#write-form").addEventListener("submit", submitWrite);
  document.querySelectorAll(".modal-backdrop").forEach(bd => {
    bd.addEventListener("click", (e) => { if (e.target === bd) bd.classList.remove("open"); });
    bd.querySelector(".modal-close").addEventListener("click", () => bd.classList.remove("open"));
  });
});
