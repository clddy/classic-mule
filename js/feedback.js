// 피드백 버튼 보조 — mailto가 열리지 않는 환경에서도 주소를 손에 쥐어준다.
//
// 윈도우에서 mailto 링크를 누르면 '앱을 선택하여 이 mailto 링크를 여세요' 창이 뜨는데,
// 거기서 Chrome을 고르면 아무 일도 일어나지 않는다(웹메일 핸들러 미등록 — 2026-08-02 제보).
// 메일 앱을 안 쓰는 방문자가 적지 않으므로, 클릭과 동시에 주소를 클립보드에 넣고
// 버튼 라벨로 알려준다. href(mailto)는 그대로 두어 메일 앱이 있는 사람은 평소대로 열린다.
(function () {
  var MAIL = "ohmjin3141@naver.com";
  document.querySelectorAll(".feedback-fab").forEach(function (el) {
    el.addEventListener("click", function () {
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(MAIL).then(function () {
        var old = el.dataset.label || el.textContent;
        el.dataset.label = old;
        el.textContent = "주소 복사됨 · " + MAIL;
        setTimeout(function () { el.textContent = old; }, 3000);
      }).catch(function () { /* 복사 실패는 조용히 — mailto는 그대로 진행된다 */ });
    });
  });
})();
