"""«Директор в кармане» (пункт 2 очереди 12.11): отдельное приложение директора на телефоне — один экран (приветствие, «Сегодня /
Неделя», четыре цифры со списками) и вопросы голосом или текстом. Вопросы — только чтение, из белого списка QUESTIONS: разбор
(LLM или ключевые слова) → факты считает СЕРВЕР → LLM пересказывает → каждое число сверяется с фактами, иначе шаблон. Команды
(напомнить, запросить новости, открыть «На решение», прочитать сводку) — существующий mf/commands.py с обязательным подтверждением.
Неизвестный вопрос — «Не знаю, вот где посмотреть» со ссылкой. Голос ответа — нейтральный TTS (director.tts_cached), не клонирование."""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
from datetime import timedelta

from fastapi import HTTPException

from . import appeals, auth, commands, db, director, meetings
from .ai import fallback, llm, similar

log = logging.getLogger("mf.boss")

QUESTIONS = {
    "whats_new": "что нового за период",
    "my_decisions": "что ждёт моего решения",
    "who_overdue": "кто просрочил",
    "main_topics": "главные темы",
    "city": "что по городу",
    "appeal": "что по обращению",
    "department": "как дела у отдела",
}
EXAMPLES = ["Что нового за неделю?", "Что ждёт моего решения?", "Кто просрочил?", "Какие главные темы?", "Что по Омску?", "Что по обращению A-027?", "Как дела у продаж?"]
PERIODS = {"today": "сегодня", "week": "за неделю"}
ANSWER_TTL = 1800
_ANSWERS: dict[str, dict] = {}


# ---------- период ----------

def _offset() -> timedelta:
    return timedelta(hours=int(db.setting("tz_offset_hours", 5) or 5))


def period_since(period: str) -> str:
    """«Сегодня» — с местной полуночи (tz_offset_hours), «неделя» — последние 7 суток. ISO в UTC для сравнения с колонками базы."""
    now = db.now()
    if period == "today":
        local_midnight = (now + _offset()).replace(hour=0, minute=0, second=0, microsecond=0)
        return db.iso(local_midnight - _offset())
    return db.iso(now - timedelta(days=7))


def _period(period: str | None) -> str:
    return period if period in PERIODS else "week"


# ---------- факты (считает сервер) ----------

def _rows() -> list[dict]:
    return [appeals.decorate(r) for r in db.q(appeals.BASE_SELECT)]


