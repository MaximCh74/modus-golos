"""Настройки из окружения и .env. Секреты — только в .env (ТЗ v1.1, раздел 14)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    """Простой .env без зависимостей: KEY=value, комментарии и пустые строки пропускаются, окружение не перебивается."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split("  #")[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_env(ROOT / ".env")

DATA_DIR = UPLOAD_DIR = DB_PATH = AUDIO_DIR = AVATAR_DIR = None   # задаются в set_data_dir()


def set_data_dir(path) -> None:
    """Папка с базой, вложениями и временным аудио. Тесты вызывают для каждого модуля со своей чистой папкой."""
    global DATA_DIR, UPLOAD_DIR, DB_PATH, AUDIO_DIR
    DATA_DIR = Path(path).resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR = DATA_DIR / "uploads"
    UPLOAD_DIR.mkdir(exist_ok=True)
    AUDIO_DIR = DATA_DIR / "audio"
    AUDIO_DIR.mkdir(exist_ok=True)
    global AVATAR_DIR
    AVATAR_DIR = DATA_DIR / "avatars"
    AVATAR_DIR.mkdir(exist_ok=True)
    DB_PATH = DATA_DIR / "mf.db"


set_data_dir(os.environ.get("MF_DATA_DIR") or (ROOT / "var"))
PUBLIC_URL = os.environ.get("MF_PUBLIC_URL", "").rstrip("/")
LLM_MODEL = os.environ.get("MF_LLM_MODEL", "gpt-4o-mini")


def secret() -> str:
    s = os.environ.get("MF_SECRET")
    if s:
        return s
    f = DATA_DIR / "secret"
    if not f.is_file():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()
