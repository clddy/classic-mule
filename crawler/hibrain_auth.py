#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""하이브레인넷(대학 채용 포털) 로그인 세션 관리 + 인증 상태 fetch.

하이브레인은 로그인해야 채용 상세(본문·마감·기관·원문링크)가 보인다.
사람이 1회 `python hibrain_auth.py` 로 로그인하면 세션이 프로필에 저장되고,
이후 크롤러(sources_hibrain.py)가 그 세션으로 헤드리스 수집한다.
로그인은 절대 자동화하지 않는다(CAPTCHA/2차인증은 사람이 화면에서).
"""
import pathlib, time, sys

HERE = pathlib.Path(__file__).resolve().parent
PROFILE = str(HERE / ".hibrain-profile")   # 로그인 세션 본체 (.gitignore)
OK_MARK = HERE / ".hibrain-ok"             # 마지막 로그인 확인 시각 (.gitignore)
COOKIES_JSON = HERE / ".hibrain-cookies.json"  # 세션 쿠키 백업 (.gitignore)
LOGIN_URL = "https://www.hibrain.net/logins/signin"
LIST_URL = "https://www.hibrain.net/recruitment"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# 로그인 안 된 상세 페이지에 나오는 문구 (세션 만료 감지용)
LOGGED_OUT_MARK = "로그인후에 이용"


def launch(p, headless=True):
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE, headless=headless, channel="chrome",
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        user_agent=UA)
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return ctx


def _logged_in(page):
    """리스트 페이지에 '로그아웃' 링크가 있으면 로그인 상태.
    ('마이메뉴' 등은 로그아웃 상태에도 있어 오탐 → 오직 '로그아웃'만 신뢰)."""
    try:
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)
        return "로그아웃" in page.content()
    except Exception:
        return False


def _load_cookies(ctx):
    """백업해둔 세션 쿠키를 컨텍스트에 주입 (프로필이 세션쿠키를 못 살렸을 때 대비)."""
    if COOKIES_JSON.exists():
        try:
            import json
            ctx.add_cookies(json.loads(COOKIES_JSON.read_text(encoding="utf-8")))
            return True
        except Exception:
            pass
    return False


def setup():
    """사람이 1회 실행 — 창이 뜨면 화면에서 로그인. 완료되면 세션 저장."""
    from playwright.sync_api import sync_playwright
    print(f"[..] 하이브레인넷 로그인 창을 띄웁니다. 프로필: {PROFILE}")
    with sync_playwright() as p:
        ctx = launch(p, headless=False)      # 창 표시 — 사람이 로그인
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("  [i] 화면의 하이브레인넷 창에서 로그인하세요. (아이디/비번, 필요시 인증)")
        print("  [i] 로그인 완료까지 최대 10분 대기합니다...")
        ok = False
        for _ in range(120):
            time.sleep(5)
            if _logged_in(page):
                ok = True
                break
        if ok:
            OK_MARK.write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
            try:
                import json
                COOKIES_JSON.write_text(
                    json.dumps(ctx.cookies(), ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            print("[OK] 로그인 성공 — 세션 저장 완료. 이제 크롤러가 대학 채용을 수집합니다.")
        else:
            print("[ERR] 로그인 확인 실패(시간초과). 다시 실행해 주세요.", file=sys.stderr)
        ctx.close()
        return ok


def fetch_many(urls, wait_ms=1400):
    """저장된 세션으로 여러 URL을 로그인 상태 HTML로 반환(dict url->html).
    세션이 만료됐으면 빈 dict + 경고(호출측이 스킵)."""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        ctx = launch(p, headless=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if not _logged_in(page):
                _load_cookies(ctx)   # 프로필이 세션쿠키를 못 살렸으면 백업 주입
            if not _logged_in(page):
                print("[WARN] 하이브레인 세션 만료/미로그인 — 수집 건너뜀. "
                      "`python hibrain_auth.py`로 다시 로그인하세요.")
                return {}
            for u in urls:
                try:
                    page.goto(u, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(wait_ms)
                    out[u] = page.content()
                except Exception:
                    continue
        finally:
            ctx.close()
    return out


def is_authenticated():
    """세션이 살아있는지 빠르게 확인(헤드리스)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = launch(p, headless=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if _logged_in(page):
                return True
            _load_cookies(ctx)
            return _logged_in(page)
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(0 if setup() else 1)