def _brief_item(a: dict) -> dict:
    return {"id": a["id"], "number": a["number"], "text": appeals.line(a, 80), "status": a["status_label"], "status_code": a["status"], "branch": a.get("branch"),
            "responsible": a.get("responsible"), "age_days": int(a["age_hours"] // 24), "overdue": a["overdue"], "type": a["type_label"]}


def _decisions() -> list[dict]:
    q = meetings.director_ideas({"role": "director", "id": 0})
    out = []
    for i in q["pending"]:
        out.append({"source": i["source"], "id": i.get("id"), "appeal_id": i.get("appeal_id"), "number": i.get("number"),
                    "text": appeals.short(i["text"], 110), "wait_days": int(i.get("wait_days") or 0), "over_threshold": bool(i.get("over_threshold")),
                    "category": i.get("category"), "category_id": i.get("category_id"), "request": i.get("request"),
                    "meeting_title": i.get("meeting_title"), "branch": i.get("branch")})
    return out


def _overdue_tasks() -> list[dict]:
    today = db.now().date().isoformat()
    rows = db.q("""SELECT i.id, i.text, i.due_date, i.meeting_id, u.name AS assignee, m.title AS meeting_title FROM meeting_items i
                   JOIN meetings m ON m.id=i.meeting_id LEFT JOIN users u ON u.id=i.assignee_id
                   WHERE i.kind='task' AND i.removed=0 AND m.status='sent' AND i.due_date IS NOT NULL AND i.due_date < ?
                   AND i.task_status IN ('assigned','in_progress') ORDER BY i.due_date""", (today,))
    for r in rows:
        y, m, d = r["due_date"].split("-")
        r["due_label"] = f"{d}.{m}"
        r["text"] = appeals.short(r["text"], 90)
    return rows


def home(user: dict, period: str | None = None) -> dict:
    """Экран «Директор в кармане»: четыре цифры за период и короткие списки за ними."""
    period = _period(period)
    since = period_since(period)
    rows = _rows()
    new = [r for r in rows if r["created_at"] >= since]
    done = [r for r in rows if r["status"] in ("done", "closed") and r["type"] != "praise" and r["closed_at"] and r["closed_at"] >= since]
    overdue = [r for r in rows if r["overdue"]]
    decisions = _decisions()
    tasks = _overdue_tasks()
    out = {"period": period, "period_label": PERIODS[period], "name": auth.display_name(user), "since": since,
           "tiles": {"new": len(new), "done": len(done), "decisions": len(decisions), "overdue": len(overdue) + len(tasks)},
           "lists": {"new": [_brief_item(a) for a in sorted(new, key=lambda r: r["created_at"], reverse=True)[:12]],
                     "done": [{**_brief_item(a), "resolution": appeals.short(a.get("resolution_text") or "", 90)} for a in sorted(done, key=lambda r: r["closed_at"] or "", reverse=True)[:12]],
                     "decisions": decisions[:12],
                     "overdue": [{"kind": "appeal", **_brief_item(a)} for a in sorted(overdue, key=lambda r: -r["age_hours"])[:12]] +
                                [{"kind": "task", **t} for t in tasks[:12]]},
           "links": {"new": "/panel#/queue?open=1", "done": "/changes", "decisions": "/panel#/decisions", "overdue": "/panel#/queue?overdue=1"}}
    out["greeting"] = greeting(user, out)
    return out


# ---------- приветствие ИИ по имени-отчеству (1–2 фразы), числа сверяются; без ключа — шаблон; кэш по версии данных ----------

def _greeting_facts(h: dict) -> dict:
    t = h["tiles"]
    return {"period": h["period_label"], "new": t["new"], "done": t["done"], "decisions": t["decisions"], "overdue": t["overdue"]}


def greeting_template(user: dict, h: dict) -> str:
    t = h["tiles"]
    p = h["period_label"]
    parts = [director.greeting(user)]
    s = f"{p[0].upper() + p[1:]} пришло {director._plural(t['new'], ('обращение', 'обращения', 'обращений'))}, решено {t['done']}"
    if t["decisions"]:
        s += f"; вашего решения {'ждёт' if t['decisions'] == 1 else 'ждут'} {t['decisions']}"
    parts.append(s + ".")
    if t["overdue"]:
        parts.append(f"Просрочено: {t['overdue']}.")
    return " ".join(parts)


def greeting(user: dict, h: dict) -> dict:
    key = f"boss_greeting:{user['id']}:{h['period']}"
    v = director.version() + ":" + (db.now() + _offset()).strftime("%Y-%m-%d-%H")[:13]   # меняется с событиями и раз в час (время суток в приветствии)
    cached = db.setting(key)
    if cached and cached.get("version") == v:
        return cached
    text, engine = None, "template"
    if llm.available():
        facts = {**_greeting_facts(h), "greeting": director.greeting(user)}
        allowed = llm.numeric_values(facts)
        try:
            cand = llm.boss_greeting(facts)
            if llm.numbers_in_answer(cand) <= allowed and not llm.negates_nonzero(cand, {"overdue": facts["overdue"], "decisions_pending": facts["decisions"]}) \
                    and not llm.has_forbidden(cand) and cand.startswith(director.greeting(user)[:12]):
                text, engine = cand, "openai"
            else:
                log.warning("приветствие: числа или термины не прошли проверку: %s", cand)
        except llm.LLMError as e:
            log.warning("приветствие: %s", e)
    out = {"text": text or greeting_template(user, h), "engine": engine, "version": v}
    db.set_setting(key, out)
    return out


# ---------- вопросы ----------

def _context() -> dict:
    return {"cities": [{"id": b["id"], "city": b["city"], "name": b["name"]} for b in db.q("SELECT id, city, name FROM branches WHERE kind != 'field' ORDER BY is_hq DESC, name")],
            "departments": db.q("SELECT id, name FROM departments ORDER BY id")}


def _stem(s: str) -> str:
    return (s or "").lower().replace("ё", "е")[:5]


def parse(text: str, user: dict) -> dict:
    """→ {kind: question|command|unknown, question, city, department, number, period, engine}."""
    text = " ".join((text or "").split())
    if len(text) < 2:
        raise HTTPException(422, "Скажите или напишите вопрос")
    ctx = _context()
    raw, engine = None, "keywords"
    if llm.available():
        try:
            raw = llm.parse_boss(text, ctx)
            engine = "openai"
        except llm.LLMError as e:
            engine = f"keywords (LLM: {str(e)[:60]})"
    if raw is None:
        raw = fallback.parse_boss(text, ctx)
    kind = raw.get("kind") if raw.get("kind") in ("question", "command", "unknown") else "unknown"
    # замечание владельца 12.11: команда — только при явном глаголе действия; иначе это вопрос, даже если модель решила иначе
    if fallback.is_action(text):
        kind = "command"
    elif kind == "command":
        kind = "question"
    raw_parts = [x for x in (raw.get("parts") or []) if isinstance(x, dict) and x.get("question") in QUESTIONS]
    if kind != "command" and not raw_parts:
        raw_parts = fallback.boss_parts(text, ctx)   # модель не разложила — разложим ключевыми словами
        if raw_parts and kind == "unknown":
            kind = "question"
    parts = _clean_parts([_resolve_part(x, text, ctx) for x in raw_parts], text) if kind == "question" else []
    if kind == "question" and not parts:
        kind = "unknown"
    first = parts[0] if parts else {"question": None, "city": None, "city_id": None, "department": None, "department_id": None, "number": None}
    return {"text": text, "kind": kind, **first, "period": raw.get("period") if raw.get("period") in PERIODS else None, "engine": engine, "parts": parts}


TOPIC_WORDS = re.compile(r"тем[аыу]|о ч[её]м пишут|что болит|повторя|чаще всего")
NEW_WORDS = re.compile(r"нового|как дела|что происходит|сводк|итог|обстановк|в целом|сколько|пришл|поступ")


def _clean_parts(parts: list[dict], text: str) -> list[dict]:
    """Части от модели → по смыслу вопроса: город или отдел, приписанные к «кто просрочил» / «что нового», — отдельной частью
    (иначе «в Павлодаре просрочено 7», хотя 7 — по всей компании); «темы» и «что нового» в составном вопросе — только если о них
    спросили словами; повторы — один раз; не больше трёх частей."""
    t = (text or "").lower().replace("ё", "е")
    out = []
    for p in parts:
        if p["question"] in ("city", "department") or not (p["city_id"] or p["department_id"]):
            out.append(p)
            continue
        out.append({**p, "city": None, "city_id": None, "department": None, "department_id": None})   # сама часть — по всей компании
        if p["city_id"]:
            out.append({"question": "city", "city": p["city"], "city_id": p["city_id"], "department": None, "department_id": None, "number": None})
        if p["department_id"]:
            out.append({"question": "department", "city": None, "city_id": None, "department": p["department"], "department_id": p["department_id"], "number": None})
    if len(out) > 1:
        kept = [p for p in out if not (p["question"] == "main_topics" and not TOPIC_WORDS.search(t)) and not (p["question"] == "whats_new" and not NEW_WORDS.search(t))]
        out = kept or out[:1]
    res, seen = [], set()
    for p in out:
        key = (p["question"], p["city_id"], p["department_id"], p["number"])
        if key not in seen:
            seen.add(key)
            res.append(p)
    return res[:3]


def _resolve_part(x: dict, text: str, ctx: dict) -> dict:
    out = {"question": x["question"], "city": None, "city_id": None, "department": None, "department_id": None, "number": None}
    if x.get("city"):
        st = _stem(str(x["city"]))
        b = next((c for c in ctx["cities"] if _stem(c["city"]) == st or _stem(c["name"]) == st), None)
        if b:
            out["city"], out["city_id"] = b["city"], b["id"]
    if x.get("department"):
        st = _stem(str(x["department"]))
        d = next((d for d in ctx["departments"] if _stem(d["name"]) == st), None)
        if d:
            out["department"], out["department_id"] = d["name"], d["id"]
    m = re.search(r"(?<![а-яa-z])[aа]-?\s?(\d{1,4})\b", str(x.get("number") or (text if x["question"] == "appeal" else "")).lower())
    if m:
        out["number"] = f"A-{int(m.group(1)):03d}"
    return out


def facts_for(p: dict, period: str) -> dict:
    """Факты для ответа — только с сервера. link — куда смотреть подробнее на сайте."""
    q = p["question"]
    since = period_since(period)
    rows = _rows()
    open_rows = [r for r in rows if r["status"] in appeals.OPEN]
    if q == "whats_new":
        new = [r for r in rows if r["created_at"] >= since]
        done = [r for r in rows if r["status"] in ("done", "closed") and r["type"] != "praise" and r["closed_at"] and r["closed_at"] >= since]
        cats: dict[str, int] = {}
        for r in new:
            if r["category"]:
                cats[r["category"]] = cats.get(r["category"], 0) + 1
        return {"period": PERIODS[period], "new": len(new), "done": len(done), "open": len(open_rows), "urgent_open": sum(1 for r in open_rows if r.get("author_urgency") == "now"),
                "decisions_pending": len(_decisions()), "overdue_appeals": sum(1 for r in open_rows if r["overdue"]), "overdue_tasks": len(_overdue_tasks()),
                "top_category": max(cats.items(), key=lambda kv: kv[1])[0] if cats else None,
                "cities": sorted({r["branch"] for r in new if r["branch"]}), "link": "/panel#/summary", "link_label": "Сводка"}
    if q == "my_decisions":
        d = _decisions()
        return {"count": len(d), "over_threshold": sum(1 for x in d if x["over_threshold"]), "threshold_days": appeals.director_wait_days(),
                "items": [{"number": x["number"], "text": x["text"], "wait_days": x["wait_days"], "source": "обращение" if x["source"] == "appeal" else "совещание"} for x in d[:5]],
                "link": "/panel#/decisions", "link_label": "На решение"}
    if q == "who_overdue":
        over = [r for r in open_rows if r["overdue"]]
        by: dict[str, list[str]] = {}
        for r in over:
            by.setdefault(r["responsible"] or "без ответственного", []).append(r["number"])
        tasks = _overdue_tasks()
        tby: dict[str, int] = {}
        for t in tasks:
            tby[t["assignee"] or "без исполнителя"] = tby.get(t["assignee"] or "без исполнителя", 0) + 1
        return {"total_overdue": len(over) + len(tasks),   # = плитка «просрочено» на главном экране
                "overdue_appeals": len(over), "by_responsible": [{"name": k, "count": len(v)} for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))[:3]],
                "overdue_tasks": len(tasks), "tasks_by_assignee": [{"name": k, "count": n} for k, n in sorted(tby.items(), key=lambda kv: -kv[1])[:3]],
                "link": "/panel#/queue?overdue=1", "link_label": "Просроченные в очереди"}
    if q == "main_topics":
        topics = []
        try:
            c = similar.clusters()
            topics = [{"topic": k["category"] or k["label"], "size": k["size"], "cities": len(k["branches"])} for k in c["clusters"][:3]]
        except Exception as e:   # noqa: BLE001
            log.warning("темы: %s", e)
        cats: dict[str, int] = {}
        for r in open_rows:
            if r["category"]:
                cats[r["category"]] = cats.get(r["category"], 0) + 1
        return {"repeated": topics, "open": len(open_rows), "top_categories": [{"category": k, "open": n} for k, n in sorted(cats.items(), key=lambda kv: -kv[1])[:3]],
                "link": "/panel#/summary", "link_label": "Повторяющиеся темы"}
    if q == "city":
        if not p["city_id"]:
            return {"unknown_city": True, "cities": [c["city"] for c in _context()["cities"]], "link": "/panel#/summary", "link_label": "Карта"}
        items = [r for r in rows if r["branch_id"] == p["city_id"]]
        op = [r for r in items if r["status"] in appeals.OPEN]
        cats: dict[str, int] = {}
        for r in op:
            if r["category"]:
                cats[r["category"]] = cats.get(r["category"], 0) + 1
        return {"city": p["city"], "period": PERIODS[period], "open": len(op), "overdue": sum(1 for r in op if r["overdue"]), "urgent_open": sum(1 for r in op if r.get("author_urgency") == "now"),
                "unassigned": sum(1 for r in op if r["unassigned"]), "new": sum(1 for r in items if r["created_at"] >= since),
                "done": sum(1 for r in items if r["status"] in ("done", "closed") and r["type"] != "praise" and r["closed_at"] and r["closed_at"] >= since),
                "top_category": max(cats.items(), key=lambda kv: kv[1])[0] if cats else None,
                "link": f"/panel#/queue?branch_id={p['city_id']}&open=1", "link_label": f"Очередь · {p['city']}"}
    if q == "appeal":
        a = next((r for r in rows if r["number"] == p["number"]), None) if p["number"] else None
        if not a:
            return {"not_found": True, "number": p["number"], "link": "/panel#/queue", "link_label": "Очередь"}
        st = appeals.stage_for(a)
        news = appeals.news_age_days(a) if a["status"] in appeals.OPEN else None
        return {"number": a["number"], "status": a["status_label"], "stage": st["label"], "type": a["type_label"], "branch": a["branch"], "category": a["category"],
                "responsible": a["responsible"] or "не назначен", "gist": appeals.line(a, 160), "age_days": int(a["age_hours"] // 24), "overdue": a["overdue"],
                "news_days": int(news) if news is not None else None, "supports": a["supports"], "priority": a["priority_label"],
                "resolution": appeals.short(a.get("resolution_text") or "", 120) or None, "director_decision": a.get("director_decision"),
                "link": f"/panel#/appeal/{a['id']}", "link_label": a["number"]}
    if q == "department":
        if not p["department_id"]:
            return {"unknown_department": True, "departments": [d["name"] for d in _context()["departments"]], "link": "/panel#/queue", "link_label": "Очередь"}
        staff = db.q("SELECT id, name FROM users WHERE department_id=? AND active=1", (p["department_id"],))
        ids = {u["id"] for u in staff}
        items = [r for r in rows if r["department_id"] == p["department_id"] or (r["responsible_id"] in ids)]
        op = [r for r in items if r["status"] in appeals.OPEN]
        today = db.now().date().isoformat()
        tasks = db.q("""SELECT i.due_date, i.task_status FROM meeting_items i JOIN meetings m ON m.id=i.meeting_id JOIN users u ON u.id=i.assignee_id
                        WHERE i.kind='task' AND i.removed=0 AND m.status='sent' AND i.task_status IN ('assigned','in_progress') AND u.department_id=?""", (p["department_id"],))
        return {"department": p["department"], "period": PERIODS[period], "staff": len(staff), "open": len(op), "overdue": sum(1 for r in op if r["overdue"]),
                "new": sum(1 for r in items if r["created_at"] >= since),
                "done": sum(1 for r in items if r["status"] in ("done", "closed") and r["type"] != "praise" and r["closed_at"] and r["closed_at"] >= since),
                "tasks_open": len(tasks), "tasks_overdue": sum(1 for t in tasks if t["due_date"] and t["due_date"] < today),
                "link": f"/panel#/queue?department_id={p['department_id']}&open=1", "link_label": f"Очередь · {p['department']}"}
    raise HTTPException(422, "Неизвестный вопрос")


# ---------- шаблонный ответ (без ключа и если ИИ исказил числа) ----------

def _pl(n: int, forms: tuple[str, str, str]) -> str:
    return director._plural(n, forms)


def template_answer(q: str, f: dict) -> str:
    if q == "whats_new":
        s = f"{f['period'][0].upper() + f['period'][1:]} пришло {_pl(f['new'], ('обращение', 'обращения', 'обращений'))}, решено {f['done']}; открыто {f['open']}"
        s += f", из них мешают работать сейчас {f['urgent_open']}." if f["urgent_open"] else "."
        if f["decisions_pending"]:
            s += f" Вашего решения {'ждёт' if f['decisions_pending'] == 1 else 'ждут'} {f['decisions_pending']}."
        if f["overdue_appeals"] or f["overdue_tasks"]:
            s += " Просрочено: " + ", ".join(x for x in (f"{_pl(f['overdue_appeals'], ('обращение', 'обращения', 'обращений'))}" if f["overdue_appeals"] else None,
                                                        f"{_pl(f['overdue_tasks'], ('поручение', 'поручения', 'поручений'))}" if f["overdue_tasks"] else None) if x) + "."
        if f["top_category"]:
            s += f" Чаще всего писали про «{f['top_category']}»."
        return s
    if q == "my_decisions":
        if not f["count"]:
            return "Вашего решения сейчас ничего не ждёт."
        s = f"Вашего решения {'ждёт' if f['count'] == 1 else 'ждут'} {_pl(f['count'], ('предложение', 'предложения', 'предложений'))}"
        if f["over_threshold"]:
            s += f", {f['over_threshold']} из них дольше {_pl(f['threshold_days'], ('дня', 'дней', 'дней'))}"
        s += ": " + "; ".join((x["number"] + " — " if x["number"] else "") + appeals.short(x["text"], 70) + f" (ждёт {_pl(x['wait_days'], ('день', 'дня', 'дней'))})" for x in f["items"][:3]) + "."
        return s
    if q == "who_overdue":
        if not f["overdue_appeals"] and not f["overdue_tasks"]:
            return "Просрочек нет: обращения получили первый ответ вовремя, поручения с совещаний в сроке."
        kinds = [x for x in (_pl(f["overdue_appeals"], ("обращение", "обращения", "обращений")) + " без первого ответа в срок" if f["overdue_appeals"] else None,
                             _pl(f["overdue_tasks"], ("поручение", "поручения", "поручений")) + " с совещаний" if f["overdue_tasks"] else None) if x]
        s = f"Всего просрочено {f['total_overdue']}: " + " и ".join(kinds) + "."
        if f["overdue_appeals"]:
            s += " Обращения: " + ", ".join(f"{x['name']} — {x['count']}" for x in f["by_responsible"][:3]) + "."
        if f["overdue_tasks"]:
            s += " Поручения: " + ", ".join(f"{x['name']} — {x['count']}" for x in f["tasks_by_assignee"][:3]) + "."
        return s
    if q == "main_topics":
        parts = []
        if f["repeated"]:
            parts.append("Повторяющиеся темы: " + "; ".join(f"{t['topic']} — {_pl(t['size'], ('обращение', 'обращения', 'обращений'))} из {_pl(t['cities'], ('города', 'городов', 'городов'))}" for t in f["repeated"]))
        if f["top_categories"]:
            parts.append("Больше всего открытых: " + ", ".join(f"{c['category']} — {c['open']}" for c in f["top_categories"]))
        return (". ".join(parts) + ".") if parts else "Открытых обращений нет, тем для разговора пока нет."
    if q == "city":
        if f.get("unknown_city"):
            return "Не понял, какой город. Есть: " + ", ".join(f["cities"]) + "."
        s = f"{f['city']}: открыто {_pl(f['open'], ('обращение', 'обращения', 'обращений'))}"
        extra = [x for x in (f"просрочено {f['overdue']}" if f["overdue"] else None, f"мешают работать сейчас {f['urgent_open']}" if f["urgent_open"] else None,
                             f"без ответственного {f['unassigned']}" if f["unassigned"] else None) if x]
        s += (", из них " + ", ".join(extra) if extra else "") + f". {f['period'][0].upper() + f['period'][1:]} пришло {f['new']}, решено {f['done']}."
        if f["top_category"]:
            s += f" Главная тема — {f['top_category']}."
        return s
    if q == "appeal":
        if f.get("not_found"):
            return f"Обращение {f['number'] or 'с таким номером'} не нашёл. Посмотрите в очереди."
        s = f"{f['number']}, {f['type'].lower()}, {f['branch'] or 'без филиала'}: {f['gist']} Стадия — {f['stage'].lower()}, отвечает {f['responsible']}, подано {_pl(f['age_days'], ('день', 'дня', 'дней'))} назад."
        if f["overdue"]:
            s += " Срок первого ответа прошёл."
        if f.get("news_days") is not None and f["news_days"] >= 1:
            s += f" Автору не сообщали новостей {_pl(f['news_days'], ('день', 'дня', 'дней'))}."
        if f.get("resolution"):
            s += f" Что сделали: {f['resolution']}"
        return s
    if q == "department":
        if f.get("unknown_department"):
            return "Не понял, какой отдел. Есть: " + ", ".join(f["departments"]) + "."
        s = f"{f['department']}: открыто {_pl(f['open'], ('обращение', 'обращения', 'обращений'))}"
        s += f", просрочено {f['overdue']}" if f["overdue"] else ""
        s += f"; {f['period']} пришло {f['new']}, решено {f['done']}."
        if f["tasks_open"]:
            s += f" Поручений с совещаний в работе {f['tasks_open']}" + (f", просрочено {f['tasks_overdue']}" if f["tasks_overdue"] else "") + "."
        return s
    return "Не знаю."


def _allowed_numbers(f: dict) -> set[int]:
    """F-12: только числа из числовых полей фактов — номера обращений и цифры из текстов сотрудников числами не считаются."""
    return llm.numeric_values(f)


def ai_answer(question: str, q: str, f: dict) -> str | None:
    """LLM пересказывает факты; числа только из фактов и без запрещённых синонимов, иначе None → шаблон."""
    if not llm.available():
        return None
    allowed = _allowed_numbers(f)
    payload = {k: v for k, v in f.items() if k not in ("link", "link_label")}
    for attempt in range(2):
        try:
            text = llm.boss_answer(question, QUESTIONS[q], payload)
        except llm.LLMError as e:
            log.warning("ответ директору: %s", e)
            return None
        nums = llm.numbers_in_answer(text)
        lie = llm.negates_nonzero(text, f)
        if lie:
            log.warning("ответ (попытка %d): «нет» вместо ненулевого факта (%s) в «%s»", attempt + 1, lie, text)
            continue
        if not nums <= allowed:
            log.warning("ответ (попытка %d): лишние числа %s в «%s»", attempt + 1, sorted(nums - allowed), text)
            continue
        word = llm.has_forbidden(text)
        if word:
            log.warning("ответ (попытка %d): запрещённый термин «%s»", attempt + 1, word)
            payload = {**payload, "note": f"В прошлом ответе было слово «{word}» — так нельзя, используй термины из глоссария."}
            continue
        return text
    return None


# ---------- спросить: вопрос → факты → ответ; команда → план на подтверждение; иначе «не знаю» ----------

def _cleanup() -> None:
    now = time.time()
    for k in [k for k, v in _ANSWERS.items() if now - v["at"] > ANSWER_TTL]:
        _ANSWERS.pop(k, None)


def ask(text: str, user: dict, period: str | None = None) -> dict:
    ref = commands.decision_ref(text, user)

    def open_ref() -> dict:   # «самое давнее на решении», «которая 12 дней» — открыть его с «Принять / Отклонить» (замечание 13.11)
        cmd = commands.parse(text, user)
        plan = commands.build_plan(cmd, user)
        pid = commands.remember(plan, cmd, user)
        return {"kind": "command", "plan_id": pid, "command": cmd, "plan": plan, "engine": "rules", "answer": plan["title"], "needs_confirmation": False}
    if ref and ref["why"] != "номер":   # отсылка без номера — всегда к «На решение», а не к рассылке
        return open_ref()
    p = parse(text, user)
    if ref and p["kind"] != "question":   # «A-027» без вопроса — открыть; «что по обращению A-027?» — это вопрос, отвечаем
        return open_ref()
    period = p["period"] or _period(period)
    if p["kind"] == "command":
        cmd = commands.parse(text, user)
        if not cmd["intent"]:
            return _unknown(text, p)
        plan = commands.build_plan(cmd, user)
        if plan["kind"] == "send" and plan.get("empty"):   # отправлять некому — без карточки команды, просто ответ словами
            return _answer_out(user, {"kind": "answer", "answer": plan["title"], "engine": p["engine"], "parse_engine": p["engine"], "parts": []})
        pid = commands.remember(plan, cmd, user)
        return {"kind": "command", "plan_id": pid, "command": cmd, "plan": plan, "engine": p["engine"],
                "answer": plan["title"], "needs_confirmation": plan["kind"] in ("send",)}
    if p["kind"] != "question":
        return _unknown(text, p)
    parts = []
    for part in p["parts"]:
        f = facts_for(part, period)
        # составной вопрос: модели — только своя часть, иначе она отвечает и за соседние
        q_text = text if len(p["parts"]) == 1 else QUESTIONS[part["question"]] + "".join(f": {v}" for v in (part["city"], part["department"], part["number"]) if v)
        ai = ai_answer(q_text, part["question"], f)
        parts.append({"question": part["question"], "question_label": QUESTIONS[part["question"]], "answer": ai or template_answer(part["question"], f),
                      "engine": "openai" if ai else "template", "facts": f, "link": f.get("link"), "link_label": f.get("link_label"),
                      "list": part_list(part, f, period)})
    first = parts[0]
    engines = {x["engine"] for x in parts}
    return _answer_out(user, {"kind": "question", "question": first["question"],
                              "question_label": first["question_label"] if len(parts) == 1 else "Ответ на вопрос",
                              "period": period, "answer": " ".join(x["answer"] for x in parts),
                              "engine": engines.pop() if len(engines) == 1 else "mixed", "parse_engine": p["engine"],
                              "facts": first["facts"], "link": first["link"], "link_label": first["link_label"], "parts": parts})


def _answer_out(user: dict, out: dict) -> dict:
    """Ответ словами (вопрос или «отправлять некому»): id для озвучки, хранится полчаса за этим пользователем."""
    _cleanup()
    aid = secrets.token_urlsafe(10)
    _ANSWERS[aid] = {"user_id": user["id"], "text": out["answer"], "at": time.time()}
    return {**out, "id": aid, "audio": llm.available()}


def part_list(p: dict, f: dict, period: str) -> dict | None:
    """Список для просмотра ВНУТРИ /boss (замечание владельца 12.11: ссылки в панель на телефоне неудобны): номер, «Коротко» одной
    строкой, статус, ответственный; нажатие — карточка в /boss."""
    q = p["question"]
    rows = _rows()
    open_rows = [r for r in rows if r["status"] in appeals.OPEN]
    order = lambda r: (not r["overdue"], -r["age_hours"])   # noqa: E731 — просроченные и самые старые сверху
    if q == "who_overdue":
        items = [{"kind": "appeal", **_brief_item(a)} for a in sorted([r for r in open_rows if r["overdue"]], key=order)] + [{"kind": "task", **t} for t in _overdue_tasks()]
        return {"title": "Просрочено", "items": items[:30]}
    if q == "city" and p.get("city_id"):
        return {"title": f"Открытые · {p['city']}", "items": [_brief_item(a) for a in sorted([r for r in open_rows if r["branch_id"] == p["city_id"]], key=order)][:30]}
    if q == "department" and p.get("department_id"):
        return {"title": f"Открытые · {p['department']}", "items": [_brief_item(a) for a in sorted([r for r in open_rows if r["department_id"] == p["department_id"]], key=order)][:30]}
    if q == "appeal" and not f.get("not_found"):
        a = next((r for r in rows if r["number"] == p["number"]), None)
        return {"title": p["number"], "items": [_brief_item(a)]} if a else None
    if q == "my_decisions":
        return {"title": "Ждут вашего решения", "items": [{"kind": "decision", **d} for d in _decisions()]}
    if q == "whats_new":
        since = period_since(period)
        return {"title": "Пришло · " + PERIODS[period], "items": [_brief_item(a) for a in sorted([r for r in rows if r["created_at"] >= since], key=lambda r: r["created_at"], reverse=True)][:30]}
    return None


def _unknown(text: str, p: dict) -> dict:
    return {"kind": "unknown", "answer": "Не знаю, вот где посмотреть.", "engine": p["engine"], "can": EXAMPLES,
            "links": [{"href": "/panel#/summary", "label": "Сводка и карта"}, {"href": "/panel#/queue", "label": "Очередь обращений"},
                      {"href": "/panel#/decisions", "label": "На решение"}, {"href": "/panel#/meetings", "label": "Совещания и поручения"}]}


def answer_audio(aid: str, user: dict) -> tuple[bytes, str]:
    _cleanup()
    a = _ANSWERS.get(aid)
    if not a or a["user_id"] != user["id"]:
        raise HTTPException(404, "Ответ не найден или устарел — спросите ещё раз")
    return director.tts_cached(a["text"])
