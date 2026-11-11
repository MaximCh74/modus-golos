#!/usr/bin/env python3
"""Видеозапись прогона сценария (Playwright, headless Chromium) → demo/backup.mp4 и чистые скрины для слайдов → demo/slides/.
Запуск при работающем сервере после tools/demo_reset.sh: python3 tools/demo_video.py [--base http://127.0.0.1:8070]
Голос в записи заменён текстом (микрофона у headless-браузера нет), остальное — как на сцене."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SLIDES = ROOT / "demo" / "slides"
TRANSCRIPT = open(ROOT / "tests" / "test_stage2.py", encoding="utf-8").read().split('TRANSCRIPT = """')[1].split('"""')[0]


def login(page, base, uid):
    page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})


def shot(page, name, full=False):
    page.wait_for_timeout(600)
    page.screenshot(path=str(SLIDES / f"{name}.png"), full_page=full)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    ap.add_argument("--no-video", action="store_true")
    a = ap.parse_args()
    base = a.base
    SLIDES.mkdir(parents=True, exist_ok=True)
    vid_dir = ROOT / "demo" / "_video"
    shutil.rmtree(vid_dir, ignore_errors=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU", device_scale_factor=1.5,
                                  record_video_dir=None if a.no_video else str(vid_dir), record_video_size={"width": 1440, "height": 900})
        page = ctx.new_page()
        # Шаг 1: QR-форма жюри (телефон) — отдельный контекст с мобильным размером
        phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, locale="ru-RU",
                                    record_video_dir=None if a.no_video else str(vid_dir / "phone"), record_video_size={"width": 390, "height": 844})
        ph = phone.new_page()
        ph.goto(f"{base}/q/PVL"); ph.wait_for_selector("textarea")
        ph.fill("textarea", "На складе сканер штрихкодов не читает этикетки номенклатуры из 1С, артикулы вбиваем вручную. Прошу заменить сканер.")
        ph.click("text=Прямо сейчас мешает")
        shot(ph, "01_qr_form_phone")
        ph.click("button:has-text('Отправить')")
        # «Похоже, об этом уже сообщали» — как на сцене: показать и нажать «Всё равно отправить»
        try:
            ph.wait_for_selector("button:has-text('Всё равно отправить')", timeout=25000)
            shot(ph, "01b_qr_similar_phone")
            ph.click("button:has-text('Всё равно отправить')")
        except Exception:   # noqa: BLE001 — похожих не нашлось, форма ушла сразу
            pass
        ph.wait_for_selector("text=принято", timeout=90000)
        shot(ph, "02_qr_accepted_phone")
        track_url = ph.eval_on_selector("a:has-text('Следить за статусом')", "e => e.href")
        # Ноутбук: директор, сводка с картой
        login(page, base, 1)
        page.goto(f"{base}/panel#/summary"); page.wait_for_selector("text=Сводка для директора", timeout=60000); page.wait_for_timeout(2500)
        shot(page, "03_director_summary")
        page.evaluate("document.querySelector('.map') && document.querySelector('.map').scrollIntoView()"); shot(page, "04_map")
        page.goto(f"{base}/panel#/queue?open=1&sort=priority"); page.wait_for_selector("table"); page.wait_for_timeout(1200); shot(page, "05_queue_priority")
        # Шаг 2: планёрка ведущего (телефон) — запасной ход текстом
        login(ph, base, 2)
        ph.goto(f"{base}/app#/meeting"); ph.wait_for_selector("text=Режим совещания")
        ph.click("summary:has-text('Вставить текст')"); ph.fill("textarea", TRANSCRIPT); ph.click("button:has-text('Разобрать текст')")
        ph.wait_for_selector("button:has-text('Отправить')", timeout=180000); ph.wait_for_timeout(800); shot(ph, "06_meeting_review_phone", full=True)
        ph.click("button:has-text('Отправить')"); ph.wait_for_selector("text=Отправлено", timeout=30000); shot(ph, "07_meeting_sent_phone")
        # Шаг 3: «Сообщить о ходе» → стадия у автора
        page.goto(f"{base}/panel#/queue"); page.wait_for_selector("table"); page.click("tbody tr >> nth=0"); page.wait_for_selector("text=Сообщить о ходе")
        page.fill("textarea[placeholder^='Сообщить о ходе']", "Сканер заказан, поставка в среду"); page.click("button:has-text('Сообщить о ходе')"); page.wait_for_timeout(1500)
        shot(page, "08_card_progress", full=True)
        ph.goto(track_url); ph.wait_for_selector("text=Проработка"); shot(ph, "09_author_stage_phone")
        # Шаг 4: «На решение»
        page.goto(f"{base}/panel#/decisions"); page.wait_for_selector("text=На решение"); page.wait_for_timeout(800); shot(page, "10_decisions", full=True)
        page.click("button:has-text('Принять') >> nth=0"); page.wait_for_timeout(1500); shot(page, "11_decision_accepted")
        # Шаг 5: что изменили, профиль, лига, награды
        login(page, base, 16)
        page.goto(f"{base}/app#/changes"); page.wait_for_selector("text=Что изменили"); page.wait_for_timeout(800); shot(page, "12_changes_thanks")
        page.goto(f"{base}/app#/u/6"); page.wait_for_selector("text=Внедрённые идеи"); shot(page, "13_profile")
        page.goto(f"{base}/app#/league"); page.wait_for_selector("text=Лига филиалов"); shot(page, "14_league")
        page.goto(f"{base}/app#/rewards"); page.wait_for_selector("text=Награды"); shot(page, "15_rewards")
        # Финал: сводка с темой и картой
        login(page, base, 1)
        page.goto(f"{base}/panel#/summary"); page.wait_for_selector("text=Повторяющиеся темы", timeout=60000); page.wait_for_timeout(2500)
        page.evaluate("document.querySelector('.cluster') && document.querySelector('.cluster').scrollIntoView()"); shot(page, "16_clusters")
        page.goto(f"{base}/panel#/meetings"); page.wait_for_selector("table"); shot(page, "17_meetings")
        ctx.close(); phone.close(); browser.close()
    if not a.no_video:
        for sub, name in (("", "backup.mp4"), ("phone", "backup_phone.mp4")):
            webm = next((vid_dir / sub).glob("*.webm"), None)
            if webm:
                out = ROOT / "demo" / name
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-vf", "fps=15", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", str(out)], check=True)
                print("видео:", out, out.stat().st_size // 1024, "КБ")
        shutil.rmtree(vid_dir, ignore_errors=True)
    print("скрины:", sorted(x.name for x in SLIDES.glob("*.png")))


if __name__ == "__main__":
    main()
