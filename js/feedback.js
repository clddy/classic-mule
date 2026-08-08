// 피드백 — 사이트 안에서 바로 쓰고 보낸다.
//
// 예전엔 mailto 링크였다. 그런데 윈도우에서 그걸 누르면 '앱을 선택하세요' 창이 뜨고,
// 거기서 크롬을 고르면 아무 일도 안 일어난다(웹메일 핸들러 미등록 — 2026-08-02 제보).
// 메일 앱을 안 쓰는 방문자에겐 사실상 막힌 통로였다.
// 이제 그 자리에서 쓰고 보내면 Cloudflare Worker 가 받아 관리자에게 간다
// (2026-08-08 사용자 지시 — "메일 식이 아니라 관리자인 나만 보이게").
(function () {
  // 배포 후 workers.dev 주소로 바꾼다 (feedback/README.md 참고).
  // 비워 두면 폼을 띄우지 않고 예전 mailto 동작으로 물러난다 — 배포 전에도 사이트는 멀쩡하다.
  var API = "";

  var STYLE = [
    ".fb-back{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9998;display:flex;",
    "align-items:flex-end;justify-content:center}",
    ".fb-box{background:var(--paper,#fff);color:inherit;width:100%;max-width:520px;",
    "border-radius:14px 14px 0 0;padding:20px 18px 18px;box-shadow:0 -6px 30px rgba(0,0,0,.25)}",
    "@media(min-width:600px){.fb-back{align-items:center}.fb-box{border-radius:14px}}",
    ".fb-box h3{margin:0 0 4px;font-size:1.05rem}",
    ".fb-box p{margin:0 0 12px;font-size:.86rem;opacity:.7;line-height:1.5}",
    ".fb-box textarea{width:100%;min-height:120px;padding:10px 12px;border-radius:10px;",
    "border:1px solid rgba(128,128,128,.45);background:transparent;color:inherit;",
    "font:inherit;font-size:.95rem;resize:vertical;box-sizing:border-box}",
    ".fb-row{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}",
    ".fb-row button{padding:9px 18px;border-radius:999px;border:1px solid rgba(128,128,128,.45);",
    "background:transparent;color:inherit;font:inherit;cursor:pointer}",
    ".fb-row button.fb-send{background:var(--claret,#7a1f2b);color:#fff;border-color:transparent}",
    ".fb-row button[disabled]{opacity:.5;cursor:default}",
    ".fb-msg{margin-top:10px;font-size:.85rem;min-height:1.2em}",
    ".fb-hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}",
  ].join("");

  function open() {
    var back = document.createElement("div");
    back.className = "fb-back";
    back.innerHTML =
      '<div class="fb-box" role="dialog" aria-modal="true" aria-label="피드백 보내기">' +
      "<h3>개발자에게 메시지 보내기</h3>" +
      "<p>문제점이나 개선사항을 알려주세요. 답장이 필요하면 연락처를 함께 적어 주세요.</p>" +
      '<textarea placeholder="내용을 남겨주세요"></textarea>' +
      // 사람 눈에 안 보이는 칸. 자동 프로그램만 여기를 채운다.
      '<input class="fb-hp" tabindex="-1" autocomplete="off" name="website" aria-hidden="true">' +
      '<div class="fb-msg"></div>' +
      '<div class="fb-row"><button class="fb-cancel">닫기</button>' +
      '<button class="fb-send">전송</button></div></div>';
    document.body.appendChild(back);

    var ta = back.querySelector("textarea");
    var hp = back.querySelector(".fb-hp");
    var msg = back.querySelector(".fb-msg");
    var send = back.querySelector(".fb-send");
    ta.focus();

    function close() { back.remove(); document.removeEventListener("keydown", onKey); }
    function onKey(e) { if (e.key === "Escape") close(); }
    document.addEventListener("keydown", onKey);
    back.querySelector(".fb-cancel").addEventListener("click", close);
    back.addEventListener("click", function (e) { if (e.target === back) close(); });

    send.addEventListener("click", function () {
      var text = (ta.value || "").trim();
      if (text.length < 5) { msg.textContent = "내용을 조금 더 적어 주세요."; return; }
      send.disabled = true;
      msg.textContent = "보내는 중…";
      fetch(API + "/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, page: location.pathname, website: hp.value }),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.ok) {
            msg.textContent = "보냈습니다. 읽어보겠습니다 — 고맙습니다.";
            ta.value = "";
            setTimeout(close, 1400);
          } else {
            msg.textContent = (d && d.error) || "보내지 못했습니다. 잠시 후 다시 시도해 주세요.";
            send.disabled = false;
          }
        })
        .catch(function () {
          msg.textContent = "보내지 못했습니다. 잠시 후 다시 시도해 주세요.";
          send.disabled = false;
        });
    });
  }

  document.querySelectorAll(".feedback-fab").forEach(function (el) {
    el.addEventListener("click", function (e) {
      if (!API) return;              // 아직 Worker 배포 전 — mailto 로 물러난다
      e.preventDefault();
      if (!document.getElementById("fb-style")) {
        var s = document.createElement("style");
        s.id = "fb-style";
        s.textContent = STYLE;
        document.head.appendChild(s);
      }
      open();
    });
  });
})();
