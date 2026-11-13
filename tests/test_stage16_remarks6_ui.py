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


_STATES: dict = {}   # сессия на пользователя: демо-вход ограничен 30 входами в минуту с адреса (площадка, 13.11) — входим по разу


def _open(browser, base, uid, width, path):
    phone = width < 500
    key = (base, uid)
    ctx = browser.new_context(viewport={"width": width, "height": 812 if phone else 900}, locale="ru-RU", is_mobile=phone, has_touch=phone,
                              service_workers="block", storage_state=_STATES.get(key))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if key not in _STATES:
        assert page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid}).ok
        _STATES[key] = ctx.storage_state()
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


# ---------- планшет 481–900 px (13.11): шапка панели за «☰», таблицы строками — без горизонтальной прокрутки ----------

@pytest.mark.parametrize("width", [520, 600, 760, 820])
def test_panel_tablet_no_horizontal_scroll(base, browser, width):
    ctx, page, errors = _open(browser, base, 1, width, "/panel#/queue")
    try:
        page.wait_for_selector(".qcard")   # очередь карточками и на планшете
        assert page.locator(".nav-toggle").is_visible() and not page.locator(".topbar .nav").is_visible()
        for path in ("/panel#/queue", "/panel#/summary", "/panel#/meetings", "/panel#/decisions", "/panel#/league", "/panel#/admin"):
            page.goto(base + path); page.wait_for_timeout(900)
            assert _fits(page), (width, path, page.evaluate("document.documentElement.scrollWidth"))
        assert not errors, errors
    finally:
        ctx.close()


# ---------- правило 13.11: в кнопках с текстом значков нет; режим совещания — две кнопки без значков ----------

TEXT_BTN_WITH_ICON = """[...document.querySelectorAll('button, a.btn, .btn')].filter(b => {
  const r = b.getBoundingClientRect(); if (!r.width) return false;
  if (b.closest('.help-wrap') || ['bn-item', 'qcard', 'marker', 'pick', 'boss-tile', 'bell'].some(c => b.classList.contains(c))) return false;   // колокольчик — значок со счётчиком
  const svg = [...b.querySelectorAll('svg')].some(s => s.getBoundingClientRect().width > 0 && getComputedStyle(s).display !== 'none');
  return svg && b.innerText.trim();
}).map(b => b.innerText.trim().slice(0, 40))"""


@pytest.mark.parametrize("uid,width,path", [(2, 375, "/app#/meeting"), (2, 1440, "/panel#/meetings"), (1, 1440, "/panel#/summary"), (1, 375, "/boss"),
                                            (15, 1440, "/panel#/admin"), (17, 375, "/app#/new"), (17, 375, "/app#/u/17"), (1, 1440, "/")])
def test_no_icons_in_text_buttons(base, browser, uid, width, path):
    ctx, page, errors = _open(browser, base, uid, width, path)
    try:
        page.wait_for_timeout(1500)
        bad = page.evaluate(TEXT_BTN_WITH_ICON)
        assert not bad, (path, bad)
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [360, 390])
def test_meeting_two_plain_buttons_fit(base, browser, width):
    ctx, page, errors = _open(browser, base, 2, width, "/app#/meeting")
    try:
        page.wait_for_selector("text=Режим совещания")
        btns = page.evaluate("[...document.querySelectorAll('.grid2 .btn-big')].map(b => [b.innerText.replace(/\\s+/g, ' ').trim(), b.scrollWidth <= b.clientWidth, b.getBoundingClientRect().right <= innerWidth, b.querySelectorAll('svg').length])")
        assert [x[0] for x in btns] == ["Начать запись", "Загрузить"] and all(x[1] and x[2] and x[3] == 0 for x in btns), btns
        inp = page.evaluate("(() => { const i = document.querySelector('.card input[type=text]'); return [i.placeholder, i.scrollWidth <= i.clientWidth]; })()")
        assert inp == ["Название (необязательно)", True]
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [375, 1280, 1440, 1920])
def test_director_map_labels_never_clipped(base, browser, width):
    ctx, page, errors = _open(browser, base, 1, width, "/panel#/summary")
    try:
        page.wait_for_selector(".map .marker"); page.wait_for_timeout(1500)
        out = page.evaluate("""(() => { const m = document.querySelector('.map').getBoundingClientRect();
          return [...document.querySelectorAll('.map .marker .mlabel, .map .map-country')].filter(l => { const r = l.getBoundingClientRect();
            return r.left < m.left - 0.5 || r.right > m.right + 0.5 || r.top < m.top - 0.5 || r.bottom > m.bottom + 0.5; }).map(l => l.innerText); })()""")
        assert not out, out
        assert page.locator(".legend .ict").count() == 2
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()
