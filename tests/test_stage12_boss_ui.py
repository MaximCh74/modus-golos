"""«Директор в кармане» в браузере (Playwright): на телефоне 390×844 и 360×700 экран помещается без прокрутки; четыре плитки;
«Сегодня / Неделя» переключает цифры; вопрос текстом → нижний лист с ответом и списком внутри /boss; плитка «ждут вашего
решения» → список с «Принять / Отклонить»; не директору — заглушка «Только для директора»."""
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
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui12-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
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


def _open(browser, base, width, height, uid):
    ctx = browser.new_context(viewport={"width": width, "height": height}, locale="ru-RU", is_mobile=True, has_touch=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})
    page.goto(base + "/boss")
    return ctx, page, errors


FIT = "({sh: document.documentElement.scrollHeight, ih: innerHeight, sw: document.documentElement.scrollWidth, iw: innerWidth})"


@pytest.mark.parametrize("width,height", [(390, 844), (360, 700)])
def test_one_screen_without_scroll(server, browser, width, height):
    ctx, page, errors = _open(browser, server, width, height, 1)
    try:
        page.wait_for_selector(".boss-tile b:not(:has-text('…'))"); page.wait_for_timeout(300)
        m = page.evaluate(FIT)
        assert m["sh"] <= m["ih"] and m["sw"] <= m["iw"], m   # один экран, без прокрутки
        assert page.locator(".boss-tile").count() == 4 and page.locator(".boss-mic").count() == 1
        assert "Сергей Михайлович" in page.locator(".boss-greet").inner_text()
        assert not errors, errors
    finally:
        ctx.close()


def test_period_toggle_question_sheet_and_decisions(server, browser):
    ctx, page, errors = _open(browser, server, 390, 844, 1)
    try:
        page.wait_for_selector(".boss-tile b:not(:has-text('…'))")
        week = int(page.locator(".boss-tile[data-tile=new] b").inner_text())
        page.click(".seg-btn[data-period=today]"); page.wait_for_timeout(600)
        today = int(page.locator(".boss-tile[data-tile=new] b").inner_text())
        assert today <= week and "Сегодня" in page.locator(".boss-greet").inner_text()
        page.fill(".boss-ask-text", "кто просрочил"); page.click(".boss-send")
        page.wait_for_selector(".boss-sheet .boss-answer")
        assert "просрочено" in page.locator(".boss-sheet .boss-answer").inner_text().lower()
        # список — внутри /boss (замечание владельца 12.11), не ссылкой в панель
        page.click(".boss-sheet button:has-text('Просрочено ·')"); page.wait_for_selector(".boss-sheet .boss-item-btn")
        page.locator(".boss-sheet .boss-item-btn").first.click(); page.wait_for_selector(".boss-sheet .boss-card")
        assert "Отвечает" in page.locator(".boss-sheet").inner_text() and "/panel" not in page.url
        page.keyboard.press("Escape"); page.wait_for_timeout(200)
        assert page.locator(".boss-sheet").count() == 0
        page.click(".boss-tile[data-tile=decisions]"); page.wait_for_selector(".boss-sheet .boss-item")
        assert page.locator(".boss-sheet button:has-text('Принять')").count() == 2 and "A-027" in page.locator(".boss-sheet").inner_text()
        page.locator(".boss-sheet button:has-text('Отклонить')").first.click()
        page.fill(".boss-sheet .boss-reason:not(.hidden)", "Отложим до бюджета следующего квартала")
        page.locator(".boss-sheet button:has-text('Подтвердить отклонение')").first.click(); page.wait_for_timeout(800)
        assert page.locator(".boss-sheet button:has-text('Принять')").count() == 1
        page.wait_for_function("document.querySelector('.boss-tile[data-tile=decisions] b').textContent === '1'")
        page.keyboard.press("Escape"); page.wait_for_timeout(200)
        page.fill(".boss-ask-text", "закажи пиццу"); page.click(".boss-send"); page.wait_for_selector(".boss-sheet .chip")
        assert "Не понял вопрос" in page.locator(".boss-sheet").inner_text() and "/panel" not in page.locator(".boss-sheet").inner_html()   # без ссылок в панель
        assert not errors, errors
    finally:
        ctx.close()


def test_not_director_sees_gate(server, browser):
    ctx, page, errors = _open(browser, server, 390, 844, 16)
    try:
        page.wait_for_selector(".boss-gate")
        assert "Только для директора" in page.locator(".boss-gate").inner_text() and page.locator(".boss-tile").count() == 0
        assert not errors, errors
    finally:
        ctx.close()
