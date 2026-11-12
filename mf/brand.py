"""Фирменный блок «логотип МОДУС ТРЕЙД | черта | МОДУС ГОЛОС» для PDF и картинок (плакаты QR, приглашения, QR-слайды) — та же геометрия,
что у шапки сайта (.brand-lock в web/a/style.css): «МОДУС ГОЛОС» — контуры букв логотипа (web/a/modus-golos-wordmark.svg,
tools/make_wordmark.py; решение владельца 13.11), общая система координат высотой 42, черта посередине между «ТРЕЙД» и «ГОЛОС»."""
from __future__ import annotations

import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "web" / "a" / "img" / "logo.svg"
WORDMARK = ROOT / "web" / "a" / "modus-golos-wordmark.svg"
LINE = "#d1d5dd"          # токен --line из style.css
H = 42.0                  # высота логотипа и знака в их собственных единицах
TEXT_END = 120.85         # правый край текста «МОДУС ТРЕЙД» в logo.svg (дальше — пустое поле до 132)
WM_PAD = 0.25             # левое поле в знаке
GAP = 0.3 * H             # промежуток до и после черты — как calc(var(--logo-h) * .3) в CSS
DIV_W, DIV_H = 1.17, 0.74 * H


def _parts(path: Path) -> tuple[float, str]:
    svg = path.read_text(encoding="utf-8")
    w = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    return w, inner


def lockup_svg() -> str:
    _, logo = _parts(LOGO)
    ww, wm = _parts(WORDMARK)
    div_x = TEXT_END + GAP
    wm_x = div_x + DIV_W + GAP - WM_PAD
    total = round(wm_x + ww, 2)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="{H:g}" viewBox="0 0 {total} {H:g}" fill="none">'
            f'{logo}<rect x="{div_x:.2f}" y="{(H - DIV_H) / 2:.2f}" width="{DIV_W}" height="{DIV_H:.2f}" fill="{LINE}"/>'
            f'<g transform="translate({wm_x:.2f} 0)">{wm}</g></svg>')


def lockup_png(height_px: int = 160):
    """PIL RGBA картинка блока заданной высоты (cairosvg)."""
    import cairosvg
    from PIL import Image
    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=lockup_svg().encode("utf-8"), write_to=buf, output_height=height_px)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGBA")


FONT = ROOT / "web" / "a" / "fonts" / "Montserrat.ttf"


def static_font(weight: int, ps_name: str, out: Path) -> Path:
    """Статическое начертание вариативного Montserrat для reportlab/PIL. Имена шрифта (name 1/3/4/6) ставятся по ps_name: после
    instancer все начертания называются «Montserrat-Thin», и reportlab склеивал их в один шрифт — жирные заголовки PDF выходили обычными."""
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    f = TTFont(str(FONT))
    instancer.instantiateVariableFont(f, {"wght": weight}, inplace=True)
    name = f["name"]
    for rec in list(name.names):
        if rec.nameID in (1, 3, 4, 6, 16, 17):
            name.removeNames(nameID=rec.nameID)
    for nid, val in ((1, ps_name), (3, ps_name), (4, ps_name), (6, ps_name)):
        name.setName(val, nid, 3, 1, 0x409); name.setName(val, nid, 1, 0, 0)
    f["OS/2"].usWeightClass = weight
    f.save(str(out))
    return out
