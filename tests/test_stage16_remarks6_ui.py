"""Шестой список замечаний владельца 13.11 — в браузере (Playwright), телефон 375 и компьютер 1440: очередь без «Возраста», «?» у колонок
совещаний, лига по линейке и вкладками на телефоне, одна главная кнопка сотрудника, нижняя панель приложения; без горизонтальной прокрутки."""
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
def base():
    port = _free_port()
    data = tempfile.mkdtemp(prefix="mf-ui16-")
    env = {**os.environ, "MF_DATA_DIR": data, "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
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
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:   # noqa: BLE001
            pytest.skip(f"нет Chromium для Playwright: {e}")
        yield b
        b.close()


def _open(browser, base, uid, width, path):
    phone = width < 500
    ctx = browser.new_context(viewport={"width": width, "height": 812 if phone else 900}, locale="ru-RU", is_mobile=phone, has_touch=phone, service_workers="block")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})
    page.goto(base + path)
    return ctx, page, errors


def _fits(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_queue_without_age_dot_at_number(base, browser):
    ctx, page, errors = _open(browser, base, 1, 1440, "/panel#/queue")
    try:
        page.wait_for_selector("table.queue tbody tr")
        heads = page.locator("table.queue thead th").all_inner_texts()
        assert [t.strip().lower() for t in heads] == ["обращение", "статус", "ответственный"]
        first = page.locator("table.queue tbody tr").first.locator("td.q-main")
        assert first.locator(".dot-overdue + .num").count() == 1   # срочные сверху: первая строка просрочена, точка — у номера
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()
    ctx, page, errors = _open(browser, base, 1, 375, "/panel#/queue")
    try:
        page.wait_for_selector(".qcard")
        card = page.locator(".qcard").first
        assert card.locator(".dot-overdue + .num").count() == 1 and "просрочено на " in card.inner_text()
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


def test_meetings_help_on_every_column(base, browser):
    ctx, page, errors = _open(browser, base, 2, 1440, "/panel#/meetings")
    try:
        page.request.post(f"{base}/api/meetings", form={"title": "Планёрка", "transcript": "Решили обновить справочник номенклатуры."})
        page.reload(); page.wait_for_selector("table.meetings thead th")
        ths = page.locator("table.meetings thead th")
        assert ths.count() == 8 and all(ths.nth(i).locator(".help-btn").count() == 1 for i in range(8))
        w = page.evaluate("[...document.querySelectorAll('table.meetings thead th')].map(th => th.getBoundingClientRect().width)")
        assert w[4] == max(w)   # «Итог» — самая широкая колонка
        assert "головной офис" not in page.locator("table.meetings tbody").inner_text()
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


def test_league_desktop_split_and_phone_tabs(base, browser):
    ctx, page, errors = _open(browser, base, 1, 1440, "/panel#/league")
    try:
        page.wait_for_selector("table.league tbody tr")
        assert not page.locator(".lg-seg").is_visible()
        left, right = page.locator(".lg-col-branches").bounding_box(), page.locator(".lg-col-top").bounding_box()
        assert right["x"] > left["x"] + left["width"] - 1   # «Филиалы» слева, «Сотрудники» справа
        num = page.locator("table.league thead th").first.bounding_box()
        assert num["width"] <= 40   # «#» — узкая колонка, сразу за ней филиал
        assert "головной офис" not in page.locator("table.league").inner_text()
        xs = page.evaluate("[...document.querySelectorAll('.lg-emp')].map(r => [r.querySelector('.lg-place').getBoundingClientRect().right, r.querySelector('.lg-who').getBoundingClientRect().left, r.querySelector('.lg-stats').getBoundingClientRect().right])")
        assert len(xs) >= 3 and all(x == xs[0] for x in xs)   # по линейке: место, имя и звёзды на одних вертикалях
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()
    ctx, page, errors = _open(browser, base, 17, 375, "/app#/league")
    try:
        page.wait_for_selector(".lg-seg")
        assert page.locator(".lg-seg").is_visible() and page.locator(".lg-col-branches").is_visible() and not page.locator(".lg-col-top").is_visible()
        page.click(".lg-seg .seg-btn[data-tab=top]")
        assert page.locator(".lg-col-top").is_visible() and not page.locator(".lg-col-branches").is_visible()
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


def test_employee_home_one_button_and_switch_in_form(base, browser):
    ctx, page, errors = _open(browser, base, 17, 375, "/app#/")
    try:
        page.wait_for_selector("#home-cta")
        assert page.locator("#home-cta").inner_text().strip() == "Есть идея или проблема?"
        txt = page.locator("#root").inner_text()
        assert "Сообщить о проблеме" not in txt and "Предложить улучшение" not in txt and "Сказать спасибо" not in txt
        page.click("#home-cta"); page.wait_for_selector(".type-switch")
        assert page.locator(".type-switch .btn").all_inner_texts() == ["Проблема", "Идея", "Спасибо"]
        assert page.locator(".type-switch .btn.on").inner_text() == "Проблема"
        page.click(".type-switch .btn:has-text('Спасибо')")
        assert page.locator(".h1").first.inner_text() == "Сказать спасибо"
        box, card = page.locator(".type-switch").bounding_box(), page.locator("form.card").bounding_box()
        assert box["x"] + box["width"] <= card["x"] + card["width"]   # переключатель не вылезает за карточку
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


def test_app_bottom_nav_on_phone_tabs_on_desktop(base, browser):
    ctx, page, errors = _open(browser, base, 17, 375, "/app#/")
    try:
        page.wait_for_selector("#bottom-nav .bn-item")
        assert page.locator("#bottom-nav .bn-label").all_inner_texts() == ["Главная", "Поручения", "Результаты", "Лига", "Профиль"]
        assert not page.locator(".tabs.app-tabs").is_visible()
        assert page.evaluate("[...document.querySelectorAll('.bn-label')].every(l => l.scrollWidth <= l.clientWidth + 1)")   # без обрезанных слов
        assert page.locator("#bottom-nav .bn-item.active .bn-label").inner_text() == "Главная"
        assert page.locator("#home-meeting").count() == 0   # «Совещание» — только у ответственных и директора
        page.click("#bottom-nav .bn-item:has-text('Профиль')"); page.wait_for_selector("#profile-rewards")
        assert page.locator("#bottom-nav .bn-item.active .bn-label").inner_text() == "Профиль"
        page.click("#profile-rewards"); page.wait_for_selector(".h1:has-text('Награды')")
        assert page.locator("#bottom-nav .bn-item.active .bn-label").inner_text() == "Профиль"   # награды — внутри профиля
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()
    ctx, page, errors = _open(browser, base, 2, 375, "/app#/")
    try:
        page.wait_for_selector("#home-meeting")
        page.click("#home-meeting"); page.wait_for_selector("text=Режим совещания")
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()
    ctx, page, errors = _open(browser, base, 1, 1440, "/app#/")
    try:
        page.wait_for_selector(".tabs.app-tabs a")
        assert not page.locator("#bottom-nav").is_visible()
        assert page.evaluate("[...document.querySelectorAll('.tabs.app-tabs a')].every(a => a.scrollWidth <= a.clientWidth + 1 && a.getBoundingClientRect().right <= a.parentElement.getBoundingClientRect().right + 1)")
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


# ---------- седьмой список 13.11 ----------

def test_admin_lands_in_administration_numbered_with_help(base, browser):
    ctx, page, errors = _open(browser, base, 15, 1440, "/panel")
    try:
        page.wait_for_selector(".staff-tbl tbody tr")
        assert page.evaluate("location.hash") == "#/admin"
        first = page.locator("#root .card").first
        assert first.locator("b").first.inner_text().startswith("Сотрудники")
        assert [t.strip() for t in first.locator(".staff-tools > button").all_inner_texts()] == ["Добавить", "Импорт CSV или Excel"]
        assert page.locator(".staff-tbl tbody tr").nth(1).locator("td.rownum").inner_text() == "2."
        num = page.locator(".staff-tbl thead th").first.bounding_box()
        assert num["width"] <= 44   # узкая колонка номера
        widths = page.evaluate("[...document.querySelectorAll('.staff-tbl thead th')].map(th => th.getBoundingClientRect().width)")
        assert widths[1] < widths[2] + widths[3] + widths[4]   # имя уже, остальные шире — без пустой середины
        missing = page.evaluate("[...document.querySelectorAll('#root th')].filter(th => th.textContent.trim() && !th.querySelector('.help-btn')).map(th => th.textContent.trim())")
        assert not missing, missing
        for sel in ("table.cats", ".rewards-tbl"):
            assert page.locator(sel + " tbody tr").first.locator("td.rownum").inner_text() == "1."
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


def test_bell_counter_red_and_points_gold_star(base, browser):
    ctx, page, errors = _open(browser, base, 17, 375, "/app#/")
    try:
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": 3})   # Ерлан благодарит Ольгу — у неё непрочитанное
        page.request.post(f"{base}/api/appeals", multipart={"type": "praise", "text": "Спасибо за быструю помощь со сверкой", "praise_to_user_id": "17"})
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": 17})
        page.reload(); page.wait_for_selector(".topbar .bell .n")
        n = page.evaluate("(() => { const s = getComputedStyle(document.querySelector('.topbar .bell .n')); return [s.backgroundColor, s.color]; })()")
        assert n == ["rgb(228, 0, 0)", "rgb(255, 255, 255)"], n
        star = page.evaluate("(() => { const s = getComputedStyle(document.querySelector('.topbar .pts .star-gold')); const p = getComputedStyle(document.querySelector('.topbar .pts')); return [s.color, s.fill, p.borderTopWidth, p.backgroundColor]; })()")
        assert star[0] == star[1] and star[0] not in ("rgb(8, 39, 66)",) and star[2] == "0px" and star[3] in ("rgba(0, 0, 0, 0)", "transparent"), star
        home = page.locator(".pts-home")
        assert home.get_attribute("href") == "#/u/17" and "Мои баллы" not in home.inner_text()
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()
