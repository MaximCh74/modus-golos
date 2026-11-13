#!/usr/bin/env python3
"""Скрины «Сводки» после ТЗ владельца 13.11 (второе): карточки одного вида без цветных кромок, справа от карты — сводка, плитки 2×2,
часы, «По статусам»; «Команда» строкой; ниже — остальное. Компьютер 1440 и телефон 375, часы устройства — по Астане. Базу не меняет,
входит один раз. Запуск: python3 tools/remarks13_shots.py <папка> [<папка2> …] [--base http://127.0.0.1:8070]"""
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
        state = None
        for w, h in ((1440, 900), (375, 812)):
            phone = w < 500
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone,
                                locale="ru-RU", timezone_id="Asia/Almaty", service_workers="block", storage_state=state)
            pg = ctx.new_page()
            if state is None:
                r = pg.request.post(f"{a.base}/api/auth/login-as", data={"user_id": 1})
                if not r.ok:
                    raise SystemExit(f"вход: {r.status}")
                state = ctx.storage_state()
            pg.goto(a.base + "/panel"); pg.wait_for_selector(".map .marker"); pg.wait_for_selector(".clock .clock-hm"); pg.wait_for_timeout(1800)
            for name, full in ((f"13_сводка_{w}_первый_экран", False), (f"13_сводка_{w}_вся_страница", True)):
                first = outs[0] / f"{name}.jpg"
                pg.screenshot(path=str(first), type="jpeg", quality=88, full_page=full)
                for o in outs[1:]:
                    shutil.copy(first, o / first.name)
                ok = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                print(f"  {name}" + ("" if ok else "  ← ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
