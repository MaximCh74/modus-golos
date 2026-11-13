#!/usr/bin/env python3
"""Скрины шестого списка замечаний владельца 13.11 (Playwright, при работающем сервере): версия в подвале, очередь без «Возраста»,
совещания, лига, администрирование у директора, главная сотрудника с одной кнопкой, нижняя панель приложения, пять статусов.
Телефон 375×812 и компьютер 1440×900. Ничего не меняет в базе: только просмотр (вход «Войти как…» создаёт сессию).
Запуск: python3 tools/remarks6_shots.py <папка> [<папка2> …] [--base http://127.0.0.1:8070]"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

DIRECTOR, RESPONSIBLE, EMPLOYEE = 1, 2, 17


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

        def page_for(uid: int, width: int):
            phone = width < 500
            ctx = b.new_context(viewport={"width": width, "height": 812 if phone else 900}, device_scale_factor=2 if phone else 1,
                                is_mobile=phone, has_touch=phone, locale="ru-RU", service_workers="block")
            pg = ctx.new_page()
            pg.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})
            return ctx, pg

        def shot(pg, name: str, full: bool = False):
            pg.wait_for_timeout(700)
            first = outs[0] / f"6_{name}.jpg"
            pg.screenshot(path=str(first), type="jpeg", quality=88, full_page=full)
            for o in outs[1:]:
                shutil.copy(first, o / first.name)
            sw = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            print(f"  6_{name}" + ("" if sw else "  ← ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))

        def go(pg, path: str, wait: str):
            pg.goto(base + path); pg.wait_for_selector(wait); pg.wait_for_timeout(900)

        # ---- п. 0: версия в подвале ----
        ctx, pg = page_for(DIRECTOR, 1440)
        go(pg, "/panel#/meetings", "table.meetings")
        pg.locator("#foot .ver").scroll_into_view_if_needed(); shot(pg, "0_версия_в_подвале_панель_1440")
        # ---- п. 1: очередь ----
        go(pg, "/panel#/queue", "table.queue tbody tr"); shot(pg, "1_очередь_без_возраста_точка_у_номера_1440")
        pg.locator("table.queue tbody tr").first.click(); pg.wait_for_selector(".appeal-card"); shot(pg, "1_карточка_просрочено_на_N_дн_1440")
        # ---- п. 2: совещания ----
        go(pg, "/panel#/meetings", "table.meetings"); shot(pg, "2_совещания_вопросики_итог_на_всю_ширину_1440")
        # ---- п. 3: лига ----
        go(pg, "/panel#/league", "table.league"); shot(pg, "3_лига_филиалы_слева_сотрудники_справа_1440")
        # ---- п. 4: администрирование у директора ----
        go(pg, "/panel#/admin", ".admin-note"); shot(pg, "4_администрирование_у_директора_строка_сверху_1440")
        pg.locator("label.check:has-text('Директор видит администрирование')").scroll_into_view_if_needed(); shot(pg, "4_настройки_переключатель_директор_видит_1440")
        # ---- дополнительно: пять статусов в сводке и на карте ----
        go(pg, "/panel#/summary", ".kpis")
        pg.locator("b:has-text('По статусам')").scroll_into_view_if_needed(); pg.mouse.wheel(0, 120); shot(pg, "7_сводка_по_статусам_и_карта_1440")
        ctx.close()

        ctx, pg = page_for(DIRECTOR, 375)
        go(pg, "/panel#/queue", ".qcard"); shot(pg, "1_очередь_карточки_375")
        go(pg, "/panel#/meetings", "table.meetings"); shot(pg, "2_совещания_375")
        go(pg, "/panel#/league", ".lg-seg"); shot(pg, "3_лига_вкладки_филиалы_375")
        pg.click(".lg-seg .seg-btn[data-tab=top]"); shot(pg, "3_лига_вкладки_сотрудники_375")
        go(pg, "/panel#/admin", ".admin-note"); shot(pg, "4_администрирование_у_директора_375")
        ctx.close()

        # ---- п. 5–6: приложение сотрудника ----
        ctx, pg = page_for(EMPLOYEE, 375)
        go(pg, "/app#/", "#home-cta"); shot(pg, "5_главная_сотрудника_одна_кнопка_нижняя_панель_375")
        pg.click("#home-cta"); pg.wait_for_selector(".type-switch"); shot(pg, "5_форма_переключатель_проблема_идея_спасибо_375")
        go(pg, "/app#/league", ".lg-seg"); pg.click(".lg-seg .seg-btn[data-tab=top]"); shot(pg, "3_лига_приложение_сотрудники_375")
        go(pg, f"/app#/u/{EMPLOYEE}", "#profile-rewards"); shot(pg, "6_профиль_награды_внутри_375")
        go(pg, "/app#/", "#home-cta"); pg.evaluate("window.scrollTo(0, document.body.scrollHeight)"); shot(pg, "0_версия_в_подвале_приложение_375")
        ctx.close()
        ctx, pg = page_for(RESPONSIBLE, 375)
        go(pg, "/app#/", "#home-meeting"); shot(pg, "6_главная_ответственного_совещание_с_главной_375")
        ctx.close()
        ctx, pg = page_for(EMPLOYEE, 1440)
        go(pg, "/app#/", "#home-cta"); shot(pg, "5_главная_сотрудника_1440")
        go(pg, "/app#/league", ".lg-emp"); shot(pg, "3_лига_приложение_1440")
        ctx.close()
        ctx, pg = page_for(DIRECTOR, 1440)
        go(pg, "/app#/", ".tabs.app-tabs"); pg.locator(".tabs.app-tabs").scroll_into_view_if_needed(); shot(pg, "6_приложение_компьютер_вкладки_без_обрезки_1440")
        ctx.close()
        b.close()


if __name__ == "__main__":
    main()
