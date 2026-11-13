#!/usr/bin/env python3
"""Скрины 13.11 (Playwright, при работающем сервере; базу не меняет, входим по разу на пользователя):
1) чистые скрины для слайдов → demo/slides/для_презентации/: телефон 390 — «Директор в кармане» (Неделя), главная сотрудника, «Мои
   обращения» со всеми пятью статусами (мастер участка Серик); компьютер 1440 — сводка с картой, лига. PNG, телефон 3×, компьютер 2×.
2) лига рядом с образцом владельца (слайд «Лучшие голоса компании», --sample) → папки из аргументов, префикс 12_.
Запуск: python3 tools/remarks12_shots.py --sample <образец.jpg> <папка> [<папка2> …] [--base http://127.0.0.1:8070]"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SLIDES = ROOT / "demo" / "slides" / "для_презентации"
DIRECTOR, SAULE, SERIK = 1, 6, 27


def side_by_side(paths: list[Path], out: Path, height: int = 1100, gap: int = 40) -> None:
    ims = [Image.open(p).convert("RGB") for p in paths]
    ims = [im.resize((round(im.width * height / im.height), height), Image.LANCZOS) for im in ims]
    sheet = Image.new("RGB", (sum(im.width for im in ims) + gap * (len(ims) + 1), height + 2 * gap), (237, 241, 246))
    x = gap
    for im in ims:
        sheet.paste(im, (x, gap))
        x += im.width + gap
    sheet.save(out, "JPEG", quality=88)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="+")
    ap.add_argument("--sample", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:8070")
    a = ap.parse_args()
    outs = [Path(o) for o in a.out]
    for o in outs + [SLIDES]:
        o.mkdir(parents=True, exist_ok=True)
    base = a.base
    tmp = SLIDES / "_tmp"
    tmp.mkdir(exist_ok=True)

    with sync_playwright() as p:
        b = p.chromium.launch()
        states: dict[int, dict] = {}

        def page_for(uid: int, width: int, height: int):
            phone = width < 500
            ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=3 if phone else 2, is_mobile=phone, has_touch=phone,
                                locale="ru-RU", timezone_id="Asia/Almaty", service_workers="block", storage_state=states.get(uid))
            pg = ctx.new_page()
            if uid not in states:
                r = pg.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})
                if not r.ok:
                    raise SystemExit(f"вход {uid}: {r.status} {r.text()}")
                states[uid] = ctx.storage_state()
            return ctx, pg

        def slide(pg, name: str, **kw):
            path = SLIDES / f"{name}.png"
            pg.screenshot(path=str(path), **kw)
            ok = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            print(f"  {path.relative_to(ROOT)}" + ("" if ok else "  ← ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"))
            return path

        # телефон 390: «Директор в кармане», неделя
        ctx, pg = page_for(DIRECTOR, 390, 844)
        pg.goto(base + "/boss"); pg.wait_for_selector(".boss-tile"); pg.wait_for_timeout(600)
        pg.click(".seg-btn[data-period=week]"); pg.wait_for_timeout(2500)
        slide(pg, "01_директор_в_кармане_неделя_390")
        ctx.close()
        # телефон 390: главная сотрудника (Сауле)
        ctx, pg = page_for(SAULE, 390, 844)
        pg.goto(base + "/app#/"); pg.wait_for_selector("#home-cta"); pg.wait_for_timeout(1200)
        slide(pg, "02_главная_сотрудника_390")
        ctx.close()
        # телефон 390: «Мои обращения» — все пять статусов (Серик): раздел со своего заголовка
        ctx, pg = page_for(SERIK, 390, 844)
        pg.goto(base + "/app#/"); pg.wait_for_selector("#home-cta"); pg.wait_for_timeout(1200)
        # раздел целиком — от заголовка «Мои обращения» до конца списка (все пять статусов в одном кадре)
        clip = pg.evaluate("""(() => { const l = [...document.querySelectorAll('.lbl')].find(e => e.textContent.includes('Мои обращения'));
          let end = l.nextElementSibling; const top = l.getBoundingClientRect().top + scrollY - 12, bottom = end.getBoundingClientRect().bottom + scrollY + 16;
          return { x: 0, y: top, width: innerWidth, height: bottom - top }; })()""")
        pg.evaluate("(() => { const n = document.getElementById('bottom-nav'); if (n) n.style.display = 'none'; })()")   # фиксированная панель легла бы поверх списка
        slide(pg, "03_мои_обращения_пять_статусов_390", full_page=True, clip=clip)
        ctx.close()
        # компьютер 1440: сводка с картой (директор стартует на «Сводке»), лига
        ctx, pg = page_for(DIRECTOR, 1440, 900)
        pg.goto(base + "/panel"); pg.wait_for_selector(".map .marker"); pg.wait_for_selector(".clock .clock-hm"); pg.wait_for_timeout(1800)
        slide(pg, "04_сводка_с_картой_1440")
        pg.goto(base + "/panel#/league"); pg.wait_for_selector(".pod-step"); pg.wait_for_timeout(900)
        league = slide(pg, "05_лига_1440", full_page=True)
        ctx.close()
        # лига на телефоне 390 (Серик — своя строка подсвечена): «Филиалы» и «Сотрудники»
        ctx, pg = page_for(SERIK, 390, 844)
        pg.goto(base + "/app#/league"); pg.wait_for_selector(".pod-step"); pg.wait_for_timeout(900)
        ph1 = tmp / "lg_390_branches.png"; pg.screenshot(path=str(ph1))
        pg.click(".lg-seg .seg-btn[data-tab=top]"); pg.wait_for_timeout(400)
        pg.evaluate("window.scrollTo(0, document.querySelector('.lg-seg').getBoundingClientRect().top + scrollY - 70)"); pg.wait_for_timeout(300)
        ph2 = tmp / "lg_390_top.png"; pg.screenshot(path=str(ph2))
        ctx.close()
        b.close()

    sample = Path(a.sample)
    first = outs[0]
    side_by_side([sample, league], first / "12_1_лига_1440_рядом_с_образцом.jpg")
    side_by_side([sample, ph1, ph2], first / "12_2_лига_телефон_390_рядом_с_образцом.jpg")
    shutil.copy(league, first / "12_3_лига_1440.png")
    for o in outs[1:]:
        for f in first.glob("12_*"):
            shutil.copy(f, o / f.name)
    shutil.rmtree(tmp)
    print("  12_1, 12_2, 12_3 →", ", ".join(str(o) for o in outs))


if __name__ == "__main__":
    main()
