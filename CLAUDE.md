# 포디엄 작업 규칙

배포: GitHub Pages (clddy.github.io/classic-mule). **사이트에 보이는 변경은 커밋+푸시까지가 한 작업 단위.**

## 함정 (이미 밟아본 것)

- **분류기·추출기(순수함수) 수정 후엔 반드시 `EXT_VER`(crawler/main.py)를 올릴 것.**
  안 올리면 이전 크롤의 subject/courses/마감일이 승계되어 새 로직이 적용 안 된 것처럼 보인다.
  tier/kind/ageGroup/obri/certReq는 final 단계에서 재적용되므로 예외.
- **제목 정리(music_only_title)에서 악기명은 절대 지우지 말 것** — 바이올린·칼림바·우쿨렐레 등.
  `_OTHER_SUBJECT` 목록에 악기를 넣으면 안 된다 (사용자·동생 강조사항).
- **미분류는 미분류로 둘 것** — 추측해서 아무 태그나 넣지 않는다. 크롤 로그의 "미분류 큐"를
  보고 규칙을 보강하는 루프(참가자모집·행정직이면 제외 규칙 쪽, 진짜 공고면 분류 규칙 쪽).
- 대형 페이지(2MB+)에서 lxml이 앵커를 누락할 수 있다 → 첨부 못 찾으면 html.parser 폴백 있음.
- 태그/필드 스키마를 바꾸면 세 군데 동기화: crawler(common.py) + js/jobs.js(TIERS·매핑·필터)
  + jobs.html(폼 옵션) + js/data.js(예시글). localStorage 옛 글은 TIER_MIGRATE로 이관.

## 크롤 검증 루틴

1. `python crawler/main.py --all` (백그라운드 ~7분, hibrain 포함 전체)
2. 로그에서 `미분류 큐`·`완료:` 확인 → data/official.json에서 결과 검증
3. 프론트는 launch.json `podium` 서버로 열어 필터·패널 동작 확인
4. data 커밋+푸시 (official.json, official-data.js, coverage_report.json)

## 경계

- 자격증명은 채팅·코드·커밋에 절대 넣지 않음 — crawler/.env, tools/.env (gitignore)
- tools/(메일 발송)는 커밋하지 않기로 함 (로컬 전용)
- 국악=풍류(자매 사이트)로 분리, 실용음악·무용 제외가 포디엄 범위 정의
