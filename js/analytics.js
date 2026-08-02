// 포디엄 계측 (GA4) — "방문자가 어떻게 사이트를 쓰는가"를 데이터화하는 층.
//
// 측정 ID(G-…)를 아래 한 곳에 넣으면 전 페이지에서 켜진다. 비어 있으면 모든 계측이
// 조용히 꺼진다(스크립트 로드도 안 함) — 개발 중 로컬 file:// 오염 방지도 겸함.
//
// 이벤트 사전 (crawler/traffic.py 가 같은 이름으로 집계한다 — 이름 바꾸면 같이 바꿀 것):
//   job_view          공고 상세 열람       {job_id, tier, inst, region, org}
//   job_outbound      원문/지원 이동 클릭  {job_id, dest: official|url|mail|tel}
//   filter_use        필터 적용 스냅샷     {tiers, insts, regions, q, results}
//   filter_empty      필터 결과 0건       {tiers, insts, regions, q}
//   practice_outbound 연습실 예약처 이동   {space}
//
// filter_use/filter_empty 가 특히 중요하다: 공고(공급)는 크롤로 다 아는데,
// 사람들이 무엇을 찾는지(수요)는 여기에만 찍힌다. '비올라로 걸렀는데 0건'은
// 프로필 디렉토리가 채워야 할 칸을 정확히 가리킨다.
window.PODIUM_GA_ID = "G-BYYPBWD5DH";   // GA4 측정 ID (2026-08-02 발급, podiumclassical.kr)

(function () {
  var ID = window.PODIUM_GA_ID;
  var enabled = ID && /^G-[A-Z0-9]+$/.test(ID) && location.protocol.indexOf("http") === 0;

  // 계측 꺼짐이어도 pdEvent 는 항상 존재해야 한다 — 호출부가 가드 없이 쓰도록
  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  window.pdEvent = function (name, params) {
    if (!enabled) return;
    try { gtag("event", name, params || {}); } catch (e) { /* 계측은 절대 본기능을 깨지 않는다 */ }
  };
  if (!enabled) return;

  var s = document.createElement("script");
  s.async = true;
  s.src = "https://www.googletagmanager.com/gtag/js?id=" + ID;
  document.head.appendChild(s);
  gtag("js", new Date());
  gtag("config", ID);

  // 선언형 배선: data-ev / data-evp 속성이 붙은 요소는 클릭 시 자동 이벤트.
  // 정적 페이지(p/*.html)처럼 JS 문맥이 없는 곳에서 쓴다.
  document.addEventListener("click", function (e) {
    var el = e.target && e.target.closest && e.target.closest("[data-ev]");
    if (!el) return;
    var p = {};
    try { p = JSON.parse(el.getAttribute("data-evp") || "{}"); } catch (err) {}
    // JSON 속성은 따옴표 이스케이프가 위험하다 — 한 값짜리는 data-evl(라벨)로 받는다
    if (el.getAttribute("data-evl")) p.label = el.getAttribute("data-evl");
    window.pdEvent(el.getAttribute("data-ev"), p);
  }, true);
})();
