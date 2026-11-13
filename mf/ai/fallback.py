"""Работа без ключа OpenAI (честная имитация, помечается в интерфейсе и docs/STATUS.md):
- classify(): категория обращения по словарю ключевых слов для 18 категорий датасета;
- analyze_meeting(): заскриптованный разбор демо-планёрки из ТЗ §10 (узнаётся по ключевым словам) и грубая
  эвристика для любой другой расшифровки (решения по «решили», ссылки на A-NNN, идеи по слову «идея»)."""
from __future__ import annotations

import re

ENGINE = "fallback"

# id категории → (ключ-основа в нижнем регистре, вес). Основы без окончаний, чтобы ловить падежи.
KEYWORDS: dict[int, list[tuple[str, int]]] = {
    1: [("межотдел", 5), ("между отдел", 5), ("смежн", 3), ("другого отдела", 3), ("заявк", 3), ("уточнен", 1), ("обязательн пол", 2), ("назначени издели", 4)],
    2: [("прозрачн", 3), ("стади", 5), ("статус проекта", 5), ("не видно", 2), ("не знаем", 2), ("контрольн", 3), ("поставщик", 2), ("ориентировочн", 2)],
    3: [("номенклатур", 6), ("каталог", 5), ("обозначен", 4), ("артикул", 5), ("карточк", 3), ("спецификац", 4), ("позици", 2), ("одного издели", 3),
        ("справочник", 4), ("дубл", 3), ("единиц измерени", 3), ("габарит", 3), ("снят с производств", 3), ("переименован", 3), ("одного и того же товар", 4)],
    4: [("обучен", 5), ("заняти", 4), ("семинар", 5), ("тренинг", 5), ("курс", 2), ("товарн линейк", 4), ("линейк", 2), ("демонстрац", 3), ("учебн", 3), ("презентац", 2), ("образц", 2)],
    5: [("документооборот", 6), ("пакет документ", 5), ("согласован", 3), ("подпис", 3), ("счет", 2), ("счёт", 2), (" акт", 2), ("на каком этапе", 3), ("документ", 1)],
    6: [("регламент", 6), ("памятк", 4), ("пошагов", 4), ("порядок", 2), ("правил", 2), ("процесс", 1), ("инструкци", 2)],
    7: [("1с", 2), ("1c", 2), ("битрикс", 5), ("интеграц", 6), ("синхрон", 5), ("две систем", 6), ("двух систем", 6), ("разных систем", 5), ("повторн ввод", 6), ("повторный ввод", 6), ("вбива", 5), ("ввод", 2), ("дважды", 3), ("систем", 2), ("программ", 2), ("сервер", 3), ("компьютер", 3), ("принтер", 4), ("почт", 2), ("vpn", 4), ("интернет", 3), ("сеть", 2), ("ит-", 3), (" it", 3), ("crm", 4), ("доступ", 1), ("парол", 3), ("автоматиз", 3)],
    8: [("наставни", 6), ("новому сотруднику", 5), ("нового сотрудника", 4), ("типов ошибок", 5), ("типовых ошибок", 5), ("передач сложн", 4), ("консультац", 2), ("знани", 3), ("опыт", 2)],
    9: [("договор", 6), ("приложени к договор", 6), ("контракт", 5), ("юрист", 4), ("версии приложения", 3), ("спецификаци к договор", 4)],
    10: [("закрыва задач", 5), ("закрывать задач", 5), ("подтвержден заказчик", 5), ("заказчик", 2), ("истори обсужден", 4), ("рабоч задач", 3), ("коммерческ", 5), ("шаблон", 2), ("кп", 4), ("задач", 1)],
    11: [("срочн", 4), ("срок ответа", 5), ("сроки ответа", 5), ("задерж", 4), ("долго", 2), ("ждём", 2), ("ждем", 2), ("оператив", 5), ("быстр", 2), ("клиентск предложени", 3), ("смежных подразделен", 3), ("уведомлен при задержк", 4)],
    12: [("чат", 4), ("канал", 3), ("мессенджер", 5), ("теряется контекст", 5), ("контекст", 2), ("итогов решени", 4), ("итоговые решени", 4), ("единое место", 4), ("разбросан", 3), ("обсужден", 2), ("коммуникац", 3)],
    13: [("проект", 2), ("состав оборудовани", 5), ("истори изменени", 5), ("пересмотр", 3), ("строки спецификац", 4), ("версий", 2)],
    14: [("загруж", 5), ("загрузк", 5), ("ресурс", 4), ("планиров", 3), ("нагрузк", 4), ("ближайшие недел", 3), ("проектн групп", 3)],
    15: [("поручен", 5), ("постановк задач", 6), ("постановке задач", 6), ("без срока", 4), ("ожидаем результат", 5), ("ожидаемого результата", 5), ("дат завершени", 4), ("цель, срок", 5), ("без ответственного", 3)],
    16: [("зон", 2), ("перерыв", 5), ("кофе", 4), ("кухн", 4), ("офис", 2), ("помещен", 3), ("атмосфер", 3), ("мероприят", 3), ("корпоратив", 4), ("отдых", 3), ("рабочих помещен", 3), ("парковк", 4), ("кондиционер", 4), ("освещен", 3)],
    17: [("папк", 5), ("актуальн редакци", 6), ("актуальную редакцию", 6), ("именован", 5), ("архив", 4), ("старых версий", 4), ("хранен", 4), ("общих папках", 6), ("файл", 1)],
    18: [("обзор", 3), ("завершённых", 3), ("завершенных", 3), ("видели результат", 5), ("результат предложен", 4), ("что изменил", 4), ("внутренних улучшени", 5), ("направленных предложени", 5), ("итоги улучшени", 4)],
    # ТЗ v2 (кастдев): 1С и завязанная на неё автоматизация
    19: [("1с", 6), ("1c", 6), ("автоматиз", 5), ("выгруз", 4), ("обработк", 2), ("конфигурац", 4), ("доработк", 3), ("отчёт в 1с", 4), ("отчет в 1с", 4), ("проводк", 3), ("регистр", 2)],
}
MIN_SCORE = 4        # ниже — «не уверены» → без категории (очередь администратора)
MIN_GAP_RATIO = 1.25  # лидер должен быть заметно впереди второго


