"""Обратная связь от клиентов в браузере (решение владельца 13.11, минимум): форма /c на компьютере и телефоне — переключатель
«Благодарность / Вопрос / Замечание», город из ссылки, контакт только с галочкой согласия, ловушка для ботов скрыта, после отправки
«Спасибо, ваше сообщение получено»; в панели вкладка «От клиентов» сразу после «Очереди» — у директора и администратора, список новые
сверху, нажатие — полный текст и фото; у ответственного вкладки нет. Без горизонтальной прокрутки."""
import io
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
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui25-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
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
                               service_workers="block")


def _png(path: Path) -> Path:
    from PIL import Image
    Image.new("RGB", (64, 48), (30, 60, 120)).save(path, "PNG")
    return path


@pytest.mark.parametrize("width", [1440, 390, 360])
def test_client_form_send_with_contact_and_consent(base, browser, width, tmp_path):
    ctx = _ctx(browser, width)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(base + "/c?city=" + "Атырау, объект ТЭЦ-2"); page.wait_for_selector(".client-form")
        thanks = "Спасибо" if width < 500 else "Благодарность"   # на телефоне «Благодарность» не влезала (13.11)
        assert page.locator(".type-switch .btn").all_inner_texts() == [thanks, "Вопрос", "Замечание"]
        assert page.locator(".type-switch .btn.on").inner_text() == thanks
        assert page.input_value("input[name=place]") == "Атырау, объект ТЭЦ-2"
        hp = page.locator("input[name=website]").bounding_box()
        assert hp is None or hp["x"] + hp["width"] < 0   # ловушка для ботов не видна человеку
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.evaluate("[...document.querySelectorAll('.type-switch .btn')].every(b => b.scrollWidth <= b.clientWidth)")   # слова не режутся
        page.locator(".type-switch .btn", has_text="Замечание").click()
        page.fill("textarea[name=text]", f"Шкаф управления насосами гудит после пусконаладки ({width})")
        page.fill("input[name=name]", "Ерлан"); page.fill("input[name=contact]", "+7 700 000 00 00")
        page.locator(".client-form button[type=submit]").click(); page.wait_for_timeout(300)
        assert "согласие" in page.locator(".toast").inner_text() and page.locator(".client-form").count() == 1   # без галочки — не отправляем
        page.locator("input[name=consent]").check()
        page.set_input_files(".client-form input[type=file]", str(_png(tmp_path / "shkaf.png")))
        page.locator(".client-form button[type=submit]").click()
        page.wait_for_selector(".card-ok")
        assert page.locator(".card-ok .h1").inner_text() == "Спасибо, ваше сообщение получено"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") and not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_panel_clients_tab_for_director_and_admin(base, browser, width):
    for uid in (1, 15):
        ctx = _ctx(browser, width)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            assert page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid}).ok
            page.goto(base + "/panel#/clients"); page.wait_for_selector("table.tbl.clients tbody tr")
            nav = page.evaluate("[...document.querySelectorAll('.nav a, .nav-panel a')].map(a => a.textContent)")
            assert "От клиентов" in nav and nav.index("От клиентов") == nav.index("Очередь") + 1, nav
            api = page.evaluate("API.get('/api/panel/client-messages')")["items"]
            rows = page.locator("table.tbl.clients tbody tr")
            assert rows.count() == len(api) >= 2
            assert api[0]["created_at"] >= api[-1]["created_at"]   # новые сверху
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            first = next(i for i, m in enumerate(api) if m["photo_url"])
            rows.nth(first).click(); page.wait_for_selector(".drawer .cm-detail")
            assert page.locator(".drawer .cm-full").inner_text() == api[first]["text"] and "замечание" in page.locator(".drawer").inner_text()
            page.locator(".drawer .cm-photo").wait_for()
            for _ in range(40):   # фото догрузилось (wait_for_function строкой не пускает CSP страницы)
                if page.evaluate("document.querySelector('.drawer .cm-photo').naturalWidth > 0"):
                    break
                page.wait_for_timeout(100)
            assert page.evaluate("document.querySelector('.drawer .cm-photo').naturalWidth > 0")
            assert page.locator(".drawer a[href^='tel:']").count() == 1   # контакт — ссылкой «позвонить»
            assert not errors, errors
        finally:
            ctx.close()


def test_no_clients_tab_for_responsible(base, browser):
    ctx = _ctx(browser, 1440)
    page = ctx.new_page()
    try:
        assert page.request.post(f"{base}/api/auth/login-as", data={"user_id": 2}).ok
        page.goto(base + "/panel#/clients"); page.wait_for_function("location.hash === '#/queue'")
        assert "От клиентов" not in page.evaluate("[...document.querySelectorAll('.nav a')].map(a => a.textContent)")
    finally:
        ctx.close()
