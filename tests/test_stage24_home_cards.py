"""Главная (замечания владельца 13.11, после меню пользователя): под картой карточки в фирменном градиенте главной кнопки — белый текст,
одной высоты, без значков, при наведении лёгкое затемнение и подъём тени, на телефоне одна под другой; их две — «Подать обращение»
(сотрудникам) и «Обратная связь для клиентов» (форма /c); «Результаты обращений» и «Статистика» — ссылками в подвале рядом с «Как
начисляются баллы». Объекты командированных снова на главной карте — тем же стилем, что города (метка, город, мелко «объект», без
служебных цифр); нажатие — форма «Объект» с подставленным городом. Окно города при загрузке не открывается — только по нажатию."""
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
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui24-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
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


def _home(browser, base, width):
    phone = width < 500
    ctx = browser.new_context(viewport={"width": width, "height": 844 if phone else 900}, locale="ru-RU", is_mobile=phone, has_touch=phone,
                              service_workers="block")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "/")
    page.wait_for_selector(".feats .feat")
    page.wait_for_timeout(1200)
    return ctx, page, errors


CARDS = """[...document.querySelectorAll('.feats > *')].map(f => { const r = f.getBoundingClientRect(), cs = getComputedStyle(f);
  return { title: f.querySelector('b').innerText, sub: f.querySelector('span').innerText, x: Math.round(r.left), y: Math.round(r.top),
           w: Math.round(r.width), h: Math.round(r.height), bg: cs.backgroundImage, color: cs.color, sub_color: getComputedStyle(f.querySelector('span')).color,
           icons: f.querySelectorAll('svg, img, .ic').length }; })"""


def test_two_gradient_cards_under_map_same_height_white_text(base, browser):
    ctx, page, errors = _home(browser, base, 1440)
    try:
        cards = page.evaluate(CARDS)
        assert [(c["title"], c["sub"]) for c in cards] == [("Подать обращение", "Сотрудникам: идеи, вопросы, проблемы"),
                                                         ("Обратная связь для клиентов", "Оставьте отзыв, вопрос или благодарность")]
        assert page.locator(".feats .feat").nth(1).get_attribute("href") == "/c"
        assert all("linear-gradient" in c["bg"] for c in cards), cards   # фирменный градиент главной кнопки
        assert all(c["color"] == c["sub_color"] == "rgb(255, 255, 255)" for c in cards), cards   # белый текст
        assert all(c["icons"] == 0 for c in cards), cards   # без значков
        assert cards[0]["h"] == cards[1]["h"] and cards[0]["y"] == cards[1]["y"] and cards[0]["w"] == cards[1]["w"], cards   # в ряд, одной высоты
        under = page.evaluate("document.querySelector('.feats').getBoundingClientRect().top >= document.querySelector('.home-map').getBoundingClientRect().bottom")
        assert under   # под картой
        assert "Статистика" not in page.locator(".feats").inner_text() and "Результаты обращений" not in page.locator(".feats").inner_text()
        css = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
        assert "background: var(--btn-main)" in css.split(".feat {", 1)[1].split("}", 1)[0]   # тот же токен, что у главной кнопки
        assert not errors, errors
    finally:
        ctx.close()


def test_card_hover_darkens_and_lifts_shadow(base, browser):
    ctx, page, errors = _home(browser, base, 1440)
    try:
        f = page.locator(".feats .feat").nth(1)
        before = page.evaluate("(() => { const f = document.querySelectorAll('.feats .feat')[1]; return [getComputedStyle(f).boxShadow, getComputedStyle(f, '::before').opacity, getComputedStyle(f).transform]; })()")
        f.hover(); page.wait_for_timeout(450)
        after = page.evaluate("(() => { const f = document.querySelectorAll('.feats .feat')[1]; return [getComputedStyle(f).boxShadow, getComputedStyle(f, '::before').opacity, getComputedStyle(f).transform]; })()")
        assert before[1] == "0" and after[1] == "1", (before, after)   # затемнение поверх градиента
        assert after[0] != before[0] and after[2] != before[2], (before, after)   # тень выше, карточка приподнята
        assert not errors, errors
    finally:
        ctx.close()


def test_cards_stack_on_phone_no_horizontal_scroll(base, browser):
    ctx, page, errors = _home(browser, base, 390)
    try:
        cards = page.evaluate(CARDS)
        assert len(cards) == 2 and cards[0]["x"] == cards[1]["x"] and cards[1]["y"] > cards[0]["y"] + cards[0]["h"] - 1, cards   # одна под другой
        assert cards[0]["h"] == cards[1]["h"] and cards[0]["w"] == cards[1]["w"], cards
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
    finally:
        ctx.close()


