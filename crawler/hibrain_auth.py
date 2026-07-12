#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""하이브레인넷(대학 채용 포털) 로그인 세션 관리 + 인증 상태 fetch.

하이브레인은 로그인해야 채용 상세(본문·마감·기관·원문링크)가 보인다.
세션 유지 3중 방어:
  1) 로그인 시 '자동로그인'(isAutoSignin) 체크 → 영구 쿠키 발급
  2) 그래도 만료되면 crawler/.env 의 HIBRAIN_ID/HIBRAIN_PW 로 자동 재로그인
     (하이브레인 로그인 폼은 CAPTCHA 없음 — 단순 POST)
  3) 자동 재로그인까지 실패하면 텔레그램 알림 후 수집 스킵
.env 는 사용자가 직접 작성(gitignore) — 자격증명은 채팅·코드에 절대 넣지 않는다.
"""
import pathlib, time, sys, os

HERE = pathlib.Path(__file__).resolve().parent
PROFILE = str(HERE / ".hibrain-profile")   # 로그인 세션 본체 (.gitignore)
OK_MARK = HERE / ".hibrain-ok"             # 마지막 로그인 확인 시각 (.gitignore)
COOKIES_JSON = HERE / ".hibrain-cookies.json"  # 세션 쿠키 백업 (.gitignore)
ENV_FILE = HERE / ".env"                   # HIBRAIN_ID / HIBRAIN_PW (.gitignore)
LOGIN_URL = "https://www.hibrain.net/logins/signin"
LIST_URL = "https://www.hibrain.net/recruitment"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# 로그인 안 된 상세 페이지에 나오는 문구 (세션 만료 감지용)
LOGGED_OUT_MARK = "로그인후에 이용"


def _load_env():
    env = {}
    if ENV_FILE.exists():
        for ln in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _notify(msg):
    """텔레그램 알림 (@podiumalarmE_bot) — 실패해도 크롤은 계속."""
    try:
        sys.path.insert(0, r"C:\ohai\telegram-notify")
        from notify import send
        send(f"[포디엄] {msg}")
    except Exception:
        pass


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


def _auto_relogin(page):
    """.env 자격증명으로 헤드리스 자동 재로그인. 성공 True.
    (하이브레인 로그인 폼: userid/passwd POST, CAPTCHA 없음 — 2026-07 확인)"""
    env = _load_env()
    uid, pw = env.get("HIBRAIN_ID"), env.get("HIBRAIN_PW")
    if not (uid and pw):
        return False
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(800)
        try:
            page.check("#isAutoSignin", timeout=3000, force=True)   # 자동로그인 → 영구 쿠키
        except Exception:
            pass
        page.fill("#userid", uid)
        page.fill("#passwd", pw)
        page.click("#submit-btn")
        page.wait_for_timeout(2500)
        if _logged_in(page):
            OK_MARK.write_text(time.strftime("%Y-%m-%d %H:%M") + " (auto)",
                               encoding="utf-8")
            try:
                import json
                COOKIES_JSON.write_text(
                    json.dumps(page.context.cookies(), ensure_ascii=False),
                    encoding="utf-8")
            except Exception:
                pass
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
        # '자동로그인' 체크 → 영구 쿠키 발급 (세션 쿠키만 받아 하루 만에 풀리는 것 방지)
        try:
            page.check("#isAutoSignin", timeout=3000, force=True)
            print("  [i] '자동로그인' 체크함 (세션 영구 유지)")
        except Exception:
            print("  [i] 자동로그인 체크박스를 못 찾음 — 화면에서 직접 체크해 주세요")
        # .env 자격증명이 있으면 아이디/비번 자동 입력 (제출은 사람이 확인)
        env = _load_env()
        if env.get("HIBRAIN_ID") and env.get("HIBRAIN_PW"):
            try:
                page.fill("#userid", env["HIBRAIN_ID"])
                page.fill("#passwd", env["HIBRAIN_PW"])
                page.click("#submit-btn")
                print("  [i] .env 자격증명으로 자동 로그인 시도")
            except Exception:
                pass
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
                _load_cookies(ctx)   # 1차: 백업 쿠키 주입
            if not _logged_in(page) and not _auto_relogin(page):  # 2차: 자동 재로그인
                print("[WARN] 하이브레인 세션 만료 + 자동 재로그인 실패 — 수집 건너뜀. "
                      "`python hibrain_auth.py`로 다시 로그인하세요.")
                _notify("하이브레인 세션 만료 — 자동 재로그인 실패. "
                        "PC에서 `python crawler/hibrain_auth.py` 실행해 재로그인 필요 "
                        "(대학 채용 수집이 멈춰 있음)")   # 3차: 알림
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
            return _logged_in(page) or _auto_relogin(page)
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(0 if setup() else 1)
