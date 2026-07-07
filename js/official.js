// 공식 채용공고 — 크롤러가 수집한 실제 데이터(data/official-data.js)를 렌더링
const TODAY = new Date().toISOString().slice(0, 10);
const DATA = window.CRAWLED || { collectedAt: "-", okCount: 0, sourceCount: 0, items: [] };

const O_INSTS = ["현악", "목관", "금관", "타악", "건반", "성악", "지휘", "전체"];
const O_REGIONS = ["서울", "경기", "인천", "대전", "대구", "부산", "기타"];
const O_KINDS = ["단원", "직원", "기타"];
const O_STATUS = ["접수중", "마감임박", "확인필요", "마감"];

const oState = { insts: new Set(), regions: new Set(), kinds: new Set(["단원"]), status: new Set(), query: "" };

function statusOf(j) {
  if (!j.deadline) return { key: "확인필요", label: "기한 확인필요", cls: "dd-always", dday: 9998 };
  const diff = Math.round((new Date(j.deadline) - new Date(TODAY)) / 86400000);
  if (diff < 0) return { key: "마감", label: "마감", cls: "dd-closed", dday: 9999 };
  if (diff <= 7) return { key: "마감임박", label: `마감임박 D-${diff}`, cls: "dd-soon", dday: diff };
  return { key: "접수중", label: `접수중 D-${diff}`, cls: "dd-open", dday: diff };
}

const $ = (s) => document.querySelector(s);

function renderOChips(id, items, set) {
  const el = $(id);
  el.innerHTML = items.map(v =>
    `<button class="chip${set.has(v) ? " on" : ""}" data-v="${v}">${v}</button>`
  ).join("");
  el.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const v = chip.dataset.v;
      set.has(v) ? set.delete(v) : set.add(v);
      renderOfficial();
    });
  });
}

function oFiltered() {
  return DATA.items.filter(j => {
    const st = statusOf(j);
    if (oState.insts.size && !oState.insts.has(j.inst)) return false;
    if (oState.regions.size && !oState.regions.has(j.region)) return false;
    if (oState.kinds.size && !oState.kinds.has(j.kind)) return false;
    if (oState.status.size && !oState.status.has(st.key)) return false;
    if (oState.query) {
      const q = oState.query.toLowerCase();
      if (!`${j.org} ${j.title}`.toLowerCase().includes(q)) return false;
    }
    return true;
  }).sort((a, b) => {
    const sa = statusOf(a), sb = statusOf(b);
    if (sa.dday !== sb.dday) return sa.dday - sb.dday;
    return (b.date || b.firstSeen || "").localeCompare(a.date || a.firstSeen || "");
  });
}

function renderOfficial() {
  renderOChips("#filter-inst", O_INSTS, oState.insts);
  renderOChips("#filter-region", O_REGIONS, oState.regions);
  renderOChips("#filter-kind", O_KINDS, oState.kinds);
  renderOChips("#filter-status", O_STATUS, oState.status);

  const newCount = DATA.items.filter(j => j.isNew).length;
  $("#crawl-meta").innerHTML =
    `마지막 수집: <strong>${DATA.collectedAt}</strong> · 기관 ${DATA.okCount}/${DATA.sourceCount} 응답 · 전체 ${DATA.items.length}건` +
    (newCount ? ` <span class="new-badge">신규 ${newCount}건</span>` : "");

  const list = oFiltered();
  $("#result-count").innerHTML = `총 <strong>${list.length}</strong>건 — 카드를 누르면 해당 기관의 원문 공고로 이동합니다`;
  const el = $("#job-list");
  if (!list.length) {
    el.innerHTML = `<div class="empty">조건에 맞는 공고가 없습니다.<br>필터를 조정해 보세요.</div>`;
    return;
  }
  el.innerHTML = list.map(j => {
    const st = statusOf(j);
    return `
    <a class="job-card${st.key === "마감" ? " closed" : ""}" href="${j.url}" target="_blank" rel="noopener" style="display:block">
      <div class="top-row">
        <span class="tag ${st.cls}">${st.label}</span>
        <span class="tag inst">${j.inst}</span>
        <span class="tag pos">${j.kind}</span>
        ${j.isNew ? `<span class="tag urgent">NEW</span>` : ""}
      </div>
      <h3>${j.title}</h3>
      <div class="meta">
        <span>${j.org}</span>
        <span>📍 ${j.region}</span>
        ${j.deadline ? `<span>마감 ${j.deadline}</span>` : ""}
        ${j.date ? `<span>게시 ${j.date}</span>` : ""}
      </div>
      <div class="source-line">
        <span>출처 <span class="src">${j.source}</span></span>
        <span>원문 보기 ↗</span>
      </div>
    </a>`;
  }).join("");
}

document.addEventListener("DOMContentLoaded", () => {
  renderOfficial();

  $("#search-input").addEventListener("input", (e) => {
    oState.query = e.target.value.trim();
    renderOfficial();
  });

  $("#filter-reset").addEventListener("click", () => {
    oState.insts.clear(); oState.regions.clear(); oState.status.clear(); oState.kinds.clear();
    oState.query = "";
    $("#search-input").value = "";
    renderOfficial();
  });
});
