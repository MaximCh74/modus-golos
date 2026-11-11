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

GLOSSARY = """Термины системы — используй только их: «мешают работать сейчас» (не «срочные», не «критичные»), «На решение»
(очередь директора), стадии обращения: «Проработка», «Принятие решения», «Реализация»; «Коротко» — пересказ; «обращение»
(не «заявка», не «тикет»); «поручение» (не «задача») с совещания; «У меня так же» — поддержка коллег."""

CLASSIFY_SYSTEM = GLOSSARY + """
Ты помощник системы обратной связи сотрудников компании (инженерные системы безопасности, филиалы в Казахстане и России).
Структурируй обращение сотрудника и перескажи его коротко для ответственного. Текст может быть голосовой расшифровкой —
длинной и сбивчивой, на русском или казахском. Пересказывай ТОЛЬКО сказанное, ничего не добавляй и не додумывай.
Отвечай ТОЛЬКО JSON вида:
{"summary": "Суть — 1–2 предложения своими словами, без вводных («шалом», «это самое»)",
 "proposed_solution": "что автор предлагает сделать, или null",
 "expects": "чего автор ждёт (ответ, срок, действие), если сказано, иначе null",
 "unclear": false,  // true, если суть неясна — тогда summary: "суть неясна" и обязательно clarifying_question
 "clarifying_question": "вопрос автору, если без него не разобраться, иначе null",
 "type": "problem|suggestion|praise",
 "category": "ровно одно название из списка категорий или null, если ни одна не подходит", "confidence": 0.0-1.0,
 "priority": "low|medium|high"}
Приоритет: учитывай ответ автора («насколько мешает» / «кого затронет»), текст и число коллег «у меня так же»:
мешает прямо сейчас всему отделу или компании — high; обходится — medium; мелочь, касается одного — low.
Категорию выбирай только из списка, не придумывай новых."""


