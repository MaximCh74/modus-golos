"""Команды директора голосом или текстом (этап 6 §2, «Джарвис»). Голос → тот же STT (/api/stt) → текст → разбор в строгий JSON
{intent, filters, deadline, note} — LLM (mf/ai/llm.parse_command) или без ключа ключевые слова (mf/ai/fallback.parse_command).
Допустимы ровно пять intent из белого списка. Получателей и обращения считает СЕРВЕР (ИИ никого не выбирает), текст сообщения
собирается шаблоном — всегда нейтральный и вежливый, как бы ни была сформулирована команда. Экран подтверждения обязателен:
parse() только строит план и хранит его в памяти под случайным id; ничего не отправляется, пока директор не нажал [Отправить]
(execute()). open_decision лишь открывает «На решение» — решение директор принимает сам кнопкой."""
from __future__ import annotations

import re
import secrets
import time
from datetime import date, timedelta

from fastapi import HTTPException

from . import appeals, db, director, meetings
from .ai import fallback, llm, names

INTENTS = {
    "remind_overdue_tasks": "напомнить исполнителям просроченных поручений с совещаний",
    "request_progress": "попросить ответственных сообщить о ходе по обращениям «В работе»",
    "remind_no_response": "напомнить ответственным об обращениях без первого ответа или просроченных по SLA",
    "open_decision": "открыть «На решение» с выбранной идеей (принять или отклонить — только кнопкой)",
    "read_briefing": "прочитать сводку",
}
EXAMPLES = {
    "remind_overdue_tasks": "Напомни про просроченные поручения",
    "request_progress": "Запроси новости по обращениям в работе в Омске до 18:00",
    "remind_no_response": "Напомни об обращениях без ответа до пятницы",
    "open_decision": "Открой идею про регламент 1С",
    "read_briefing": "Прочитай сводку",
}
WEEKDAY_GEN = ["понедельника", "вторника", "среды", "четверга", "пятницы", "субботы", "воскресенья"]
DAT_NUM = {1: "одному", 2: "двум", 3: "трём", 4: "четырём", 5: "пяти", 6: "шести", 7: "семи", 8: "восьми", 9: "девяти", 10: "десяти"}
PLAN_TTL = 900
_PLANS: dict[str, dict] = {}


def help_lines() -> list[str]:
    return [f"{INTENTS[k]} — например: «{EXAMPLES[k]}»" for k in INTENTS]


# ---------- срок ----------

MONTH_STEMS = ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")


WORD_HOURS = {"одного": 1, "часу": 1, "двух": 2, "трех": 3, "четырех": 4, "пяти": 5, "шести": 6, "семи": 7, "восьми": 8, "девяти": 9, "десяти": 10,
              "одиннадцати": 11, "двенадцати": 12}


def parse_time(text: str) -> str | None:
    """«до 18:00», «до 18», «к 17 часам», «в 9.30», «до шести вечера», «к часу» → «18:00»; «до 18 ноября» — это дата, не время."""
    t = text.lower().replace("ё", "е")
    if "обед" in t:
        return "13:00"
    m = re.search(r"\b(?:до|к)\s+(" + "|".join(WORD_HOURS) + r")(?:\s+(часов|часа|утра|вечера|дня))?", t)
    if m:
        hour, q = WORD_HOURS[m.group(1)], m.group(2)
        if q == "вечера" or (q == "дня" and hour <= 6) or (q in (None, "часов", "часа") and hour <= 8):
            hour += 12   # рабочий день: «до шести» — 18:00, «к часу» — 13:00
        return f"{hour:02d}:00"
    if "конца дня" in t or "концу дня" in t or "вечера" in t:
        return "18:00"
    for m in re.finditer(r"\b(?:до|к|в)\s+(\d{1,2})(?:[:.](\d{2}))?\s*(час(?:ов|а|у)?|ч\b)?", t):
        hour, minute, word = int(m.group(1)), m.group(2), m.group(3)
        tail = t[m.end():].lstrip()
        if not minute and not word and any(tail.startswith(s) for s in MONTH_STEMS):
            continue   # «до 18 ноября»
        if 0 <= hour <= 23 and (minute or word or hour >= 7):
            return f"{hour:02d}:{minute or '00'}"
    return None


