"""Меню пользователя во всех шапках (замечание владельца 13.11): кнопка «Имя · роль» → «Сменить пользователя», «Выйти»; в демо — «Быстро
войти как» (директор, ответственный, сотрудник, администратор): переключение в два нажатия, сразу на стартовый экран роли; «Выйти» —
с любой страницы; главная после входа остаётся главной; переключение с открытой демо-сессии не упирается в лимит входов."""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def base():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui23-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "mf.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/api/health", timeout=1).read()
                break
            except Exception:   # noqa: BLE001
                time.sleep(0.2)
        else:
            raise RuntimeError("сервер не поднялся")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:   # noqa: BLE001
            pytest.skip(f"нет Chromium для Playwright: {e}")
        yield b
        b.close()


def _ctx(browser, width):
    phone = width < 500
    return browser.new_context(viewport={"width": width, "height": 844 if phone else 900}, locale="ru-RU", is_mobile=phone, has_touch=phone,
                               service_workers="block", reduced_motion="reduce")


def _switch(page, name):
    if page.locator(".user-btn:visible").count():
        page.locator(".user-btn:visible").first.click()   # нажатие 1 — меню
        page.locator(".user-wrap.open .um-quick", has_text=name).click()   # нажатие 2 — вход под ним
    else:   # панель на телефоне: меню пользователя — в «☰»
        page.locator(".nav-toggle").click()
        page.locator(".nav-panel.open .um-quick", has_text=name).click()


def _at(page, path, hash_=""):
    from urllib.parse import urlparse
    page.wait_for_url(lambda u: urlparse(u).path == path and urlparse(u).fragment.startswith(hash_.lstrip("#")), timeout=60000, wait_until="commit")


@pytest.mark.parametrize("width", [1440, 390])
def test_switch_director_employee_admin_in_two_clicks(base, browser, width):
    ctx = _ctx(browser, width)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        assert page.request.post(f"{base}/api/auth/login-as", data={"user_id": 23}).ok   # Кирилл, сотрудник
        page.goto(base + "/"); page.wait_for_selector(".user-btn")
        assert page.evaluate("location.pathname") == "/"   # главная после входа остаётся главной
        assert page.locator(".user-btn").inner_text().replace("\n", " ").startswith("Кирилл")
        for name, path, hash_ in (("Сергей Михайлович", "/panel", "#/summary"), ("Сауле Абишева", "/app", ""), ("Игорь Лебедев", "/panel", "#/admin")):
            _switch(page, name)
            _at(page, path, hash_)
            page.wait_for_selector(".user-btn:visible" if width > 900 or path != "/panel" else ".nav-toggle"); page.wait_for_timeout(300)
            me = page.evaluate("API.me().then(m => m.name)")
            assert me == name, (me, name)
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("path,uid", [("/", 23), ("/app", 23), ("/panel#/summary", 1), ("/boss", 1)])
def test_logout_from_any_page(base, browser, path, uid):
    ctx = _ctx(browser, 1440)
    page = ctx.new_page()
    try:
        assert page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid}).ok
        page.goto(base + path); page.wait_for_selector(".user-btn:visible"); page.wait_for_timeout(300)
        page.locator(".user-btn:visible").first.click()
        menu = page.locator(".user-wrap.open .user-menu")
        assert "Сменить пользователя" in menu.inner_text() and "Быстро войти как" in menu.inner_text()
        menu.locator(".um-item", has_text="Выйти").click()
        _at(page, "/"); page.wait_for_selector(".site-head a:has-text('Войти')", timeout=60000)
        assert page.evaluate("fetch('/api/me').then(r => r.status)") == 401
    finally:
        ctx.close()


def test_quick_block_hidden_without_demo_login_and_login_returns_home(base, browser):
    ctx = _ctx(browser, 1440)
    page = ctx.new_page()
    try:
        page.goto(base + "/login?next=/"); page.wait_for_timeout(800)
        page.locator("text=Кирилл Смирнов").first.click()
        _at(page, "/"); page.wait_for_selector(".user-btn")   # вход с главной — обратно на главную
        n = page.evaluate("""(async () => { _cfgP = Promise.resolve({ demo_login: false }); const me = await API.me(); const box = userMenuItems(me);
          await new Promise(r => setTimeout(r, 50)); return [box.querySelectorAll('.um-quick').length, box.textContent.includes('Выйти')]; })()""")
        assert n == [0, True]   # в пилоте (демо-вход выключен) — только «Сменить пользователя» и «Выйти»
    finally:
        ctx.close()


def test_switching_with_demo_session_not_rate_limited(base, browser):
    """Новые входы с одного адреса ограничены (аудит), переключение с уже открытой демо-сессии — нет: сессия заменяется, не копится."""
    lead = _ctx(browser, 1440)   # ведущий: демо-сессия открыта заранее
    fresh = _ctx(browser, 1440)
    try:
        assert lead.request.post(f"{base}/api/auth/login-as", data={"user_id": 1}).ok
        codes = []
        for _ in range(35):   # без cookie — каждый раз новый вход
            codes.append(fresh.request.post(f"{base}/api/auth/login-as", data={"user_id": 23}).status)
            fresh.clear_cookies()
        assert 429 in codes   # лимит на новые входы работает
        ok = sum(lead.request.post(f"{base}/api/auth/login-as", data={"user_id": uid}).ok for uid in (2, 6, 15, 1) * 9)
        assert ok == 36   # 36 переключений подряд — ни одного отказа, хотя лимит новых входов исчерпан
    finally:
        lead.close(); fresh.close()
