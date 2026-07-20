// 등록 폼 스펙 v1 엔진 (v2.0 개정) — 유형 선택 → 폼 · 유형별 필수/선택 매트릭스 ·
// 구조화 보수 · 제목 자동 제안 · 등록 직후 미리보기+공유. jobs.js 뒤에 로드.
// v2.0: 구직·급구 제거(신뢰 시장 불가침), 오브리 → '교회'(반주·지휘·솔리스트, 상시·정기 포지션 전용).
(function () {
  const $ = s => document.querySelector(s);
  const form = $("#write-form");
  if (!form) return;
  const blockOf = f => document.querySelector(`.wf[data-f="${f}"]`);

  // ---------- 유형별 매트릭스 (필수 개수 늘리는 변경은 원칙적으로 거부) ----------
  const COMMON_REQ = ["title", "region", "org", "contact"];
  const M = {
    "연주":            { req: ["cat", "instr", "when", "pay", "rehearsal"], opt: ["regular", "deadline", "program", "personnel", "body"] },
    "교회":            { req: ["cat", "instr", "regular", "when", "pay"],   opt: ["rehearsal", "body"] },
    "교육 — 대학":     { req: ["cat", "deadline", "degree", "applyLink"],  opt: ["instr", "pay", "career", "personnel", "body"] },
    "교육 — 입시·전공": { req: ["instr", "pay"], opt: ["when", "career", "deadline", "body"] },
    "교육 — 취미·입문": { req: ["instr", "pay"], opt: ["when", "career", "deadline", "cert", "body"] },
  };
  const CATS = {
    "연주": [["객원/대타", "객원"], ["단원모집", "단원"], ["행사연주", "행사연주"], ["반주", "반주"]],
    "교회": [["반주", "반주"], ["지휘/음악감독", "지휘"], ["솔리스트", "솔리스트"]],
    "교육 — 대학": [["교수", "교수"], ["겸임교수", "겸임교수"], ["시간강사", "시간강사"]],
  };
  const PRIMARY = { title: "w-title", region: "w-region", org: "w-org", cat: "w-cat", instr: "w-inst",
                    when: "w-when", regular: "w-regular", rehearsal: "w-rehearsalCount", deadline: "w-deadline",
                    degree: "w-degree", applyLink: "w-applyLink" };

  let wtype = null;

  // ---------- 스텝: 유형 선택 → 폼 ----------
  function showStep(n) {   // 1 = 유형 선택, 2 = 폼
    $("#ws-2").style.display = n === 1 ? "" : "none";
    form.style.display = n === 2 ? "" : "none";
    $("#write-done").style.display = "none";
    $("#write-head").textContent = n === 1 ? "공고 올리기 — 유형 선택" : `공고 올리기 — ${wtype}`;
  }
  window.PodiumWrite = { reset: () => showStep(1) };

  document.querySelectorAll("#ws-2 .ws-big").forEach(b => b.addEventListener("click", () => {
    wtype = b.dataset.wtype; buildForm(); showStep(2);
  }));
  $("#ws-back2").addEventListener("click", () => showStep(1));

  // ---------- 폼 조립 — 블록을 필수/상세 컨테이너로 이동 (입력값은 노드 이동으로 자연 보존) ----------
  function buildForm() {
    const m = M[wtype];
    const req = $("#wf-req"), opt = $("#wf-opt-body"), pool = $("#wf-pool");
    document.querySelectorAll(".wf").forEach(el => pool.appendChild(el));
    for (const f of COMMON_REQ) req.appendChild(blockOf(f));
    for (const f of m.req) req.appendChild(blockOf(f));
    for (const f of m.opt) opt.appendChild(blockOf(f));
    if (CATS[wtype]) {
      $("#cat-label").textContent = wtype === "교회" ? "포지션" : "분야";
      form.elements["w-cat"].innerHTML = CATS[wtype].map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
    }
    $("#pay-label").textContent = wtype === "교회" ? "사례비" : "보수";
    $("#instr-label").textContent = /입시|취미/.test(wtype) ? "과목 (악기군)" : (wtype === "교육 — 대학" ? "전공 분야" : "악기군");
    $("#when-label").textContent = /교육/.test(wtype) ? "요일·시간" : "일시 (연주·근무일)";
    // 교회는 상시·정기 포지션 전용 — 단발 옵션 없음
    if (form.elements["w-regular"]) {
      $("#regular-label").textContent = wtype === "교회" ? "근무 형태" : "정기/단발";
      form.elements["w-regular"].innerHTML = wtype === "교회"
        ? `<option value="정기">정기 (매주)</option><option value="상시">상시</option>`
        : `<option value="단발">단발 (하루)</option><option value="정기">정기 (매주)</option>`;
    }
    if (form.elements["w-when"])
      form.elements["w-when"].placeholder = wtype === "교회" ? "예: 매주 일요일 1·2부 예배" : (/교육/.test(wtype) ? "예: 주 2회, 평일 오후 협의" : "예: 7/24(금) 저녁 공연");
    $("#deadline-hint").style.display = wtype === "교육 — 대학" ? "none" : "";
    updateProvided(); validate();
  }

  // 악기 제공 세트 — 연주(타악·건반)·교회(건반)일 때만 필수 영역에 등장
  function updateProvided() {
    const g = form.elements["w-inst"] ? form.elements["w-inst"].value : "";
    const need = (wtype === "연주" && (g === "타악" || g === "건반")) || (wtype === "교회" && g === "건반");
    const blk = blockOf("provided");
    if (need) { $("#wf-req").appendChild(blk); }
    else if (blk.parentElement !== $("#wf-pool")) $("#wf-pool").appendChild(blk);
    $("#prov-perc").style.display = g === "타악" ? "" : "none";
    $("#prov-key").style.display = g === "건반" ? "" : "none";
    $("#prov-detail").style.display = g === "타악" ? "" : "none";
  }

  // ---------- 검증: 필수 미입력 시에만 등록 비활성 ----------
  const val = n => (form.elements[n] ? String(form.elements[n].value).trim() : "");
  function validate() {
    const m = M[wtype] || { req: [] };
    let ok = !!val("w-title") && !!val("w-org") && !!val("w-region");
    ok = ok && !!(val("w-phone") || val("w-email") || val("w-chat"));          // 연락 ≥1
    for (const f of m.req) {
      if (f === "pay") ok = ok && (form.elements["w-pay-nego"].checked || !!val("w-pay-amt"));
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
    if (!region || !instr) return "";
    const when = val("w-when"), catL = form.elements["w-cat"] ? form.elements["w-cat"].selectedOptions[0]?.textContent : "";
    if (wtype === "교회")
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

  form.addEventListener("input", () => { validate(); updateSuggestion(); });
  form.addEventListener("change", e => {
    if (e.target.name === "w-inst") updateProvided();
    if (e.target.name === "w-pay-nego") form.elements["w-pay-amt"].disabled = e.target.checked;
    validate(); updateSuggestion();
  });

  // ---------- 제출 → 카드 스키마로 매핑 ----------
  const BAND_BY_CAT = { "객원/대타": "객원·대체", "단원모집": "단원", "행사연주": "행사연주", "반주": "반주",
                        "지휘/음악감독": "지휘", "교수": "교수", "겸임교수": "교수", "시간강사": "강사·레슨" };
  form.addEventListener("submit", e => {
    e.preventDefault();
    if (!validate()) return;
    const cid = Date.now();
    const item = {
      key: "c" + cid, cid, src: "소규모", mine: true, type: "구인",
      tier: /교육/.test(wtype) ? wtype : "연주",
      obri: wtype === "교회",   // 크롤 필드와 같은 의미(교회·행사) — '교회 공고만' 필터에 걸린다
      band: BAND_BY_CAT[val("w-cat")] || (/교육/.test(wtype) ? "강사·레슨" : "기타"),
      insts: [val("w-instDetail") || val("w-inst")].filter(Boolean),
      group: val("w-inst"),
      region: val("w-region"),
      title: val("w-title"), org: val("w-org"),
      phone: val("w-phone") || null, applyEmail: val("w-email") || null, chatLink: val("w-chat") || null,
      pay: payStr() || "협의",
      payAmount: form.elements["w-pay-nego"].checked ? null : (+val("w-pay-amt") || null),
      payUnit: form.elements["w-pay-unit"].value, payNego: form.elements["w-pay-nego"].checked,
      when: [val("w-regular") === "정기" ? "정기(매주)" : "", val("w-when")].filter(Boolean).join(" ") || null,
      program: val("w-program") || null,
      personnel: val("w-personnel") || null,
      rehearsalCount: +val("w-rehearsalCount") || null, rehearsalWhen: val("w-rehearsalWhen") || null,
      instProvided: blockOf("provided").parentElement.id === "wf-req" ? val("w-instProvided") : null,
      instProvidedDetail: val("w-instProvidedDetail") || null,
      setup: val("w-setup") || null, keyboard: val("w-keyboard") || null,
      applyLink: val("w-applyLink") || null,
      degreeReq: val("w-degree") || "무관", careerReq: val("w-career") || "미기재", certReq: val("w-cert") || "무관",
      // 교회는 상시·정기 전용 — 다른 유형에서 입력하다 전환해도 잔존 마감일을 무시한다
      deadline: wtype === "교회" ? null : (val("w-deadline") || null),
      deadlineText: wtype === "교회" ? "상시" : (val("w-deadline") || "충원 시 마감"),
      date: TODAY,
      body: val("w-body"),
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