def _norm(text: str) -> str:
    t = " " + (text or "").lower().replace("ё", "е") + " "
    return re.sub(r"\s+", " ", t)


_patterns: dict[str, re.Pattern] = {}


def _pattern(key: str) -> re.Pattern:
    """Ключ совпадает только с началом слова: «чат» ловит «чаты», но не «печатает»."""
    if key not in _patterns:
        _patterns[key] = re.compile(r"(?<![а-яa-z0-9әіңғүұқөһ])" + re.escape(key.strip()))
    return _patterns[key]


def classify(text: str, categories: list[dict] | None = None) -> dict:
    """→ {category_id, category, confidence, engine, scores}. category_id=None, если словарь не уверен."""
    t = _norm(text)
    scores: dict[int, int] = {}
    for cid, words in KEYWORDS.items():
        s = 0
        for w, weight in words:
            n = len(_pattern(w).findall(t))
            if n:
                s += weight * min(n, 2)
        if s:
            scores[cid] = s
    names = {c["id"]: c["name"] for c in (categories or [])}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    out = {"category_id": None, "category": None, "confidence": 0.0, "engine": "keywords",
           "scores": [{"category_id": cid, "category": names.get(cid), "score": s} for cid, s in ranked[:3]]}
    if not ranked:
        return out
    top_id, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if top < MIN_SCORE or (second and top < second * MIN_GAP_RATIO):
        out["confidence"] = round(min(top / 10, 0.5), 2)
        return out
    out.update({"category_id": top_id, "category": names.get(top_id), "confidence": round(min(0.5 + top / 20, 0.9), 2)})
    return out


# ---------- разбор совещания ----------

