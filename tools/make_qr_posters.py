#!/usr/bin/env python3
"""Печатные QR-плакаты в стиле «Модус Трейд» (этап 5): A4 на каждый филиал и «Объект», плюс большой QR для слайда и жюри.
Адрес — постоянный (MF_PUBLIC_URL из .env). Запуск: python3 tools/make_qr_posters.py → demo/qr_posters.pdf + demo/slides/qr_*.png"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import cairosvg
import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mf import config, db  # noqa: E402

RED, NAVY, INK, MUTED = (0.894, 0, 0), (0.031, 0.153, 0.259), (0.196, 0.227, 0.278), (0.392, 0.455, 0.553)
FONT = ROOT / "web" / "a" / "fonts" / "Montserrat.ttf"
STATIC = Path("/tmp/claude-1000/-home-mark07-Desktop------------------/dd8555dc-6520-412f-9fb0-178e27c5e5ed/scratchpad/fonts")


def static_fonts() -> dict[str, Path]:
    """reportlab не понимает оси вариативного шрифта — делаем статические начертания через fontTools (во временную папку)."""
    import tempfile
    from mf import brand
    d = Path(tempfile.mkdtemp(prefix="mf-fonts-"))
    return {name: brand.static_font(w, f"MG-{name}", d / f"{name}.ttf")
            for name, w in (("Montserrat", 400), ("Montserrat-SemiBold", 600), ("Montserrat-ExtraBold", 800))}


def qr_png(url: str, px: int = 1200) -> Image.Image:
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    q.add_data(url); q.make(fit=True)
    return q.make_image(fill_color="#082742", back_color="white").convert("RGB").resize((px, px), Image.NEAREST)


def logo_png(height_px: int = 160) -> Image.Image:
    """Фирменный блок «логотип | черта | МОДУС ГОЛОС» (контуры букв логотипа, mf/brand.py) — как шапка сайта."""
    from mf import brand
    return brand.lockup_png(height_px)


def rgb(c, col): c.setFillColorRGB(*col); c.setStrokeColorRGB(*col)


def poster(c: canvas.Canvas, base: str, branch: dict, big: bool = False) -> None:
    W, H = A4
    url = f"{base}/q/{branch['code']}"
    # фирменные элементы: блок «логотип | черта | МОДУС ГОЛОС», красная метка с чертой, сетка красных точек
    logo = logo_png(220)
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(logo), 20 * mm, H - 30 * mm, width=logo.width / logo.height * 16 * mm, height=16 * mm, mask="auto")
    rgb(c, RED)
    for i in range(6):
        for j in range(4):
            c.circle(W - 45 * mm + i * 6 * mm, H - 14 * mm - j * 6 * mm, 1.1 * mm, fill=1, stroke=0)
    c.setLineWidth(1.2); c.line(20 * mm, H - 48 * mm, 30 * mm, H - 48 * mm)
    rgb(c, NAVY)   # подпись тёмно-синяя, красная только черта (правило владельца: красного текста нет)
    c.setFont("Montserrat-SemiBold", 11); c.drawString(33 * mm, H - 49.5 * mm, "МОДУС ГОЛОС · " + ("ОБЪЕКТ" if branch["kind"] == "field" else "ФИЛИАЛ").upper())
    rgb(c, NAVY); c.setFont("Montserrat-ExtraBold", 30 if not big else 26)
    title = "Есть идея или проблема?" ; c.drawString(20 * mm, H - 64 * mm, title)
    c.setFont("Montserrat-SemiBold", 22); c.drawString(20 * mm, H - 76 * mm, "Наведите камеру")
    rgb(c, MUTED); c.setFont("Montserrat", 13); c.drawString(20 * mm, H - 86 * mm, "Без установки и регистрации — одна минута. Вы увидите статус по ссылке.")
    img = qr_png(url)
    size = 120 * mm if not big else 140 * mm
    x = (W - size) / 2; y = H - 100 * mm - size
    rgb(c, (0.82, 0.86, 0.9)); c.setLineWidth(0.8); c.roundRect(x - 6 * mm, y - 6 * mm, size + 12 * mm, size + 12 * mm, 6 * mm, stroke=1, fill=0)
    c.drawImage(ImageReader(img), x, y, width=size, height=size)
    rgb(c, NAVY); c.setFont("Montserrat-ExtraBold", 20)
    city = branch["city"] or branch["name"]
    c.drawCentredString(W / 2, y - 16 * mm, city if branch["kind"] != "field" else "Объект · командировка")
    if branch["kind"] == "field":
        rgb(c, MUTED); c.setFont("Montserrat", 11); c.drawCentredString(W / 2, y - 29 * mm, "Укажите город или объект в форме — геолокация не нужна")
    rgb(c, MUTED); c.setFont("Montserrat", 10); c.drawCentredString(W / 2, y - 23 * mm, url)
    c.setFont("Montserrat", 9); c.drawCentredString(W / 2, 14 * mm, "ГК «Модус Трейд» · «Модус Голос» — каждый голос услышан · демо")
    c.showPage()


def slide_qr(base: str, code: str, out: Path, label: str) -> None:
    img = qr_png(f"{base}/q/{code}", 1600)
    canvas_img = Image.new("RGB", (2000, 2420), "white")
    lock = logo_png(150)   # фирменный блок сверху по центру — как шапка сайта
    canvas_img.paste(lock, ((2000 - lock.width) // 2, 80), lock)
    canvas_img.paste(img, (200, 320))
    from PIL import ImageDraw, ImageFont
    d = ImageDraw.Draw(canvas_img)
    fonts = static_fonts()
    f = ImageFont.truetype(str(fonts["Montserrat-ExtraBold"]), 96); f2 = ImageFont.truetype(str(fonts["Montserrat"]), 56)
    d.text((1000, 2030), label, fill=(8, 39, 66), font=f, anchor="mm")
    d.text((1000, 2150), f"{base}/q/{code}", fill=(100, 116, 141), font=f2, anchor="mm")
    d.text((1000, 2270), "Наведите камеру — без установки и регистрации", fill=(8, 39, 66), font=f2, anchor="mm")   # без красного текста
    canvas_img.save(out, "PNG")


def main() -> None:
    base = (os.environ.get("MF_PUBLIC_URL") or config.PUBLIC_URL or "https://modus.cq-systems.kz").rstrip("/")
    for name, path in static_fonts().items():
        pdfmetrics.registerFont(TTFont(name, str(path)))
    db.conn()
    branches = db.q("SELECT code, name, city, kind FROM branches ORDER BY is_hq DESC, kind, name")
    out_pdf = ROOT / "demo" / "qr_posters.pdf"
    out_pdf.parent.mkdir(exist_ok=True)
    c = canvas.Canvas(str(out_pdf), pagesize=A4)
    c.setTitle("QR-плакаты — «Модус Голос», ГК «Модус Трейд»")
    for b in branches:
        poster(c, base, b)
    c.save()
    slides = ROOT / "demo" / "slides"; slides.mkdir(exist_ok=True)
    slide_qr(base, "PVL", slides / "qr_slide_PVL.png", "Павлодар — для жюри")
    slide_qr(base, "OMSK", slides / "qr_slide_OMSK.png", "Омск — головной офис")
    print(f"{out_pdf} ({out_pdf.stat().st_size // 1024} КБ, {len(branches)} страниц), {slides}/qr_slide_*.png, адрес {base}")


if __name__ == "__main__":
    main()