def deadline_info(text: str | None, base: date | None = None) -> dict | None:
    """«сегодня», «до пятницы», «до 18:00», «завтра к обеду» → {text, date, time, label} с человеческой подписью для сообщения."""
    if not text or not str(text).strip():
        return None
    base = base or db.now().date()
    t = str(text).lower().replace("ё", "е")
    d = meetings.parse_due(t, base)
    tm = parse_time(t)
    if d is None and tm:
        d = base.isoformat()
    if d is None:
        return {"text": text, "date": None, "time": tm, "label": None}
    dd = date.fromisoformat(d)
    weekday_said = any(s in t for s, _ in meetings.WEEKDAYS)
    if weekday_said:   # как сказал директор: «до пятницы (13.11)», даже если пятница — завтра
        label = "до " + WEEKDAY_GEN[dd.weekday()] + f" ({dd.strftime('%d.%m')})"
    elif dd == base:
        label = "сегодня"
    elif dd == base + timedelta(days=1):
        label = "завтра"
    else:
        label = "до " + dd.strftime("%d.%m")
    if tm:
        label += f" до {tm}" if dd == base or dd == base + timedelta(days=1) else f" {tm}"
    return {"text": text, "date": d, "time": tm, "label": label}


# ---------- разбор ----------

def _context() -> dict:
    return {"cities": [{"id": b["id"], "city": b["city"], "name": b["name"]} for b in db.q("SELECT id, city, name FROM branches WHERE kind != 'field' ORDER BY is_hq DESC, name")],
            "departments": db.q("SELECT id, name FROM departments ORDER BY id"),
            "people": db.q("SELECT id, name, role, branch_id, department_id FROM users WHERE active=1 ORDER BY id")}


def _stem(s: str) -> str:
    return (s or "").lower().replace("ё", "е")[:5]


def _resolve(raw: dict, ctx: dict, user: dict) -> dict:
    f = raw.get("filters") or {}
    out = {"branch_id": None, "branch": None, "department_id": None, "department": None, "person_id": None, "person": None,
           "stale_only": bool(f.get("stale_only")), "overdue_only": bool(f.get("overdue_only"))}
    if f.get("city"):
        st = _stem(f["city"])
        b = next((x for x in ctx["cities"] if _stem(x["city"]) == st or _stem(x["name"]) == st), None)
        if b:
            out["branch_id"], out["branch"] = b["id"], b["city"]
    if f.get("department"):
        st = _stem(f["department"])
        d = next((x for x in ctx["departments"] if _stem(x["name"]) == st), None)
        if d:
            out["department_id"], out["department"] = d["id"], d["name"]
    if f.get("person"):
        m = names.match(str(f["person"]), [p for p in ctx["people"] if p["id"] != user["id"]])
        if m["user"]:
            out["person_id"], out["person"] = m["user"]["id"], m["user"]["name"]
    return out


