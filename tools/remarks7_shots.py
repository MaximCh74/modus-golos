#!/usr/bin/env python3
"""Скрины седьмого списка замечаний владельца 13.11 (Playwright, при работающем сервере): администратор сразу в «Администрировании»,
таблица сотрудников без пустой середины, нумерация строк, «?» у блоков и колонок, красный счётчик на колокольчике (панель, приложение,
/boss), баллы — золотистая звезда без рамки. Телефон 375×812 и компьютер 1440×900.
Внимание: для счётчика у директора создаёт «спасибо» директору от сотрудника — после скринов вернуть базу tools/demo_reset.sh.
Запуск: python3 tools/remarks7_shots.py <папка> [<папка2> …] [--base http://127.0.0.1:8070]"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

DIRECTOR, ADMIN, EMPLOYEE = 1, 15, 17


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

        states: dict[int, dict] = {}   # демо-вход ограничен 30 входами за 10 минут с адреса — входим по разу на пользователя

        def page_for(uid: int, width: int):
            phone = width < 500
            ctx = b.new_context(viewport={"width": width, "height": 812 if phone else 900}, device_scale_factor=2 if phone else 1,
                                is_mobile=phone, has_touch=phone, locale="ru-RU", service_workers="block", storage_state=states.get(uid))
            pg = ctx.new_page()
            if uid not in states:
                r = pg.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})
                if not r.ok:
                    raise SystemExit(f"вход {uid}: {r.status} {r.text()}")
                states[uid] = ctx.storage_state()
            return ctx, pg

        def shot(pg, name: str):
            pg.wait_for_timeout(700)
            first = outs[0] / f"7_{name}.jpg"
            pg.screenshot(path=str(first), type="jpeg", quality=88)
            for o in outs[1:]:
                shutil.copy(first, o / first.name)
            sw = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            print(f"  7_{name}" + ("" if sw else "  ← ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))

        def to(pg, sel: str, dy: int = -70):
            pg.locator(sel).first.scroll_into_view_if_needed(); pg.mouse.wheel(0, dy); pg.wait_for_timeout(300)

        # ---- 1–4: администратор ----
        ctx, pg = page_for(ADMIN, 1440)
        pg.goto(base + "/panel"); pg.wait_for_selector(".staff-tbl tbody tr"); pg.wait_for_timeout(900)
        shot(pg, "1_администратор_сразу_в_администрировании_сотрудники_сверху_1440")
        pg.click(".staff-tbl thead th:nth-child(3) .help-btn"); pg.wait_for_selector(".help-wrap.open .help-pop")
        shot(pg, "4_подсказка_у_заголовка_колонки_1440")
        pg.keyboard.press("Escape"); pg.mouse.click(5, 300)
        to(pg, "table.cats"); shot(pg, "3_нумерация_категории_1440")
        to(pg, ".rewards-tbl", -160); shot(pg, "3_нумерация_награды_и_заявки_1440")
        to(pg, "text=Филиалы и QR", -40); shot(pg, "3_нумерация_филиалы_битрикс_1440")
        to(pg, "text=Объекты на карте", -40); shot(pg, "3_нумерация_объекты_аватарки_1440")
        ctx.close()
        ctx, pg = page_for(ADMIN, 375)
        pg.goto(base + "/panel"); pg.wait_for_selector(".staff-tbl tbody tr"); pg.wait_for_timeout(900)
        shot(pg, "1_администратор_сразу_в_администрировании_375")
        to(pg, ".staff-tbl tbody tr", -40); shot(pg, "2_сотрудники_нумерация_375")
        ctx.close()

        # ---- 5: красный счётчик — у директора настоящее «спасибо» от сотрудника (потом demo_reset) ----
        ctx, pg = page_for(DIRECTOR, 1440)
        if not pg.request.get(f"{base}/api/me").json().get("unread"):   # «спасибо» — только если у директора ещё нет непрочитанных
            ectx, epg = page_for(EMPLOYEE, 1440)
            epg.request.post(f"{base}/api/appeals", multipart={"type": "praise", "text": "Спасибо за быстрое решение по номенклатуре", "praise_to_user_id": str(DIRECTOR)})
            ectx.close()
        pg.goto(base + "/panel#/summary"); pg.wait_for_selector(".topbar .bell .n"); pg.wait_for_timeout(900)
        shot(pg, "5_колокольчик_красный_счётчик_панель_1440")
        ctx.close()
        ctx, pg = page_for(DIRECTOR, 375)
        pg.goto(base + "/boss"); pg.wait_for_selector(".boss-head .bell .n"); pg.wait_for_timeout(1500)
        shot(pg, "5_колокольчик_красный_счётчик_boss_375")
        ctx.close()

        # ---- 5–6: приложение сотрудника ----
        ctx, pg = page_for(EMPLOYEE, 375)
        pg.goto(base + "/app#/"); pg.wait_for_selector("#home-cta"); pg.wait_for_timeout(900)
        shot(pg, "6_баллы_золотая_звезда_без_рамки_и_счётчик_375")
        pg.click(".pts-home"); pg.wait_for_selector("#profile-rewards"); shot(pg, "6_баллы_нажатие_ведёт_в_профиль_375")
        pg.goto(base + "/app#/league"); pg.wait_for_selector(".lg-seg"); pg.click(".lg-seg .seg-btn[data-tab=top]"); shot(pg, "6_лига_звёзды_золотые_375")
        ctx.close()
        ctx, pg = page_for(EMPLOYEE, 1440)
        pg.goto(base + "/app#/"); pg.wait_for_selector("#home-cta"); pg.wait_for_timeout(900)
        shot(pg, "6_баллы_и_счётчик_приложение_1440")
        ctx.close()
        b.close()


if __name__ == "__main__":
    main()
