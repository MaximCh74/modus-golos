#!/usr/bin/env python3
"""Скрины этапа 6 (Playwright, headless Chromium): главная с картой (ноутбук и телефон), вход, сводка с блоком «Команда», экран
подтверждения с вежливым текстом из резкой команды, отправка, уведомление получателю, событие в истории, «не понял команду»,
администрирование (статус Битрикс24). Запуск при работающем сервере: python3 tools/stage6_shots.py <папка> [--base http://127.0.0.1:8070]
Меняет демо-базу (уведомления, события) — после прогона tools/demo_reset.sh."""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

RUDE = "Срочно всех бездельников в Омске заставь отчитаться по обращениям в работе до 18:00!!!"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    base = a.base

    def shot(page, name, full=False):
        page.wait_for_timeout(700)
        page.screenshot(path=str(out / f"{name}.jpg"), type="jpeg", quality=88, full_page=full)
        print("  ", name)

    def login(page, uid):
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1366, "height": 860}, locale="ru-RU", device_scale_factor=1.25)
        page = ctx.new_page()
        page.goto(f"{base}/")
        page.wait_for_selector("button.marker")
        shot(page, "70_главная_карта_ноутбук")
        page.click("button.marker[title*='Павлодар']")
        page.wait_for_selector(".city-card img")
        shot(page, "71_главная_карточка_Павлодар_QR")
        page.goto(f"{base}/login")
        page.wait_for_selector(".user-card")
        shot(page, "72_вход_демо_без_Битрикса")
        login(page, 1)
        page.goto(f"{base}/panel#/summary")
        page.wait_for_selector(".cmd-text")
        page.wait_for_timeout(1500)
        shot(page, "73_сводка_директора_команда_и_карта", full=True)
        page.fill(".cmd-text", RUDE)
        page.press(".cmd-text", "Enter")
        page.wait_for_selector(".cmd-rec", timeout=60000)
        page.locator(".command").scroll_into_view_if_needed()
        shot(page, "74_команда_резкая_формулировка_вежливый_текст")
        page.click(".command .card-info .btn-primary")
        page.wait_for_selector(".command .card-ok", timeout=30000)
        shot(page, "75_команда_отправлено")
        page.fill(".cmd-text", "закажи пиццу в офис")
        page.press(".cmd-text", "Enter")
        page.wait_for_selector(".command .card-warn", timeout=60000)
        shot(page, "76_команда_не_понял_список_возможностей")
        page.fill(".cmd-text", "Напомни Ерлану об обращениях без ответа до пятницы")
        page.press(".cmd-text", "Enter")
        page.wait_for_selector(".cmd-rec", timeout=60000)
        shot(page, "77_команда_фильтр_по_сотруднику_срок")
        a15 = page.evaluate("async () => (await (await fetch('/api/panel/appeals?q=A-015')).json())[0].id")
        page.goto(f"{base}/panel#/appeal/{a15}")
        page.wait_for_selector(".hist")
        page.locator(".hist").scroll_into_view_if_needed()
        shot(page, "78_история_A-015_директор_запросил_новости")
        login(page, 2)
        page.goto(f"{base}/app#/notifications")
        page.wait_for_selector(".list .item")
        shot(page, "79_уведомление_получателю_Олег")
        login(page, 15)
        page.goto(f"{base}/panel#/admin")
        page.wait_for_selector("details.card")
        shot(page, "80_администрирование_статус_Битрикс24_иконки", full=True)
        ctx.close()
        # телефон
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, locale="ru-RU", device_scale_factor=2, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(f"{base}/")
        page.wait_for_selector(".city-buttons .btn")
        shot(page, "81_главная_телефон_карта_и_города")
        page.click(".city-buttons .btn:has-text('Павлодар')")
        page.wait_for_selector(".city-card img")
        page.locator(".city-card").scroll_into_view_if_needed()
        shot(page, "82_главная_телефон_карточка_города")
        login(page, 1)
        page.goto(f"{base}/app")
        page.wait_for_selector(".cmd-text")
        page.locator(".command").scroll_into_view_if_needed()
        shot(page, "83_приложение_директор_команда_телефон")
        page.fill(".cmd-text", "прочитай сводку")
        page.press(".cmd-text", "Enter")
        page.wait_for_selector(".command .card-info", timeout=60000)
        shot(page, "84_команда_прочитать_сводку_телефон")
        page.goto(f"{base}/app#/new?type=problem")
        page.wait_for_selector(".mic")
        shot(page, "85_новое_обращение_иконки_телефон")
        ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
