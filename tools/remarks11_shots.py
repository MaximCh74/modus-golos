#!/usr/bin/env python3
"""Скрины ТЗ владельца 13.11 «панель директора — меню, «Сводка», часы по городам» (Playwright, при работающем сервере): «Сводка» на 1920,
1024 и 375; часы на Омске и на Самаре. Часы устройства — по Астане (timezone_id), как у владельца: «+1 ч к вашему» у Омска, «−1 ч» у
Самары. Ничего не меняет в базе; входим один раз (лимит демо-входа). Запуск: python3 tools/remarks11_shots.py <папка> [<папка2> …]"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

DIRECTOR = 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="+")
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    a = ap.parse_args()
    outs = [Path(o) for o in a.out]
    for o in outs:
        o.mkdir(parents=True, exist_ok=True)
    base = a.base

    with sync_playwright() as p:
        b = p.chromium.launch()
        state: dict = {}

        def page_for(width: int, height: int):
            phone = width < 500
            ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone,
                                locale="ru-RU", timezone_id="Asia/Almaty", service_workers="block", storage_state=state.get("s"))
            pg = ctx.new_page()
            if "s" not in state:
                r = pg.request.post(f"{base}/api/auth/login-as", data={"user_id": DIRECTOR})
                if not r.ok:
                    raise SystemExit(f"вход: {r.status} {r.text()}")
                state["s"] = ctx.storage_state()
            return ctx, pg

        def save(pg, name: str, full: bool = False, el=None):
            first = outs[0] / f"11_{name}.jpg"
            (el or pg).screenshot(path=str(first), type="jpeg", quality=88, **({"full_page": True} if full and not el else {}))
            for o in outs[1:]:
                shutil.copy(first, o / first.name)
            sw = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            print(f"  11_{name}" + ("" if sw else "  ← ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))

        def open_summary(w: int, h: int):
            ctx, pg = page_for(w, h)
            pg.goto(base + "/panel")   # без адреса раздела: директор попадает на «Сводку» сам
            pg.wait_for_selector(".map .marker"); pg.wait_for_selector(".clock .clock-hm"); pg.wait_for_timeout(1800)
            assert pg.evaluate("location.hash") == "#/summary"
            return ctx, pg

        # «Сводка» на 1920: первый экран и вся страница
        ctx, pg = open_summary(1920, 1080)
        save(pg, "1_сводка_1920_первый_экран")
        save(pg, "2_сводка_1920_вся_страница", full=True)
        # часы: Омск по умолчанию, затем Самара
        card = pg.locator(".stats-card")
        card.scroll_into_view_if_needed(); pg.wait_for_timeout(400)
        save(pg, "5_часы_Омск_1920", el=card)
        pg.locator(".clock-cities .chip", has_text="Самара").click(); pg.wait_for_timeout(500)
        save(pg, "6_часы_Самара_1920", el=card)
        pg.locator(".clock-cities .chip", has_text="Омск").click()
        ctx.close()
        # узкий экран: ~1024 и телефон 375 — колонки друг под другом
        ctx, pg = open_summary(1024, 900)
        save(pg, "3_сводка_1024_первый_экран")
        save(pg, "3_сводка_1024_вся_страница", full=True)
        ctx.close()
        ctx, pg = open_summary(375, 812)
        save(pg, "4_сводка_375_первый_экран")
        pg.locator(".sum-side .summary-ai").scroll_into_view_if_needed(); pg.wait_for_timeout(400)
        save(pg, "4_сводка_375_сводка_и_команда")
        card = pg.locator(".stats-card"); card.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
        pg.locator(".clock-cities .chip", has_text="Самара").click(); pg.wait_for_timeout(400)
        save(pg, "4_часы_Самара_375", el=card)
        pg.locator(".clock-cities .chip", has_text="Омск").click()
        ctx.close()
        b.close()


if __name__ == "__main__":
    main()
