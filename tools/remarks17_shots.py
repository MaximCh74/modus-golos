#!/usr/bin/env python3
"""Скрины меню пользователя (замечание владельца 13.11): кнопка с именем в шапках главной, приложения, панели и /boss, меню «Сменить
пользователя / Выйти / Быстро войти как». Компьютер 1440 и телефон 390. Базу не меняет (входы — демо). Запуск:
python3 tools/remarks17_shots.py <папка> [<папка2> …] [--base http://127.0.0.1:8070]"""
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
                                locale="ru-RU", service_workers="block", reduced_motion="reduce", storage_state=states.get(uid))
            pg = ctx.new_page()
            if uid not in states:
                assert pg.request.post(f"{a.base}/api/auth/login-as", data={"user_id": uid}).ok
                states[uid] = ctx.storage_state()
            return ctx, pg

        def save(pg, name: str):
            first = outs[0] / f"17_{name}.jpg"
            pg.screenshot(path=str(first), type="jpeg", quality=88)
            for o in outs[1:]:
                shutil.copy(first, o / first.name)
            print(f"  17_{name}")

        shots = [(23, 1440, 900, "/", "главная_1440_меню"), (1, 1440, 900, "/panel#/summary", "панель_1440_меню"),
                 (23, 390, 844, "/", "главная_390_меню"), (23, 390, 844, "/app", "приложение_390_меню"), (1, 390, 844, "/boss", "boss_390_меню")]
        for uid, w, h, path, name in shots:
            ctx, pg = page_for(uid, w, h)
            pg.goto(a.base + path); pg.wait_for_selector(".user-btn"); pg.wait_for_timeout(1200)
            pg.locator(".user-btn:visible").first.click(); pg.wait_for_selector(".user-wrap.open .um-quick"); pg.wait_for_timeout(300)
            save(pg, name)
            ctx.close()
        ctx, pg = page_for(1, 390, 844)   # панель на телефоне: те же пункты — в «☰»
        pg.goto(a.base + "/panel#/summary"); pg.wait_for_selector(".nav-toggle"); pg.wait_for_timeout(1000)
        pg.click(".nav-toggle"); pg.wait_for_selector(".nav-panel.open .um-quick"); pg.wait_for_timeout(300)
        save(pg, "панель_390_меню_в_гамбургере")
        ctx.close()
        b.close()


if __name__ == "__main__":
    main()
