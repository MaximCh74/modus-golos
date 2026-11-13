#!/usr/bin/env python3
"""Скрины девятого и десятого списков замечаний владельца 13.11 (Playwright, при работающем сервере): режим совещания — две кнопки
без значков; правило «в кнопках с текстом значков нет» по экранам; карта директора — новая рамка, объект как город, подписи не
обрезаются. Телефон 360/375/390, компьютер 1440 и 1920. Ничего не меняет в базе; входим по разу на пользователя (лимит демо-входа).
Запуск: python3 tools/remarks9_shots.py <папка> [<папка2> …] [--base http://127.0.0.1:8070]"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

DIRECTOR, RESPONSIBLE, EMPLOYEE, ADMIN = 1, 2, 17, 15


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
        states: dict[int, dict] = {}

        def page_for(uid: int | None, width: int, height: int | None = None):
            phone = width < 500
            ctx = b.new_context(viewport={"width": width, "height": height or (812 if phone else 900)}, device_scale_factor=2 if phone else 1,
                                is_mobile=phone, has_touch=phone, locale="ru-RU", service_workers="block", storage_state=states.get(uid) if uid else None)
            pg = ctx.new_page()
            if uid and uid not in states:
                r = pg.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})
                if not r.ok:
                    raise SystemExit(f"вход {uid}: {r.status} {r.text()}")
                states[uid] = ctx.storage_state()
            return ctx, pg

        def shot(pg, name: str):
            pg.wait_for_timeout(700)
            first = outs[0] / f"9_{name}.jpg"
            pg.screenshot(path=str(first), type="jpeg", quality=88)
            for o in outs[1:]:
                shutil.copy(first, o / first.name)
            sw = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            print(f"  9_{name}" + ("" if sw else "  ← ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))

        # ---- режим совещания: две кнопки без значков, «?» объясняет, что загрузить ----
        for w in (360, 390):
            ctx, pg = page_for(RESPONSIBLE, w)
            pg.goto(base + "/app#/meeting"); pg.wait_for_selector("text=Режим совещания"); pg.wait_for_timeout(900)
            shot(pg, f"1_совещание_две_кнопки_без_значков_{w}")
            if w == 390:
                pg.click(".help-btn[data-term=meeting]"); pg.wait_for_selector(".help-wrap.open .help-pop"); shot(pg, "1_совещание_что_загрузить_в_подсказке_390")
            ctx.close()
        ctx, pg = page_for(RESPONSIBLE, 1440)
        pg.goto(base + "/panel#/meetings/new"); pg.wait_for_selector("text=Режим совещания"); shot(pg, "1_совещание_1440")
        ctx.close()

        # ---- правило: в кнопках с текстом значков нет ----
        ctx, pg = page_for(None, 1440)
        pg.goto(base + "/"); pg.wait_for_timeout(5000); pg.mouse.wheel(0, 420); shot(pg, "2_главная_кнопки_и_карточки_без_значков_1440")
        ctx.close()
        ctx, pg = page_for(EMPLOYEE, 375)
        pg.goto(base + "/app#/"); pg.wait_for_selector("#home-cta"); shot(pg, "2_приложение_без_значков_в_кнопках_375")
        pg.goto(base + "/app#/new"); pg.wait_for_selector(".type-switch"); pg.mouse.wheel(0, 500); shot(pg, "2_форма_обращения_без_значков_375")
        ctx.close()
        ctx, pg = page_for(ADMIN, 1440)
        pg.goto(base + "/panel"); pg.wait_for_selector(".staff-tbl tbody tr"); shot(pg, "2_администрирование_кнопки_без_значков_1440")
        ctx.close()

        # ---- карта директора ----
        for w, h in ((1440, 900), (1920, 1080), (375, 812)):
            ctx, pg = page_for(DIRECTOR, w, h)
            pg.goto(base + "/panel#/summary"); pg.wait_for_selector(".map .marker"); pg.wait_for_timeout(1800)
            pg.locator(".map-card").scroll_into_view_if_needed(); pg.wait_for_timeout(400)
            shot(pg, f"3_карта_директора_рамка_объект_как_город_{w}")
            if w == 375:
                pg.goto(base + "/boss"); pg.wait_for_selector(".boss-tile"); pg.wait_for_timeout(1200); shot(pg, "2_boss_кнопки_без_значков_375")
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
