"""Главная (замечания владельца 13.11): одна подложка и одна рамка карты, как у директора (46…86° в. д., 45…62° с. ш.), на всю ширину
блока (объекты командированных — тоже, см. test_stage24_home_cards.py); карта реально движется — и при «уменьшить движение» в системе (мягкий дрейф 30 с, метки без вспышек); окно
города по образцу — шапка с меткой и крестиком, плитки «Открытых» и «Решено за месяц», QR, «Главная тема», кнопка «Подать обращение» —
целиком внутри карты; на телефоне — шторкой снизу."""
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
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui22-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
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


def _home(browser, base, width, reduced="no-preference"):
    phone = width < 500
    ctx = browser.new_context(viewport={"width": width, "height": 844 if phone else 900}, locale="ru-RU", is_mobile=phone, has_touch=phone,
                              service_workers="block", reduced_motion=reduced)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "/")
    page.wait_for_selector(".map .marker")
    page.wait_for_timeout(1200)
    return ctx, page, errors


def test_home_map_same_frame_full_width(base, browser):
    ctx, page, errors = _home(browser, base, 1440)
    try:
        g = page.evaluate("""(() => { const m = document.querySelector('.map').getBoundingClientRect(), slot = document.querySelector('.home-map').getBoundingClientRect();
          return { src: document.querySelector('.map-bg').getAttribute('src'), ratio: m.width / m.height, full: Math.abs(m.width - slot.width) <= 1,
                   sites: document.querySelectorAll('.map .marker.site').length, cropped: document.querySelector('.map').classList.contains('cropped') }; })()""")
        # объекты командированных снова на главной (замечание владельца 13.11, после этого теста): Атырау из начальных данных
        assert g["src"] == "/a/img/map-director.svg" and abs(g["ratio"] - 900 / 643) < 0.02 and g["full"] and g["sites"] == 1 and not g["cropped"]
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("reduced,name", [("no-preference", "kenburns"), ("reduce", "map-drift")])
def test_home_map_really_moves_even_with_reduced_motion(base, browser, reduced, name):
    ctx, page, errors = _home(browser, base, 1440, reduced)
    try:
        a = page.evaluate("document.querySelector('.map.live .map-scene').getAnimations().map(x => [x.animationName, x.playState, x.effect.getTiming().duration, x.effect.getTiming().direction])")
        assert a and a[0][0] == name and a[0][1] == "running", a
        t0 = page.evaluate("getComputedStyle(document.querySelector('.map-scene')).transform")
        page.wait_for_timeout(1500)
        assert page.evaluate("getComputedStyle(document.querySelector('.map-scene')).transform") != t0   # движется на самом деле
        if reduced == "reduce":
            assert a[0][2] * (2 if a[0][3] == "alternate" else 1) == 30000   # цикл 30 с
            assert page.evaluate("[...document.querySelectorAll('.map .marker')].reduce((n, m) => n + m.getAnimations({ subtree: true }).length, 0)") == 0   # без вспышек
        assert not errors, errors
    finally:
        ctx.close()


def test_city_window_like_sample_inside_map(base, browser):
    ctx, page, errors = _home(browser, base, 1440)
    try:
        api = page.evaluate("API.get('/api/public/map')")
        sam = next(b for b in api["branches"] if b["city"] == "Самара")
        page.locator(".map .marker", has_text="Самара").click(force=True); page.wait_for_timeout(500)
        pop = page.locator(".citypop:not(.hidden)")
        assert pop.locator(".cc-head .cc-pin").count() == 1 and pop.locator(".cc-head .cc-close").count() == 1 and pop.locator(".cc-name b").inner_text() == "Самара"
        assert pop.locator(".cc-open b").inner_text() == str(sam["open"]) and pop.locator(".cc-done b").inner_text() == str(sam["done_month"])
        assert pop.locator(".cc-qr").count() == 1 and "Главная тема:" in pop.locator(".cc-theme").inner_text()
        r = page.evaluate("""(() => { const m = document.querySelector('.map').getBoundingClientRect(), c = document.querySelector('.citypop').getBoundingClientRect(),
            go = document.querySelector('.citypop .cc-go').getBoundingClientRect(), body = document.querySelector('.citypop .cc-line').getBoundingClientRect(),
            lab = [...document.querySelectorAll('.map .marker')].find(x => x.textContent.includes('Самара')).querySelector('.mlabel').getBoundingClientRect();
          return { inside: c.left >= m.left && c.right <= m.right && c.top >= m.top && c.bottom <= m.bottom, full: Math.abs(go.width - body.width) <= 1,
                   covers: c.left < lab.right && c.right > lab.left && c.top < lab.bottom && c.bottom > lab.top,
                   tiles: [...document.querySelectorAll('.citypop .cc-tile')].every(t => t.scrollWidth <= t.clientWidth + 1) }; })()""")
        assert r == {"inside": True, "full": True, "covers": False, "tiles": True}, r   # внутри карты, кнопка на всю ширину, подпись не закрыта
        assert page.locator(".citypop .cc-go").inner_text() == "Подать обращение" and page.locator(".citypop .cc-go svg").count() == 0
        tiles = page.evaluate("[...document.querySelectorAll('.citypop .cc-tile')].map(t => [Math.round(t.getBoundingClientRect().width), Math.round(t.getBoundingClientRect().height), Math.round(t.querySelector('b').getBoundingClientRect().top)])")
        assert tiles[0] == tiles[1], tiles   # плитки одного размера, цифры на одной высоте
        assert page.evaluate("(() => { const s = document.querySelector('.citypop .cc-done span'); return Math.round(s.getBoundingClientRect().height / parseFloat(getComputedStyle(s).lineHeight)); })()") == 2   # «Решено / за месяц» — в две строки
        page.locator(".citypop .cc-close").click(); page.wait_for_timeout(200)
        assert page.locator(".citypop.hidden").count() == 1
        assert not errors, errors
    finally:
        ctx.close()


def test_city_window_bottom_sheet_on_phone(base, browser):
    ctx, page, errors = _home(browser, base, 390)
    try:
        page.locator(".city-pills .btn", has_text="Самара").click(); page.wait_for_timeout(500)
        sh = page.evaluate("(() => { const s = document.querySelector('.sheet').getBoundingClientRect(); return [Math.round(s.bottom), innerHeight, !!document.querySelector('.sheet .cc-head .cc-close')]; })()")
        assert sh[0] == sh[1] and sh[2]   # шторка снизу, с крестиком в шапке
        assert page.evaluate("[...document.querySelectorAll('.sheet .cc-tile')].every(t => t.scrollWidth <= t.clientWidth + 1)")
        page.locator(".sheet .cc-close").click(); page.wait_for_timeout(200)
        assert page.locator(".sheet").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") and not errors, errors
    finally:
        ctx.close()
