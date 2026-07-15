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
PAGES = [
    ("index.html", None),
    ("jobs.html", "#write-form"),
    ("practice.html", None),
    ("lessons.html", None),
    ("market.html", None),
    ("community.html", None),
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
    """유저 제출 플로우 E2E — 폼을 실제로 채워 등록하고 board 반영을 확인한다.

    등록된 글은 이 헤드리스 브라우저의 localStorage에만 남고 세션 종료 시 사라진다
    (공고는 애초에 기기 로컬 저장 — 공유 백엔드 없음).
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

        # 모달을 연 뒤 required 항목만 채운다 (선택은 첫 유효 옵션)
        page.evaluate("document.querySelector('#write-modal').classList.add('open')")
        for name in ("w-tier", "w-cat", "w-inst", "w-region"):
            sel = form.locator(f"select[name='{name}']")
            if sel.count() == 0:
                rep.add("HIGH", "제출", f"필수 항목 {name}가 폼에서 사라졌다")
                return
            opts = [v for v in sel.locator("option").evaluate_all(
                "els => els.map(e => e.value)") if v]
            if not opts:
                rep.add("HIGH", "제출", f"{name} 선택지가 비었다")
                return
            sel.select_option(opts[0])
        form.locator("input[name='w-title']").fill(marker)
        form.locator("input[name='w-org']").fill("헬스체크")
        form.locator("textarea[name='w-body']").fill("자동 점검용 글입니다.")

        form.locator("button[type='submit']").click()
        page.wait_for_timeout(1200)

        # 저장 / 목록 반영 / 상세 열림을 따로 본다.
        # 목록(#job-list)을 콕 집어 확인해야 한다 — body 전체를 보면 상세 모달에
        # 제목이 떠 있는 것만으로 통과해서, 목록 렌더가 죽어도 못 잡는다.
        stored = page.evaluate(
            "JSON.parse(localStorage.getItem('podium_user_posts_v2') || '[]').length")
        in_list = page.evaluate(
            "(m) => (document.querySelector('#job-list')?.innerText || '').includes(m)", marker)
        in_detail = page.evaluate(
            "(m) => (document.querySelector('#detail-modal')?.innerText || '').includes(m)", marker)
        if stored < 1:
            rep.add("HIGH", "제출", "등록 후 localStorage에 공고가 저장되지 않았다")
        elif not in_list:
            rep.add("HIGH", "제출", "등록은 됐으나 목록(#job-list)에 반영되지 않았다")
        elif not in_detail:
            rep.add("MED", "제출", "등록 후 상세 모달이 열리지 않았다")
        if errors:
            rep.add("HIGH", "제출", f"제출 중 JS 에러 — {errors[0][:110]}")
    except Exception as e:
        rep.add("HIGH", "제출", f"제출 플로우 점검 실패 — {type(e).__name__}: {e}")
    finally:
        ctx.close()


def check_site(rep, doc):
    check_deploy(rep, doc)
    check_pages(rep)