DEMO_MARKERS = ("повторн", "две системы", "шаблон", "коммерческ")
DEMO_ANALYSIS = {
    "summary": ("Обсудили повторный ввод одних и тех же данных в две системы (жалоба бухгалтерии, обращение A-007): Ерлан до пятницы "
                "собирает список таких операций и оценивает, что можно синхронизировать. Решили фиксировать итоговые решения по задачам "
                "в одном месте — в системе (закрывает A-012); Айгерим готовит короткое правило для отдела продаж, срок не назван. "
                "Идея Айгерим — шаблон коммерческого предложения с обязательными полями — уходит директору на решение."),
    "decisions": ["Итоговые решения по задачам фиксируем в одном месте — в системе"],
    "tasks": [
        {"text": "Собрать список операций с повторным вводом данных в двух системах и оценить, что можно синхронизировать; показать результат",
         "assignee_name": "Ерлан", "due": "до пятницы", "quote": "Давай, Ерлан, до пятницы собери и покажи."},
        {"text": "Подготовить короткое правило фиксации итоговых решений для отдела продаж",
         "assignee_name": "Айгерим", "due": None, "quote": "Айгерим, подготовь короткое правило для своего отдела."},
    ],
    "ideas": [
        {"text": "Шаблон коммерческого предложения с обязательными полями, чтобы не переделывать по три раза",
         "type": "suggestion", "category": "Задачи и коммуникации", "voiced_by": "Айгерим"},
    ],
    "linked_appeals": [
        {"number": "A-007", "decision": "Ерлан собирает список операций с повторным вводом до пятницы и оценит, что можно синхронизировать"},
        {"number": "A-012", "decision": "Решили: итоговые решения по задачам фиксируем в одном месте — в системе"},
    ],
    "open_questions": ["Срок для правила Айгерим не назван"],
}


def is_demo_transcript(transcript: str) -> bool:
    t = _norm(transcript)
    return sum(1 for m in DEMO_MARKERS if m in t) >= 3


def analyze_meeting(transcript: str, users: list[dict] | None = None, open_appeals: list[dict] | None = None) -> dict:
    """Схема как у llm.analyze_meeting (ТЗ §7) + engine='fallback', demo=True для заскриптованного разбора."""
    if is_demo_transcript(transcript):
        return {**DEMO_ANALYSIS, "engine": ENGINE, "demo": True}
    lines = [ln.strip() for ln in (transcript or "").splitlines() if ln.strip()]
    text = _norm(transcript)
    decisions = [re.sub(r"^[^:]{1,40}:\s*", "", ln) for ln in lines if re.search(r"решили|договорились|принято решение", ln.lower())]
    ideas = [{"text": re.sub(r"^[^:]{1,40}:\s*", "", ln), "type": "suggestion", "category": None,
              "voiced_by": (ln.split(":", 1)[0].strip() if ":" in ln[:40] else None)}
             for ln in lines if re.search(r"\bиде[яи]\b|предлага", ln.lower())]
    numbers = sorted(set(re.findall(r"a-\d{3}", text)))
    known = {a["number"].lower(): a for a in (open_appeals or [])}
    linked = [{"number": n.upper(), "decision": "Упоминалось на совещании (разбор без ИИ — уточните решение)"} for n in numbers if n in known or not known]
    summary = " ".join(lines)[:400] + ("…" if len(" ".join(lines)) > 400 else "")
    return {"summary": summary, "decisions": decisions[:5], "tasks": [], "ideas": ideas[:5], "linked_appeals": linked[:5],
            "open_questions": ["Разбор без ИИ: ключ OpenAI не задан — поручения добавьте вручную, пункты проверьте"],
            "engine": ENGINE, "demo": False}


# ---------- «Коротко» без ключа ----------

def brief(text: str) -> dict:
    """Первые два предложения текста + пометка, что автопересказ недоступен."""
    t = " ".join((text or "").split())
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", t) if x.strip()]
    gist = " ".join(parts[:2]) if parts else t
    if len(gist) > 240:
        gist = gist[:239].rstrip() + "…"
    return {"gist": gist, "proposes": None, "expects": None, "unclear": False, "question": None, "note": "автопересказ недоступен (без ключа)"}


# ---------- команды директора без ключа (этап 6 §2): те же пять intent по ключевым словам ----------

CITY_STEMS = {"омск": "Омск", "самар": "Самара", "тюмен": "Тюмень", "астан": "Астана", "павлодар": "Павлодар"}


