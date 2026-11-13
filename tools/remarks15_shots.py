#!/usr/bin/env python3
"""Скрины замечаний владельца 13.11 (08:20–08:23): лига — «Показать всех», «Подробнее» строками, «Как начисляются баллы» и «Витрина наград»,
«Из чего баллы»; администрирование — «Аватарки» сеткой, колонки вровень. Компьютер 1440, телефон 390 (лига) и 375 (администрирование).
Базу не меняет (кнопку «Да» не нажимает), входит по разу на пользователя. Запуск: python3 tools/remarks15_shots.py <папка> [<папка2> …]"""
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
        states: dict = {}

        def page_for(uid: int, w: int, h: int):
            phone = w < 500
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone,
                                locale="ru-RU", service_workers="block", storage_state=states.get(uid))
            pg = ctx.new_page()
            if uid not in states:
                assert pg.request.post(f"{a.base}/api/auth/login-as", data={"user_id": uid}).ok
                states[uid] = ctx.storage_state()
            return ctx, pg

        def save(pg, name: str, full: bool = False, el=None):
            first = outs[0] / f"15_{name}.jpg"
            if full and not el:
                pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(200)   # фиксированная шапка приложения — вверху, а не посреди снимка
            (el or pg).screenshot(path=str(first), type="jpeg", quality=88, **({"full_page": True} if full and not el else {}))
            for o in outs[1:]:
                shutil.copy(first, o / first.name)
            ok = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            print(f"  15_{name}" + ("" if ok else "  ← ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))

        # лига 1440 — сотрудник Серик (своя строка в топе), свёрнуто, развёрнуто, «Подробнее», «Из чего баллы»
        ctx, pg = page_for(27, 1440, 900)
        pg.goto(a.base + "/app#/league"); pg.wait_for_selector(".pod-step"); pg.wait_for_timeout(900)
        save(pg, "1_лига_1440_свёрнуто", full=True)
        pg.click(".lg-all"); pg.click(".lg-more"); pg.wait_for_timeout(600)
        save(pg, "2_лига_1440_показать_всех_и_подробнее", full=True)
        pg.click(".lg-all"); pg.wait_for_timeout(300)
        pg.locator(".emp-card .pts-btn").first.click(); pg.wait_for_selector(".pts-pop.open .pts-part"); pg.wait_for_timeout(300)
        save(pg, "3_лига_1440_из_чего_баллы")
        ctx.close()
        # лига 390 — Нурлан (не в топ-10): вкладка «Сотрудники», свёрнуто и «Показать всех» (прокрутка к своей строке)
        ctx, pg = page_for(28, 390, 844)
        pg.goto(a.base + "/app#/league"); pg.wait_for_selector(".pod-step"); pg.wait_for_timeout(900)
        save(pg, "4_лига_390_филиалы", full=True)
        pg.click(".lg-seg .seg-btn[data-tab=top]"); pg.wait_for_timeout(300)
        save(pg, "5_лига_390_сотрудники_свёрнуто", full=True)
        pg.click(".lg-all"); pg.wait_for_timeout(500)
        pg.locator(".lg-all").scroll_into_view_if_needed(); pg.wait_for_timeout(300)
        save(pg, "6_лига_390_показать_всех")
        ctx.close()
        # администрирование — «Аватарки»: 1440 (наведение) и 375 (нажатие, подтверждение)
        for w, h in ((1440, 900), (375, 812)):
            ctx, pg = page_for(15, w, h)
            pg.goto(a.base + "/panel#/admin"); pg.wait_for_selector(".ava-grid"); pg.wait_for_timeout(1200)
            if w == 1440:
                save(pg, "7_администрирование_1440_вся_страница", full=True)
            card = pg.locator(".ava-card"); card.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
            if w == 1440:
                pg.locator(".ava-photo").nth(2).hover(); pg.wait_for_timeout(300)
                save(pg, "8_аватарки_1440_наведение", el=card)
            else:
                pg.locator(".ava-photo").nth(1).tap(); pg.wait_for_timeout(300)
                pg.locator(".ava-tile.show .ava-remove").tap(); pg.wait_for_timeout(300)
                save(pg, "9_аватарки_375_подтверждение", el=card)
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
