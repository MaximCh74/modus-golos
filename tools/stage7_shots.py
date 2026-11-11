#!/usr/bin/env python3
"""Скрины этапа 7, шаг 1 (Playwright): главная на ноутбуке 1440 и телефоне 375, карточка города, лист снизу, /design, /changes,
плюс сравнение с макетом Марка рядом. Запуск при работающем сервере: python3 tools/stage7_shots.py <папка> [--mockup <файл>]"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    ap.add_argument("--mockup", default="")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); base = a.base

    def shot(page, name, full=False):
        page.wait_for_timeout(900)
        page.screenshot(path=str(out / f"{name}.jpg"), type="jpeg", quality=90, full_page=full)
        print("  ", name)

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU", device_scale_factor=1.25)
        page = ctx.new_page()
        page.goto(f"{base}/"); page.wait_for_selector(".citypop .citycard")
        shot(page, "10_главная_1440_Омск")
        page.click("button.marker[title*='Павлодар']"); page.wait_for_timeout(300)
        shot(page, "11_главная_1440_Павлодар")
        page.goto(f"{base}/design"); page.wait_for_selector(".swatches")
        shot(page, "12_design_справочник", full=True)
        page.goto(f"{base}/changes"); page.wait_for_selector(".card")
        shot(page, "13_что_изменили_без_входа")
        ctx.close()
        ctx = b.new_context(viewport={"width": 375, "height": 812}, locale="ru-RU", device_scale_factor=2, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(f"{base}/"); page.wait_for_selector(".city-pills .btn")
        shot(page, "14_главная_375")
        shot(page, "15_главная_375_вся", full=True)
        page.click(".city-pills .btn:has-text('Омск')"); page.wait_for_selector(".sheet .citycard")
        shot(page, "16_главная_375_карточка_снизу")
        ctx.close(); b.close()
    if a.mockup and Path(a.mockup).is_file():
        from PIL import Image
        m = Image.open(a.mockup).convert("RGB"); ours = Image.open(out / "10_главная_1440_Омск.jpg").convert("RGB")
        hgt = 900
        m = m.resize((round(m.width * hgt / m.height), hgt)); ours = ours.resize((round(ours.width * hgt / ours.height), hgt))
        canvas = Image.new("RGB", (m.width + ours.width + 40, hgt + 20), "white")
        canvas.paste(m, (0, 10)); canvas.paste(ours, (m.width + 40, 10))
        canvas.save(out / "01_сравнение_макет_слева_наша_справа.jpg", "JPEG", quality=88)
        print("   01_сравнение_макет_слева_наша_справа")


if __name__ == "__main__":
    main()