def parse_command(text: str, ctx: dict) -> dict:
    """→ {intent, filters: {city, department, person, stale_only, overdue_only}, deadline_text, note, idea}. Та же форма, что у LLM."""
    t = _norm(text)
    intent = None
    if re.search(r"сводк|бриф|что нового|расскажи|прочитай|озвуч", t):
        intent = "read_briefing"
    if re.search(r"идея|идею|идеи|предложени|на решение|прими|принять|открой|отклон", t) and not re.search(r"поручен|без ответа|сводк", t):
        intent = "open_decision"
    if re.search(r"поручен", t) and re.search(r"просроч|напомн|поторопи|срок", t):
        intent = "remind_overdue_tasks"
    if re.search(r"без ответа|не ответил|первого ответа|первый ответ|не отвеч|sla|сла\b", t) or (re.search(r"просроч", t) and re.search(r"обращен", t)):
        intent = "remind_no_response"
    if (re.search(r"ход|новост|прогресс|статус|как дела|отчита|доложи|сообщи", t) or (re.search(r"расскаж|что по|как там", t) and re.search(r"обращен|в работе", t))) \
            and not re.search(r"поручен|без ответа|первого ответа", t) and intent not in ("open_decision",):
        intent = "request_progress"
    city = next((v for k, v in CITY_STEMS.items() if k in t), None)
    department = next((d["name"] for d in ctx.get("departments", []) if len(d["name"]) > 2 and _norm(d["name"])[1:5] in t), None)
    person = None
    try:
        from . import names as _names
        others = [p for p in ctx.get("people", []) if p.get("role") != "director"]
        for w in re.findall(r"[а-яa-z-]{3,}", t):
            if w in ("омск", "омске", "самаре", "тюмени", "астане", "павлодаре"):
                continue
            m = _names.match(w, others)
            if m["user"] and m["score"] >= 0.95:
                person = m["user"]["name"]
                break
    except Exception:   # noqa: BLE001
        person = None
    dl = re.search(r"((?:сегодня|завтра|послезавтра)(?:\s+(?:до|к)\s+[\w:.]+(?:\s+час\w*)?)?|\b(?:до|к)\s+(?:конца\s+\w+|обеда|вечера|[а-я]+\s+(?:вечера|утра|дня|часов)|\d{1,2}(?:[:.]\d{2})?(?:\s+час\w*)?|[а-я]+(?:\s+\d{1,2}(?:[:.]\d{2})?)?)|через\s+\w+)", t)
    deadline_text = dl.group(1).strip() if dl else None
    if deadline_text and re.fullmatch(r"(?:до|к)\s+(?:ответственн\w*|исполнител\w*|сотрудник\w*|них|всех|них)", deadline_text):
        deadline_text = None
    idea = None
    if intent == "open_decision":
        m = re.search(r"(?:про|о|об|насчет|насчёт)\s+(.+)$", t) or re.search(r"(a-\d{3})", t)
        idea = m.group(1).strip() if m else None
    return {"intent": intent, "filters": {"city": city, "department": department, "person": person,
                                          "stale_only": bool(re.search(r"без новостей|давно|молч", t)), "overdue_only": bool(re.search(r"просроч", t)) and intent == "remind_no_response"},
            "deadline_text": deadline_text, "note": None, "idea": idea}


# ---------- «Директор в кармане» без ключа (пункт 2 очереди 12.11): вопрос → тип из белого списка по ключевым словам ----------

ACTION = re.compile(r"(?<![а-яa-z])(напомни(?:те)?|попроси(?:те)?|запроси(?:те)?|отправь(?:те)?|разошли(?:те)?|поторопи(?:те)?|открой(?:те)?"
                    r"|прочитай(?:те)?|прочти(?:те)?|озвучь(?:те)?)(?![а-яa-z])"
                    r"|(?<![а-яa-z])пусть\s+(?:[а-яa-z-]+\s+){0,3}(?:отчита\w*|сообщ\w*|ответ\w*|доложа\w*|напиш\w*)", re.IGNORECASE)


def is_action(text: str) -> bool:
    """Команда — только при явном глаголе действия к людям или к системе: «напомни», «попроси», «отправь», «пусть отчитаются»,
    «открой», «прочитай». Вопросы «кто / что / сколько / как дела», «скажи», «расскажи» — только ответ (замечание владельца 12.11)."""
    return bool(ACTION.search((text or "").lower().replace("ё", "е")))


def _find_name(name: str, t: str) -> int:
    """Позиция упоминания города или отдела: начало слова и первые 5 букв («Производство» ≠ «происходит», «Самара» ≠ «самое»); -1 — нет."""
    stem = _norm(name).strip()[:5]
    if len(stem) < 3:
        return -1
    m = re.search(r"(?<![а-яa-z0-9])" + re.escape(stem), t)
    return m.start() if m else -1


