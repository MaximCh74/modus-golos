"""Этап 9 (упрощение): таблица очереди никогда не шире контейнера и страница — без горизонтальной прокрутки на 1280, 1440 и во фрейме
(compact); карточка при недостатке ширины открывается панелью поверх таблицы, а на широком экране — справа; главная директора — четыре
плитки и строка «Требуют внимания». Нужны Playwright и Chromium (локально есть); без них тест пропускается. Сервер поднимается
отдельным процессом на свободном порту со своей базой."""
import os
import socket
import subprocess
import sys
import tempfile
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
def server():
    port = _free_port()
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "mf.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1).read()
                break
            except Exception:   # noqa: BLE001
                time.sleep(0.2)
        else:
            raise RuntimeError("сервер не поднялся")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:   # noqa: BLE001
            pytest.skip(f"нет Chromium для Playwright: {e}")
        yield b
        b.close()


MEASURE = """() => { const t = document.querySelector('#queue-table .tbl'); const c = document.querySelector('#queue-table .card');
  return {doc: document.documentElement.scrollWidth, vw: window.innerWidth, table: t ? t.scrollWidth : 0, container: c ? c.clientWidth : 0,
          drawer: !!document.querySelector('.drawer .appeal-card'), side: !!document.querySelector('#card .appeal-card')}; }"""


def _open(browser, base, width, path="/panel#/queue", uid=1):
    ctx = browser.new_context(viewport={"width": width, "height": 860}, locale="ru-RU")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})
    page.goto(base + path)
    page.wait_for_selector("table")
    page.wait_for_timeout(300)
    return ctx, page, errors


@pytest.mark.parametrize("width,path,expect_side", [(1280, "/panel#/queue", False), (1440, "/panel#/queue", False), (1600, "/panel#/queue", True), (1100, "/panel?compact=1#/queue", False)])
def test_queue_no_horizontal_scroll_and_card_placement(server, browser, width, path, expect_side):
    ctx, page, errors = _open(browser, server, width, path)
    try:
        m = page.evaluate(MEASURE)
        assert m["doc"] <= width and m["table"] <= m["container"], m   # правило 1: нет горизонтальной прокрутки
        assert page.locator("table thead th").count() == 4   # четыре колонки по умолчанию
        page.click("tbody tr >> nth=0")
        page.wait_for_selector(".appeal-card")
        m = page.evaluate(MEASURE)
        assert m["doc"] <= width and m["table"] <= m["container"], m   # таблица не сжимается из-за карточки
        assert m["side"] == expect_side and m["drawer"] == (not expect_side), m
        assert page.locator(".appeal-card .btn-primary").count() == 1   # одна главная кнопка
        if not expect_side:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            assert not page.evaluate(MEASURE)["drawer"]   # Esc закрывает панель
        if "compact" in path:
            assert page.evaluate("getComputedStyle(document.querySelector('.topbar .brand')).display") == "none"   # во фрейме без нашей шапки
        assert not errors, errors
    finally:
        ctx.close()


def test_director_home_four_tiles_and_attention_line(server, browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="ru-RU")
    page = ctx.new_page()
    try:
        page.request.post(f"{server}/api/auth/login-as", data={"user_id": 1})
        page.goto(server + "/panel#/summary")
        page.wait_for_selector(".kpis")
        page.wait_for_timeout(500)
        assert page.locator(".kpi").count() == 4
        assert page.locator(".attention").count() >= 1 and "Требуют внимания" in page.locator(".attention").first.inner_text()
        assert page.evaluate("document.documentElement.scrollWidth") <= 1280
        assert page.locator(".summary-ai > p").count() <= 3   # сводка — до трёх строк (остальное свёрнуто за «ещё»)
        assert "демо" not in page.locator(".topbar").inner_text()   # слово «демо» — только в подвале
        assert "демо" in page.locator("#foot").inner_text()
    finally:
        ctx.close()
