"""Безопасное открытие картинок от пользователей (аудит 12.11: F-19, F-17). Pillow разбирает десятки форматов, и в декодерах редких
форматов (TIFF, MPO, DCX, EPS, PDF, BMP-RLE, JPEG 2000…) находят уязвимости — открываем только JPEG, PNG и WebP (GIF — по отдельному
флагу, без пересохранения анимации), ограничиваем размер в пикселях, не трогаем раздутый EXIF и сохраняем без метаданных (EXIF с
координатами телефона, комментарии, ICC). Pillow ≥ 13 — в Docker-образе (Python 3.12); на Python 3.10 последняя версия — 12.3.0."""
from __future__ import annotations

import io

from fastapi import HTTPException

MAX_PIXELS = 40_000_000          # 40 Мп: фото с любого телефона проходит, «бомба распаковки» — нет
MAX_EXIF = 64 * 1024             # больше — не разбираем EXIF (уязвимость разбора eXIf в PNG), просто без поворота
SAFE_FORMATS = ("JPEG", "PNG", "WEBP")


def _pil():
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    return Image


def open_image(data: bytes, formats=SAFE_FORMATS):
    """→ открытая картинка (первый кадр, пиксели загружены) или HTTPException 415."""
    Image = _pil()
    try:
        img = Image.open(io.BytesIO(data), formats=list(formats))
        if img.width < 1 or img.height < 1 or img.width * img.height > MAX_PIXELS:
            raise ValueError("размер")
        img.load()
        return img
    except HTTPException:
        raise
    except Exception:   # noqa: BLE001 — формат вне списка, битый файл, бомба распаковки
        raise HTTPException(415, "Нужна картинка JPEG, PNG или WebP")


def upright(img):
    """Повернуть по EXIF (снимок с телефона), если EXIF разумного размера."""
    from PIL import ImageOps
    exif = img.info.get("exif") or b""
    if len(exif) > MAX_EXIF:
        return img
    try:
        return ImageOps.exif_transpose(img)
    except Exception:   # noqa: BLE001
        return img


def clean_bytes(img, fmt: str | None = None, quality: int = 88) -> tuple[bytes, str, str]:
    """Пересохранить без метаданных → (данные, mime, расширение). JPEG остаётся JPEG, PNG — PNG (прозрачность), WebP → JPEG."""
    fmt = (fmt or img.format or "JPEG").upper()
    out = io.BytesIO()
    if fmt == "PNG":
        clean = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
        clean.info = {}
        clean.save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png", ".png"
    clean = img.convert("RGB")
    clean.info = {}
    clean.save(out, "JPEG", quality=quality)
    return out.getvalue(), "image/jpeg", ".jpg"
