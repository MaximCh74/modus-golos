"""Администрирование (замечание владельца 13.11): «Аватарки» — в левой колонке под «Заявками на награды», сетка круглых фото ~64 px с именем
(5 в ряд на компьютере, 3 на телефоне), «Убрать» — при наведении на фото (на телефоне — по нажатию), подтверждение «Да / Нет» на плитке;
две колонки кончаются примерно на одной высоте. Сервер — на демо-снапшоте (27 портретов)."""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

from mf import demo

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not demo.FIXTURE.is_file(), reason="нет снапшота demo/fixtures/mf-demo.db")


@pytest.fixture(scope="module")
def base():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui21-"), "MF_DEMO_SNAPSHOT": "1", "MF_STT": "off", "MF_STT_WARMUP": "0",
           "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "mf.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
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


_STATE: dict = {}


def _open(browser, base, width):
    phone = width < 500
    ctx = browser.new_context(viewport={"width": width, "height": 812 if phone else 900}, locale="ru-RU", is_mobile=phone, has_touch=phone,
                              service_workers="block", storage_state=_STATE.get(base))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if base not in _STATE:
        assert page.request.post(f"{base}/api/auth/login-as", data={"user_id": 15}).ok
        _STATE[base] = ctx.storage_state()
    page.goto(base + "/panel#/admin")
    page.wait_for_selector(".ava-grid")
    page.wait_for_timeout(1200)
    return ctx, page, errors


PER_ROW = "(() => { const t = [...document.querySelectorAll('.ava-tile')]; const y0 = Math.round(t[0].getBoundingClientRect().y); return t.filter(x => Math.round(x.getBoundingClientRect().y) === y0).length; })()"


def test_avatars_grid_left_under_claims_and_columns_even(base, browser):
    ctx, page, errors = _open(browser, base, 1440)
    try:
        cols = page.evaluate("""[...document.querySelectorAll('.wrap > .split > div')].map(c => ({ h: c.getBoundingClientRect().height,
          titles: [...c.children].map(x => (x.querySelector('b') || x).textContent.trim()) }))""")
        assert len(cols) == 2
        left = cols[0]["titles"]
        assert left.index("Аватарки") == left.index("Заявки на награды") + 1   # слева, сразу под «Заявками на награды»
        assert "Аватарки" not in cols[1]["titles"]
        assert abs(cols[0]["h"] - cols[1]["h"]) <= 250, cols   # колонки кончаются примерно вровень
        assert page.evaluate(PER_ROW) == 5 and page.locator(".ava-card table, .ava-card .list").count() == 0
        size = page.locator(".ava-photo .avatar").first.bounding_box()
        assert 60 <= size["width"] <= 68 and abs(size["width"] - size["height"]) < 1
        lines = page.evaluate("[...document.querySelectorAll('.ava-name')].map(n => Math.round(n.getBoundingClientRect().height / parseFloat(getComputedStyle(n).lineHeight)))")
        assert max(lines) <= 2   # имя — не больше двух строк
        n0 = page.locator(".ava-tile").count()
        assert page.evaluate("getComputedStyle(document.querySelector('.ava-remove')).opacity") == "0"
        page.locator(".ava-photo").first.hover(); page.wait_for_timeout(300)
        assert page.evaluate("getComputedStyle(document.querySelector('.ava-remove')).opacity") == "1"   # при наведении — «Убрать»
        page.locator(".ava-remove").first.click()
        assert page.locator(".ava-tile.ask .ava-ask").inner_text().startswith("Убрать фото?")
        page.locator(".ava-tile.ask button", has_text="Нет").click(); page.wait_for_timeout(200)
        assert page.locator(".ava-tile.ask").count() == 0 and page.locator(".ava-tile").count() == n0   # «Нет» — ничего не убрано
        page.locator(".ava-photo").first.hover(); page.locator(".ava-remove").first.click()
        page.locator(".ava-tile.ask button", has_text="Да").click(); page.wait_for_timeout(1200)
        assert page.locator(".ava-tile").count() == n0 - 1
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") and not errors, errors
    finally:
        ctx.close()


def test_avatars_phone_three_in_row_tap_to_remove(base, browser):
    ctx, page, errors = _open(browser, base, 375)
    try:
        page.locator(".ava-card").scroll_into_view_if_needed()
        assert page.evaluate(PER_ROW) == 3
        page.locator(".ava-photo").nth(1).tap(); page.wait_for_timeout(300)
        assert page.locator(".ava-tile.show").count() == 1 and page.locator(".ava-tile.ask").count() == 0   # первое нажатие — показать «Убрать»
        page.locator(".ava-tile.show .ava-remove").tap(); page.wait_for_timeout(200)
        assert page.locator(".ava-tile.ask .ava-ask").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") and not errors, errors
    finally:
        ctx.close()
