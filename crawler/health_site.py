# 배포된 사이트 점검 — health_check.py --site 에서 호출된다.
#
# 로컬 파일이 멀쩡해도 배포가 안 됐거나, 데이터 파일 하나가 깨져서 board 전체가
# 안 뜨는 경우를 잡는다. 뮤지션 대부분이 폰으로 보므로 모바일 렌더링도 같이 본다.
import json
from datetime import date, timedelta

import requests

BASE = "https://clddy.github.io/classic-mule"

# 데이터 파일 하나가 깨지면 그 페이지 전체가 빈 화면이 된다 — 치명적이라 개별 확인.
DATA_FILES = [
    "data/official.json",
    "data/official-data.js",
    "data/practice-seed.js",
    "data/practice-coords.js",
    "data/practice-instant.js",
    "data/practice-public.js",
    "data/practice-yeyak.js",
]

# 각 페이지에 최소한 이 요소는 있어야 '렌더된 것'으로 본다.
# v2.0(2026-07-21): lessons/market/community는 리다이렉트 스텁 — 점검 대상에서 제외
# (헤드리스가 열면 meta refresh로 index를 또 점검할 뿐이다). about·sources 신설 페이지 추가.
PAGES = [
    ("index.html", "#recent-list"),
    ("jobs.html", "#write-form"),
    ("practice.html", None),
    ("about.html", None),
    ("sources.html", "#src-rows"),
]

# 외부에서 끌어오는 것 — 우리 배포 문제가 아니므로 404 집계에서 뺀다.
EXTERNAL = ("fonts.googleapis.com", "fonts.gstatic.com", "unpkg.com",
            "cdn.jsdelivr.net", "tile.openstreetmap.org", "openstreetmap.org")


def check_deploy(rep, doc):
    """배포 성공 여부 + 데이터 파일 정상 파싱."""
    for path in DATA_FILES:
        url = f"{BASE}/{path}"
        try:
            r = requests.get(url, timeout=25)
        except Exception as e:
            rep.add("HIGH", "배포", f"{path}: 접속 실패 — {type(e).__name__}")
            continue
        if r.status_code != 200:
            rep.add("HIGH", "배포", f"{path}: HTTP {r.status_code} — 배포 누락")
            continue
        if len(r.content) < 100:
            rep.add("HIGH", "배포", f"{path}: {len(r.content)}바이트 — 비었거나 잘림")
            continue
        if path.endswith(".json"):
            try:
                json.loads(r.text)
            except Exception as e:
                rep.add("HIGH", "배포", f"{path}: JSON 파싱 실패 — {e}")

    # 배포된 데이터가 오늘 크롤 결과를 반영하고 있는가 (푸시 실패 감지)
    try:
        live = requests.get(f"{BASE}/data/official.json", timeout=25).json()
    except Exception:
        return
    live_at, local_at = live.get("collectedAt"), doc.get("collectedAt")
    if live_at and local_at and live_at < local_at:
        gap = (date.fromisoformat(local_at) - date.fromisoformat(live_at)).days
        sev = "HIGH" if gap >= 2 else "MED"
        rep.add(sev, "배포",
                f"배포된 데이터가 {live_at} (로컬 {local_at}, {gap}일 뒤처짐) — 커밋·푸시 실패 의심")