def boss_parts(text: str, ctx: dict) -> list[dict]:
    """Составной вопрос → части по порядку упоминания: просрочки, решения, темы, обращение, город(а), отдел, «что нового» (если больше ничего)."""
    t = _norm(text)
    found: list[tuple[int, dict]] = []

    def add(pos, q, **kw):
        found.append((pos, {"question": q, "city": kw.get("city"), "department": kw.get("department"), "number": kw.get("number")}))
    m = re.search(r"(?<![а-яa-z])[aа]-?\s?(\d{1,4})\b", t)
    if m:
        add(m.start(), "appeal", number=f"A-{int(m.group(1)):03d}")
    m = re.search(r"просроч|просрач|не отвеч|тянет|тянут|опазд|опозда|по задачам|поручени", t)
    if m:
        add(m.start(), "who_overdue")
    m = re.search(r"решени|на решение|ждут меня|ждет меня|предложени", t)
    if m:
        add(m.start(), "my_decisions")
    m = re.search(r"тем[аы]|о чем пишут|что болит|повторя|чаще всего", t)
    if m:
        add(m.start(), "main_topics")
    for c in ctx.get("cities", []):
        i = _find_name(c["city"], t)
        if i >= 0:
            add(i, "city", city=c["city"])
    for d in ctx.get("departments", []):
        i = _find_name(d["name"], t)
        if i >= 0 and re.search(r"отдел|подразделен|как дела|что у|что по", t):
            add(i, "department", department=d["name"])
    if not found and re.search(r"что нового|нового|как дела|что происходит|сводк|итог|обстановк|в целом|что у нас|сколько|пришл|поступил|решили|решено", t):
        add(0, "whats_new")
    if not found and re.search(r"(?<![а-яa-z])город|филиал", t):
        add(0, "city")
    if not found and re.search(r"отдел|подразделен", t):
        add(0, "department")
    out, seen = [], set()
    for _, p in sorted(found, key=lambda x: x[0]):
        key = (p["question"], p["city"], p["department"], p["number"])
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out[:3]


def parse_boss(text: str, ctx: dict) -> dict:
    """→ {kind, question, city, department, number, period, parts} — та же форма, что у llm.parse_boss."""
    t = _norm(text)
    city = next((c["city"] for c in ctx.get("cities", []) if _find_name(c["city"], t) >= 0), None)
    department = next((d["name"] for d in ctx.get("departments", []) if _find_name(d["name"], t) >= 0), None)
    m = re.search(r"(?<![а-яa-z])[aа]-?\s?(\d{1,4})\b", t)   # «A-027», «а 27» — латиница и кириллица, как пишет STT
    number = f"A-{int(m.group(1)):03d}" if m else None
    period = "today" if re.search(r"сегодня|за день|с утра", t) else "month" if re.search(r"месяц|30 дн|тридцать дн", t) else "week" if re.search(r"недел", t) else None
    # команда — только явный глагол действия (is_action); иначе это вопрос, даже если в нём есть «просрочил» или «напоминание»
    if is_action(text):
        return {"kind": "command", "question": None, "city": city, "department": department, "number": number, "period": period, "parts": []}
    parts = boss_parts(text, ctx)
    if parts:
        return {"kind": "question", **parts[0], "period": period, "parts": parts}
    q = None
    if number and re.search(r"обращен|номер|[aа]-?\s?\d", t):
        q = "appeal"
    elif re.search(r"решени|на решение|ждут меня|ждет меня|предложени", t):
        q = "my_decisions"
    elif re.search(r"просроч|не отвеч|тянет|тянут|опозда", t):
        q = "who_overdue"
    elif re.search(r"тем[аы]|о чем пишут|что болит|повторя|чаще всего", t):
        q = "main_topics"
    elif department and re.search(r"отдел|подразделен|как дела|что у|что по", t):
        q = "department"
    elif city and re.search(r"город|филиал|как дела|что по|что в|что у|как там", t):
        q = "city"
    elif re.search(r"что нового|нового|как дела|что происходит|сводк|итог|обстановк|в целом|что у нас", t):
        q = "whats_new"
    elif city or re.search(r"\bгород|филиал", t):
        q = "city"   # город не из списка → сервер ответит «не понял, какой город» и перечислит известные
    elif department or re.search(r"отдел|подразделен", t):
        q = "department"
    return {"kind": "question" if q else "unknown", "question": q, "city": city, "department": department, "number": number, "period": period,
            "parts": [{"question": q, "city": city, "department": department, "number": number}] if q else []}
