#!/usr/bin/env python3
"""Скрины этапа 8 §4 (Playwright, при работающем сервере): администратор добавляет рабочего «Павлодар, производство» и получает
приглашение (QR, ссылка, PDF), импорт CSV с ошибочной строкой, карточка-приглашение (PDF → JPG через pdftoppm), телефон 375 px:
страница приглашения → «Войти» → рабочий вошёл и видит свои баллы → ссылка уже использована.
Запуск: python3 tools/stage8_shots.py <папка> [--base http://127.0.0.1:8070]. Создаёт тестовых сотрудников в живой базе —
после скринов вернуть демо-состояние (tools/demo_reset.sh)."""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

CSV = ("Имя;Город;Отдел;Роль;Телефон;Должность;Почта\r\n"
       "Марат Ибраев;Павлодар;Производство;Сотрудник;+7 701 000 00 01;Оператор участка;\r\n"
       "Ошибочная Строка;Караганда;Производство;Сотрудник;;;\r\n"
       "Асель Мусина;Объект;Проектирование;Сотрудник;+7 702 000 00 02;Инженер;asel@example.kz\r\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    ap.add_argument("--start", type=int, default=40)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); base = a.base
    n = [a.start]

    def shot(page, name, full=False):
        page.wait_for_timeout(900)
        page.screenshot(path=str(out / f"{n[0]}_{name}.jpg"), type="jpeg", quality=90, full_page=full)
        print("  ", n[0], name); n[0] += 1

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU", device_scale_factor=1.25)
        page = ctx.new_page()
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": 15})
        page.goto(f"{base}/panel#/admin"); page.wait_for_selector(".staff")
        page.click("button:has-text('Добавить сотрудника')"); page.wait_for_selector("text=Новый сотрудник")
        page.fill("input[placeholder='Имя Фамилия']", "Ержан Касымов")
        page.select_option(".grid3 select >> nth=0", label="Павлодар"); page.select_option(".grid3 select >> nth=1", label="Производство")
        page.fill("input[placeholder='например, Оператор участка']", "Сварщик"); page.fill("input[placeholder='+7 701 000 00 00']", "+7 701 444 55 66")
        shot(page, "админ_добавление_рабочего_Павлодар_производство")
        page.click(".card-info button.btn-primary:has-text('Добавить')"); page.wait_for_selector(".invite-card img.inv-qr"); page.wait_for_timeout(600)
        shot(page, "админ_приглашение_QR_ссылка_PDF")
        url = page.input_value(".invite-card input.inv-link")
        inv_id = page.eval_on_selector(".invite-card a[href*='cards.pdf']", "e => e.getAttribute('href').split('ids=')[1]")
        # импорт CSV с ошибочной строкой
        page.click("button:has-text('Импорт из CSV или Excel')"); page.wait_for_selector("text=Импорт списком")
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8-sig") as f:
            f.write(CSV); csv_path = f.name
        page.set_input_files("input[type=file]", csv_path)
        page.click("button:has-text('Импортировать')"); page.wait_for_selector("text=не найден"); page.wait_for_timeout(400)
        shot(page, "админ_импорт_CSV_ошибочная_строка_остальные_загружены")
        page.evaluate("document.querySelector('.staff-tbl').scrollIntoView()"); shot(page, "админ_таблица_сотрудников_приглашения")
        # карточка PDF → JPG
        pdf = page.request.get(f"{base}/api/admin/invites/cards.pdf?ids={inv_id}")
        pdf_path = out / f"{n[0]}_карточка_приглашение.pdf"; pdf_path.write_bytes(pdf.body())
        subprocess.run(["pdftoppm", "-jpeg", "-r", "110", "-singlefile", str(pdf_path), str(out / f"{n[0]}_карточка_приглашение_PDF")], check=True)
        print("  ", n[0], "карточка_приглашение (pdf + jpg)"); n[0] += 1
        ctx.close()
        # телефон: приглашение → вход → баллы → повторное открытие
        phone = b.new_context(viewport={"width": 375, "height": 812}, locale="ru-RU", device_scale_factor=2, is_mobile=True, has_touch=True)
        ph = phone.new_page()
        ph.goto(url); ph.wait_for_selector("button:has-text('Войти')")
        shot(ph, "телефон_приглашение_375")
        ph.click("button:has-text('Войти')"); ph.wait_for_url("**/app**", timeout=15000); ph.wait_for_selector("text=Мои баллы"); ph.wait_for_timeout(500)
        shot(ph, "телефон_рабочий_вошёл_видит_баллы_375")
        phone.close()
        phone2 = b.new_context(viewport={"width": 375, "height": 812}, locale="ru-RU", device_scale_factor=2, is_mobile=True, has_touch=True)
        ph2 = phone2.new_page(); ph2.goto(url); ph2.wait_for_selector("text=Ссылка уже использована")
        shot(ph2, "телефон_ссылка_уже_использована_375")
        phone2.close(); b.close()


if __name__ == "__main__":
    main()