def check_pages(rep):
    """페이지별 JS 콘솔 에러 · 404 리소스 · 모바일 가로 스크롤."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for path, must in PAGES:
                _check_one(rep, browser, path, must)
            _check_submit(rep, browser)
        finally:
            browser.close()


def _check_one(rep, browser, path, must):
    ctx = browser.new_context(viewport={"width": 375, "height": 812},  # 폰 기준
                              user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                                          "Mobile/15E148 Safari/604.1"))
    page = ctx.new_page()
    errors, failed = [], []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("response", lambda r: failed.append((r.status, r.url))
            if r.status >= 400 and not any(x in r.url for x in EXTERNAL) else None)
    try:
        page.goto(f"{BASE}/{path}", timeout=45000, wait_until="networkidle")
        page.wait_for_timeout(1200)

        if must:
            # 모달 안에 있어 평소엔 숨어있는 요소가 많다 — 존재 여부만 본다
            try:
                page.wait_for_selector(must, timeout=5000, state="attached")
            except Exception:
                rep.add("HIGH", "사이트", f"{path}: 핵심 요소 {must} 없음 — 렌더 실패")

        text_len = page.evaluate("document.body.innerText.trim().length")
        if text_len < 200:
            rep.add("HIGH", "사이트", f"{path}: 본문이 사실상 빈 화면 ({text_len}자)")

        # 모바일 가로 스크롤 — 폰에서 좌우로 밀리면 바로 티나는 버그
        over = page.evaluate(
            "Math.max(0, document.documentElement.scrollWidth - window.innerWidth)")
        if over > 4:
            rep.add("MED", "모바일", f"{path}: 375px에서 가로 스크롤 {over}px 발생")

        if errors:
            rep.add("HIGH", "사이트", f"{path}: JS 에러 {len(errors)}건 — {errors[0][:110]}")
        if failed:
            st, url = failed[0]
            rep.add("MED", "사이트",
                    f"{path}: 리소스 로드 실패 {len(failed)}건 — {st} {url.replace(BASE, '')}")
    except Exception as e:
        rep.add("HIGH", "사이트", f"{path}: 열기 실패 — {type(e).__name__}: {e}")
    finally:
        ctx.close()


def _check_submit(rep, browser):
    """유저 제출 플로우 E2E — v2.0 스텝 폼(유형 선택 → 폼) 기준.

    '연주' 유형 경로로 필수 필드만 채워 등록하고 board 반영을 확인한다.
    (js/write.js 의 매트릭스 M["연주"].req 가 이 목록의 원본 — 폼 스펙이 바뀌면
    여기도 같이 바꿔야 한다. 전례 2건: 2026-07-18 옛 단일 폼 기준이 스펙 v1 배포 후
    'w-tier 사라짐' 오검출, 2026-07-21 v1 기준이 v2.0(구직 Step1 삭제) 배포 후
    "Step1 '구인' 버튼이 없다" 오검출.)
    등록된 글은 이 헤드리스 브라우저의 localStorage에만 남고 세션 종료 시 사라진다.
    """
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    marker = "헬스체크 자동 점검 공고"
    try:
        page.goto(f"{BASE}/jobs.html", timeout=45000, wait_until="networkidle")
        page.evaluate("localStorage.clear()")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(800)

        form = page.locator("#write-form")
        if form.count() == 0:
            rep.add("HIGH", "제출", "글쓰기 폼(#write-form)이 없다")
            return

        # 스텝 진입 (v2.0): 모달 열기 → 유형(연주) 선택 → 폼 조립. 구직 Step은 폐지됨.
        page.evaluate("window.PodiumWrite && PodiumWrite.reset();"
                      "document.querySelector('#write-modal').classList.add('open')")
        s2 = page.locator("#ws-2 button[data-wtype='연주']")
        if s2.count() == 0:
            rep.add("HIGH", "제출", "유형 선택의 '연주' 버튼이 없다 (스텝 폼 구조 변경?)")
            return
        s2.click()
        page.wait_for_timeout(300)

        # 연주 유형의 필수 블록이 실제로 조립됐는지 (공통 4 + 연주 매트릭스)
        for name in ("w-title", "w-region", "w-org", "w-phone",
                     "w-cat", "w-inst", "w-when", "w-pay-amt", "w-rehearsalCount"):
            if form.locator(f"[name='{name}']").count() == 0:
                rep.add("HIGH", "제출", f"필수 항목 {name}가 폼에서 사라졌다")
                return

        form.locator("[name='w-title']").fill(marker)
        form.locator("[name='w-region']").select_option("서울")
        form.locator("[name='w-org']").fill("헬스체크")
        form.locator("[name='w-phone']").fill("010-0000-0000")
        cat_opts = [v for v in form.locator("[name='w-cat'] option").evaluate_all(
            "els => els.map(e => e.value)") if v]
        if not cat_opts:
            rep.add("HIGH", "제출", "w-cat 선택지가 비었다 (유형별 옵션 주입 실패)")
            return
        form.locator("[name='w-cat']").select_option(cat_opts[0])
        # 현악 고정 — 타악·건반을 고르면 '악기 제공' 블록이 필수로 추가돼 시나리오가 달라진다
        form.locator("[name='w-inst']").select_option("현악")
        # 날짜 숫자를 넣으면 급구 힌트 경로가 끼어든다 — 숫자 없는 문구로 고정
        form.locator("[name='w-when']").fill("헬스체크 점검용 일정")
        form.locator("[name='w-pay-amt']").fill("10")
        form.locator("[name='w-rehearsalCount']").fill("1")

        submit = page.locator("#wf-submit")
        if submit.is_disabled():
            rep.add("HIGH", "제출", "필수를 다 채웠는데 등록 버튼이 비활성 — validate() 로직 확인")
            return
        submit.click()
        page.wait_for_timeout(1200)

        # 저장 → 완료 화면 미리보기 → (닫은 뒤) 목록 반영을 따로 본다.
        # 목록(#job-list)을 콕 집어 확인해야 한다 — body 전체를 보면 완료 화면에
        # 제목이 떠 있는 것만으로 통과해서, 목록 렌더가 죽어도 못 잡는다.
        stored = page.evaluate(
            "JSON.parse(localStorage.getItem('podium_user_posts_v2') || '[]').length")
        in_preview = page.evaluate(
            "(m) => (document.querySelector('#wd-preview')?.innerText || '').includes(m)", marker)
        if stored < 1:
            rep.add("HIGH", "제출", "등록 후 localStorage에 공고가 저장되지 않았다")
            return
        if not in_preview:
            rep.add("MED", "제출", "등록 후 완료 화면 미리보기(#wd-preview)에 글이 안 보인다")
        page.locator("#wd-close").click()
        page.wait_for_timeout(500)
        in_list = page.evaluate(
            "(m) => (document.querySelector('#job-list')?.innerText || '').includes(m)", marker)
        if not in_list:
            rep.add("HIGH", "제출", "등록은 됐으나 목록(#job-list)에 반영되지 않았다")
        if errors:
            rep.add("HIGH", "제출", f"제출 중 JS 에러 — {errors[0][:110]}")
    except Exception as e:
        rep.add("HIGH", "제출", f"제출 플로우 점검 실패 — {type(e).__name__}: {e}")
    finally:
        ctx.close()


def check_site(rep, doc):
    check_deploy(rep, doc)
    check_pages(rep)
