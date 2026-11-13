#!/usr/bin/env python3
"""Скрины пункта 2 очереди 12.11 — «Директор в кармане» (Playwright, при работающем сервере, телефон 390×844): главный экран за неделю
и за сегодня, ответ на вопрос, список «ждут вашего решения», «пришло», «не знаю», подтверждение команды, заглушка не-директору.
Запуск: python3 tools/stage12_shots.py <папка> [--base http://127.0.0.1:8070]. Решения не принимает, команды не отправляет."""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    ap.add_argument("--start", type=int, default=20)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); base = a.base
    n = [a.start]

    def wait_text(page, needle):   # CSP запрещает eval — ждём текст приветствия опросом
        for _ in range(300):
            if needle in page.locator(".boss-greet-text").inner_text():
                return
            page.wait_for_timeout(200)
        raise RuntimeError("не дождались приветствия: " + needle)

    def shot(page, name):
        page.wait_for_timeout(700)
        page.screenshot(path=str(out / f"{n[0]:02d}_{name}.jpg"), type="jpeg", quality=90)
        print("  ", n[0], name); n[0] += 1

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="ru-RU")
        page = ctx.new_page()
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": 1})
        page.goto(f"{base}/boss"); page.wait_for_selector(".boss-tile b:not(:has-text('…'))"); page.wait_for_timeout(1200)
        page.click(".seg-btn[data-period=week]"); page.wait_for_timeout(1000)
        shot(page, "директор_в_кармане_неделя_390")
        page.click(".seg-btn[data-period=month]"); wait_text(page, "За месяц"); page.wait_for_timeout(400)
        shot(page, "директор_в_кармане_сегодня_390")
        page.click(".seg-btn[data-period=week]"); wait_text(page, "недел"); page.wait_for_timeout(400)
        for text, name in (("Кто просрочил?", "вопрос_кто_просрочил"), ("Что по Омску?", "вопрос_что_по_Омску"), ("Что по обращению A-027?", "вопрос_обращение_A-027")):
            page.fill(".boss-ask-text", text); page.click(".boss-send"); page.wait_for_selector(".boss-sheet .boss-answer", timeout=60000); page.wait_for_timeout(500)
            shot(page, name + "_390")
            page.keyboard.press("Escape"); page.wait_for_timeout(300)
        page.click(".boss-tile[data-tile=decisions]"); page.wait_for_selector(".boss-sheet .boss-item")
        shot(page, "плитка_ждут_решения_принять_отклонить_390")
        page.keyboard.press("Escape"); page.wait_for_timeout(300)
        page.click(".boss-tile[data-tile=overdue]"); page.wait_for_selector(".boss-sheet .boss-item")
        shot(page, "плитка_просрочено_список_390")
        page.keyboard.press("Escape"); page.wait_for_timeout(300)
        page.fill(".boss-ask-text", "Запроси новости по обращениям в работе в Омске до 18:00"); page.click(".boss-send"); page.wait_for_selector(".boss-sheet .boss-item", timeout=60000)
        shot(page, "команда_подтверждение_перед_отправкой_390")
        page.keyboard.press("Escape"); page.wait_for_timeout(300)
        page.fill(".boss-ask-text", "Закажи пиццу в офис"); page.click(".boss-send"); page.wait_for_selector(".boss-sheet .chip", timeout=60000)
        shot(page, "неизвестный_вопрос_не_знаю_390")
        page.keyboard.press("Escape")
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": 16})
        page.goto(f"{base}/boss"); page.wait_for_selector(".boss-gate")
        shot(page, "не_директор_заглушка_390")
        ctx.close(); b.close()


if __name__ == "__main__":
    main()
