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
// GA4 측정 ID (2026-08-02 발급, podiumclassical.kr).
// ⚠ 2026-08-06: 여기 'G-BYYPBWD5DH'(Y)로 한 글자 오타가 있어 나흘간 수집이 0이었다.
// GA는 존재하지 않는 측정 ID로 온 요청도 오류 없이 버린다 — 브라우저 네트워크 탭에
// /g/collect 200이 보여도 그것만으로는 정상이라는 증거가 못 된다. Admin API로
// 스트림의 measurement_id와 대조하는 것이 유일한 확인법.
window.PODIUM_GA_ID = "G-BVYPBWD5DH";

(function () {
  var ID = window.PODIUM_GA_ID;

  // ---------- 자기 트래픽 제외 (2026-08-06) ----------
  // 운영자가 확인하러 들어온 기록이 섞이면 방문자가 적을수록 비율이 통째로 왜곡된다.
  // GA4 콘솔의 IP 필터만으로는 부족하다 — 집 IP는 바뀌고, 밖에서 폰으로 보면 안 걸린다.
  // 그래서 기기 단위 스위치를 같이 둔다: ?pd_optout=1 로 켜고, ?pd_optout=0 으로 푼다.
  // (localStorage 라 그 브라우저에서 영구 유지 — IP가 바뀌어도 계속 제외된다)
  var optout = false, optoutTouched = false, optoutFailed = false;
  try {
    var m = location.search.match(/[?&]pd_optout=([01])/);
    if (m) { localStorage.setItem("podium_ga_optout", m[1]); optoutTouched = true; }
    optout = localStorage.getItem("podium_ga_optout") === "1";
    // 저장이 실제로 됐는지 되읽어 확인 — 사파리 사생활 모드는 setItem 을 조용히 무시한다
    if (m && (localStorage.getItem("podium_ga_optout") !== m[1])) optoutFailed = true;
  } catch (e) {
    if (location.search.indexOf("pd_optout") >= 0) { optoutTouched = true; optoutFailed = true; }
  }

  // 눈에 보이는 확인 — 폰에서는 콘솔을 못 보므로 화면에 띄운다.
  // 이게 없으면 "눌렀는데 됐는지 모르겠다"가 된다 (2026-08-17 사용자 지적).
  if (optoutTouched) {
    var msg = optoutFailed
      ? "⚠ 저장 실패 — 사생활 보호 모드에서는 제외가 유지되지 않습니다"
      : (optout ? "✔ 이 기기는 통계에서 제외됩니다" : "○ 제외 해제 — 이 기기 방문이 통계에 집계됩니다");
    var bg = optoutFailed ? "#7a2a38" : (optout ? "#1f5f3a" : "#444");
    var show = function () {
      var d = document.createElement("div");
      d.textContent = msg;
      d.setAttribute("style", "position:fixed;left:50%;top:16px;transform:translateX(-50%);z-index:99999;" +
        "background:" + bg + ";color:#fff;padding:12px 18px;border-radius:8px;font-size:14px;" +
        "font-family:system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.28);max-width:90vw;text-align:center");
      d.addEventListener("click", function () { d.remove(); });
      document.body.appendChild(d);
      setTimeout(function () { d.style.transition = "opacity .4s"; d.style.opacity = "0";
                               setTimeout(function () { d.remove(); }, 400); }, 5000);
    };
    if (document.body) show();
    else document.addEventListener("DOMContentLoaded", show);
  }

  // 개발용 접속(로컬 프리뷰·사설망·file://)은 언제나 제외. 실측정 ID가 붙은 뒤로는
  // localhost 테스트도 실제 데이터를 오염시킨다.
  var h = location.hostname;
  var isDev = location.protocol === "file:" ||
              /^(localhost|127\.|0\.0\.0\.0|::1|192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h);

  var enabled = ID && /^G-[A-Z0-9]+$/.test(ID) &&
                location.protocol.indexOf("http") === 0 && !isDev && !optout;
  // 제외 상태를 눈으로 확인할 수 있게 (운영자 전용 — 일반 방문자는 볼 일이 없다)
  if (optout || isDev) {
    try { console.info("[포디엄] 계측 제외됨 —", optout ? "이 기기 제외 설정" : "개발용 접속"); } catch (e) {}
  }
  window.podiumTrackingStatus = function () {
    return { enabled: enabled, optout: optout, isDev: isDev, id: ID };
  };

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
