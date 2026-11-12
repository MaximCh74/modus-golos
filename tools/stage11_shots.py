#!/usr/bin/env python3
"""Скрины пункта 1 очереди 12.11 (Playwright, при работающем сервере): подсказки «?» на сводке и в настройках, «Справка» в панели,
«?» в карточке обращения и у счётчика очереди, «Мои поручения» со счётчиком на телефоне (Сауле, у которой есть поручение в демо-базе).
Запуск: python3 tools/stage11_shots.py <папка> [--base http://127.0.0.1:8070]. Базу не меняет."""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    ap.add_argument("--start", type=int, default=1)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); base = a.base
    n = [a.start]

    def shot(page, name, full=False):
        page.wait_for_timeout(700)
        page.screenshot(path=str(out / f"{n[0]:02d}_{name}.jpg"), type="jpeg", quality=90, full_page=full)
        print("  ", n[0], name); n[0] += 1

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU", device_scale_factor=1.25)
        page = ctx.new_page()
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": 1})
        page.goto(f"{base}/panel#/summary"); page.wait_for_selector(".kpis"); page.wait_for_timeout(1500)
        page.click(".help-btn[data-term=kpi_considered]"); page.wait_for_selector(".help-wrap.open .help-pop")
        shot(page, "сводка_подсказка_доля_рассмотренных_1440")
        page.keyboard.press("Escape")
        page.click(".help-btn[data-term=attention]"); page.wait_for_selector(".help-wrap.open .help-pop")
        shot(page, "сводка_подсказка_требуют_внимания_1440")
        page.click(".help-wrap.open .help-pop a"); page.wait_for_selector("#help-body"); page.wait_for_timeout(400)
        shot(page, "справка_разделы_термин_подсвечен_1440")
        page.evaluate("window.scrollTo(0, 0)"); page.fill("input[aria-label='Поиск по справке']", "срок"); page.wait_for_timeout(300)
        shot(page, "справка_поиск_срок_1440")
        page.goto(f"{base}/panel#/queue"); page.wait_for_selector("table"); page.wait_for_timeout(600)
        page.click(".help-btn[data-term=attention]"); page.wait_for_selector(".help-wrap.open .help-pop")
        shot(page, "очередь_подсказка_у_счётчика_1440")
        page.keyboard.press("Escape")
        page.click("tbody tr >> nth=0"); page.wait_for_selector(".appeal-card")
        page.click(".appeal-card details.sect >> nth=0 >> summary"); page.wait_for_timeout(300)
        page.click(".appeal-card .help-btn[data-term=first_response]"); page.wait_for_selector(".help-wrap.open .help-pop")
        shot(page, "карточка_подробности_срок_первого_ответа_1440")
        page.keyboard.press("Escape")
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": 15})
        page.goto(f"{base}/panel#/admin"); page.wait_for_selector("text=Настройки"); page.wait_for_timeout(800)
        page.evaluate("document.querySelector('.help-btn[data-term=set_league_done]').scrollIntoView({block: 'center'})"); page.wait_for_timeout(300)
        page.click(".help-btn[data-term=set_league_done]"); page.wait_for_selector(".help-wrap.open .help-pop")
        shot(page, "администрирование_настройки_подсказка_вес_лиги_1440")
        page.goto(f"{base}/panel#/league"); page.wait_for_selector(".tbl.league"); page.wait_for_timeout(800); page.evaluate("window.scrollTo(0, 0)")
        page.click(".help-btn[data-term=league_score]"); page.wait_for_selector(".help-wrap.open .help-pop")
        shot(page, "лига_подсказка_балл_1440")
        ctx.close()
        phone = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="ru-RU")
        ph = phone.new_page()
        ph.request.post(f"{base}/api/auth/login-as", data={"user_id": 6})
        ph.goto(f"{base}/app"); ph.wait_for_selector("#my-tasks"); ph.wait_for_timeout(800)
        shot(ph, "телефон_главная_мои_поручения_счётчик_390")
        ph.click("#my-tasks"); ph.wait_for_selector("text=Поручения с совещаний"); ph.wait_for_timeout(300)
        ph.click(".help-btn[data-term=my_tasks]"); ph.wait_for_selector(".help-wrap.open .help-pop")
        shot(ph, "телефон_мои_поручения_подсказка_390")
        ph.goto(f"{base}/app#/"); ph.wait_for_selector("#my-tasks"); ph.click(".list .item >> nth=0"); ph.wait_for_selector("text=История"); ph.wait_for_timeout(300)
        ph.click(".help-btn[data-term=stages]"); ph.wait_for_selector(".help-wrap.open .help-pop")
        shot(ph, "телефон_обращение_подсказка_стадии_390")
        phone.close(); b.close()


if __name__ == "__main__":
    main()