# ---------- отсылки к «На решение»: «самое давнее», «которая 12 дней», «первая», «A-027» (замечание владельца 13.11) ----------
# После сводки директор говорит «самая дальняя, которая 12 дней…» — это про самое давнее обращение на решении, а не про рассылку.
# Распознаём до ИИ: уверенно → открыть его с «Принять / Отклонить»; неуверенно → короткий вопрос «Вы про A-027 (ждёт решения 12 дней)?».
REF_OLDEST = re.compile(r"сам(?:ое|ая|ый|ую|ой)\s+(?:давн|стар|дальн|долг|перв|ранн)|\bдавн(?:ее|яя|ий|юю|ей)\b|\bстар(?:ое|ая|ейш)|\bдальн(?:ее|яя|юю)\b|\bперв(?:ое|ая|ую|ый|ой)\b", re.I)
REF_WORDS = re.compile(r"\bкотор|\bжд[её]т|\bвиси|\bлежи|на\s+решени|\b(?:та|ту|эта|эту|тот|той)\b", re.I)
REF_POINT = re.compile(r"\bкотор|\b(?:та|ту|эта|эту|тот|той)\b", re.I)   # указание на конкретное — для «неясной» отсылки
ACTION = re.compile(r"\b(?:напомн|запрос|попрос|разошл|отправ|сообщ|прочита|прочти)", re.I)
APPEAL_NUM = re.compile(r"\b[aа]\s*-?\s*0*(\d{1,4})\b", re.I)
DAYS = re.compile(r"(\d{1,3})\s*(?:-?\s*)?(?:дн|день|дня|дней|сут)", re.I)
NUM_WORDS = {"один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
             "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
             "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20, "тридцать": 30}


def _days_in(text: str) -> int | None:
    m = DAYS.search(text)
    if m:
        return int(m.group(1))
    words = re.findall(r"[а-яё]+", text.lower())
    for i, w in enumerate(words):
        if w.startswith(("дн", "день", "дня", "дней", "сут")) and i:
            n = NUM_WORDS.get(words[i - 1])
            if n and i > 1 and words[i - 2] in ("двадцать", "тридцать") and n < 10:
                n += NUM_WORDS[words[i - 2]]
            if n:
                return n
    return None


def decision_ref(text: str, user: dict) -> dict | None:
    """Отсылка к обращению на решении → {"item": pending, "sure": bool, "why": str} или None (обычная команда)."""
    t = " ".join((text or "").split())
    if not t:
        return None
    pending = meetings.director_ideas(user)["pending"]
    if not pending:
        return None
    m = APPEAL_NUM.search(t)
    if m:
        num = f"A-{int(m.group(1)):03d}"
        it = next((p for p in pending if p.get("number") == num), None)
        if it:
            return {"item": it, "sure": True, "why": "номер"}
    if ACTION.search(t):   # «напомни…», «запроси…» — это другие команды, отсылкой не считаем
        return None
    oldest = pending[0]   # список отсортирован: дольше всех ждёт — первым
    days = _days_in(t)
    if days is not None and (REF_WORDS.search(t) or REF_OLDEST.search(t)):
        exact = [p for p in pending if p.get("wait_days") is not None and int(p["wait_days"]) == days]
        if len(exact) == 1:
            return {"item": exact[0], "sure": True, "why": "дни"}
        near = min(pending, key=lambda p: abs((p.get("wait_days") or 0) - days))
        return {"item": near, "sure": False, "why": "дни примерно"}
    if REF_OLDEST.search(t):
        return {"item": oldest, "sure": True, "why": "самое давнее"}
    if REF_POINT.search(t) and re.search(r"решени|давн|ждёт|ждет", t, re.I):   # «а та, что ждёт решения?» — переспросить
        return {"item": oldest, "sure": False, "why": "неясно"}
    return None


def parse(text: str, user: dict) -> dict:
    text = " ".join((text or "").split())
    if len(text) < 2:
        raise HTTPException(422, "Скажите или напишите команду")
    ref = decision_ref(text, user)
    if ref:
        it = ref["item"]
        return {"text": text, "intent": "open_decision", "filters": _resolve({}, {"cities": [], "departments": [], "people": []}, user), "deadline": None,
                "note": None, "idea": None, "engine": "rules", "ref": {"source": it.get("source"), "id": it.get("id"), "appeal_id": it.get("appeal_id"),
                                                                       "number": it.get("number"), "sure": ref["sure"], "why": ref["why"]}}
    ctx = _context()
    raw, engine = None, "keywords"
    if llm.available():
        try:
            raw = llm.parse_command(text, ctx)
            engine = "openai"
        except llm.LLMError as e:   # ключ есть, но ответ невалиден → ключевые слова
            raw = None
            engine = f"keywords (LLM: {str(e)[:60]})"
    if raw is None:
        raw = fallback.parse_command(text, ctx)
    intent = raw.get("intent") if raw.get("intent") in INTENTS else None
    return {"text": text, "intent": intent, "filters": _resolve(raw, ctx, user), "deadline": deadline_info(raw.get("deadline_text")),
            "note": (raw.get("note") or "").strip() or None, "idea": (raw.get("idea") or "").strip() or None, "engine": engine}


# ---------- план (получателей считает сервер) ----------

def _dat(n: int, one: str, many: str) -> str:
    return f"{DAT_NUM.get(n, str(n))} {one if n == 1 else many}"


def _nums(numbers: list[str]) -> str:
    if len(numbers) == 1:
        return numbers[0]
    return ", ".join(numbers[:-1]) + " и " + numbers[-1]


def _fits(f: dict, branch_id, department_id, user_id) -> bool:
    if f["branch_id"] and branch_id != f["branch_id"]:
        return False
    if f["department_id"] and department_id != f["department_id"]:
        return False
    if f["person_id"] and user_id != f["person_id"]:
        return False
    return True


def _first(user: dict) -> str:
    """От чьего имени сообщение: директор — по имени и отчеству («Сергей Михайлович просит…»), остальные — по имени."""
    from . import auth
    return auth.display_name(user)


def _message(intent: str, user: dict, items: list[dict], deadline: dict | None, note: str | None) -> str:
    who = _first(user)
    dl = f" {deadline['label']}" if deadline and deadline.get("label") else ""
    if intent == "request_progress":
        nums = [i["number"] for i in items]
        msg = f"{who} просит{dl} сообщить о ходе работ по {'обращению' if len(nums) == 1 else 'обращениям'} {_nums(nums)}"
    elif intent == "remind_no_response":
        nums = [i["number"] for i in items]
        msg = f"{who} просит{dl} дать первый ответ автору по {'обращению' if len(nums) == 1 else 'обращениям'} {_nums(nums)}"
        if any(i.get("overdue") for i in items):
            msg += " — срок первого ответа по SLA прошёл"
    else:
        parts = [f"«{appeals.short(i['title'], 70)}» (срок был {i['due_label']})" for i in items]
        msg = f"{who} просит{dl} сообщить о статусе {'поручения' if len(items) == 1 else 'поручений'} с совещаний: " + "; ".join(parts)
    msg += "."
    if note:
        msg += f" Пояснение: {appeals.short(note, 160)}"
    return msg


def _recipient(recipients: dict, u: dict) -> dict:
    return recipients.setdefault(u["id"], {"user_id": u["id"], "name": u["name"], "position": u.get("position"), "branch": u.get("branch"), "items": []})


def _users_map() -> dict:
    return {u["id"]: u for u in db.q("SELECT u.id, u.name, u.position, u.branch_id, u.department_id, b.city AS branch FROM users u LEFT JOIN branches b ON b.id=u.branch_id WHERE u.active=1")}


def build_plan(cmd: dict, user: dict) -> dict:
    intent = cmd["intent"]
    if not intent:
        return {"kind": "unknown", "title": "Не понял команду. Могу:", "help": help_lines(), "examples": list(EXAMPLES.values())}
    if intent == "read_briefing":
        d = director.summary(user)
        return {"kind": "briefing", "intent": intent, "title": "Прочитать сводку", "sentences": d["sentences"], "engine": d["engine"],
                "message": " ".join(s["text"] for s in d["sentences"])}
    if intent == "open_decision":
        return _plan_open_decision(cmd, user)
    f = cmd["filters"]
    users = _users_map()
    recipients: dict[int, dict] = {}
    today = db.now().date().isoformat()
    if intent == "request_progress":
        th = appeals.news_days_setting()
        for a in db.q(appeals.BASE_SELECT + " WHERE a.status='in_progress' AND a.responsible_id IS NOT NULL ORDER BY a.id"):
            u = users.get(a["responsible_id"])
            if not u or u["id"] == user["id"] or not _fits(f, a["branch_id"], a["department_id"] or u["department_id"], u["id"]):
                continue
            age = appeals.news_age_days(a) or 0
            if f["stale_only"] and age < th:
                continue
            _recipient(recipients, u)["items"].append({"kind": "appeal", "id": a["id"], "number": a["number"], "title": appeals.line(a, 80), "news_days": int(age)})
    elif intent == "remind_no_response":
        admins = appeals.admins()
        for a in db.q(appeals.BASE_SELECT + " WHERE a.status IN ('new','review','clarify') AND a.first_response_at IS NULL ORDER BY a.id"):
            a = appeals.decorate(a)
            if f["overdue_only"] and not a["overdue"]:
                continue
            targets = [a["responsible_id"]] if a["responsible_id"] else admins
            for uid in targets:
                u = users.get(uid)
                if not u or uid == user["id"] or not _fits(f, a["branch_id"], a["department_id"] or u["department_id"], uid):
                    continue
                _recipient(recipients, u)["items"].append({"kind": "appeal", "id": a["id"], "number": a["number"], "title": appeals.line(a, 80), "overdue": a["overdue"],
                                                           "age_hours": a["age_hours"]})
    elif intent == "remind_overdue_tasks":
        rows = db.q("""SELECT i.*, m.title AS meeting_title FROM meeting_items i JOIN meetings m ON m.id=i.meeting_id
                       WHERE i.kind='task' AND i.removed=0 AND m.status='sent' AND i.assignee_id IS NOT NULL AND i.due_date IS NOT NULL AND i.due_date < ?
                       AND i.task_status IN ('assigned','in_progress') ORDER BY i.due_date""", (today,))
        for t in rows:
            u = users.get(t["assignee_id"])
            if not u or u["id"] == user["id"] or not _fits(f, u["branch_id"], u["department_id"], u["id"]):
                continue
            y, m, d = t["due_date"].split("-")
            _recipient(recipients, u)["items"].append({"kind": "task", "id": t["id"], "meeting_id": t["meeting_id"], "number": None, "title": t["text"],
                                                       "meeting": t["meeting_title"], "due": t["due_date"], "due_label": f"{d}.{m}"})
    recs = list(recipients.values())
    for r in recs:
        r["message"] = _message(intent, user, r["items"], cmd["deadline"], cmd["note"])
    n_users = len(recs)
    n_items = sum(len(r["items"]) for r in recs)
    is_tasks = intent == "remind_overdue_tasks"
    what = "запрос новостей" if intent == "request_progress" else "напоминание"
    if not recs:   # замечание владельца 12.11: без служебного «Некому отправлять» — просто словами, что напоминать не о чем
        where = ", ".join(x for x in (f["branch"] and "в городе " + f["branch"], f["department"] and "в отделе «" + f["department"] + "»", f["person"] and "у " + f["person"]) if x)
        where = (" " + where) if where else ""
        title = ("Напоминать не о чем: просроченных поручений с совещаний" + where + " нет." if is_tasks
                 else "Напоминать не о чем: обращений без первого ответа" + where + " нет." if intent == "remind_no_response"
                 else "Запрашивать новости не о чем: обращений «В работе»" + where + (" без новостей дольше порога" if f["stale_only"] else "") + " нет.")
    else:
        title = f"Отправить {what} {_dat(n_users, 'сотруднику', 'сотрудникам')} по {_dat(n_items, 'поручению' if is_tasks else 'обращению', 'поручениям' if is_tasks else 'обращениям')}"
    scope = ", ".join(x for x in (f["branch"], f["department"], f["person"], "без новостей дольше порога" if f["stale_only"] else None, "только просроченные по SLA" if f["overdue_only"] else None) if x)
    return {"kind": "send", "intent": intent, "title": title, "recipients": recs, "counts": {"users": n_users, "appeals": 0 if is_tasks else n_items, "tasks": n_items if is_tasks else 0},
            "deadline": cmd["deadline"], "note": cmd["note"], "scope": scope or "все", "empty": not recs}


STOP = {"прими", "примите", "принять", "открой", "открыть", "идею", "идея", "идеи", "про", "по", "на", "решение", "решения", "с", "и", "в", "о", "об", "покажи",
        "отклони", "предложение", "предложения", "давай", "мне", "нужно", "хочу"}


def _wait_label(it: dict) -> str:
    w = it.get("wait_days")
    if w is None:
        return "ждёт решения"
    d = int(w)
    return "ждёт решения " + ("меньше дня" if d < 1 else director._plural(d, ("день", "дня", "дней")))


def _plan_open_decision(cmd: dict, user: dict) -> dict:
    q = meetings.director_ideas(user)
    pending = q["pending"]
    ref = cmd.get("ref")
    if ref:   # отсылка распознана правилами: само обращение (или идея) с «Принять / Отклонить» прямо в ответе
        it = next((p for p in pending if (ref.get("appeal_id") and p.get("appeal_id") == ref["appeal_id"]) or (not ref.get("appeal_id") and p.get("id") == ref.get("id"))), None)
        if it:
            name = it.get("number") or "идея с совещания"
            item = {"source": it["source"], "id": it.get("id"), "appeal_id": it.get("appeal_id"), "number": it.get("number"),
                    "text": appeals.short(it["text"], 120), "wait_days": it.get("wait_days")}
            if not ref.get("sure"):
                return {"kind": "clarify", "intent": "open_decision", "title": f"Вы про {name} ({_wait_label(it)})? Открыть?", "item": item,
                        "decision": it, "href": "#/decisions", "pending": len(pending), "empty": False, "message": None}
            return {"kind": "open", "intent": "open_decision", "title": f"{name} — {_wait_label(it)}", "item": item, "decision": it,
                    "href": "#/decisions", "pending": len(pending), "empty": False, "message": None}
    words = [w for w in re.findall(r"[a-zа-яё0-9-]+", (cmd["idea"] or cmd["text"]).lower().replace("ё", "е")) if w not in STOP and len(w) > 2]
    best, best_score = None, 0
    for it in pending:
        txt = (it.get("text") or "").lower().replace("ё", "е") + " " + (it.get("number") or "").lower()
        score = sum(1 for w in words if w[:5] in txt)
        if it.get("number") and it["number"].lower() in (cmd["text"] or "").lower():
            score += 10
        if score > best_score:
            best, best_score = it, score
    item = None
    if best:
        item = {"source": best["source"], "id": best.get("id"), "appeal_id": best.get("appeal_id"), "number": best.get("number"),
                "text": appeals.short(best["text"], 120), "wait_days": best.get("wait_days")}
    title = "Открыть «На решение»" + (f": «{item['text']}»" if item else " — идея по описанию не найдена, покажу весь список")
    return {"kind": "open", "intent": "open_decision", "title": title, "item": item, "href": "#/decisions", "pending": len(pending), "empty": False,
            "message": None}


# ---------- хранение плана и выполнение после подтверждения ----------

def _cleanup() -> None:
    now = time.time()
    for k in [k for k, v in _PLANS.items() if now - v["at"] > PLAN_TTL]:
        _PLANS.pop(k, None)


def remember(plan: dict, cmd: dict, user: dict) -> str:
    _cleanup()
    pid = secrets.token_urlsafe(12)
    _PLANS[pid] = {"plan": plan, "cmd": cmd, "user_id": user["id"], "at": time.time(), "sent": None}
    return pid


def get_plan(pid: str, user: dict) -> dict:
    _cleanup()
    p = _PLANS.get(pid)
    if not p or p["user_id"] != user["id"]:
        raise HTTPException(404, "План команды не найден или устарел — повторите команду")
    return p


def execute(pid: str, user: dict, messages: dict | None = None) -> dict:
    """Только после [Отправить]: уведомления получателям (и в Битрикс24 через appeals.notify), событие в истории каждого обращения,
    короткий ответ для озвучки. Повторная отправка того же плана запрещена."""
    p = get_plan(pid, user)
    if p["sent"]:
        raise HTTPException(409, "Эта команда уже отправлена")
    plan = p["plan"]
    kind = plan["kind"]
    if kind == "unknown":
        raise HTTPException(422, "Команда не распознана — отправлять нечего")
    if kind == "briefing":
        p["sent"] = {"reply": plan["message"], "users": 0, "items": 0}
        return {"ok": True, "kind": kind, **p["sent"]}
    if kind in ("open", "clarify"):
        p["sent"] = {"reply": "Открываю «На решение»." if not plan["item"] else f"Открываю «На решение»: {plan['item']['text']}", "users": 0, "items": 0, "href": plan["href"], "item": plan["item"]}
        return {"ok": True, "kind": kind, **p["sent"]}
    if plan.get("empty"):
        raise HTTPException(422, plan["title"])
    messages = {int(k): v for k, v in (messages or {}).items() if str(k).isdigit()}
    sent_users = sent_appeals = sent_tasks = 0
    intent = plan["intent"]
    label = (plan.get("deadline") or {}).get("label")
    for r in plan["recipients"]:
        msg = " ".join((messages.get(r["user_id"]) or r["message"]).split())[:600]
        if not msg:
            continue
        app_items = [i for i in r["items"] if i["kind"] == "appeal"]
        link = f"/panel#/appeal/{app_items[0]['id']}" if len(app_items) == 1 else "/panel#/queue?status=in_progress" if intent == "request_progress" else "/panel#/queue?open=1" if app_items else "/app#/tasks"
        appeals.notify(r["user_id"], msg, link)
        sent_users += 1
        for i in r["items"]:
            if i["kind"] == "appeal":
                appeals.add_event(i["id"], user["id"], "director_requested_news", {"text": msg, "deadline": label, "intent": intent, "to": r["user_id"]})
                sent_appeals += 1
            else:
                db.ex("UPDATE meeting_items SET reminded_at=? WHERE id=?", (db.now_iso(), i["id"]))
                sent_tasks += 1
    if intent == "request_progress":
        reply = f"Отправил запрос новостей {_dat(sent_users, 'сотруднику', 'сотрудникам')} по {_dat(sent_appeals, 'обращению', 'обращениям')}."
    elif intent == "remind_no_response":
        reply = f"Отправил напоминания {_dat(sent_users, 'сотруднику', 'сотрудникам')} по {_dat(sent_appeals, 'обращению', 'обращениям')}."
    else:
        reply = f"Отправил напоминания {_dat(sent_users, 'сотруднику', 'сотрудникам')} по {_dat(sent_tasks, 'поручению', 'поручениям')}."
    p["sent"] = {"reply": reply, "users": sent_users, "items": sent_appeals + sent_tasks, "appeals": sent_appeals, "tasks": sent_tasks, "at": db.now_iso()}
    return {"ok": True, "kind": kind, **p["sent"]}
