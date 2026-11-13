"""ТЗ владельца 13.11 «панель директора — меню, страница «Сводка», часы по городам»: порядок меню, стартовая страница директора,
раскладка «Сводки» (карта ~60 % слева, справа сводка с командой по высоте карты, ниже на всю ширину; до 1200 px — друг под другом),
часы по городам филиалов (зоны IANA, по умолчанию Омск, выбор запоминается, скрытая вкладка — таймер стоит), зона у филиала."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from mf import db, geo
from mf.main import app

TABLE = {"Самара": "Europe/Samara", "Тюмень": "Asia/Yekaterinburg", "Омск": "Asia/Omsk", "Павлодар": "Asia/Almaty", "Астана": "Asia/Almaty",
         "Атырау": "Asia/Atyrau"}
FIXED = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)   # пятница, 13 ноября 2026


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def test_branch_timezone_filled_by_city_and_in_map_data(c):
    assert c.post("/api/auth/login-as", json={"user_id": 1}).status_code == 200
    m = c.get("/api/panel/map").json()
    got = {b["city"]: b["timezone"] for b in m["branches"]} | {s["city"]: s["timezone"] for s in m["sites"]}
    assert got == TABLE   # те же города, что на карте: пять филиалов и объект в Атырау
    assert [b["city"] for b in m["branches"] if b["is_hq"]] == ["Омск"]   # головной офис — город часов по умолчанию
    rows = {r["code"]: r["timezone"] for r in db.q("SELECT code, timezone FROM branches")}
    assert all(rows.values()) and rows["OMSK"] == "Asia/Omsk" and rows["FIELD"] == "Asia/Almaty"   # колонка заполнена по городу


def test_new_branch_without_zone_gets_almaty_and_set_zone_is_kept(c):
    ids = [db.ex("INSERT INTO branches(code, name, city, country, kind) VALUES('TZ1', 'Новоград', 'Новоград', 'Казахстан', 'office')"),
           db.ex("INSERT INTO branches(code, name, city, country, kind) VALUES('TZ2', 'Без города', NULL, 'Казахстан', 'office')"),
           db.ex("INSERT INTO branches(code, name, city, country, kind, timezone) VALUES('TZ3', 'Самара-2', 'Самара', 'Россия', 'office', 'Europe/Moscow')")]
    try:
        db.fill_timezones(db.conn())
        tz = {r["code"]: r["timezone"] for r in db.q("SELECT code, timezone FROM branches WHERE code LIKE 'TZ%'")}
        assert tz == {"TZ1": "Asia/Almaty", "TZ2": "Asia/Almaty", "TZ3": "Europe/Moscow"}
    finally:
        for i in ids:
            db.ex("DELETE FROM branches WHERE id=?", (i,))


def test_every_directory_city_has_valid_iana_zone():
    cities = list(geo.KZ) + list(geo.RU)
    missing = [x for x in cities if x not in geo.ZONES]
    assert not missing, missing
    for z in set(geo.ZONES.values()) | {geo.DEFAULT_TZ}:
        ZoneInfo(z)   # имя зоны есть в базе часовых поясов
    assert geo.timezone_for("г. Тюмень, промзона") == "Asia/Yekaterinburg" and geo.timezone_for("Нур-Султан") == "Asia/Almaty"
    assert geo.timezone_for("Неизвестноград") == geo.timezone_for(None) == "Asia/Almaty"


def test_zone_offsets_on_fixed_date_python():
    """При текущих правилах: Омск = Астана + 1 ч, Самара = Астана − 1 ч, Тюмень = Астана (Казахстан — UTC+5 с 1 марта 2024)."""
    t = {city: FIXED.astimezone(ZoneInfo(z)).utcoffset().total_seconds() / 3600 for city, z in TABLE.items()}
    assert t["Омск"] - t["Астана"] == 1 and t["Самара"] - t["Астана"] == -1 and t["Тюмень"] == t["Астана"] == t["Павлодар"]


# ---------- в браузере ----------

import os   # noqa: E402
import socket   # noqa: E402
import subprocess   # noqa: E402
import sys   # noqa: E402
import tempfile   # noqa: E402
import time   # noqa: E402
import urllib.request   # noqa: E402
from pathlib import Path   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MENU = ["Сводка", "Очередь", "Совещания", "На решение", "Лига", "Администрирование"]


@pytest.fixture(scope="module")
def base():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui18-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
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


_STATES: dict = {}   # демо-вход ограничен по частоте — входим по разу на пользователя


def _open(browser, base, uid, width, path, height=None):
    phone = width < 500
    key = (base, uid)
    ctx = browser.new_context(viewport={"width": width, "height": height or (812 if phone else 900)}, locale="ru-RU", timezone_id="Asia/Almaty",
                              is_mobile=phone, has_touch=phone, service_workers="block", storage_state=_STATES.get(key))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if key not in _STATES:
        assert page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid}).ok
        _STATES[key] = ctx.storage_state()
    page.goto(base + path)
    return ctx, page, errors


@pytest.mark.parametrize("uid,menu,start", [(1, MENU, "#/summary"), (15, MENU, "#/admin"), (2, ["Очередь", "Совещания", "Лига"], "")])
def test_menu_order_and_start_page(base, browser, uid, menu, start):
    """Меню: Сводка · Очередь · Совещания · На решение · Лига · Администрирование; директор после входа — на «Сводке», администратор —
    в «Администрировании», ответственный — в очереди, как раньше."""
    ctx, page, errors = _open(browser, base, uid, 1440, "/panel")
    try:
        page.wait_for_selector(".topbar .nav a"); page.wait_for_timeout(1200)
        assert page.locator(".topbar .nav a").all_inner_texts() == menu
        assert page.evaluate("location.hash") == start
        if uid == 1:
            assert page.locator(".sum-top .map-card").count() == 1 and page.locator(".topbar .nav a.active").inner_text() == "Сводка"
            assert page.locator(".topbar .brand").get_attribute("href") == "#/summary"
            page.goto(base + "/panel#/league"); page.wait_for_selector(".pod-step")   # прямые ссылки работают как раньше
            assert page.evaluate("location.hash") == "#/league"
        if uid == 2:
            page.wait_for_selector("table.queue tbody tr")
        assert not errors, errors
    finally:
        ctx.close()


def test_clock_math_on_fixed_date_in_browser(base, browser):
    """Время по зонам IANA (Intl.DateTimeFormat) на фиксированной дате: Омск = Астана + 1 ч, Самара = Астана − 1 ч, Тюмень = Астана;
    разница с устройством — словами."""
    ctx, page, errors = _open(browser, base, 1, 1440, "/panel#/summary")
    try:
        page.wait_for_selector(".clock")
        r = page.evaluate("""(() => { const d = new Date('2026-11-13T09:00:07Z'); const z = ['Asia/Almaty', 'Asia/Omsk', 'Europe/Samara', 'Asia/Yekaterinburg', 'Asia/Atyrau'];
          return { t: z.map(x => clockAt(d, x)), off: z.map(x => zoneOffsetMin(d, x)),
                   diff: ['Asia/Omsk', 'Europe/Samara', 'Asia/Yekaterinburg', 'Asia/Kolkata'].map(x => zoneDiffText(d, x, 300)) }; })()""")
        assert [x["hm"] for x in r["t"]] == ["14:00", "15:00", "13:00", "14:00", "14:00"] and r["t"][1]["ss"] == "07"
        assert r["t"][0]["date"] == "пятница, 13 ноября"
        assert r["off"] == [300, 360, 240, 300, 300]
        assert r["diff"] == ["+1 ч к вашему", "−1 ч к вашему", "то же время", "+30 мин к вашему"]
        assert not errors, errors
    finally:
        ctx.close()


def _box(page, sel):
    return page.locator(sel).first.bounding_box()


def test_summary_layout_wide_and_narrow(base, browser):
    ctx, page, errors = _open(browser, base, 1, 1920, "/panel#/summary", height=1080)
    try:
        page.wait_for_selector(".map .marker"); page.wait_for_timeout(1200)
        top, m, side = _box(page, ".sum-top"), _box(page, ".map-card"), _box(page, ".sum-side")
        assert 0.55 <= m["width"] / top["width"] <= 0.65 and side["x"] > m["x"] + m["width"]   # карта ~60 % слева, сводка справа
        assert abs(side["height"] - m["height"]) <= 2 and abs(side["y"] - m["y"]) <= 1   # правая колонка — по высоте карты
        assert page.locator(".sum-side .summary-ai").count() == 1 and page.locator(".sum-side .command").count() == 1
        assert top["width"] >= 1920 - 2 * 24 - 2   # на всю ширину, без пустой колонки слева
        order = page.evaluate("""[...document.querySelector('.sum-page').children].map(e => e.classList.contains('sum-top') ? 'top' : e.classList.contains('attention') ? 'attention'
          : e.classList.contains('kpis') ? 'kpis' : e.classList.contains('stats-card') ? 'stats' : e.querySelector('.by-branch') ? 'branches' : '')""")
        assert [x for x in order if x] == ["top", "attention", "kpis", "stats", "branches"]
        widths = page.evaluate("['.attention', '.kpis', '.stats-card', '.by-branch'].map(s => Math.round((s === '.by-branch' ? document.querySelector(s).closest('.card') : document.querySelector(s)).getBoundingClientRect().width))")
        assert all(abs(w - top["width"]) <= 2 for w in widths), widths
        assert page.evaluate("getComputedStyle(document.querySelector('.sum-chips .badge')).fontSize") == "15px"   # чипы ×1,25 (обычный — 12 px)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        # узкий экран: колонки друг под другом — карта, сводка с командой, остальное
        page.set_viewport_size({"width": 1024, "height": 900}); page.wait_for_timeout(600)
        m, s, cmd, att = _box(page, ".map-card"), _box(page, ".sum-side .summary-ai"), _box(page, ".sum-side .command"), _box(page, ".attention")
        assert s["y"] >= m["y"] + m["height"] and cmd["y"] >= s["y"] + s["height"] and att["y"] >= cmd["y"] + cmd["height"]
        assert page.evaluate("document.querySelector('.sum-side .summary-ai').style.maxHeight") == ""
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") and not errors, errors
    finally:
        ctx.close()


def test_long_summary_scrolls_inside_card(base, browser):
    """Текст сводки длиннее колонки — прокрутка внутри карточки, карта не растягивается."""
    ctx, page, errors = _open(browser, base, 1, 1280, "/panel#/summary")
    try:
        page.wait_for_selector(".map .marker"); page.wait_for_timeout(1200)
        before = _box(page, ".map-card")["height"]
        page.evaluate("""(() => { const c = document.querySelector('.sum-side .summary-ai'); for (let i = 0; i < 30; i++) c.append(Object.assign(document.createElement('p'), { textContent: 'строка ' + i })); })()""")
        page.wait_for_timeout(500)
        m, side, card = _box(page, ".map-card"), _box(page, ".sum-side"), page.evaluate("(() => { const c = document.querySelector('.sum-side .summary-ai'); return [c.scrollHeight > c.clientHeight + 100, c.classList.contains('more-down')]; })()")
        assert abs(m["height"] - before) <= 1 and abs(side["height"] - m["height"]) <= 2 and card == [True, True]
        assert not errors, errors
    finally:
        ctx.close()


def test_city_clock_default_omsk_switch_remember_and_pause_when_hidden(base, browser):
    ctx, page, errors = _open(browser, base, 1, 1440, "/panel#/summary")
    try:
        page.wait_for_selector(".clock .clock-hm"); page.wait_for_timeout(300)
        cities = page.locator(".clock-cities .chip").all_inner_texts()
        assert cities == ["Самара", "Атырау", "Тюмень", "Астана", "Омск", "Павлодар"]   # города с карты, с запада на восток
        clock = page.locator(".clock")
        assert clock.get_attribute("data-city") == "Омск" and page.locator(".clock-cities .chip.on").inner_text() == "Омск"
        assert page.locator(".clock-diff").inner_text() == "+1 ч к вашему"   # устройство — по Астане (timezone_id)
        assert page.locator(".clock-date").inner_text() == page.evaluate("new Intl.DateTimeFormat('ru-RU', { timeZone: 'Asia/Omsk', weekday: 'long', day: 'numeric', month: 'long' }).format(new Date())")
        hm = lambda: page.locator(".clock-hm").inner_text()   # noqa: E731
        omsk = hm()
        page.locator(".clock-cities .chip", has_text="Самара").click()
        assert clock.get_attribute("data-tz") == "Europe/Samara" and page.locator(".clock-diff").inner_text() == "−1 ч к вашему"
        h1, h2 = (int(x.split(":")[0]) * 60 + int(x.split(":")[1]) for x in (omsk, hm()))
        assert (h1 - h2) % 1440 in (120, 119)   # Самара = Омск − 2 ч (на границе минуты — на минуту меньше)
        ss = page.locator(".clock-ss").inner_text()
        page.wait_for_timeout(1300)
        assert page.locator(".clock-ss").inner_text() != ss   # тикает раз в секунду
        page.reload(); page.wait_for_selector(".clock .clock-hm")
        assert page.locator(".clock").get_attribute("data-city") == "Самара"   # выбор запоминается
        # вкладка скрыта — таймер стоит; вернулись — сразу пересчёт
        page.evaluate("""(() => { window.__hidden = true; Object.defineProperty(document, 'hidden', { configurable: true, get: () => window.__hidden });
          document.dispatchEvent(new Event('visibilitychange')); })()""")
        frozen = page.locator(".clock-ss").inner_text()
        page.wait_for_timeout(2300)
        assert page.locator(".clock-ss").inner_text() == frozen
        page.evaluate("window.__hidden = false; document.dispatchEvent(new Event('visibilitychange'))")
        assert page.locator(".clock-ss").inner_text() != frozen
        page.wait_for_timeout(1200)
        assert page.locator(".clock-ss").inner_text() != frozen
        # маленькое время в шапке сводки — как было
        assert page.locator(".summary-ai .small.muted").first.inner_text().count(":") == 1
        page.locator(".clock-cities .chip", has_text="Омск").click()   # вернуть по умолчанию для следующих тестов
        assert not errors, errors
    finally:
        ctx.close()


def test_volume_tokens_and_no_new_colors():
    """Объём (п. 4): тени и фон — токены в :root; карточкам панели двухслойная тень и светлая кромка; у карты — внутренняя тень."""
    css = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
    assert "--bg-page:" in css and "--shadow-card:" in css and "--map-inset:" in css
    assert css.count(",", css.index("--shadow-card:"), css.index(";", css.index("--shadow-card:"))) >= 5   # два слоя тени
    assert "html.panel-page .map::after" in css and 'class="panel-page"' in (ROOT / "web" / "panel.html").read_text(encoding="utf-8")
