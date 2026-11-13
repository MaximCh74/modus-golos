"""Вход внутри фрейма портала в Firefox при заблокированных сторонних cookie (симптом владельца: «auth2.bitrix24.net will not allow
Firefox to display the page if another site has embedded it» — приложение уходило на OAuth-вход прямо во фрейме).
Эмуляция без портала: отдельный сервер приложения с BITRIX_PORTAL=http://127.0.0.1:<порт родителя>, родительская страница с iframe на
/bitrix/app?s=<токен> (так открывает фрейм портал после POST AUTH_ID), Firefox с network.cookie.cookieBehavior=1 (сторонние cookie запрещены).
Проверяем: панель открылась; переход на /app внутри фрейма — вход сохранён; перезагрузка фрейма — вход сохранён; выход → страница входа без
кнопки «Войти через Битрикс24» и с подсказкой; /bitrix/login из фрейма — страница восстановления, никакого редиректа на портал/auth2."""
import http.server
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def stack():
    parent_port, app_port = _free_port(), _free_port()
    app_base = f"http://127.0.0.1:{app_port}"
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ff-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": "",
           "BITRIX_PORTAL": f"http://127.0.0.1:{parent_port}", "BITRIX_CLIENT_ID": "local.test", "BITRIX_CLIENT_SECRET": "x"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "mf.main:app", "--host", "127.0.0.1", "--port", str(app_port), "--log-level", "warning"], cwd=ROOT, env=env)

    class Parent(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            import urllib.parse as up
            src = app_base + up.unquote(self.path.split("?src=", 1)[1]) if "?src=" in self.path else app_base + "/bitrix/app"
            body = f"<!doctype html><meta charset='utf-8'><title>portal</title><h1>Портал</h1><iframe id='app' src='{src}' width='1100' height='800'></iframe>".encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):   # noqa: D401 — тихо
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", parent_port), Parent)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(app_base + "/api/health", timeout=1).read()
                break
            except Exception:   # noqa: BLE001
                time.sleep(0.2)
        else:
            raise RuntimeError("сервер не поднялся")
        yield {"app": app_base, "parent": f"http://127.0.0.1:{parent_port}"}
    finally:
        srv.shutdown(); proc.terminate(); proc.wait(timeout=10)


def test_frame_login_survives_navigation_reload_and_logout_in_firefox(stack):
    import json
    import urllib.parse
    # сессия как после POST AUTH_ID от портала (303 → /bitrix/app?s=<токен>): берём токен через демо-вход директора
    req = urllib.request.Request(stack["app"] + "/api/auth/login-as", data=json.dumps({"user_id": 1}).encode(), headers={"Content-Type": "application/json"})
    cookie = urllib.request.urlopen(req).headers.get("set-cookie", "")
    token = cookie.split("mf_sid=")[1].split(";")[0]
    with playwright.sync_playwright() as p:
        try:
            browser = p.firefox.launch(firefox_user_prefs={"network.cookie.cookieBehavior": 1})   # сторонние cookie запрещены
        except Exception as e:   # noqa: BLE001
            pytest.skip(f"нет Firefox для Playwright: {e}")
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(stack["parent"] + "/?src=" + urllib.parse.quote(f"/bitrix/app?s={token}"))
        frame = page.frames[1]
        frame.wait_for_selector(".topbar .nav a", timeout=20000)
        assert "Очередь" in frame.inner_text(".topbar")
        assert frame.evaluate("document.documentElement.classList.contains('compact')")   # компактный режим во фрейме
        # переход внутри фрейма на /app (ссылка «Приложение») — без cookie третьей стороны вход должен сохраниться через sessionStorage
        frame.click(".topbar a[href='/app']")
        frame.wait_for_selector(".topbar", timeout=20000)
        frame.wait_for_timeout(800)
        assert "/app" in frame.url and "/login" not in frame.url, frame.url
        assert "Мои обращения" in frame.inner_text("body")
        # перезагрузка фрейма — тоже без потери входа
        frame.evaluate("location.reload()")
        page.wait_for_timeout(1500)
        frame = page.frames[1]
        frame.wait_for_selector(".topbar", timeout=20000); frame.wait_for_timeout(800)
        assert "/login" not in frame.url and "Мои обращения" in frame.inner_text("body")
        # выход: страница входа внутри фрейма без кнопки OAuth, с подсказкой «откройте из меню портала»
        if frame.locator(".topbar .user-btn").is_visible():   # меню пользователя (13.11): «Сменить пользователя»
            frame.click(".topbar .user-btn")
        else:
            frame.click(".topbar .nav-toggle")
        frame.click(".user-wrap.open .um-item:has-text('Сменить пользователя'), .nav-panel.open .um-item:has-text('Сменить пользователя')")
        frame.wait_for_selector(".user-grid", timeout=20000)
        frame.click("button:has-text('Выйти')")
        page.wait_for_timeout(1500)
        frame = page.frames[1]
        frame.wait_for_selector(".user-grid", timeout=20000)
        text = frame.inner_text("body")
        assert "Войти через Битрикс24" not in text and "Откройте «Модус Голос» из левого меню" in text
        # прямой заход на /bitrix/login из фрейма — страница восстановления, не редирект на портал
        resp = frame.goto(stack["app"] + "/bitrix/login")
        assert resp is not None and resp.status == 200, resp and resp.status   # страница-развилка, не редирект на портал
        frame = page.frames[1]
        frame.wait_for_selector("text=Сессия не найдена", timeout=10000)   # во фрейме → /bitrix/app (восстановление), не OAuth портала
        assert "/bitrix/app" in page.frames[1].url and "auth2" not in page.frames[1].url and "/oauth/" not in page.frames[1].url
        assert not errors, errors
        browser.close()
