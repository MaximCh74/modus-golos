#!/usr/bin/env python3
"""Скрины главной после замечаний владельца 13.11 (после меню пользователя): карточки под картой в градиенте главной кнопки, «Статистика»
в подвале, объект Атырау на карте как город; нажатие — форма «Объект» с подставленным городом; карта директора с Атырау. Компьютер
1440 и телефон 390. Базу не меняет (вход директора — демо, один раз). Запуск: python3 tools/remarks18_shots.py <папка> [<папка2> …]
[--base http://127.0.0.1:8070]"""
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

        def ctx_for(w: int, h: int, state=None):
            phone = w < 500
            return b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone,
                                 locale="ru-RU", timezone_id="Asia/Almaty", service_workers="block", reduced_motion="reduce", storage_state=state)

        def save(pg, name: str, full: bool = False):
            first = outs[0] / f"18_{name}.jpg"
            pg.screenshot(path=str(first), type="jpeg", quality=88, full_page=full)
            for o in outs[1:]:
                shutil.copy(first, o / first.name)
            ok = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            print(f"  18_{name}" + ("" if ok else "  <- ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))

        for w, h in ((1440, 900), (390, 844)):
            ctx = ctx_for(w, h)
            pg = ctx.new_page()
            pg.goto(a.base + "/"); pg.wait_for_selector(".feats .feat"); pg.wait_for_timeout(1500)
            save(pg, f"главная_{w}_вся_страница", full=True)
            if w > 500:
                pg.locator(".feats").scroll_into_view_if_needed(); pg.locator(".feats .feat").nth(1).hover(); pg.wait_for_timeout(400)
                save(pg, f"главная_{w}_карточки_наведение")
            pg.locator(".map .marker.site").click(force=True)
            pg.wait_for_url("**/q/FIELD?city=*"); pg.wait_for_selector("input[name=site_city]"); pg.wait_for_timeout(400)
            save(pg, f"форма_объект_атырау_{w}")
            ctx.close()
        ctx = ctx_for(1440, 900)
        pg = ctx.new_page()
        assert pg.request.post(f"{a.base}/api/auth/login-as", data={"user_id": 1}).ok
        pg.goto(a.base + "/panel#/summary"); pg.wait_for_selector(".map .marker.site"); pg.wait_for_timeout(1500)
        save(pg, "карта_директора_1440_атырау")
        ctx.close()
        b.close()


if __name__ == "__main__":
    main()
