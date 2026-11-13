#!/usr/bin/env python3
"""Скрины восьмого списка замечаний владельца 13.11 (Playwright, при работающем сервере): карта директора больше, подписи не
обрезаются краем; «Уточнение» без значка; без значка ИИ — пояснение в «?»; филиал — только город. Телефон 375×812, компьютер
1440×900 и 1280×800. Ничего не меняет в базе. Демо-вход ограничен 30 входами за 10 минут — входим по разу на пользователя.
Запуск: python3 tools/remarks8_shots.py <папка> [<папка2> …] [--base http://127.0.0.1:8070]"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

DIRECTOR, EMPLOYEE = 1, 17


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
            first = outs[0] / f"8_{name}.jpg"
            pg.screenshot(path=str(first), type="jpeg", quality=88)
            for o in outs[1:]:
                shutil.copy(first, o / first.name)
            sw = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            print(f"  8_{name}" + ("" if sw else "  ← ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))

        def to(pg, sel: str, dy: int = -70):
            pg.locator(sel).first.scroll_into_view_if_needed(); pg.mouse.wheel(0, dy); pg.wait_for_timeout(400)

        for w, h in ((1440, 900), (1280, 800)):
            ctx, pg = page_for(DIRECTOR, w, h)
            pg.goto(base + "/panel#/summary"); pg.wait_for_selector(".map .marker"); pg.wait_for_timeout(1500)
            to(pg, ".map-card", -10); shot(pg, f"1_карта_директора_больше_подписи_не_обрезаются_{w}")
            if w == 1440:
                to(pg, "b:has-text('Повторяющиеся темы')", -40); shot(pg, "3_4_повторяющиеся_темы_без_значка_ИИ_только_города_1440")
                pg.click(".help-btn[data-term=repeated_topics]"); pg.wait_for_selector(".help-wrap.open .help-pop"); shot(pg, "3_подсказка_темы_находит_ИИ_1440")
                pg.keyboard.press("Escape")
                pg.goto(base + "/panel#/queue?status=clarify"); pg.wait_for_selector("table.queue tbody tr"); pg.wait_for_timeout(800)
                shot(pg, "2_уточнение_без_значка_1440")
                pg.locator("table.queue tbody tr").first.click(); pg.wait_for_selector(".appeal-card .brief"); pg.wait_for_timeout(500)
                pg.click(".appeal-card .help-btn[data-term=brief]"); pg.wait_for_selector(".help-wrap.open .help-pop"); shot(pg, "3_коротко_без_значка_ИИ_подсказка_1440")
                pg.goto(base + "/panel#/meetings"); pg.wait_for_selector("table.meetings"); shot(pg, "3_4_совещания_без_значка_ИИ_только_город_1440")
                pg.goto(base + "/panel#/admin"); pg.wait_for_selector(".staff-tbl"); to(pg, "text=Филиалы и QR", -40); shot(pg, "4_филиалы_и_QR_только_город_1440")
            ctx.close()
        ctx, pg = page_for(DIRECTOR, 375)
        pg.goto(base + "/panel#/summary"); pg.wait_for_selector(".map .marker"); pg.wait_for_timeout(1500)
        to(pg, ".map-card", -10); shot(pg, "1_карта_директора_375")
        pg.goto(base + "/boss"); pg.wait_for_selector(".boss-greet .help-btn"); pg.wait_for_timeout(1200)
        pg.click(".boss-greet .help-btn"); pg.wait_for_selector(".help-wrap.open .help-pop"); shot(pg, "3_boss_без_значка_ИИ_подсказка_375")
        ctx.close()
        ctx, pg = page_for(None, 375)
        pg.goto(base + "/q/FIELD"); pg.wait_for_selector(".type-switch"); shot(pg, "4_QR_форма_объекта_без_командировки_375")
        ctx.close()
        ctx, pg = page_for(EMPLOYEE, 375)
        pg.goto(base + "/app#/league"); pg.wait_for_selector(".lg-row"); shot(pg, "4_лига_только_города_375")
        ctx.close()
        b.close()


if __name__ == "__main__":
    main()
