"""Нечёткое сопоставление имён из расшифровки с пользователями.
STT искажает имена (особенно казахские: «Ерлан» → «Ирлан», «Айгерим» → «Айгерин»), LLM может вернуть имя в косвенном
падеже («Ерлану», «Айгерим»). Правило ТЗ: при неуверенном совпадении никого не угадывать — исполнитель пуст + флаг."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

CONFIDENT = 0.85     # выше — берём; ниже — пусто + флаг «нет ответственного», кандидаты подсказываются в интерфейсе
AMBIGUOUS_GAP = 0.08  # два кандидата ближе этого — не угадываем
_VOWELS = "аеёиоуыэюя"


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    return re.sub(r"[^a-zа-яәіңғүұқөһ\s-]", " ", s).strip()


def _stem(word: str) -> str:
    """Срезать русское падежное окончание: «ерлану» → «ерлан», «айгерим» → «айгерим», «сауле» → «саул»."""
    w = word
    for suf in ("ому", "ему", "ого", "его", "ой", "ей", "ом", "ем", "ую", "ью", "ия", "ие", "ию", "ия", "у", "ю", "а", "я", "е", "ы", "и", "о"):
        if len(w) > 3 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w


def _tokens(s: str) -> list[str]:
    return [t for t in _norm(s).replace("-", " ").split() if len(t) > 1]


def score(name: str, user_name: str) -> float:
    """0..1: лучшее совпадение любого слова из name с именем или фамилией пользователя (по основам)."""
    q = _tokens(name)
    u = _tokens(user_name)
    if not q or not u:
        return 0.0
    best = 0.0
    for a in q:
        sa = _stem(a)
        for b in u:
            sb = _stem(b)
            if sa == sb or a == b:
                best = max(best, 1.0)
                continue
            r = SequenceMatcher(None, sa, sb).ratio()
            # совпадение начала слова важнее: «ирлан» ~ «ерлан» (0.8), «айгерин» ~ «айгерим» (0.86)
            if sa[:3] == sb[:3]:
                r = max(r, 0.5 + r / 2)
            best = max(best, r)
    # имя + фамилия оба совпали — ещё увереннее
    if len(q) >= 2 and len(u) >= 2 and best >= CONFIDENT:
        best = max(best, 0.95)
    return round(best, 3)


def match(name: str | None, users: list[dict]) -> dict:
    """→ {user: dict|None, score, candidates: [{id, name, score}]}. Пусто/неуверенно/неоднозначно → user=None."""
    if not name or not name.strip():
        return {"user": None, "score": 0.0, "candidates": []}
    scored = sorted(({"id": u["id"], "name": u["name"], "score": score(name, u["name"]), "_u": u} for u in users),
                    key=lambda x: -x["score"])
    top = scored[0] if scored else None
    candidates = [{"id": c["id"], "name": c["name"], "score": c["score"]} for c in scored[:3] if c["score"] >= 0.5]
    if not top or top["score"] < CONFIDENT:
        return {"user": None, "score": top["score"] if top else 0.0, "candidates": candidates}
    second = scored[1]["score"] if len(scored) > 1 else 0.0
    if top["score"] < 1.0 and top["score"] - second < AMBIGUOUS_GAP:
        return {"user": None, "score": top["score"], "candidates": candidates}
    if top["score"] == 1.0 and second == 1.0:   # два полных тёзки по имени
        return {"user": None, "score": 1.0, "candidates": candidates}
    return {"user": top["_u"], "score": top["score"], "candidates": candidates}
