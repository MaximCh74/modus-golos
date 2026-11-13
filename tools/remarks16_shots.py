#!/usr/bin/env python3
"""Скрины главной после замечаний владельца 13.11: карта в той же рамке, что у директора, на всю ширину; окно города по образцу (Самара);
телефон — шторка. Часы устройства — по Астане, движение — «уменьшить» (мягкий дрейф: кадр стабильнее). Без входа, базу не меняет.
Запуск: python3 tools/remarks16_shots.py <папка> [<папка2> …] [--base http://127.0.0.1:8070]"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="+")
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    a = ap.parse_args()
    outs = [Path(o) for o in a.out]
    for o in outs:
        o.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w, h in ((1440, 900), (390, 844)):
            phone = w < 500
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone,
                                locale="ru-RU", timezone_id="Asia/Almaty", service_workers="block", reduced_motion="reduce")
            pg = ctx.new_page()
            pg.goto(a.base + "/"); pg.wait_for_selector(".map .marker"); pg.wait_for_timeout(1500)

            def save(name: str, full: bool = False):
                first = outs[0] / f"16_{name}.jpg"
                pg.screenshot(path=str(first), type="jpeg", quality=88, full_page=full)
                for o in outs[1:]:
                    shutil.copy(first, o / first.name)
                ok = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                print(f"  16_{name}" + ("" if ok else "  ← ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))

            if phone:
                save(f"главная_{w}_карта")
                pg.locator(".city-pills .btn", has_text="Самара").click(); pg.wait_for_timeout(600)
                save(f"главная_{w}_самара_шторка")
            else:
                pg.locator(".map .marker", has_text="Самара").click(force=True); pg.wait_for_timeout(600)
                pg.locator(".home-map").scroll_into_view_if_needed(); pg.wait_for_timeout(300)
                save(f"главная_{w}_самара")
                save(f"главная_{w}_вся_страница", full=True)
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
