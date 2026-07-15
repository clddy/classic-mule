// 공공 연습공간 실데이터(큐레이션) — 각 기관 공식 홈페이지에서 확인한 사실만 수록 (verified=확인일).
// 서울문화재단 생활예술플랫폼 기준 거점형 생활문화센터 3곳 전부 (2026-07-15 기준).
// 스키마: category='public'(신청제·공공) — 지시서 필드 체계.
// ※ yeyak.seoul.go.kr 수집분은 data/practice-yeyak.js (crawler/practice_yeyak.py가 생성).
// ※ 민간(즉시 예약)은 호스트 직접 등록 원칙 — 타 플랫폼 크롤 금지.
window.PUBLIC_ROOMS = [
  {
    name: "서울생활문화센터 체부",
    category: "public",
    region: "종로구", addr: "서울 종로구 자하문로1나길 3-2 (체부동, 옛 체부동교회)",
    spaces: "체부홀(본관) · 금오재(한옥)",
    price: "체부홀 3만원/타임(2.5h) · 금오재 1만원/타임(2h)", free: false,
    selection: "정기(분기)+수시", apply_method: "온라인·방문", apply_timing: "분기 일괄 + 잔여 수시",
    eligibility: "누구나(생활음악 동아리 중심)",
    hours: "화~금 10~22시 · 주말 10~18:30 (월 휴관)",
    instruments: ["성악·앙상블가능", "대편성가능"],   // 오케스트라·합창 연습 거점 (공식 명시)
    booking_url: "https://ccasc.or.kr/33", src: "ccasc.or.kr",
    notes: "생활음악 동아리 거점공간 — 오케스트라·합창 연습. 공연대관 시 체부홀 5만원.",
    verified: "2026-07-15"
  },
  {
    name: "서울생활문화센터 낙원",
    category: "public",
    region: "종로구", addr: "서울 종로구 삼일대로 428, 낙원악기상가 1층·하부",
    spaces: "합주·연습 공간",
    price: "홈페이지 공고 참조", free: false,
    selection: "정기(분기)+수시", apply_method: "온라인", apply_timing: "분기 일괄 + 잔여 수시",
    eligibility: "누구나",
    hours: "센터 공지 참조 · ☎ 02-6959-8323",
    instruments: [],
    booking_url: "http://nakwon-communityart.or.kr/bbs/space01", src: "nakwon-communityart.or.kr",
    notes: "생활음악 특화 — 낙원악기상가 하부공간.",
    verified: "2026-07-15"
  },
  {
    name: "서울생활문화센터 서교",
    category: "public",
    region: "마포구", addr: "서울 마포구 양화로 72, 효성해링턴타워 B1~B2 (서교동)",
    spaces: "연습실 1·2·3·4",
    price: "홈페이지 로그인 후 확인", free: false,
    selection: "선착순(온라인)", apply_method: "온라인", apply_timing: "희망일 7일 전 17시까지",
    eligibility: "누구나(회원가입)",
    hours: "☎ 02-336-7531",
    instruments: [],
    booking_url: "https://seogyocenter.or.kr/space1rent", src: "seogyocenter.or.kr",
    notes: "홍대앞 창작문화 플랫폼 — 연습실 4실.",
    verified: "2026-07-15"
  },
];
