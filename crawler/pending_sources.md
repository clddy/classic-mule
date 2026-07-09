# 직접 파서 미부착 기관 목록 (2026-07-09)

> 명부(75곳) 중 **직접 크롤 소스가 없는 30곳.** 대부분 아트인포·아트모아 포털로는 잡히나,
> 자기 사이트에만 올리는 공고를 놓치지 않으려면 개별 파서가 필요.
> 각 기관 **채용/오디션 게시판 '목록' URL**을 확보하면 파서 부착 가능.
> (probe = 2026-07-09 실측 결과)

## 진행 로그 (2026-07-09 세션)
탐색 도구: `crawler/probe_pending.py`(홈→게시판링크), `crawler/probe_anchors.py`(글행 구조), `crawler/probe_js.py`(JS 홈 렌더→게시판링크)

**✅ 부착 완료 (엔드투엔드 검증 — 라이브 파싱 에러 0, 필터 유닛테스트 통과. 현재 활성 단원공고 없어 수집 0건은 정상)**
| 기관 | 소스 | board_url | 방식·필터 |
|---|---|---|---|
| 과천시립예술단 | `g_gcart` | gcart.or.kr `/kr/commu/recruitList.do` | 정적, 기본 MUSIC (예술 전용판) |
| 목포시립교향악단·예술단 | `g_mokpo` | mokpo.go.kr `/…/notification/incruit` | 정적, **strict** (시청 통합판) |
| 여수시립예술단 | `g_yeosu` | yeosu.go.kr `/…/news/recruit` | 정적, **strict** (going_recruit?idx=) |
| 원주시립교향악단·합창단 | `g_wonju` | wonju.go.kr `selectBbsNttList.do?bbsNo=1129` | **needs_js**, strict (시 임기제 채용판) |
| 포항문화재단(시립교향악단·합창단) | `phcf` (커스텀) | phcf.or.kr `/phcf/recruitment/view.do` | **needs_js + onclick** `moveDetail(N)`→`detail.do?BRD_SEQ=N`, strict |
| 구미시립예술단 | `g_gumi` | gumi.go.kr `/job/saeol/gosi/list.do?seCode=98` | **needs_js + 새올 data-action**, strict — ✅ **실공고 "구미시립무용단 객원무용수 모집" 캡처** |

- 파서 개선:
  1. sources.py `STRICT_ENSEMBLE_PAT`(앙상블명사+채용동사 인접 / (상임·객원)단원만) + 엔트리 `"strict":true`(또는 커스텀 `"title_pat"`).
     city-wide·재단 통합판의 "수석전문관 채용"·"예술단**체** 지원사업 코디네이터" 등 행정 오탐 차단.
  2. `_make_generic_parser`가 `needs_js`면 jsfetch 렌더 사용.
  3. **새올(표준 지자체 게시판) 범용 지원**: href가 `#`/javascript면 앵커의 `data-action`(예: `/…/saeol/gosi/view.do?notAncmtMgtNo=N`)을 permalink로 사용. `req.post` 흉내 불필요 — 새올 쓰는 모든 지자체에 `needs_js:true`만으로 부착 가능. 탐색툴 `crawler/probe_saeol.py`.

**✅ 이미 커버됨 (별도 부착 불필요)**
- **충남교향악단(천안)** → 기존 `cfac`(천안문화재단) generic이 겸함
- **마산시립교향악단** → 기존 `cwcf`(창원문화재단)가 겸함 (마산=창원 통합)

**⛔ 부착 보류 — 헤드리스 불가 (연결된 Chrome 필요) + aggregator가 이미 겸함**
> 2026-07-09 추가조사 결론: 아래 5곳의 계절성 단원 오디션(대개 지방공무원/공무직 채용)은
> **아트인포·아트모아 aggregator가 이미 수집**한다(검증: 검색 시 artinfokorea.com/jobs/336=충북도립교향악단,
> /jobs/131=충청북도립 노출). 자체 게시판 직접부착은 marginal — 급하지 않음.
> 직접부착하려면 게시판이 JS/POST/차단이라 **연결된 Chrome(claude-in-chrome)** 로 목록 URL 확보 필요.
> (이 세션엔 연결된 브라우저 없어 진행 불가 — `list_connected_browsers`=[])
- **진주시립교향악단** — `06660.web` 글행 없음, 채용은 **경남워크넷**(gyeongnam.work.go.kr/jinju/regionBoard/…/retrieveBoardContList.do)로 라우팅. 그러나 워크넷 목록도 렌더 시 0건(메뉴/보드 파라미터 기반 AJAX 그리드) → 대화형 내비 필요
- **김천시** — gimcheon.go.kr HTTPS `SSLError` + Playwright `ERR_CONNECTION_CLOSED`(헤드리스 차단)
- **익산·청주·강릉** — 홈 JS 렌더해도 게시판 링크·새올 경로 0(이미지 메가메뉴). 청주시향은 청주시청+청주예술의전당(cheongju.go.kr/ac, JS)에 게시
→ **다음 세션 진행법**: Chrome에 Claude 확장 연결 후 각 시 채용/오디션 게시판 방문 → 목록 URL 확보 → 새올이면 `needs_js:true`만으로, 아니면 board_url로 generic 등록. `probe_saeol.py`로 새올 여부 재확인

