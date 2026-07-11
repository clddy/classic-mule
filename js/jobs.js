// 통합 구인구직 보드 — 공식(크롤링) + 소규모(개인·팀 게시글)
// 날짜는 한국시간(KST) 기준 — toISOString은 UTC라 자정~오전9시에 하루 밀리는 문제 방지
const TODAY = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);

// 집계 포털(매개체) 도메인 — 출처로 표기하지 않고, 링크로도 내보내지 않는다
const PORTAL_RE = /artinfokorea|artmore|hibrain|jobkorea|saramin|albamon|work\.go\.kr\/portal/i;
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
  tier: j.tier || "프로",
  band: KIND2BAND[j.kind] || "기타",
  insts: j.instDetails || [], group: j.inst,
  subject: j.subject,   // 대학 교수 초빙: 전공/과목
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
  date: j.date, body: j.body, urgent: j.urgent, cid: j.id,
  sample: true   // data.js는 '예시' 게시글만 담음 — 카드 옅게 + '예시' 배지
}));

// ---------- 필터 정의 ----------
// 구분: 프로(국공립·직업) / 전공·입시(유스·입시레슨) / 교육·취미(방과후·취미레슨) / 오브리(교회·웨딩·행사)
const TIERS = ["프로", "전공·입시", "교육·취미", "오브리"];
const TIER_CLS = { "프로": "src-official", "전공·입시": "pos", "교육·취미": "dd-open", "오브리": "inst" };
const BANDS = ["단원", "객원·대체", "반주", "행사연주", "강사·레슨", "지휘", "교수", "직원·스태프", "기타"];
const INST_GROUPS = [
  ["현악", ["바이올린", "비올라", "첼로", "더블베이스"]],
  ["목관", ["플루트", "오보에", "클라리넷", "바순"]],
  ["금관", ["호른", "트럼펫", "트롬본", "튜바", "색소폰"]],
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
    ${j.sample ? `<span class="tag sample">예시</span>` : ""}
    <span class="tag ${TIER_CLS[j.tier] || "cat"}">${j.tier}</span>
    ${j.type === "구직" ? `<span class="tag type-seek">구직</span>` : ""}
    <span class="tag cat">${j.band}</span>
    ${j.subject && !j.insts.includes(j.subject) ? `<span class="tag inst">${j.subject}</span>` : ""}
    ${j.insts.map(i => `<span class="tag inst">${i}</span>`).join("")}
    ${(j.positions || []).filter(p => /수석|악장|차석/.test(p)).map(p => `<span class="tag pos">${p}</span>`).join("")}
    <span class="tag ${st.cls}">${st.label}</span>
    ${j.urgent ? `<span class="tag urgent">급구</span>` : ""}
    ${j.isNew ? `<span class="tag urgent">NEW</span>` : ""}`;
  const region = j.region && j.region !== "기타" ? `<span>${j.region}</span>` : "";
  const pay = okPay(j.pay) ? `<span class="pay">${cleanVal(j.pay)}</span>` : "";
  const meta = `
    <span>${j.org}</span>
    ${region}
    ${j.when ? `<span>${j.when}</span>` : ""}
    ${pay}
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
      <div class="source-line"><span>${sourceLabel(j) ? `출처 <span class="src">${sourceLabel(j)}</span>` : ""}</span><span>눌러서 상세보기</span></div>
    </article>`;
  }
  return `
    <article class="job-card${st.key === "마감" ? " closed" : ""}${j.sample ? " is-sample" : ""}" data-cid="${j.cid}">
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

// 상단 메타 = 사실(기관·지역·마감) + 구조화 필드(형태·모집·자격·일정 …)
function metaRows(j) {
  const st = statusOf(j);
  const dl = j.deadline
    ? `${j.deadline} <span style="color:var(--ink-soft)">(${st.label})</span>`
    : (j.deadlineText === "상시" ? "상시 모집" : (j.src === "공식" ? "기한 확인필요" : (j.deadlineText || "협의")));
  const rows = [["기관", j.org], ["지역", j.region], ["마감", dl]];
  const insts = (j.insts || []).join("·");
  const senior = (j.positions || []).filter(p => /수석|악장|차석/.test(p)).join("·");
  if (j.band && j.band !== "기타") rows.push(["형태", j.band]);
  if (j.subject) rows.push(["전공", cleanVal(j.subject)]);   // 대학 교수: 어떤 과목/전공인지
  if (j.recruitSummary) rows.push(["모집", cleanVal(j.recruitSummary)]);
  else if (j.personnel) rows.push(["모집", cleanVal((insts ? insts + " " : "") + j.personnel)]);
  else if (insts) rows.push(["모집", insts + (senior ? " " + senior : "")]);
  const q = cleanVal(j.qualification);
  if (q && q.length >= 4) rows.push(["자격", q]);
  const reh = cleanVal(j.rehearsal || j.when);
  if (reh && /\d/.test(reh)) rows.push(["리허설", reh]);
  const con = cleanVal(j.concertDate);
  if (con && /\d/.test(con)) rows.push(["연주일", con]);
  if (j.auditionDate) rows.push(["오디션", cleanVal(j.auditionDate)]);
  if (j.contract) rows.push(["계약", cleanVal(j.contract)]);
  if (okPay(j.pay)) rows.push(["페이", cleanVal(j.pay)]);
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
    <span class="tag cat">${j.band}</span>
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
      // 연락처를 못 뽑은 드문 경우 — 링크 없이 안내만 (포털行 방지)
      act.style.display = "none";
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
  const j = COMMUNITY_ITEMS.find(x => x.cid === cid);
  if (!j) return;
  $("#detail-tags").innerHTML = `
    ${j.sample ? `<span class="tag sample">예시</span>` : ""}
    <span class="tag ${TIER_CLS[j.tier] || "cat"}">${j.tier}</span>
    <span class="tag ${j.type === "구인" ? "type-offer" : "type-seek"}">${j.type}</span>
    <span class="tag cat">${j.band}</span>
    ${j.insts.map(i => `<span class="tag inst">${i}</span>`).join("")}
    ${j.urgent ? `<span class="tag urgent">급구</span>` : ""}`;
  $("#detail-title").textContent = j.title;
  $("#detail-meta").innerHTML = metaRows(j) + `<dt>등록일</dt><dd>${j.date}</dd>`;
  $("#detail-body").textContent = j.body || shortSummary(j) || "";
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
