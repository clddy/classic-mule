# Playwright 기반 JS 렌더링 fetch — SPA/동적 게시판용
from playwright.sync_api import sync_playwright

UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

def render(url, selector=None, wait_ms=2500, click=None):
    """URL을 헤드리스 크롬으로 열고 렌더링된 HTML 반환.
    selector: 이 요소가 나타날 때까지 대기(최대 8초)
    click: 렌더 후 클릭할 셀렉터(탭 전환 등), 클릭 후 wait_ms 추가 대기
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=UA_STR, ignore_https_errors=True)
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            if selector:
                try:
                    page.wait_for_selector(selector, timeout=8000)
                except Exception:
                    pass
            page.wait_for_timeout(wait_ms)
            if click:
                try:
                    page.click(click, timeout=5000)
                    page.wait_for_timeout(wait_ms)
                except Exception:
                    pass
            return page.content()
        finally:
            browser.close()