def test_results_and_statistics_are_footer_links_next_to_points_rules(base, browser):
    ctx, page, errors = _home(browser, base, 1440)
    try:
        links = page.evaluate("[...document.querySelectorAll('.home-foot a')].map(a => [a.innerText, a.getAttribute('href'), a.parentElement === document.querySelector('.home-foot a[href=\"/rules\"]').parentElement])")
        assert ["Как начисляются баллы", "/rules", True] in links
        stats = [x for x in links if x[0] == "Статистика"]
        assert stats and stats[0][2] and "/panel#/summary" in stats[0][1].replace("%23", "#").replace("%2F", "/"), links   # рядом, в той же строке
        assert ["Результаты обращений", "/changes", True] in links
        names = [x[0] for x in links]
        assert names.index("Результаты обращений") + 1 == names.index("Статистика"), names   # «Результаты обращений» — рядом со «Статистикой»
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_sites_on_home_map_like_cities_click_opens_object_form_with_city(base, browser, width):
    ctx, page, errors = _home(browser, base, width)
    try:
        site = page.evaluate("""(() => { const m = document.querySelector('.map .marker.site'), city = document.querySelector('.map .marker:not(.site):not(.sel)');   // выбранный город — темнее
          return { label: m.querySelector('.mlabel b').innerText, small: m.querySelector('.m-site').innerText, cls: m.className, rest: m.querySelectorAll('.m-rest').length,
                   pin: getComputedStyle(m.querySelector('.pin')).color, city_pin: getComputedStyle(city.querySelector('.pin')).color, shown: getComputedStyle(m).display !== 'none',
                   size: getComputedStyle(m.querySelector('.pin svg')).width, city_size: getComputedStyle(city.querySelector('.pin svg')).width }; })()""")
        assert site["label"] == "Атырау" and site["small"] == "объект" and site["rest"] == 0 and site["shown"], site   # без «откр.» и просрочек
        assert "m-late" not in site["cls"] and "m-ok" not in site["cls"] and site["pin"] == site["city_pin"] and site["size"] == site["city_size"], site   # как город
        page.locator(".map .marker.site").click(force=True)   # карта движется — клик только с force
        page.wait_for_url("**/q/FIELD?city=*"); page.wait_for_selector("input[name=site_city]")
        assert page.input_value("input[name=site_city]") == "Атырау" and page.inner_text(".h1") == "Объект"
        assert page.locator(".btn-outline").count() == 0 and not errors, errors
    finally:
        ctx.close()


def test_object_form_city_param_is_trimmed_and_only_for_field(base, browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU", service_workers="block")
    page = ctx.new_page()
    try:
        page.goto(base + "/q/FIELD?city=" + "%20Тенгиз" + "x" * 120); page.wait_for_selector("input[name=site_city]")
        v = page.input_value("input[name=site_city]")
        assert v.startswith("Тенгиз") and len(v) == 80
        page.goto(base + "/q/OMSK?city=Атырау"); page.wait_for_selector("form .type-switch")
        assert page.locator("input[name=site_city]").count() == 0   # у филиала поля «Город / объект» нет — параметр ни на что не влияет
    finally:
        ctx.close()


def test_no_city_window_on_load_submit_asks_to_pick_city(base, browser):
    """Замечание владельца 13.11: при загрузке — просто карта с городами, окно города не всплывает; «Подать обращение» без выбранного
    города просит выбрать город на карте и никуда не уводит; окно открывается по нажатию на город."""
    ctx, page, errors = _home(browser, base, 1440)
    try:
        assert page.evaluate("document.querySelector('.citypop').classList.contains('hidden') && !document.querySelector('.map .marker.sel')")
        page.locator(".feats .feat").first.click(); page.wait_for_timeout(400)
        assert page.url.rstrip("/") == base and "Сначала выберите город на карте" in page.locator(".toast").last.inner_text()
        page.locator(".map .marker", has_text="Омск").click(force=True); page.wait_for_timeout(400)
        assert page.locator(".citypop:not(.hidden) .cc-name b").inner_text() == "Омск"
        page.locator(".feats .feat").first.click(); page.wait_for_url("**/q/*")
        assert not errors, errors
    finally:
        ctx.close()
