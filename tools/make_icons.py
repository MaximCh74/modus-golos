#!/usr/bin/env python3
"""Иконки приложений из SVG-логотипа заказчика (web/a/img/logo.svg) — без растровых заготовок и без слов (подпись даёт телефон по short_name,
скругляет он тоже сам). Замечание владельца 12.11:
- «Модус Голос» (сотрудники): знак логотипа на белом;
- «Директор»: тот же знак + тёмно-синяя и красная волна внизу.
Размеры: 180 (apple-touch-icon), 192, 512 и maskable 192/512 (знак внутри безопасного круга 80 %). Те же файлы берёт APK (Bubblewrap качает
iconUrl/maskableIconUrl с сайта). Запуск: python3 tools/make_icons.py → web/a/img/icons/*.png и *.svg."""
from __future__ import annotations

import re
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "a" / "img" / "icons"
NAVY, RED = "#082742", "#ED1111"
MARK_BOX = (9.75, 1.5, 48.0, 40.5)   # знак в координатах logo.svg: две дуги, красный круг, блик (первые четыре контура)


def mark_paths() -> str:
    svg = (ROOT / "web" / "a" / "img" / "logo.svg").read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<path[^>]*/>", svg)[:4])


def place(size: float, cx: float, cy: float) -> str:
    """Знак размером size (по большей стороне), центр в (cx, cy) холста 512."""
    x0, y0, x1, y1 = MARK_BOX
    k = size / max(x1 - x0, y1 - y0)
    tx, ty = cx - (x0 + x1) / 2 * k, cy - (y0 + y1) / 2 * k
    return f'<g transform="translate({tx:.2f} {ty:.2f}) scale({k:.4f})">{mark_paths()}</g>'


def waves() -> str:
    """Две волны внизу: красная полоса выглядывает над тёмно-синей."""
    red = f'<path d="M0 402 C 96 370, 192 370, 288 402 S 448 438, 512 406 L512 512 L0 512 Z" fill="{RED}"/>'
    navy = f'<path d="M0 428 C 96 396, 192 396, 288 428 S 448 464, 512 432 L512 512 L0 512 Z" fill="{NAVY}"/>'
    return red + navy


def svg(body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512"><rect width="512" height="512" fill="#ffffff"/>{body}</svg>'


ICONS = {
    # обычная: знак крупно; maskable: знак внутри круга 80 % (Android обрезает до круга/капли)
    "icon": svg(place(330, 256, 256)),
    "maskable": svg(place(250, 256, 256)),
    "boss": svg(place(262, 256, 196) + waves()),
    "boss-maskable": svg(place(204, 256, 212) + waves()),
}
SIZES = {"icon": (180, 192, 512), "maskable": (192, 512), "boss": (180, 192, 512), "boss-maskable": (192, 512)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in ICONS.items():
        (OUT / f"{name}.svg").write_text(body, encoding="utf-8")
        for s in SIZES[name]:
            cairosvg.svg2png(bytestring=body.encode("utf-8"), write_to=str(OUT / f"{name}-{s}.png"), output_width=s, output_height=s)
            print("  ", f"{name}-{s}.png")


if __name__ == "__main__":
    main()