def classify_appeal(text: str, categories: list[dict], type_hint: str | None = None, author_urgency: str | None = None,
                    author_scope: str | None = None, supports: int = 0, clarifications: list[dict] | None = None) -> dict:
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

    cats = "\n".join(f"- {c['name']}" + (f" (ответственный: {c['responsible']})" if c.get("responsible") else " (ответственный не назначен)") for c in categories)
    from .. import appeals as _ap
    ctx = []
    if type_hint:
        ctx.append(f"Автор отметил тип: {type_hint}")
    if author_urgency:
        ctx.append(f"Автор ответил «насколько мешает работать»: {_ap.URGENCY.get(author_urgency, author_urgency)}")
    if author_scope:
        ctx.append(f"Автор ответил «кого затронет»: {_ap.SCOPE.get(author_scope, author_scope)}")
    if supports:
        ctx.append(f"Коллег «у меня так же»: {supports}")
    qa = ""
    if clarifications:
        qa = "\n\nУточнения (вопрос ответственного → ответ автора), учти их в пересказе:\n" + "\n".join(f"— {q.get('q')}\n  → {q.get('a')}" for q in clarifications)
    user = "Категории (с ответственным по должности — выбирай ту, чей ответственный будет решать вопрос):\n" + cats + \
           ("\n\n" + "\n".join(ctx) if ctx else "") + f"\n\nОбращение:\n{text}" + qa
    d = chat_json(CLASSIFY_SYSTEM, user, validate, max_tokens=600)
    cat = next((c for c in categories if c["name"] == d["category"]), None)
    try:
        conf = float(d.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    unclear = bool(d.get("unclear")) or (str(d.get("summary") or "").strip().lower().startswith("суть неясна"))
    brief = {"gist": d.get("summary") or "", "proposes": d.get("proposed_solution"), "expects": d.get("expects"),
             "unclear": unclear, "question": d.get("clarifying_question")}
    return {"category_id": cat["id"] if cat else None, "category": cat["name"] if cat else None, "confidence": round(conf, 2),
            "priority": d.get("priority") or "medium", "summary": d.get("summary"), "proposed_solution": d.get("proposed_solution"),
            "type": d.get("type"), "clarifying_question": d.get("clarifying_question"), "brief": brief, "engine": ENGINE}


# ---------- сводка директора: ИИ только пересказывает готовые факты ----------

SUMMARY_SYSTEM = GLOSSARY + """
Ты пишешь короткую деловую сводку для директора по готовым фактам. Правила:
- 3–5 предложений, человеческим языком, деловой тон, без воды и без оценок;
- используй ТОЛЬКО числа из фактов, ничего не вычисляй и не добавляй; если факт равен нулю — можно не упоминать;
- каждое предложение — об одном факте: обращения за период (new — пришло, done — решено, open — открыто, urgent_open —
  «мешают работать прямо сейчас»), ждущие решения директора (decisions_pending, самое давнее decision_max_days дней),
  главная повторяющаяся тема (cluster: category, size обращений, cities — обязательно упомяни, если есть), просроченные
  поручения с совещаний (tasks_overdue), авторы без новостей дольше news_days дней (no_news);
- начни с приветствия, которое дано в фактах, дословно; tasks_open и decision_threshold_days не упоминай.
Отвечай ТОЛЬКО JSON: {"sentences": ["...", "..."]}"""


def director_summary(facts: dict) -> list[str]:
    def validate(d: dict) -> None:
        if not isinstance(d, dict) or not isinstance(d.get("sentences"), list) or not d["sentences"]:
            raise ValueError("нет sentences")
        if not all(isinstance(x, str) and x.strip() for x in d["sentences"]):
            raise ValueError("пустые предложения")
    d = chat_json(SUMMARY_SYSTEM, "Факты (JSON):\n" + json.dumps(facts, ensure_ascii=False), validate, max_tokens=500)
    return [x.strip() for x in d["sentences"]][:6]


FORBIDDEN = ("срочн", "критичн", "заявк", "тикет", "задач")   # запрещённые синонимы в сводке — повтор, затем шаблон


def has_forbidden(text: str) -> str | None:
    t = text.lower()
    return next((w for w in FORBIDDEN if w in t), None)


# ---------- разбор совещания (ТЗ §7) ----------

MEETING_SYSTEM = """Ты разбираешь расшифровку рабочего совещания (планёрки) компании. Речь может быть на русском и казахском,
расшифровка автоматическая — имена и слова могут быть искажены. Выдели:
- summary: итог 3–5 строк — о чём договорились и что осталось открытым;
- decisions: принятые решения — договорённости и правила («решили…», «договорились…»); поручения сюда НЕ дублировать;
- tasks: поручения: {"text": что сделать, "assignee_name": имя исполнителя как прозвучало (или null), "due": срок как прозвучало
  («до пятницы», «к 15 ноября», ISO-дата) или null, "quote": цитата из расшифровки};
- ideas: идеи и проблемы, которые нужно вынести директору: {"text", "type": "suggestion|problem", "category": название из списка категорий
  (у каждой указан ответственный — выбирай категорию, чей ответственный по должности будет это делать) или null, "voiced_by": кто озвучил или null};
- linked_appeals: обращения из списка открытых, которых касалось обсуждение — по смыслу, не только по номеру: если на совещании
  обсудили проблему или приняли решение по теме открытого обращения, это связь. {"number": "A-007", "decision": что сообщить автору обращения};
- open_questions: что осталось без решения, срока или ответственного.
Не придумывай имена: если имя не прозвучало или неразборчиво — null. Отвечай ТОЛЬКО JSON с этими шестью ключами; пустые разделы — пустой список [].
Форма ответа: {"summary": "...", "decisions": ["..."], "tasks": [{"text": "...", "assignee_name": null, "due": null, "quote": "..."}],
"ideas": [{"text": "...", "type": "suggestion", "category": null, "voiced_by": null}], "linked_appeals": [{"number": "A-001", "decision": "..."}], "open_questions": []}"""


def _validate_meeting(d: dict) -> None:
    """Проверка схемы с мягкой нормализацией: пустое поле → [], строка вместо списка → [строка]."""
    if not isinstance(d, dict) or not d.get("summary"):
        raise ValueError("нет поля summary")
    for key in ("decisions", "tasks", "ideas", "linked_appeals", "open_questions"):
        v = d.get(key)
        if v is None or v == "":
            d[key] = []
        elif isinstance(v, (str, dict)):
            d[key] = [v]
        elif not isinstance(v, list):
            raise ValueError(f"{key} не список")
    d["decisions"] = [x.get("text", "") if isinstance(x, dict) else str(x) for x in d["decisions"]]
    d["open_questions"] = [x.get("text", "") if isinstance(x, dict) else str(x) for x in d["open_questions"]]
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
    cats = "\n".join(f"- {c['name']}" + (f" (ответственный: {c['responsible']})" if c.get("responsible") else " (ответственный не назначен)") for c in categories)
    context = f"Сотрудники:\n{people}\n\nКатегории обращений:\n{cats}\n\n"
    tail = (f"\n\nОткрытые обращения сотрудников — проверь КАЖДОЕ: касалось ли его обсуждение по смыслу (та же проблема, принятое решение по этой теме)?"
            f" Все такие — в linked_appeals с текстом, что сообщить автору.\n{appeals_txt}")
    parts = _chunks(transcript)
    results = [chat_json(MEETING_SYSTEM, context + f"Расшифровка (часть {i + 1} из {len(parts)}):\n{p}" + tail, _validate_meeting, max_tokens=2500)
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


# ---------- команды директора (этап 6 §2): только разбор в JSON, получателей считает сервер ----------

COMMAND_INTENTS = ("remind_overdue_tasks", "request_progress", "remind_no_response", "open_decision", "read_briefing")
COMMAND_SYSTEM = GLOSSARY + """
Ты разбираешь короткую команду директора (голосом или текстом) в системе обратной связи сотрудников. Верни ТОЛЬКО JSON:
{"intent": один из ["remind_overdue_tasks","request_progress","remind_no_response","open_decision","read_briefing"] или null,
 "filters": {"city": город из списка или null, "department": подразделение из списка или null, "person": имя сотрудника из списка или null,
             "stale_only": true только если директор просит тех, у кого давно нет новостей / «молчат», иначе false,
             "overdue_only": true только если директор говорит именно о просроченных по SLA, иначе false},
 "deadline": {"text": срок как прозвучал («сегодня», «до пятницы», «до 18:00», «завтра к обеду») или null},
 "note": короткое нейтральное пояснение для получателей, если директор назвал причину или контекст (например «нужно для отчёта в пятницу»),
         без оценок, упрёков и резких слов; иначе null,
 "idea": для open_decision — ключевые слова идеи или номер обращения (A-027), которую нужно открыть; иначе null}
Соответствие команд: remind_overdue_tasks — напомнить/поторопить исполнителей просроченных поручений с совещаний;
request_progress — запросить новости, ход работ, статус, «как дела» по обращениям «В работе»;
remind_no_response — напомнить ответственным об обращениях без первого ответа или просроченных по SLA;
open_decision — открыть «На решение» с конкретной идеей или предложением (принять или отклонить директор решает сам кнопкой);
read_briefing — прочитать, озвучить, рассказать сводку.
Команда вне этого списка (например «закажи пиццу», «уволь Иванова») → intent null. Город, подразделение и сотрудника бери только из списков,
иначе null. Резкий тон команды на разбор не влияет; получателей выбирает сервер, не ты."""


def parse_command(text: str, ctx: dict) -> dict:
    def validate(d: dict) -> None:
        if not isinstance(d, dict) or "intent" not in d:
            raise ValueError("нет поля intent")
        if d["intent"] is not None and d["intent"] not in COMMAND_INTENTS:
            raise ValueError(f"intent вне белого списка: {d['intent']}")
        if d.get("filters") is not None and not isinstance(d["filters"], dict):
            raise ValueError("filters не объект")
        if d.get("deadline") is not None and not isinstance(d["deadline"], (dict, str)):
            raise ValueError("deadline не объект")
    user = ("Города: " + ", ".join(c["city"] for c in ctx["cities"]) + "\nПодразделения: " + ", ".join(d["name"] for d in ctx["departments"]) +
            "\nСотрудники: " + ", ".join(p["name"] for p in ctx["people"]) + f"\n\nКоманда директора:\n{text}")
    d = chat_json(COMMAND_SYSTEM, user, validate, max_tokens=350)
    f = d.get("filters") or {}
    dl = d.get("deadline")
    return {"intent": d.get("intent"), "filters": {"city": f.get("city"), "department": f.get("department"), "person": f.get("person"),
                                                   "stale_only": bool(f.get("stale_only")), "overdue_only": bool(f.get("overdue_only"))},
            "deadline_text": (dl.get("text") if isinstance(dl, dict) else dl) or None, "note": d.get("note"), "idea": d.get("idea")}


# ---------- озвучка (OpenAI TTS тем же ключом) ----------

TTS_MODEL = os.environ.get("MF_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("MF_TTS_VOICE", "alloy")


def speak(text: str) -> bytes:
    """Текст → mp3. Деловой спокойный тон; кэширует вызывающий код (один и тот же текст — один вызов)."""
    if not available():
        raise LLMError("OPENAI_API_KEY не задан")
    kwargs = {"model": TTS_MODEL, "voice": TTS_VOICE, "input": text[:4000], "response_format": "mp3"}
    if TTS_MODEL.startswith("gpt-4o"):
        kwargs["instructions"] = "Деловой, спокойный тон, русский язык, без спешки. Это короткая сводка для директора компании."
    r = _client().audio.speech.create(**kwargs)
    return r.content
