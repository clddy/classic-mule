// 등록 폼 스펙 v1 엔진 — Step(구분→유형→폼) · 유형별 필수/선택 매트릭스 · 구조화 보수 ·
// 제목 자동 제안 · 등록 직후 미리보기+공유. jobs.js 뒤에 로드 (USER_POSTS·cardHTML 등 사용).
(function () {
  const $ = s => document.querySelector(s);
  const form = $("#write-form");
  if (!form) return;
  const blockOf = f => document.querySelector(`.wf[data-f="${f}"]`);

  // ---------- 유형별 매트릭스 (스펙 표 그대로 — 필수 개수 늘리는 변경은 원칙적으로 거부) ----------
  const COMMON_REQ = ["title", "region", "org", "contact"];   // 구직은 region 대신 seekRegions
  const M = {
    "연주":            { req: ["cat", "instr", "when", "pay", "rehearsal"], opt: ["regular", "deadline", "program", "personnel", "urgent", "body"] },
    "오브리":          { req: ["cat", "instr", "regular", "when", "pay"],   opt: ["rehearsal", "urgent", "body"] },
    "교육 — 대학":     { req: ["cat", "deadline", "degree", "applyLink"],  opt: ["instr", "pay", "career", "personnel", "body"] },
    "교육 — 입시·전공": { req: ["instr", "pay"], opt: ["when", "career", "deadline", "body"] },
    "교육 — 취미·입문": { req: ["instr", "pay"], opt: ["when", "career", "deadline", "cert", "body"] },
    "구직":            { req: ["seekInstr", "seekTypes", "seekRegions"],   opt: ["seekEdu", "seekCareer", "seekWhen", "pay", "body"] },
  };
  const CATS = {
    "연주": [["객원/대타", "객원·대타"], ["단원모집", "단원"], ["행사연주", "행사연주"], ["반주", "반주"]],
    "오브리": [["반주", "반주"], ["솔리스트", "솔리스트"], ["지휘/음악감독", "지휘"], ["기타포지션", "그 외 포지션"]],
    "교육 — 대학": [["교수", "교수"], ["겸임교수", "겸임교수"], ["시간강사", "시간강사"]],
  };
  // 블록별 대표 입력(필수 판정 기준)
  const PRIMARY = { title: "w-title", region: "w-region", org: "w-org", cat: "w-cat", instr: "w-inst",
                    when: "w-when", regular: "w-regular", rehearsal: "w-rehearsalCount", deadline: "w-deadline",
                    degree: "w-degree", applyLink: "w-applyLink" };

  let kind = "offer", wtype = null;   // kind: offer/seek · wtype: 매트릭스 키

  // ---------- 스텝 전환 ----------
  const steps = { 1: $("#ws-1"), 2: $("#ws-2") };
  function showStep(n) {
    steps[1].style.display = n === 1 ? "" : "none";
    steps[2].style.display = n === 2 ? "" : "none";
    form.style.display = n === 3 ? "" : "none";
    $("#write-done").style.display = "none";
    $("#write-head").textContent =
      n === 1 ? "글 올리기 — 어떤 글인가요?" :
      n === 2 ? "글 올리기 — 유형 선택" :
      kind === "seek" ? "구직 프로필 올리기" : `구인 — ${wtype}`;
  }
  window.PodiumWrite = { reset: () => showStep(1) };

  document.querySelectorAll("#ws-1 .ws-big").forEach(b => b.addEventListener("click", () => {
    kind = b.dataset.kind;
    if (kind === "seek") { wtype = "구직"; buildForm(); showStep(3); }
    else showStep(2);
  }));
  document.querySelectorAll("#ws-2 .ws-big").forEach(b => b.addEventListener("click", () => {
    wtype = b.dataset.wtype; buildForm(); showStep(3);
  }));
  $("#ws-back1").addEventListener("click", () => showStep(1));
  $("#ws-back2").addEventListener("click", () => showStep(kind === "seek" ? 1 : 2));

  // ---------- 폼 조립 — 블록을 필수/상세 컨테이너로 이동 (입력값은 노드 이동으로 자연 보존) ----------
  function buildForm() {
    const m = M[wtype];
    const req = $("#wf-req"), opt = $("#wf-opt-body"), pool = $("#wf-pool");
    // 모든 블록을 일단 풀로 회수
    document.querySelectorAll(".wf").forEach(el => pool.appendChild(el));
    const commons = wtype === "구직" ? ["title", "org", "contact"] : COMMON_REQ;
    for (const f of [...commons.slice(0, 1), ...(m.req.includes("cat") ? [] : []), ...commons.slice(1)]) req.appendChild(blockOf(f));
    for (const f of m.req) req.appendChild(blockOf(f));
    for (const f of m.opt) opt.appendChild(blockOf(f));
    // 라벨·옵션 유형별 스왑
    if (CATS[wtype]) {
      $("#cat-label").textContent = wtype === "오브리" ? "포지션" : "분야";
      form.elements["w-cat"].innerHTML = CATS[wtype].map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
    }
    $("#pay-label").textContent = wtype === "오브리" ? "사례비" : (wtype === "구직" ? "희망 보수" : "보수");
    $("#instr-label").textContent = /입시|취미/.test(wtype) ? "과목 (악기군)" : (wtype === "교육 — 대학" ? "전공 분야" : "악기군");
    $("#when-label").textContent = /교육/.test(wtype) ? "요일·시간" : "일시 (연주·근무일)";
    $("#org-label").textContent = wtype === "구직" ? "이름/활동명" : "게시자명 (기관/팀명 또는 이름)";
    // 풀(#wf-pool)은 form 밖이라 미사용 블록의 input은 form.elements에 없다 — 반드시 가드
    if (form.elements["w-when"])
      form.elements["w-when"].placeholder = wtype === "오브리" ? "예: 7/20(일) 1·2부 예배 / 매주 일요일" : (/교육/.test(wtype) ? "예: 주 2회, 평일 오후 협의" : "예: 7/24(금) 저녁 공연");
    $("#deadline-hint").style.display = wtype === "교육 — 대학" ? "none" : "";
    updateProvided(); validate();
  }

  // 악기 제공 세트 — 연주(타악·건반)·오브리(건반)일 때만 필수 영역에 등장
  function updateProvided() {
    const g = form.elements["w-inst"] ? form.elements["w-inst"].value : "";
    const need = (wtype === "연주" && (g === "타악" || g === "건반")) || (wtype === "오브리" && g === "건반");
    const blk = blockOf("provided");
    if (need) { $("#wf-req").appendChild(blk); }
    else if (blk.parentElement !== $("#wf-pool")) $("#wf-pool").appendChild(blk);
    $("#prov-perc").style.display = g === "타악" ? "" : "none";
    $("#prov-key").style.display = g === "건반" ? "" : "none";
    $("#prov-detail").style.display = g === "타악" ? "" : "none";
  }

  // ---------- 검증: 필수 미입력 시에만 등록 비활성 ----------
  const val = n => (form.elements[n] ? String(form.elements[n].value).trim() : "");
  const checked = n => [...form.querySelectorAll(`input[name="${n}"]:checked`)].map(i => i.value);
  function validate() {
    const m = M[wtype] || { req: [] };
    let ok = !!val("w-title") && !!val("w-org");
    if (wtype !== "구직") ok = ok && !!val("w-region");
    ok = ok && !!(val("w-phone") || val("w-email") || val("w-chat"));          // 연락 ≥1
    if (form.elements["w-urgent"] && form.elements["w-urgent"].checked && !val("w-phone")) ok = false;  // 급구→전화
    for (const f of m.req) {
      if (f === "pay") ok = ok && (form.elements["w-pay-nego"].checked || !!val("w-pay-amt"));
      else if (f === "seekInstr") ok = ok && checked("ws-i").length > 0;
      else if (f === "seekTypes") ok = ok && checked("ws-t").length > 0;
      else if (f === "seekRegions") ok = ok && checked("ws-r").length > 0;
      else if (PRIMARY[f]) ok = ok && !!val(PRIMARY[f]);
    }
    $("#wf-submit").disabled = !ok;
    return ok;
  }

  // ---------- 보수 컴포넌트 ----------
  function payStr() {
    if (form.elements["w-pay-nego"].checked) return "협의";
    const a = val("w-pay-amt");
    return a ? `${form.elements["w-pay-unit"].value} ${a}만원` : "";
  }

  // ---------- 제목 자동 제안 ----------
  function suggestion() {
    const region = val("w-region"), instr = val("w-instDetail") || val("w-inst"), pay = payStr();
    if (wtype === "구직") {
      const i2 = val("w-instDetail2") || checked("ws-i").join("·");
      const t = checked("ws-t").join("·"), r = checked("ws-r").join("·");
      return i2 && t ? `[${i2}] ${t} 가능합니다${r ? ` (${r})` : ""}` : "";
    }
    if (!region || !instr) return "";
    const when = val("w-when"), catL = form.elements["w-cat"] ? form.elements["w-cat"].selectedOptions[0]?.textContent : "";
    if (wtype === "오브리")
      return `[${region}] ${form.elements["w-regular"].value === "정기" ? "주일 " : ""}${instr} ${catL || "반주자"}${when || pay ? ` (${[when, pay].filter(Boolean).join(" · ")})` : ""}`;
    if (wtype === "연주")
      return `[${region}] ${instr} ${catL || "객원"} ${val("w-personnel") || ""}명${when || pay ? ` (${[when, pay].filter(Boolean).join(" · ")})` : ""}`.replace(" 명", " 1명");
    return `[${region}] ${instr} ${wtype.replace("교육 — ", "")} 강사 모집${pay ? ` (${pay})` : ""}`;
  }
  function updateSuggestion() {
    const s = suggestion(), box = $("#title-sugg"), btn = $("#title-sugg-btn");
    if (s && s !== val("w-title")) { box.style.display = ""; btn.textContent = `제안: ${s}`; btn.dataset.s = s; }
    else box.style.display = "none";
  }
  $("#title-sugg-btn").addEventListener("click", e => {
    form.elements["w-title"].value = e.currentTarget.dataset.s || "";
    updateSuggestion(); validate();
  });

  // 급구 자동 제안: 연주일이 7일 이내면 힌트
  function updateUrgentHint() {
    const m = val("w-when").match(/(\d{1,2})\s*[/월.]\s*(\d{1,2})/);
    let soon = false;
    if (m) {
      const d = new Date(`${new Date().getFullYear()}-${String(m[1]).padStart(2, "0")}-${String(m[2]).padStart(2, "0")}`);
      const diff = (d - new Date(TODAY)) / 86400000;
      soon = diff >= 0 && diff <= 7;
    }
    $("#urgent-hint").style.display = soon && wtype !== "구직" && !/교육/.test(wtype) ? "" : "none";
  }

  form.addEventListener("input", () => { validate(); updateSuggestion(); updateUrgentHint(); });
  form.addEventListener("change", e => {
    if (e.target.name === "w-inst") updateProvided();
    if (e.target.name === "w-pay-nego") form.elements["w-pay-amt"].disabled = e.target.checked;
    validate(); updateSuggestion();
  });

  // ---------- 제출 → 카드 스키마로 매핑 ----------
  const SEEK_REGION = { "충청권": "충남", "영남권": "부산", "호남권": "광주·전남" };
  const BAND_BY_CAT = { "객원/대타": "객원·대체", "단원모집": "단원", "행사연주": "행사연주", "반주": "반주",
                        "지휘/음악감독": "지휘", "교수": "교수", "겸임교수": "교수", "시간강사": "강사·레슨" };
  form.addEventListener("submit", e => {
    e.preventDefault();
    if (!validate()) return;
    const cid = Date.now();
    const seek = wtype === "구직";
    const seekRegs = checked("ws-r");
    const item = {
      key: "c" + cid, cid, src: "소규모", mine: true,
      type: seek ? "구직" : "구인",
      tier: /교육/.test(wtype) ? wtype : "연주",
      obri: wtype === "오브리" || checked("ws-t").includes("오브리"),
      band: seek ? ({ "객원·대타": "객원·대체", "오브리": "행사연주", "반주": "반주", "레슨": "강사·레슨" }[checked("ws-t")[0]] || "기타")
                 : (BAND_BY_CAT[val("w-cat")] || (/교육/.test(wtype) ? "강사·레슨" : "기타")),
      insts: [seek ? (val("w-instDetail2") || checked("ws-i")[0]) : (val("w-instDetail") || val("w-inst"))].filter(Boolean),
      group: seek ? checked("ws-i")[0] : val("w-inst"),
      region: seek ? (SEEK_REGION[seekRegs[0]] || seekRegs[0] || "기타") : val("w-region"),
      seekTypes: seek ? checked("ws-t") : undefined,
      seekRegions: seek ? seekRegs : undefined,
      title: val("w-title"), org: val("w-org"),
      phone: val("w-phone") || null, applyEmail: val("w-email") || null, chatLink: val("w-chat") || null,
      pay: payStr() || "협의",
      payAmount: form.elements["w-pay-nego"].checked ? null : (+val("w-pay-amt") || null),
      payUnit: form.elements["w-pay-unit"].value, payNego: form.elements["w-pay-nego"].checked,
      when: [val("w-regular") === "정기" ? "정기(매주)" : "", val("w-when")].filter(Boolean).join(" ") || (seek ? val("w-seek-when") : null) || null,
      program: val("w-program") || null,
      personnel: val("w-personnel") || null,
      qualification: seek ? (val("w-seek-edu") || null) : null,
      rehearsalCount: +val("w-rehearsalCount") || null, rehearsalWhen: val("w-rehearsalWhen") || null,
      instProvided: blockOf("provided").parentElement.id === "wf-req" ? val("w-instProvided") : null,
      instProvidedDetail: val("w-instProvidedDetail") || null,
      setup: val("w-setup") || null, keyboard: val("w-keyboard") || null,
      applyLink: val("w-applyLink") || null,
      degreeReq: val("w-degree") || "무관", careerReq: val("w-career") || "미기재", certReq: val("w-cert") || "무관",
      deadline: val("w-deadline") || null,
      deadlineText: val("w-deadline") || (wtype === "오브리" ? (val("w-when") || "연주일") : "충원 시 마감"),
      date: TODAY, urgent: !!(form.elements["w-urgent"] && form.elements["w-urgent"].checked),
      body: [seek && val("w-seek-career") ? `경력: ${val("w-seek-career")}` : "",
             seek && seekRegs.length ? `가능 지역: ${seekRegs.join("·")}` : "",
             seek && checked("ws-t").length ? `가능 유형: ${checked("ws-t").join("·")}` : "",
             val("w-body")].filter(Boolean).join("\n"),
    };
    USER_POSTS.unshift(item);
    saveUserPosts();
    renderAll();
    // 등록 직후: 미리보기 + 공유 + 관리 안내
    form.style.display = "none";
    $("#write-done").style.display = "";
    $("#write-head").textContent = "등록 완료";
    $("#wd-preview").innerHTML = cardHTML(item);
    const link = location.origin + location.pathname + "#post=c" + cid;
    $("#wd-copy").onclick = () => { navigator.clipboard?.writeText(link); $("#wd-copy").textContent = "✓ 복사됨"; };
    $("#wd-kakao").onclick = () => { navigator.clipboard?.writeText(link); alert("링크를 복사했어요 — 카톡 대화방에 붙여넣으면 공유됩니다."); };
    $("#wd-close").onclick = () => { $("#write-modal").classList.remove("open"); form.reset(); showStep(1); };
  });
})();
