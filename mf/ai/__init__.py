"""ИИ-адаптеры (ТЗ v1.1, раздел 7). Все вызовы ИИ — только отсюда; модели и ключи — из .env.
stt.py — расшифровка аудио (faster-whisper локально, запасной OpenAI whisper-1);
llm.py — OpenAI, строгий JSON по схеме с валидацией и одним повтором;
fallback.py — работа без ключа: словарь ключевых слов для категорий и заскриптованный разбор демо-планёрки;
names.py — нечёткое сопоставление имён из расшифровки с пользователями."""

from __future__ import annotations

import logging

log = logging.getLogger("mf.ai")


def classify_appeal(text: str, categories: list[dict], type_hint: str | None = None) -> dict:
    """Категория/приоритет обращения: LLM при наличии ключа, иначе (или при LLMError) словарь ключевых слов.
    → {category_id, category, confidence, priority, engine, ...}; category_id=None — «не уверены» → очередь администратора."""
    from . import fallback, llm
    if llm.available():
        try:
            return llm.classify_appeal(text, categories, type_hint)
        except llm.LLMError as e:
            log.warning("классификация: %s — словарь", e)
    out = fallback.classify(text, categories)
    out["priority"] = "medium"
    return out
