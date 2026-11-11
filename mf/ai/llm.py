"""LLM-адаптер: OpenAI chat, модель из .env (MF_LLM_MODEL), ключ OPENAI_API_KEY. Ответ — строгий JSON по схеме;
валидируется, при невалидном ответе один повтор, затем LLMError → вызывающий код уходит в ручной режим (ТЗ v1.1 §7)."""
from __future__ import annotations

import json
import logging
import os

from ..config import LLM_MODEL

log = logging.getLogger("mf.ai.llm")
ENGINE = "openai"
CHUNK_CHARS = 12000   # длинную расшифровку режем на куски (ТЗ §7)


class LLMError(Exception):
    pass


def available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _client():
    from openai import OpenAI
    return OpenAI(timeout=float(os.environ.get("MF_LLM_TIMEOUT", "60")))


def chat_json(system: str, user: str, validate, *, max_tokens: int = 2000) -> dict:
    """Два захода: невалидный JSON или схема → повтор с указанием ошибки; после второго — LLMError."""
    if not available():
        raise LLMError("OPENAI_API_KEY не задан")
    client = _client()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    kwargs = {"model": LLM_MODEL, "response_format": {"type": "json_object"}, "max_completion_tokens": max_tokens}
    if LLM_MODEL.startswith("gpt-4"):
        kwargs["temperature"] = 0.2
    last = None
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(messages=messages, **kwargs)
            content = resp.choices[0].message.content or ""
            data = json.loads(content)
            validate(data)
            return data
        except Exception as e:   # noqa: BLE001 — сеть, JSON, схема: всё одинаково → повтор, потом ручной режим
            last = e
            log.warning("LLM попытка %d: %s", attempt + 1, e)
            messages.append({"role": "assistant", "content": content if "content" in dir() and content else "{}"})
            messages.append({"role": "user", "content": f"Ответ невалиден: {e}. Верни корректный JSON строго по схеме."})
    raise LLMError(f"LLM не дал валидный ответ: {last}")


# ---------- структурирование обращения (ТЗ §7) ----------

CLASSIFY_SYSTEM = """Ты помощник системы обратной связи сотрудников компании (инженерные системы безопасности, филиалы в Казахстане и России).
Структурируй обращение сотрудника. Отвечай ТОЛЬКО JSON вида:
{"summary": "суть в одной фразе", "proposed_solution": "предлагаемое решение или null", "type": "problem|suggestion|praise",
 "category": "ровно одно название из списка категорий или null, если ни одна не подходит", "confidence": 0.0-1.0,
 "priority": "low|medium|high", "clarifying_question": "вопрос автору, если без него не разобраться, иначе null"}
Текст может быть на русском или казахском. Категорию выбирай только из списка, не придумывай новых."""


def classify_appeal(text: str, categories: list[dict], type_hint: str | None = None) -> dict:
    names = [c["name"] for c in categories]

    def validate(d: dict) -> None:
        if not isinstance(d, dict) or "category" not in d:
            raise ValueError("нет поля category")
        if d["category"] is not None and d["category"] not in names:
            raise ValueError(f"категория вне списка: {d['category']}")
        if d.get("type") not in ("problem", "suggestion", "praise", None):
            raise ValueError("type вне списка")
        if d.get("priority") not in ("low", "medium", "high", None):
            raise ValueError("priority вне списка")

    user = "Категории:\n- " + "\n- ".join(names) + (f"\n\nАвтор отметил тип: {type_hint}" if type_hint else "") + f"\n\nОбращение:\n{text}"
    d = chat_json(CLASSIFY_SYSTEM, user, validate, max_tokens=400)
    cat = next((c for c in categories if c["name"] == d["category"]), None)
    try:
        conf = float(d.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    return {"category_id": cat["id"] if cat else None, "category": cat["name"] if cat else None, "confidence": round(conf, 2),
            "priority": d.get("priority") or "medium", "summary": d.get("summary"), "proposed_solution": d.get("proposed_solution"),
            "type": d.get("type"), "clarifying_question": d.get("clarifying_question"), "engine": ENGINE}


# ---------- разбор совещания (ТЗ §7) ----------

MEETING_SYSTEM = """Ты разбираешь расшифровку рабочего совещания (планёрки) компании. Речь может быть на русском и казахском,
расшифровка автоматическая — имена и слова могут быть искажены. Выдели:
- summary: итог 3–5 строк — о чём договорились и что осталось открытым;
- decisions: принятые решения (список строк);
- tasks: поручения: {"text": что сделать, "assignee_name": имя исполнителя как прозвучало (или null), "due": срок как прозвучало
  («до пятницы», «к 15 ноября», ISO-дата) или null, "quote": цитата из расшифровки};
- ideas: идеи и проблемы, которые нужно вынести директору: {"text", "type": "suggestion|problem", "category": название из списка категорий или null,
  "voiced_by": кто озвучил или null};
- linked_appeals: обращения из списка открытых, которые обсуждались (по смыслу, не только по номеру): {"number": "A-007", "decision": что решили сообщить автору};
- open_questions: что осталось без решения, срока или ответственного.
Не придумывай имена: если имя не прозвучало или неразборчиво — null. Отвечай ТОЛЬКО JSON с этими шестью ключами."""


def _validate_meeting(d: dict) -> None:
    for key in ("summary", "decisions", "tasks", "ideas", "linked_appeals", "open_questions"):
        if key not in d:
            raise ValueError(f"нет поля {key}")
    for key in ("decisions", "tasks", "ideas", "linked_appeals", "open_questions"):
        if not isinstance(d[key], list):
            raise ValueError(f"{key} не список")
    for t in d["tasks"]:
        if not isinstance(t, dict) or not t.get("text"):
            raise ValueError("task без text")
    for i in d["ideas"]:
        if not isinstance(i, dict) or not i.get("text"):
            raise ValueError("idea без text")
    for la in d["linked_appeals"]:
        if not isinstance(la, dict) or not la.get("number"):
            raise ValueError("linked_appeal без number")


def _chunks(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text]
    out, cur = [], ""
    for para in text.split("\n"):
        if len(cur) + len(para) > CHUNK_CHARS and cur:
            out.append(cur)
            cur = ""
        cur += para + "\n"
    if cur.strip():
        out.append(cur)
    return out


def analyze_meeting(transcript: str, users: list[dict], open_appeals: list[dict], categories: list[dict]) -> dict:
    people = "\n".join(f"- {u['name']} — {u.get('position') or u.get('role')}, {u.get('branch') or ''}, {u.get('department') or ''}".rstrip(", ") for u in users)
    appeals_txt = "\n".join(f"- {a['number']}: {a['text']}" for a in open_appeals)
    cats = ", ".join(c["name"] for c in categories)
    context = f"Сотрудники:\n{people}\n\nОткрытые обращения:\n{appeals_txt}\n\nКатегории: {cats}\n\n"
    parts = _chunks(transcript)
    results = [chat_json(MEETING_SYSTEM, context + f"Расшифровка (часть {i + 1} из {len(parts)}):\n{p}", _validate_meeting, max_tokens=2500)
               for i, p in enumerate(parts)]
    if len(results) == 1:
        d = results[0]
    else:
        d = {"summary": " ".join(r["summary"] for r in results), "decisions": [], "tasks": [], "ideas": [], "linked_appeals": [], "open_questions": []}
        for r in results:
            for key in ("decisions", "tasks", "ideas", "linked_appeals", "open_questions"):
                d[key].extend(r[key])
    d["engine"] = ENGINE
    d["demo"] = False
    return d
