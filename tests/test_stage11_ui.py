"""Пункт 1 очереди 12.11 в браузере (Playwright, как test_stage9_ui): подсказки «?» на сводке открываются поповером и закрываются Esc,
«Справка» в панели показывает разделы и подсвечивает термин из ссылки, у сотрудника на главной «Мои поручения» со счётчиком;
горизонтальной прокрутки нет ни на 1280, ни на телефоне."""
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
TRANSCRIPT = open(ROOT / "tests" / "test_stage2.py", encoding="utf-8").read().split('TRANSCRIPT = """')[1].split('"""')[0]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui11-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
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


def _page(browser, base, width, height, uid, path, mobile=False):
    ctx = browser.new_context(viewport={"width": width, "height": height}, locale="ru-RU", is_mobile=mobile, has_touch=mobile)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})
    page.goto(base + path)
    return ctx, page, errors


def test_help_popovers_and_help_page(server, browser):
    ctx, page, errors = _page(browser, server, 1280, 860, 1, "/panel#/summary")
    try:
        page.wait_for_selector(".kpis"); page.wait_for_timeout(500)
        assert page.locator(".kpi .help-btn").count() == 4   # «?» у каждой метрики
        assert page.locator(".attention .help-btn").count() >= 1   # и у строки «Требуют внимания»
        page.click(".help-btn[data-term=kpi_considered]")
        page.wait_for_selector(".help-wrap.open .help-pop")
        pop = page.locator(".help-wrap.open .help-pop")
        assert "Доля рассмотренных" in pop.inner_text() and "первый ответ" in pop.inner_text()
        box = pop.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 1280   # поповер не выходит за экран
        assert page.evaluate("document.documentElement.scrollWidth") <= 1280
        page.keyboard.press("Escape"); page.wait_for_timeout(200)
        assert page.locator(".help-wrap.open").count() == 0
        page.click(".help-btn[data-term=attention]")
        page.click(".help-wrap.open .help-pop a")   # «Подробнее в справке»
        page.wait_for_selector("#help-body")
        assert page.locator("#help-body .card").count() >= 7
        assert page.locator(".help-term.hit b").first.inner_text().startswith("Требуют внимания")
        page.fill("input[aria-label='Поиск по справке']", "первого ответа"); page.wait_for_timeout(200)
        assert 2 <= page.locator(".help-term").count() < 20 and "Срок первого ответа" in page.locator("#help-body").inner_text()   # поиск сужает список
        assert not errors, errors
    finally:
        ctx.close()


def test_employee_home_my_tasks_counter_phone(server, browser):
    ctx, page, errors = _page(browser, server, 390, 844, 2, "/app", mobile=True)
    try:
        page.wait_for_selector("#my-tasks")
        assert "невыполненных нет" in page.locator("#my-tasks").inner_text() and page.locator("#my-tasks .count").count() == 0   # нули не показываем
        # планёрка Олега → поручение Ерлану; у Ерлана на главной счётчик 1
        r = page.request.post(f"{server}/api/meetings", form={"title": "Планёрка", "transcript": TRANSCRIPT})
        mid = r.json()["id"]
        for _ in range(100):   # разбор идёт в фоне сервера — ждём статус «На проверке»
            if page.request.get(f"{server}/api/meetings/{mid}").json()["status"] == "review":
                break
            page.wait_for_timeout(200)
        assert page.request.post(f"{server}/api/meetings/{mid}/send").ok
        page.request.post(f"{server}/api/auth/login-as", data={"user_id": 3})
        page.goto(server + "/app"); page.wait_for_selector("#my-tasks .count")
        assert page.locator("#my-tasks .count").inner_text() == "1" and "1 невыполненное" in page.locator("#my-tasks").inner_text()
        assert page.locator("#bottom-nav .bn-item[href='#/tasks'] .n").inner_text() == "1"   # телефон: счётчик в нижней панели (13.11, п. 6)
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        page.click("#my-tasks"); page.wait_for_selector("text=Поручения с совещаний")
        page.click(".help-btn[data-term=my_tasks]"); page.wait_for_selector(".help-wrap.open .help-pop")
        box = page.locator(".help-wrap.open .help-pop").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390
        assert not errors, errors
    finally:
        ctx.close()
