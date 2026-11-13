#!/usr/bin/env python3
"""Скрины «Обратная связь от клиентов» (решение владельца 13.11, минимум): главная с карточкой для клиентов и без окна города при
загрузке, форма /c (компьютер 1440 и телефон 390) — заполненная и «Спасибо, ваше сообщение получено», вкладка «От клиентов» в панели
директора — список и сообщение с фото. ВНИМАНИЕ: отправляет одно сообщение клиента с фото в базу — после скринов tools/demo_reset.sh.
Запуск: python3 tools/remarks19_shots.py <папка> [<папка2> …] [--base http://127.0.0.1:8070] [--panel-only]"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def cabinet_photo(path: Path) -> Path:
    """Синтетическое «фото» шкафа управления (рисунок, не снимок): серый шкаф, дверца, индикаторы, табличка."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (900, 1200), (214, 218, 222))
    d = ImageDraw.Draw(im)
    d.rectangle((150, 80, 750, 1140), fill=(176, 182, 188), outline=(120, 126, 132), width=6)
    d.rectangle((190, 120, 710, 1100), fill=(196, 201, 206), outline=(140, 146, 152), width=4)
    d.rectangle((640, 520, 670, 700), fill=(90, 96, 102))
    for i, col in enumerate(((46, 160, 67), (230, 170, 20), (200, 40, 40))):
        d.ellipse((260 + i * 90, 200, 320 + i * 90, 260), fill=col, outline=(60, 60, 60), width=3)
    d.rectangle((260, 320, 560, 400), fill=(240, 240, 236), outline=(90, 90, 90), width=3)
    d.text((280, 345), "ШУ-1  насосы", fill=(40, 40, 40))
    im.save(path, "JPEG", quality=90)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="+")
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    ap.add_argument("--panel-only", action="store_true", help="только панель — сообщение уже отправлено")
    a = ap.parse_args()
    outs = [Path(o) for o in a.out]
    for o in outs:
        o.mkdir(parents=True, exist_ok=True)
    photo = cabinet_photo(Path(tempfile.mkdtemp()) / "shkaf_nasosy.jpg")
    with sync_playwright() as p:
        b = p.chromium.launch()
        states: dict = {}

        def page_for(w: int, h: int, uid: int | None = None):
            phone = w < 500
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone,
                                locale="ru-RU", timezone_id="Asia/Almaty", service_workers="block", reduced_motion="reduce", storage_state=states.get(uid))
            pg = ctx.new_page()
            if uid and uid not in states:
                assert pg.request.post(f"{a.base}/api/auth/login-as", data={"user_id": uid}).ok
                states[uid] = ctx.storage_state()
            return ctx, pg

        def save(pg, name: str, full: bool = False):
            first = outs[0] / f"19_{name}.jpg"
            pg.screenshot(path=str(first), type="jpeg", quality=88, full_page=full)
            for o in outs[1:]:
                shutil.copy(first, o / first.name)
            ok = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            print(f"  19_{name}" + ("" if ok else "  <- ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))

        for w, h in () if a.panel_only else ((1440, 900), (390, 844)):
            ctx, pg = page_for(w, h)
            pg.goto(a.base + "/"); pg.wait_for_selector(".feats .feat"); pg.wait_for_timeout(1500)
            save(pg, f"главная_{w}_вся_страница", full=True)
            pg.goto(a.base + "/c"); pg.wait_for_selector(".client-form"); pg.wait_for_timeout(400)
            if w > 500:
                save(pg, f"форма_клиента_{w}_пустая")
            pg.locator(".type-switch .btn", has_text="Замечание").click()
            pg.fill("textarea[name=text]", "На шкафу управления насосами мигает индикатор «Авария», а инструкции рядом нет. Пришлите, пожалуйста, специалиста.")
            pg.fill("input[name=place]", "Павлодар, насосная станция")
            pg.fill("input[name=name]", "Андрей, главный инженер"); pg.fill("input[name=contact]", "andrey@example.com")
            pg.locator("input[name=consent]").check()
            if w < 500:
                pg.set_input_files(".client-form input[type=file]", str(photo)); pg.wait_for_timeout(300)
            save(pg, f"форма_клиента_{w}_заполнена", full=True)
            if w < 500:
                pg.locator(".client-form button[type=submit]").click(); pg.wait_for_selector(".card-ok"); pg.wait_for_timeout(300)
                save(pg, f"форма_клиента_{w}_спасибо")
            ctx.close()
        for w, h in ((1440, 900), (390, 844)):
            ctx, pg = page_for(w, h, 1)
            pg.goto(a.base + "/panel#/clients"); pg.wait_for_selector("table.tbl.clients tbody tr"); pg.wait_for_timeout(600)
            save(pg, f"панель_от_клиентов_{w}", full=w < 500)
            pg.locator("table.tbl.clients tbody tr").first.click(); pg.wait_for_selector(".drawer .cm-detail")
            for _ in range(40):   # фото догрузилось (wait_for_function строкой не пускает CSP страницы)
                if pg.evaluate("(() => { const i = document.querySelector('.drawer .cm-photo'); return !i || i.naturalWidth > 0; })()"):
                    break
                pg.wait_for_timeout(100)
            pg.wait_for_timeout(300)
            save(pg, f"панель_от_клиентов_{w}_сообщение_с_фото")
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