---

## A. JS SPA — 정적 파싱 불가, 헤드리스 렌더/내부 API 필요
| 기관 | 사이트 | probe |
|---|---|---|
| 롯데콘서트홀 | lotteconcerthall.com (`/kor/CommunityNotice`) | 목록 JS 로드, 정적 HTML 1.4KB 껍데기 |
| LG아트센터 | lgart.com | JS SPA 추정 |
| 강동아트센터 | gangdongart.or.kr | 미확인(JS 가능성) |
| 마포문화재단 | mapoart.or.kr | 미확인 |

## B. 지방 시립교향악단·예술단 — gov CMS, 게시판 위치가 사이트마다 다름
| 기관 | 지역 | 사이트(추정) | probe |
|---|---|---|---|
| 포항시립교향악단 | 경북 | 포항문화재단 phcf.or.kr | 기존 게시판 URL 404(이전됨) |
| 춘천시립교향악단 | 강원 | 춘천문화재단 / chuncheon.go.kr | 미확인 |
| 원주시립교향악단 | 강원 | wonju.go.kr | 미확인 |
| 강릉시립교향악단 | 강원 | gn.go.kr | 미확인 |
| 진주시립교향악단 | 경남 | jinju.go.kr | 정적이나 공고가 시청 통합 게시판에 묻힘 |
| 김해시립예술단 | 경남 | 김해문화재단 / gimhae.go.kr | 미확인 |
| 구미시립예술단 | 경북 | 구미문화예술회관 gumi.go.kr | 400 |
| 군산시립예술단 | 전북 | gunsan.go.kr (gsart) | 아트인포로 일부 포착됨 |
| 목포시립교향악단·예술단 | 전남 | mokpo.go.kr | 404 |
| 여수시립예술단 | 전남 | yeosu.go.kr | 미확인 |
| 제주도립예술단 | 제주 | jejuartcenter.or.kr | 접속 차단(봇) |
| 경상북도립예술단 | 경북 | gb.go.kr | 미확인 |
| 청주시립교향악단·합창단 | 충북 | cheongju.go.kr | 404 |
| 익산시립교향악단 | 전북 | iksan.go.kr | 미확인 |
| 김천시립교향악단 | 경북 | gimcheon.go.kr | 미확인 |
| 과천시립교향악단 | 경기 | 과천시립예술단 gcart.or.kr | 미확인 |
| 마산시립교향악단 | 경남 | 창원문화재단 cwcf.or.kr | **기존 창원 소스로 겸할 수 있음(확인 요)** |
| 충남교향악단(천안) | 충남 | 천안문화재단 cfac.or.kr | **기존 천안 소스로 겸할 수 있음(확인 요)** |

## C. 시립합창단 (중소도시) — 자체 게시판 소수
| 기관 | 지역 | 사이트(추정) |
|---|---|---|
| 순천시립합창단 | 전남 | 순천문화예술회관 / suncheon.go.kr |
| 경주시립합창단 | 경북 | gyeongju.go.kr |
| 안동시립합창단 | 경북 | andong.go.kr |
| 양산시립합창단 | 경남 | yangsan.go.kr |
| 남양주시립합창단 | 경기 | nyj.go.kr |
| 정읍·김제시립예술단 | 전북 | jeongeup.go.kr / gimje.go.kr |
| 속초·동해·삼척시립합창단 | 강원 | 각 시청 |
| 서귀포시립합창단 | 제주 | seogwipo.go.kr |

---
## 파서 부착에 필요한 것 (기관당)
각 기관에서 아래 하나만 확보하면 즉시 부착:
- **채용/오디션/공지 게시판의 '목록' 페이지 URL** (상세글 말고 리스트)
- 예: `https://www.○○.go.kr/…/board/list.do?bbsId=…` 또는 `…/공지사항` 목록

JS SPA(롯데·LG 등)는 목록 대신 **내부 API(JSON) URL** 또는 헤드리스 렌더가 필요.
