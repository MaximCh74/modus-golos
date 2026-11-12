"""Суточный потолок платных вызовов ИИ (аудит 12.11, F-07): защита баланса OpenAI. Каждый вызов (разбор, пересказ, эмбеддинги, озвучка,
облачное распознавание) учитывается в settings.ai_usage:<дата UTC>; после settings.ai_daily_limit (по умолчанию 1500) — исключение,
вызывающий код уходит в запасной режим без ИИ (словарь, шаблоны, ключевые слова), как без ключа. Сброс — в полночь UTC."""
from __future__ import annotations

import threading

DEFAULT_LIMIT = 1500
_lock = threading.Lock()


class Exhausted(Exception):
    pass


def limit() -> int:
    from .. import db
    try:
        return max(0, int(db.setting("ai_daily_limit", DEFAULT_LIMIT) or 0))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def _key() -> str:
    from .. import db
    return "ai_usage:" + db.now().strftime("%Y-%m-%d")


def usage() -> dict:
    from .. import db
    u = db.setting(_key(), {}) or {}
    return {"date": _key().split(":", 1)[1], "calls": int(u.get("calls", 0)), "by_kind": u.get("by_kind", {}), "limit": limit()}


def spend(kind: str) -> None:
    """Учесть один платный вызов; если потолок суток достигнут — Exhausted (вызов не делается)."""
    from .. import db
    with _lock:
        key = _key()
        u = db.setting(key, {}) or {}
        calls = int(u.get("calls", 0))
        lim = limit()
        if lim and calls >= lim:
            raise Exhausted(f"суточный лимит вызовов ИИ исчерпан ({lim}) — до полуночи UTC работает режим без ИИ")
        by = u.get("by_kind", {})
        by[kind] = int(by.get(kind, 0)) + 1
        db.set_setting(key, {"calls": calls + 1, "by_kind": by})
