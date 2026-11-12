"""Телефон (замечания владельца 12.11): панель на 375 px — меню за кнопкой «☰», шапка в одну строку, очередь карточками, ни один экран
не шире телефона (очередь, карточка, сводка, совещания, лига, администрирование); /boss — шапка не обрезана, плейсхолдер влезает.
Нужны Playwright и Chromium; сервер — отдельным процессом со своей базой."""
import pytest

from tests.test_stage9_ui import browser, server   # noqa: F401 — общие фикстуры: сервер на свободном порту и Chromium

playwright = pytest.importorskip("playwright.sync_api")

WIDTH = """() => document.documentElement.scrollWidth"""


def phone(browser, server, uid):
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True, locale="ru-RU")
    page = ctx.new_page()
    page.request.post(f"{server}/api/auth/login-as", data={"user_id": uid})
    return ctx, page


def test_panel_on_phone_fits_and_uses_cards(browser, server):
    ctx, page = phone(browser, server, 1)
    try:
        page.goto(f"{server}/panel#/queue"); page.wait_for_selector(".qcard")
        assert page.evaluate(WIDTH) <= 375
        assert not page.locator(".topbar .nav").is_visible() and page.locator(".nav-toggle").is_visible()
        top = page.locator(".topbar").bounding_box()
        assert top["height"] < 64   # шапка в одну строку
        assert page.locator("#queue-table table").count() == 0
        first = page.locator(".qcard").first.inner_text()
        assert "A-" in first and ("Новое" in first or "рассмотрении" in first)
        page.click(".nav-toggle"); page.wait_for_selector(".nav-panel.open")
        assert page.locator(".nav-panel a:has-text('Администрирование')").is_visible() and page.locator(".nav-panel a:has-text('Приложение')").is_visible()
        page.click(".nav-panel a:has-text('Сводка')"); page.wait_for_timeout(1500)
        assert "#/summary" in page.url and not page.locator(".nav-panel.open").count()
        for h in ("#/appeal/7", "#/summary", "#/meetings", "#/league", "#/admin", "#/decisions"):
            page.goto(f"{server}/panel{h}"); page.reload(); page.wait_for_timeout(1500)
            assert page.evaluate(WIDTH) <= 375, h
    finally:
        ctx.close()


def test_boss_header_and_placeholder_fit(browser, server):
    ctx, page = phone(browser, server, 1)
    try:
        page.goto(f"{server}/boss"); page.wait_for_selector(".boss-tile b:not(:has-text('…'))")
        right = page.evaluate("document.querySelector('.boss-head').lastElementChild.getBoundingClientRect().right")
        assert right <= 375 - 8
        fits = page.evaluate("""() => { const ta = document.querySelector('.boss-ask-text'); const cs = getComputedStyle(ta, '::placeholder');
          const c = document.createElement('canvas').getContext('2d'); c.font = cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
          return c.measureText(ta.placeholder).width <= ta.clientWidth - parseFloat(getComputedStyle(ta).paddingLeft) - parseFloat(getComputedStyle(ta).paddingRight); }""")
        assert fits and page.locator(".boss-ask-text").get_attribute("placeholder") == "Спросите, например: что по Омску?"
        assert page.evaluate(WIDTH) <= 375
    finally:
        ctx.close()
