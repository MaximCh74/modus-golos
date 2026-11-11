"""ИИ-адаптеры (ТЗ v1.1, раздел 7). Все вызовы ИИ — только отсюда; модели и ключи — из .env.
stt.py — расшифровка аудио (faster-whisper локально, запасной OpenAI whisper-1);
llm.py — OpenAI, строгий JSON по схеме с валидацией и одним повтором;
fallback.py — работа без ключа: словарь ключевых слов для категорий и заскриптованный разбор демо-планёрки;
names.py — нечёткое сопоставление имён из расшифровки с пользователями."""

from __future__ import annotations

import logging

log = logging.getLogger("mf.ai")


def classify_appeal(text: str, categories: list[dict], type_hint: str | None = None, author_urgency: str | None = None,
                    author_scope: str | None = None, supports: int = 0, clarifications: list[dict] | None = None) -> dict:
    """Категория, приоритет и «Коротко»: LLM при наличии ключа (один вызов), иначе (или при LLMError) словарь ключевых слов,
    матрица приоритета из ответа автора и первые два предложения вместо пересказа.
    → {category_id, category, confidence, priority, brief, engine, ...}; category_id=None — «не уверены» → очередь администратора."""
    from .. import appeals as _ap
    from . import fallback, llm
    if llm.available():
        try:
            return llm.classify_appeal(text, categories, type_hint, author_urgency, author_scope, supports, clarifications)
        except llm.LLMError as e:
            log.warning("классификация: %s — словарь", e)
    out = fallback.classify(text, categories)
    out["priority"] = _ap.matrix_priority(type_hint or "problem", author_urgency, author_scope) or "medium"
    out["brief"] = fallback.brief(text)
    return out
