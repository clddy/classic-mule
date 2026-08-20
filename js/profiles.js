// 프로필 디렉토리 — 제출·관리·목록 (작업 H, 2026-08-20)
//
// 개인정보는 이 저장소에 저장되지 않는다. 전부 Worker(KV)에만 있고 여기서는 오갈 뿐이다.
// 확인 코드(토큰)는 제출 응답에 한 번만 실려 오며 localStorage 에도 남기지 않는다 —
// 저장해 두면 그 기기를 쓰는 다른 사람이 남의 프로필을 지울 수 있게 된다.
(function () {
  "use strict";
  var API = "https://podium-feedback.ohmjin314.workers.dev";
  var REGIONS = ["서울", "부산", "대구", "인천", "대전", "울산", "세종", "경기",
    "강원", "충북", "충남", "전북", "광주·전남", "경북", "경남", "제주"];

  function $(s, r) { return (r || document).querySelector(s); }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fillRegions(sel, cur) {
    if (!sel) return;
    if (!sel.querySelector('option[value=""]')) {
      sel.insertAdjacentHTML("beforeend", '<option value="">고르세요</option>');
    }
    REGIONS.forEach(function (r) {
      var o = document.createElement("option");
      o.value = r;
      o.textContent = r;
      if (r === cur) o.selected = true;
      sel.appendChild(o);
    });
  }

  function post(path, body) {
    return fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false }; });
    });
  }

  function say(el, msg, bad) {
    if (!el) return;
    el.textContent = msg || "";
    el.style.color = bad ? "#8c2f2f" : "#3f6b3f";
  }

  function values(form) {
    var o = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name) return;
      o[el.name] = el.type === "checkbox" ? el.checked : el.value;
    });
    return o;
  }

  // 남은 분량을 눈으로 보게 — 100자·500자 상한이 있는 칸들
  function wireCounters(root) {
    var scope = root || document;
    Array.prototype.forEach.call(scope.querySelectorAll(".pf-count"), function (c) {
      var f = scope.querySelector('[name="' + c.getAttribute("data-for") + '"]');
      if (!f) return;
      var max = f.getAttribute("maxlength") || "";
      var upd = function () { c.textContent = f.value.length + "/" + max; };
      f.addEventListener("input", upd);
      upd();
    });
  }

  // ---- 제출 폼 ----
  function initSubmit() {
    var form = $("#pf-form");
    if (!form) return;
    fillRegions(form.querySelector('[name="region"]'));
    wireCounters(form.parentNode);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = $("#pf-submit");
      var msg = $("#pf-msg");
      say(msg, "");
      var v = values(form);
      if (!v.consent) {
        say(msg, "공개 게시 동의가 필요합니다.", true);
        return;
      }
      btn.disabled = true;
      btn.textContent = "보내는 중…";
      post("/api/profile", v).then(function (d) {
        btn.disabled = false;
        btn.textContent = "등록 신청";
        if (!d.ok) {
          say(msg, d.error || "등록에 실패했습니다.", true);
          return;
        }
        form.hidden = true;
        var done = $("#pf-done");
        if (done) {
          done.hidden = false;
          // 봇 덫에 걸린 요청도 ok 로 답하지만 토큰이 없다 — 그때는 코드 자리를 비운다
          $("#pf-token").textContent = d.token ? (d.id + " / " + d.token) : "(발급되지 않았습니다)";
        }
      }).catch(function () {
        btn.disabled = false;
        btn.textContent = "등록 신청";
        say(msg, "연결에 실패했습니다. 잠시 후 다시 시도해 주세요.", true);
      });
    });
  }

  // ---- 관리(수정·삭제) ----
  function initManage() {
    var auth = $("#pm-auth");
    if (!auth) return;
    var cred = null;
    var form = $("#pm-form");
    fillRegions(form && form.querySelector('[name="region"]'));

    auth.addEventListener("submit", function (e) {
      e.preventDefault();
      var msg = $("#pm-msg");
      var v = values(auth);
      say(msg, "확인 중…");
      post("/api/profile/view", { id: v.id.trim(), token: v.token.trim() }).then(function (d) {
        if (!d.ok) {
          say(msg, d.error || "불러오지 못했습니다.", true);
          return;
        }
        cred = { id: v.id.trim(), token: v.token.trim() };
        say(msg, "");
        auth.hidden = true;
        $("#pm-edit").hidden = false;
        ["name", "inst", "intro", "career", "contact"].forEach(function (k) {
          var el = form.querySelector('[name="' + k + '"]');
          if (el) el.value = d.profile[k] || "";
        });
        var rs = form.querySelector('[name="region"]');
        if (rs) rs.value = d.profile.region || "";
        $("#pm-status").textContent = d.status === "published"
          ? "현재 상태: 공개 중"
          : (d.status === "rejected"
            ? "현재 상태: 게시 보류 (문의는 피드백으로)"
            : "현재 상태: 운영자 확인 대기");
      });
    });

    if (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        if (!cred) return;
        var msg = $("#pm-status");
        var payload = values(form);
        payload.id = cred.id;
        payload.token = cred.token;
        post("/api/profile/update", payload).then(function (d) {
          say(msg, d.ok ? "저장했습니다. 운영자 확인 후 다시 공개됩니다." : (d.error || "저장 실패"), !d.ok);
        });
      });
    }

    var del = $("#pm-del");
    if (del) {
      del.addEventListener("click", function () {
        if (!cred) return;
        if (!window.confirm("정말 지울까요? 되돌릴 수 없습니다.")) return;
        post("/api/profile/delete", cred).then(function (d) {
          if (!d.ok) {
            say($("#pm-status"), d.error || "삭제 실패", true);
            return;
          }
          $("#pm-edit").hidden = true;
          auth.hidden = false;
          auth.reset();
          say($("#pm-msg"), "프로필을 지웠습니다.");
          cred = null;
        });
      });
    }
  }

  // ---- 디렉토리 목록 ----
  function initDirectory() {
    var wrap = $("#pd-list");
    if (!wrap) return;
    var all = [];
    var fInst = "";
    var fRegion = "";

    function render() {
      var rows = all.filter(function (p) {
        return (!fRegion || p.region === fRegion) &&
          (!fInst || (p.inst || "").indexOf(fInst) >= 0);
      });
      var n = $("#pd-count");
      if (n) n.textContent = rows.length + "명";
      if (!rows.length) {
        wrap.innerHTML = '<p style="color:#6b6154;font-size:0.9rem">해당하는 프로필이 없습니다.</p>';
        return;
      }
      wrap.innerHTML = rows.map(function (p) {
        var link = /^https?:/i.test(p.contact)
          ? '<a href="' + esc(p.contact) + '" target="_blank" rel="noopener nofollow">' + esc(p.contact) + "</a>"
          : '<a href="mailto:' + esc(p.contact) + '">' + esc(p.contact) + "</a>";
        return '<article class="job-card" style="cursor:pointer">' +
          '<div class="top-row"><span class="tag inst">' + esc(p.inst) + "</span>" +
          '<span class="tag org">' + esc(p.region) + "</span></div>" +
          "<h3>" + esc(p.name) + "</h3>" +
          '<div class="meta"><span>' + esc(p.intro) + "</span></div>" +
          '<div class="pd-more" hidden style="margin-top:10px;font-size:0.9rem;line-height:1.7">' +
          (p.career ? "<p>" + esc(p.career) + "</p>" : "") +
          "<p>연락: " + link + "</p></div></article>";
      }).join("");
    }

    // 개별 프로필에 별도 URL을 주지 않는다(v0) — 카드를 눌러 그 자리에서 펼친다
    wrap.addEventListener("click", function (e) {
      if (e.target.tagName === "A") return;
      var card = e.target.closest(".job-card");
      if (!card) return;
      var more = card.querySelector(".pd-more");
      if (more) more.hidden = !more.hidden;
    });

    var ri = $("#pd-region");
    fillRegions(ri);
    if (ri) {
      ri.addEventListener("change", function () {
        fRegion = ri.value;
        render();
      });
    }
    var ii = $("#pd-inst");
    if (ii) {
      ii.addEventListener("input", function () {
        fInst = ii.value.trim();
        render();
      });
    }

    fetch(API + "/api/profiles").then(function (r) {
      return r.json();
    }).then(function (d) {
      all = (d && d.items) || [];
      render();
    }).catch(function () {
      wrap.innerHTML = '<p style="color:#8c2f2f;font-size:0.9rem">목록을 불러오지 못했습니다.</p>';
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initSubmit();
    initManage();
    initDirectory();
  });
})();
