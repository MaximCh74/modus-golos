"""QR-плакаты филиалов (A4, в стиле «Модус Трейд») — отдаются по запросу из администрирования: один филиал или все.
Та же вёрстка, что в tools/make_qr_posters.py (demo/qr_posters.pdf для показа); шрифты Montserrat — статические начертания из mf/staff."""
from __future__ import annotations

import io

from . import db
from .staff import FRAME, INK, MUTED, NAVY, RED, _fonts, _logo

KIND_RU = {"office": "офис", "production": "производство", "field": "объекты"}


def kind_label(kind: str | None) -> str:
    return KIND_RU.get(kind or "", kind or "")


def posters_pdf(branches: list[dict], base: str) -> bytes:
    """A4 на каждый филиал: логотип, красная сетка точек, заголовок, QR, город, адрес формы."""
    import qrcode
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    fonts = _fonts()
    logo = _logo()
    W, H = A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("QR-плакаты — «Модус Голос», ГК «Модус Трейд»")

    def rgb(col):
        c.setFillColorRGB(*col); c.setStrokeColorRGB(*col)

    for b in branches:
        url = f"{base.rstrip('/')}/q/{b['code']}"
        if logo is not None:
            c.drawImage(ImageReader(logo), 20 * mm, H - 30 * mm, width=logo.width / logo.height * 16 * mm, height=16 * mm, mask="auto")
        else:
            rgb(NAVY); c.setFont(fonts["extrabold"], 16); c.drawString(20 * mm, H - 26 * mm, "МОДУС ТРЕЙД")
        rgb(RED)
        for i in range(6):
            for j in range(4):
                c.circle(W - 45 * mm + i * 6 * mm, H - 14 * mm - j * 6 * mm, 1.1 * mm, fill=1, stroke=0)
        c.setLineWidth(1.2); c.line(20 * mm, H - 48 * mm, 30 * mm, H - 48 * mm)
        c.setFont(fonts["semibold"], 11); c.drawString(33 * mm, H - 49.5 * mm, "МОДУС ГОЛОС · " + ("ОБЪЕКТ" if b["kind"] == "field" else "ФИЛИАЛ"))
        rgb(NAVY); c.setFont(fonts["extrabold"], 30); c.drawString(20 * mm, H - 64 * mm, "Есть идея или проблема?")
        c.setFont(fonts["semibold"], 22); c.drawString(20 * mm, H - 76 * mm, "Наведите камеру")
        rgb(MUTED); c.setFont(fonts["regular"], 13); c.drawString(20 * mm, H - 86 * mm, "Без установки и регистрации — одна минута. Вы увидите статус по ссылке.")
        q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
        q.add_data(url); q.make(fit=True)
        img = q.make_image(fill_color="#082742", back_color="white").convert("RGB")
        size = 120 * mm
        x = (W - size) / 2; y = H - 100 * mm - size
        rgb(FRAME); c.setLineWidth(0.8); c.roundRect(x - 6 * mm, y - 6 * mm, size + 12 * mm, size + 12 * mm, 6 * mm, stroke=1, fill=0)
        c.drawImage(ImageReader(img), x, y, width=size, height=size)
        rgb(NAVY); c.setFont(fonts["extrabold"], 20)
        c.drawCentredString(W / 2, y - 16 * mm, (b["city"] or b["name"]) if b["kind"] != "field" else "Объект")   # только город; объект — без «(командировка)» (13.11)
        if b["kind"] == "field":
            rgb(MUTED); c.setFont(fonts["regular"], 11); c.drawCentredString(W / 2, y - 29 * mm, "Укажите город или объект в форме — геолокация не нужна")
        rgb(MUTED); c.setFont(fonts["regular"], 10); c.drawCentredString(W / 2, y - 23 * mm, url)
        c.setFont(fonts["regular"], 9); c.drawCentredString(W / 2, 14 * mm, "ГК «Модус Трейд» · «Модус Голос» — каждый голос услышан")
        c.showPage()
    c.save()
    return buf.getvalue()


def branches_for_posters(code: str | None = None) -> list[dict]:
    if code:
        b = db.one("SELECT code, name, city, kind FROM branches WHERE code=?", (code.upper(),))
        return [b] if b else []
    return db.q("SELECT code, name, city, kind FROM branches ORDER BY is_hq DESC, kind, name")
