// 구인구직 보드 로직
const state = {
  type: "offer",      // offer(구인) | seek(구직)
  cats: new Set(),
  insts: new Set(),
  regions: new Set(),
  query: ""
};

let jobs = [...JOBS];

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ---------- 필터 칩 렌더 ----------
function renderChips(containerId, items, set) {
  const el = $(containerId);
  el.innerHTML = items.map(v =>
    `<button class="chip${set.has(v) ? " on" : ""}" data-v="${v}">${v}</button>`
  ).join("");
  el.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const v = chip.dataset.v;
      set.has(v) ? set.delete(v) : set.add(v);
      renderAll();
    });
  });
}

// ---------- 목록 렌더 ----------
function filtered() {
  return jobs.filter(j => {
    if (j.type !== state.type) return false;
    if (state.cats.size && !state.cats.has(j.cat)) return false;
    if (state.insts.size && !state.insts.has(j.inst)) return false;
    if (state.regions.size && !state.regions.has(j.region)) return false;
    if (state.query) {
      const q = state.query.toLowerCase();
      const hay = `${j.title} ${j.org} ${j.instDetail} ${j.body}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }).sort((a, b) => b.date.localeCompare(a.date));
}

function jobCardHTML(j) {
  return `
    <article class="job-card" data-id="${j.id}">
      <div class="top-row">
        <span class="tag ${j.type === "offer" ? "type-offer" : "type-seek"}">${j.type === "offer" ? "구인" : "구직"}</span>
        <span class="tag cat">${j.cat}</span>
        <span class="tag inst">${j.instDetail}</span>
        ${j.urgent ? `<span class="tag urgent">급구</span>` : ""}
      </div>
      <h3>${j.title}</h3>
      <div class="meta">
        <span>${j.org}</span>
        <span>📍 ${j.region}</span>
        <span class="pay">${j.pay}</span>
        <span>마감 ${j.deadline}</span>
      </div>
    </article>`;
}

function renderList() {
  const list = filtered();
  $("#result-count").innerHTML = `총 <strong>${list.length}</strong>건`;
  const listEl = $("#job-list");
  if (!list.length) {
    listEl.innerHTML = `<div class="empty">조건에 맞는 공고가 없습니다.<br>필터를 조정해 보세요.</div>`;
    return;
  }
  listEl.innerHTML = list.map(jobCardHTML).join("");
  listEl.querySelectorAll(".job-card").forEach(card => {
    card.addEventListener("click", () => openDetail(+card.dataset.id));
  });
}

function renderTabs() {
  const offerCount = jobs.filter(j => j.type === "offer").length;
  const seekCount = jobs.filter(j => j.type === "seek").length;
  $("#tab-offer").innerHTML = `구인 <span class="count">${offerCount}</span>`;
  $("#tab-seek").innerHTML = `구직 <span class="count">${seekCount}</span>`;
  $("#tab-offer").classList.toggle("active", state.type === "offer");
  $("#tab-seek").classList.toggle("active", state.type === "seek");
}

function renderAll() {
  renderTabs();
  renderChips("#filter-cat", CATS, state.cats);
  renderChips("#filter-inst", INSTS, state.insts);
  renderChips("#filter-region", REGIONS, state.regions);
  renderList();
}

// ---------- 상세 모달 ----------
function openDetail(id) {
  const j = jobs.find(x => x.id === id);
  if (!j) return;
  $("#detail-tags").innerHTML = `
    <span class="tag ${j.type === "offer" ? "type-offer" : "type-seek"}">${j.type === "offer" ? "구인" : "구직"}</span>
    <span class="tag cat">${j.cat}</span>
    <span class="tag inst">${j.instDetail}</span>
    ${j.urgent ? `<span class="tag urgent">급구</span>` : ""}`;
  $("#detail-title").textContent = j.title;
  $("#detail-meta").innerHTML = `
    <dt>${j.type === "offer" ? "기관/팀" : "이름"}</dt><dd>${j.org}</dd>
    <dt>지역</dt><dd>${j.region}</dd>
    <dt>보수</dt><dd>${j.pay}</dd>
    <dt>마감</dt><dd>${j.deadline}</dd>
    <dt>등록일</dt><dd>${j.date}</dd>`;
  $("#detail-body").textContent = j.body;
  $("#detail-modal").classList.add("open");
}

// ---------- 글쓰기 모달 ----------
function openWrite() {
  $("#write-modal").classList.add("open");
}

function submitWrite(e) {
  e.preventDefault();
  const f = e.target;
  const newJob = {
    id: Math.max(...jobs.map(j => j.id)) + 1,
    type: f.elements["w-type"].value,
    cat: f.elements["w-cat"].value,
    inst: f.elements["w-inst"].value,
    instDetail: f.elements["w-instDetail"].value || f.elements["w-inst"].value,
    title: f.elements["w-title"].value,
    org: f.elements["w-org"].value,
    region: f.elements["w-region"].value,
    pay: f.elements["w-pay"].value || "협의",
    date: "2026-07-07",
    deadline: f.elements["w-deadline"].value || "상시",
    urgent: f.elements["w-urgent"].checked,
    body: f.elements["w-body"].value
  };
  jobs.unshift(newJob);
  state.type = newJob.type;
  f.reset();
  $("#write-modal").classList.remove("open");
  renderAll();
  openDetail(newJob.id);
}

// ---------- 초기화 ----------
document.addEventListener("DOMContentLoaded", () => {
  renderAll();

  $("#tab-offer").addEventListener("click", () => { state.type = "offer"; renderAll(); });
  $("#tab-seek").addEventListener("click", () => { state.type = "seek"; renderAll(); });

  $("#search-input").addEventListener("input", (e) => {
    state.query = e.target.value.trim();
    renderList();
  });

  $("#filter-reset").addEventListener("click", () => {
    state.cats.clear(); state.insts.clear(); state.regions.clear();
    state.query = "";
    $("#search-input").value = "";
    renderAll();
  });

  $("#btn-write").addEventListener("click", openWrite);
  $("#write-form").addEventListener("submit", submitWrite);

  $$(".modal-backdrop").forEach(bd => {
    bd.addEventListener("click", (e) => { if (e.target === bd) bd.classList.remove("open"); });
    bd.querySelector(".modal-close").addEventListener("click", () => bd.classList.remove("open"));
  });
});
