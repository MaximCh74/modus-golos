"""Обращения: создание и маршрутизация, статусы и журнал, уточнения, поддержка «У меня так же», баллы, просрочка.
Правила — docs/TZ_v1.1.md, раздел 5."""
from __future__ import annotations

import json
import math
import secrets
from datetime import timedelta

from fastapi import HTTPException

from . import db, realtime
from .integrations import bitrix

STATUSES = {
    "new": "Новое", "review": "На рассмотрении", "clarify": "Ожидает уточнения", "in_progress": "В работе",
    "done": "Реализовано", "closed": "Закрыто", "rejected": "Отклонено",
}
# На экране — пять статусов (решение владельца 13.11): внутренние коды и STATUSES не меняются, только отображение. Таблица — CONCEPT.md.
STATUS_DISPLAY = {"new": "Новое", "review": "В работе", "in_progress": "В работе", "clarify": "Уточнение", "done": "Решено", "closed": "Решено",
                  "rejected": "Отклонено"}
# пункты меню смены статуса у ответственного: два «В работе» различаются уточнением
NEXT_LABELS = {"review": "В работе: рассматриваем", "in_progress": "В работе: выполняем", "clarify": "Уточнение у автора", "done": "Решено: реализовано",
               "closed": "Решено: закрыть", "rejected": "Отклонено"}
# Новое → На рассмотрении ⇄ Ожидает уточнения → В работе → Реализовано → Закрыто; «Отклонено» — из любого незакрытого
TRANSITIONS = {
    "new": ("review", "rejected"),
    "review": ("clarify", "in_progress", "rejected"),
    "clarify": ("review", "rejected"),
    "in_progress": ("done", "rejected"),
    "done": ("closed",),
    "closed": (),
    "rejected": (),
}
OPEN = ("new", "review", "clarify", "in_progress")
TYPES = {"problem": "Проблема", "suggestion": "Предложение", "praise": "Положительный отзыв"}
PRIORITIES = {"low": "Низкий", "medium": "Средний", "high": "Высокий"}
SOURCES = ("qr", "app", "voice", "meeting")
STAFF = ("responsible", "director", "admin")
DEFAULT_POINTS = {"accepted": 10, "done": 50, "support": 2, "support_cap": 20}
POINT_REASONS = {"accepted": "принято к рассмотрению", "done": "реализовано", "support": "«У меня так же» от коллеги"}
DEFAULT_SLA = 48
PUBLIC_EVENT_KINDS = ("praise_addressed",) + ("created", "assigned", "status_changed", "comment", "clarification_requested",
                      "clarification_answered", "discussed_at_meeting", "supported", "director_requested", "director_decided", "progress", "thanked", "priority_changed",
                      "director_requested_news")
DIRECTOR_DECISIONS = {"pending": "На решении", "accepted": "Принято", "rejected": "Отклонено"}
# Оценка автора (этап 4): один необязательный вопрос вместо «выберите приоритет» — итоговый приоритет ставит система с ответственным
URGENCY = {"now": "Прямо сейчас мешает", "workaround": "Мешает, но обхожусь", "minor": "Мелочь"}
SCOPE = {"me": "Меня", "department": "Мой отдел", "company": "Всю компанию"}
MATRIX = {("now", "me"): "medium", ("now", "department"): "high", ("now", "company"): "high",
          ("workaround", "me"): "low", ("workaround", "department"): "medium", ("workaround", "company"): "high",
          ("minor", "me"): "low", ("minor", "department"): "low", ("minor", "company"): "medium"}
PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}
# Стадии для автора — словами собственника (внутренние статусы не меняются)
STAGES = [("accepted", "Принято"), ("elaboration", "Проработка"), ("decision", "Принятие решения"), ("implementation", "Реализация"), ("done", "Готово")]


def matrix_priority(type: str, urgency: str | None, scope: str | None) -> str | None:
    """Без ключа: матрица из ответа автора. Для проблемы масштаб по умолчанию «мой отдел», для идеи срочность — «мешает, но обхожусь»."""
    if not urgency and not scope:
        return None
    urgency = urgency if urgency in URGENCY else ("workaround" if type == "suggestion" else None)
    scope = scope if scope in SCOPE else ("department" if type == "problem" else None)
    if not urgency or not scope:
        return None
    return MATRIX[(urgency, scope)]


def bump(priority: str) -> str:
    return {"low": "medium", "medium": "high"}.get(priority, "high")


def brief_of(a: dict) -> dict | None:
    try:
        return json.loads(a["brief"]) if a.get("brief") else None
    except (TypeError, ValueError):
        return None


def line(a: dict, n: int = 90) -> str:
    """Одна строка про обращение: первая строка «Коротко», если есть, иначе начало текста (ТЗ этапа 4 §3.2)."""
    b = brief_of(a)
    if b and b.get("gist") and not b.get("unclear"):
        return short(b["gist"], n)
    return short(a["text"], n)


def stage_for(a: dict) -> dict:
    """Трекер для автора стадиями собственника: Принято → Проработка → Принятие решения → Реализация → Готово; «Не принято» — отдельный финал."""
    st = a["status"]
    rejected = st == "rejected"
    if st == "new":
        idx = 0
    elif st in ("review", "clarify"):
        idx = 2 if a.get("director_decision") == "pending" else 1
    elif st == "in_progress":
        idx = 3
    elif st in ("done", "closed"):
        idx = 4
    else:
        idx = 4
    steps = []
    for i, (code, label) in enumerate(STAGES):
        state = "done" if i < idx else "cur" if i == idx else "future"
        if code == "decision" and i < idx and a.get("director_decision") != "accepted":
            state = "skip"   # в работу без директора — стадия отмечена пройденной автоматически
        if rejected and i == 4:
            label, state = "Не принято", "cur"
        if rejected and i < 4 and i >= idx:
            state = "future"
        steps.append({"code": code, "label": label, "state": state})
    cur = steps[idx]
    note = None
    if st == "clarify":
        note = "нужно ваше уточнение"
    elif a.get("director_decision") == "pending":
        note = "ждёт решения директора"
    elif rejected:
        note = "с причиной — см. ниже"
    return {"code": "rejected" if rejected else cur["code"], "label": cur["label"], "index": idx, "steps": steps, "note": note}

# филиал на экране — город (db.BRANCH_LABEL); у обращения с объекта — «объект · Атырау» (13.11)
BRANCH_LABEL = db.BRANCH_LABEL
BASE_SELECT = """SELECT a.*, c.name AS category, c.sla_first_response_hours AS sla,
  CASE WHEN b.kind='field' THEN 'объект' || COALESCE(' · ' || NULLIF(a.site_city, ''), '') ELSE COALESCE(NULLIF(b.city, ''), b.name) END AS branch,
  b.name AS branch_name, b.code AS branch_code, b.city AS branch_city, d.name AS department,
  u.name AS responsible, u.position AS responsible_position,
  (SELECT COUNT(*) FROM supports s WHERE s.appeal_id = a.id) AS supports
  FROM appeals a
  LEFT JOIN categories c ON c.id = a.category_id
  LEFT JOIN branches b ON b.id = a.branch_id
  LEFT JOIN departments d ON d.id = a.department_id
  LEFT JOIN users u ON u.id = a.responsible_id"""


def points_cfg() -> dict:
    return {**DEFAULT_POINTS, **(db.setting("points", {}) or {})}


def short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


# ---------- чтение ----------

def get(appeal_id: int) -> dict:
    row = db.one(BASE_SELECT + " WHERE a.id=?", (appeal_id,))
    if not row:
        raise HTTPException(404, "Обращение не найдено")
    return decorate(row)


def by_token(token: str) -> dict:
    row = db.one(BASE_SELECT + " WHERE a.tracking_token=?", (token,))
    if not row:
        raise HTTPException(404, "Ссылка недействительна")
    return decorate(row)


def author_id(appeal_id: int) -> int | None:
    row = db.one("SELECT user_id FROM appeal_authors WHERE appeal_id=?", (appeal_id,))
    return row["user_id"] if row else None


def is_overdue(a: dict) -> bool:
    if a["first_response_at"] or a["status"] not in OPEN:
        return False
    created = db.parse(a["created_at"])
    return created + timedelta(hours=a.get("sla") or DEFAULT_SLA) < db.now()


def city_of(a: dict) -> str | None:
    """Филиал на экране — только город («Омск», без «головной офис»; замечания владельца 13.11); объект командировки — его город."""
    return a.get("site_city") or a.get("branch_city") or a.get("branch")


def overdue_days(a: dict) -> int | None:
    """На сколько дней просрочен первый ответ (замечание владельца 13.11: «просрочено на N дн»): неполный день — как день."""
    if not is_overdue(a):
        return None
    due = db.parse(a["created_at"]) + timedelta(hours=a.get("sla") or DEFAULT_SLA)
    return max(1, math.ceil((db.now() - due).total_seconds() / 86400))


def decorate(a: dict) -> dict:
    """Производные поля для списков и карточки."""
    created = db.parse(a["created_at"])
    a["age_hours"] = round((db.now() - created).total_seconds() / 3600, 1)
    a["overdue"] = is_overdue(a)
    a["overdue_days"] = overdue_days(a)
    a["unassigned"] = a["responsible_id"] is None and a["status"] in OPEN
    a["status_label"] = STATUS_DISPLAY.get(a["status"], a["status"])   # на экране — пять статусов
    a["type_label"] = TYPES.get(a["type"], a["type"])
    a["priority_label"] = PRIORITIES.get(a["priority"], a["priority"])
    fr = db.parse(a["first_response_at"])
    a["first_response_hours"] = round((fr - created).total_seconds() / 3600, 1) if fr else None
    return a


def events_of(appeal_id: int) -> list[dict]:
    rows = db.q("""SELECT e.id, e.kind, e.payload, e.created_at, e.actor_id, u.name AS actor, u.position AS actor_position
                   FROM appeal_events e LEFT JOIN users u ON u.id = e.actor_id WHERE e.appeal_id=? ORDER BY e.id""", (appeal_id,))
    for r in rows:
        r["payload"] = json.loads(r["payload"] or "{}")
    return rows


def attachments_of(appeal_id: int) -> list[dict]:
    return db.q("SELECT id, filename, mime, size, created_at FROM attachments WHERE appeal_id=? ORDER BY id", (appeal_id,))


# ---------- журнал, уведомления, баллы ----------

def add_event(appeal_id: int, actor_id: int | None, kind: str, payload: dict | None = None) -> int:
    ts = db.now_iso()
    eid = db.ex("INSERT INTO appeal_events(appeal_id, actor_id, kind, payload, created_at) VALUES(?,?,?,?,?)",
                (appeal_id, actor_id, kind, json.dumps(payload or {}, ensure_ascii=False), ts))
    db.ex("UPDATE appeals SET updated_at=? WHERE id=?", (ts, appeal_id))
    return eid


def touch_news(appeal_id: int) -> None:
    """Автор увидел новость (статус, комментарий, ход работы, уточнение) — от этого считается «последняя новость автору»."""
    db.ex("UPDATE appeals SET last_news_at=? WHERE id=?", (db.now_iso(), appeal_id))


def notify(user_id: int | None, text: str, link: str | None = None) -> None:
    if not user_id:
        return
    nid = db.ex("INSERT INTO notifications(user_id, text, link, created_at) VALUES(?,?,?,?)", (user_id, text, link, db.now_iso()))
    realtime.publish(user_id, {"type": "notification", "id": nid, "text": text, "link": link})
    try:
        bitrix.notify(user_id, text, link)   # дубль в чат Битрикс24, если интеграция настроена и сотрудник сопоставлен (этап 6 §1)
    except Exception:   # noqa: BLE001
        pass


def admins() -> list[int]:
    return [u["id"] for u in db.q("SELECT id FROM users WHERE role='admin' AND active=1")]


def award(a: dict, reason: str) -> int:
    """Баллы автору. Не за отправку, не за отклонённые, не за отзывы, не анонимным; accepted/done — один раз на обращение;
    support — по +2 до потолка на обращение. Каждое начисление — запись в журнал, событие и уведомление."""
    if a["is_anonymous"] or a["type"] == "praise":
        return 0
    uid = author_id(a["id"])
    if not uid:
        return 0
    cfg = points_cfg()
    if reason in ("accepted", "done"):
        if db.one("SELECT 1 FROM points_ledger WHERE appeal_id=? AND reason=?", (a["id"], reason)):
            return 0
        amount = int(cfg[reason])
    elif reason == "support":
        row = db.one("SELECT COALESCE(SUM(amount),0) AS s FROM points_ledger WHERE appeal_id=? AND reason='support'", (a["id"],))
        amount = min(int(cfg["support"]), int(cfg["support_cap"]) - int(row["s"]))
    else:
        raise ValueError(reason)
    if amount <= 0:
        return 0
    db.ex("INSERT INTO points_ledger(user_id, appeal_id, reason, amount, created_at) VALUES(?,?,?,?,?)",
          (uid, a["id"], reason, amount, db.now_iso()))
    add_event(a["id"], None, "points_awarded", {"user_id": uid, "amount": amount, "reason": reason})
    notify(uid, f"+{amount} баллов за {a['number']}: {POINT_REASONS[reason]}", "/app#/points")
    realtime.publish(uid, {"type": "points", "amount": amount, "appeal_id": a["id"]})
    return amount


def balance(user_id: int) -> int:
    row = db.one("SELECT COALESCE(SUM(amount),0) AS s FROM points_ledger WHERE user_id=?", (user_id,))
    return int(row["s"])


# ---------- создание и маршрутизация ----------

def next_number() -> str:
    row = db.one("SELECT number FROM appeals ORDER BY id DESC LIMIT 1")
    n = int(row["number"].split("-")[1]) + 1 if row else 1
    return f"A-{n:03d}"


def dev_head() -> dict | None:
    """Руководитель отдела развития (ТЗ v2 §2.1): предложения по умолчанию идут ему, если у категории не задан свой ответственный."""
    uid = db.setting("dev_department_head_id")
    u = db.one("SELECT * FROM users WHERE id=? AND active=1", (uid,)) if uid else None
    if not u:
        u = db.one("SELECT u.* FROM users u JOIN departments d ON d.id=u.department_id WHERE d.name='Отдел развития' AND u.role='responsible' AND u.active=1 ORDER BY u.id LIMIT 1")
    return u


def route(a: dict, actor_id: int | None = None, by_category: bool = False) -> dict | None:
    """Проблемы — ответственному категории. Предложения (ТЗ v2 по кастдеву) — ответственному за предложения в категории,
    иначе руководителю отдела развития; by_category=True (идея принята директором) — как проблемы.
    Нет ответственного или он неактивен — очередь администратора с меткой «Без ответственного».
    Руководителю автора — уведомление-копия о предложении."""
    resp = None
    cat = db.one("SELECT * FROM categories WHERE id=?", (a["category_id"],)) if a["category_id"] else None
    if a["type"] == "suggestion" and not by_category:
        if cat and cat["suggestion_responsible_user_id"]:
            resp = db.one("SELECT * FROM users WHERE id=? AND active=1", (cat["suggestion_responsible_user_id"],))
        resp = resp or dev_head()
    if not resp and cat and cat["responsible_user_id"]:
        resp = db.one("SELECT * FROM users WHERE id=? AND active=1", (cat["responsible_user_id"],))
    if a["type"] == "suggestion" and not a["is_anonymous"]:
        author = db.one("SELECT * FROM users WHERE id=?", (author_id(a["id"]),)) if author_id(a["id"]) else None
        if author and author["manager_id"] and author["manager_id"] not in (resp["id"] if resp else None,):
            notify(author["manager_id"], f"Ваш сотрудник {author['name']} подал предложение {a['number']}: {short(a['text'])}", f"/panel#/appeal/{a['id']}")
    if resp:
        db.ex("UPDATE appeals SET responsible_id=? WHERE id=?", (resp["id"], a["id"]))
        add_event(a["id"], actor_id, "assigned", {"responsible_id": resp["id"], "responsible": resp["name"], "auto": actor_id is None})
        notify(resp["id"], f"Новое обращение {a['number']}: {line(a)}", f"/panel#/appeal/{a['id']}")
    else:
        db.ex("UPDATE appeals SET responsible_id=NULL WHERE id=?", (a["id"],))
        add_event(a["id"], actor_id, "assigned", {"responsible_id": None, "auto": True, "reason": "no_responsible"})
        why = f"у категории «{cat['name']}» нет ответственного" if cat else "категория не определена"
        for uid in admins():
            notify(uid, f"Обращение {a['number']} без ответственного: {why}", f"/panel#/appeal/{a['id']}")
    return resp


def create(*, type: str, text: str, proposed_solution: str | None = None, category_id: int | None = None,
           priority: str = "medium", branch_id: int | None = None, department_id: int | None = None,
           author: dict | None = None, is_anonymous: bool = False, source: str = "app", meeting_id: int | None = None,
           ai: dict | None = None, site_city: str | None = None, route_by_category: bool = False,
           author_urgency: str | None = None, author_scope: str | None = None, input_mode: str | None = None,
           praise_to_user_id: int | None = None, praise_to_department_id: int | None = None) -> dict:
    """ai — результат mf.ai.classify_appeal (категория подставлена ИИ или словарём): пишется событием ai_classified до маршрутизации.
    praise_to_* — «Кому спасибо» (только для type=praise): адресату и его руководителю уходит уведомление, запись видна в профиле адресата."""
    if type not in TYPES:
        raise HTTPException(422, "Неверный тип обращения")
    author_urgency = author_urgency if author_urgency in URGENCY else None
    author_scope = author_scope if author_scope in SCOPE else None
    if priority not in PRIORITIES:
        priority = matrix_priority(type, author_urgency, author_scope) or "medium"
    if source not in SOURCES:
        source = "app"
    text = (text or "").strip()
    if len(text) < 5:
        raise HTTPException(422, "Опишите проблему или идею хотя бы в нескольких словах")
    if category_id and not db.one("SELECT 1 FROM categories WHERE id=?", (category_id,)):
        raise HTTPException(422, "Категория не найдена")
    if branch_id and not db.one("SELECT 1 FROM branches WHERE id=?", (branch_id,)):
        raise HTTPException(422, "Филиал не найден")
    if author and not is_anonymous:   # F-08: анонимному — ни отдела, ни филиала автора (в маленьком отделе это раскрыло бы его)
        branch_id = branch_id or author["branch_id"]
        department_id = department_id or author["department_id"]
    number = next_number()
    aid = db.ex("""INSERT INTO appeals(number, type, category_id, branch_id, department_id, text, proposed_solution, priority,
                   status, is_anonymous, source, meeting_id, tracking_token, created_at, updated_at, site_city,
                   author_urgency, author_scope, brief, brief_engine, brief_at, input_mode)
                   VALUES(?,?,?,?,?,?,?,?,'new',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (number, type, category_id, branch_id, department_id, text, (proposed_solution or "").strip() or None, priority,
                 1 if is_anonymous else 0, source, meeting_id, secrets.token_urlsafe(24), db.now_iso(), db.now_iso(),
                 (site_city or "").strip()[:80] or None, author_urgency, author_scope,
                 json.dumps(ai["brief"], ensure_ascii=False) if ai and ai.get("brief") else None,
                 (ai or {}).get("engine") if ai and ai.get("brief") else None, db.now_iso() if ai and ai.get("brief") else None, input_mode))
    if author:
        db.ex("INSERT INTO appeal_authors(appeal_id, user_id) VALUES(?,?)", (aid, author["id"]))
    actor = None if (is_anonymous or not author) else author["id"]
    add_event(aid, actor, "created", {"source": source, "type": type, "anonymous": bool(is_anonymous)})
    if ai:
        add_event(aid, None, "ai_classified", {"engine": ai.get("engine"), "category_id": ai.get("category_id"), "category": ai.get("category"),
                                               "confidence": ai.get("confidence"), "priority": ai.get("priority"), "summary": ai.get("summary")})
    a = get(aid)
    if type == "praise" and (praise_to_user_id or praise_to_department_id):
        praise_address(aid, author, praise_to_user_id, praise_to_department_id)
        a = get(aid)
    route(a, by_category=route_by_category)
    realtime.publish_roles(("director", "admin"), {"type": "appeal_created", "id": aid, "number": number,
                                                   "branch_id": branch_id, "branch_code": a.get("branch_code")})
    return get(aid)


def praise_address(appeal_id: int, author: dict | None, user_id: int | None, department_id: int | None) -> None:
    """«Кому спасибо»: адресат-коллега (и его руководитель) или отдел (все его сотрудники) получают уведомление; запись видна в профиле адресата."""
    a = get(appeal_id)
    who = (author["name"] if author else None) or "Коллега"
    target = db.one("SELECT id, name, manager_id FROM users WHERE id=? AND active=1", (user_id,)) if user_id else None
    dept = db.one("SELECT id, name FROM departments WHERE id=?", (department_id,)) if department_id else None
    if not target and not dept:
        return
    db.ex("UPDATE appeals SET praise_to_user_id=?, praise_to_department_id=? WHERE id=?", (target["id"] if target else None, dept["id"] if dept else None, appeal_id))
    add_event(appeal_id, None, "praise_addressed", {"user_id": target["id"] if target else None, "user": target["name"] if target else None,
                                                   "department_id": dept["id"] if dept else None, "department": dept["name"] if dept else None})
    link = f"/app#/appeal/{appeal_id}"
    if target:
        notify(target["id"], f"{who} говорит вам спасибо: «{short(a['text'], 90)}»", link)
        if target["manager_id"] and target["manager_id"] != (author or {}).get("id"):
            notify(target["manager_id"], f"{target['name']}: спасибо от коллеги — «{short(a['text'], 90)}»", link)
    elif dept:
        for u in db.q("SELECT id FROM users WHERE department_id=? AND active=1", (dept["id"],)):
            if not author or u["id"] != author["id"]:
                notify(u["id"], f"Отделу «{dept['name']}» говорят спасибо: «{short(a['text'], 90)}»", link)


def praises_for(user_id: int, limit: int = 20) -> list[dict]:
    """Благодарности, адресованные сотруднику (профиль): номер, текст, от кого (если не анонимно), когда."""
    rows = db.q("""SELECT a.id, a.number, a.text, a.created_at, a.is_anonymous, aa.user_id AS from_id, u.name AS from_name
                   FROM appeals a LEFT JOIN appeal_authors aa ON aa.appeal_id=a.id LEFT JOIN users u ON u.id=aa.user_id
                   WHERE a.type='praise' AND a.praise_to_user_id=? ORDER BY a.created_at DESC LIMIT ?""", (user_id, limit))
    return [{"id": r["id"], "number": r["number"], "text": short(r["text"], 160), "created_at": r["created_at"],
             "from": None if r["is_anonymous"] else r["from_name"]} for r in rows]


def staff_search(q: str, limit: int = 8) -> dict:
    """Поиск адресата «спасибо» по имени (коллега) или названию отдела; минимум два символа."""
    q = " ".join((q or "").split()).lower().replace("ё", "е")
    if len(q) < 2:
        return {"users": [], "departments": []}
    users = [u for u in db.q("""SELECT u.id, u.name, u.position, d.name AS department, b.city FROM users u LEFT JOIN departments d ON d.id=u.department_id
                                LEFT JOIN branches b ON b.id=u.branch_id WHERE u.active=1 ORDER BY u.name""") if q in u["name"].lower().replace("ё", "е")][:limit]
    deps = [d for d in db.q("SELECT id, name FROM departments ORDER BY name") if q in d["name"].lower().replace("ё", "е")][:limit]
    return {"users": users, "departments": deps}


# ---------- права ----------

def can_manage(a: dict, user: dict) -> bool:
    """Ответственный — свои и своих подразделений (а также обращения, назначенные его подчинённым); директор и админ — все."""
    if user["role"] in ("director", "admin"):
        return True
    if user["role"] != "responsible":
        return False
    if a["responsible_id"] == user["id"] or (a["department_id"] and a["department_id"] == user["department_id"]):
        return True
    if a["responsible_id"] and db.one("SELECT 1 FROM users WHERE id=? AND manager_id=?", (a["responsible_id"], user["id"])):
        return True
    return False


def can_view(a: dict, user: dict) -> bool:
    """Полная карточка: ведущий, автор; реализованные — всем (лента «Результаты обращений»). Поддержавший («У меня так же») видит только
    краткую карточку — view_limited (аудит 12.11, F-05: раньше поддержка открывала любое обращение вместе с вложениями)."""
    if can_manage(a, user):
        return True
    if author_id(a["id"]) == user["id"]:
        return True
    return a["status"] == "done"   # лента «Результаты обращений» — открыта всем сотрудникам


def supported_by(a: dict, user: dict) -> bool:
    return bool(db.one("SELECT 1 FROM supports WHERE appeal_id=? AND user_id=?", (a["id"], user["id"])))


LIMITED_EVENT_KINDS = ("created", "status_changed", "supported", "discussed_at_meeting", "priority_changed")


def view_limited(a: dict, user: dict) -> dict:
    """Карточка для поддержавшего: номер, статус и стадия, суть (до 200 знаков), категория, филиал, ответственный, итог.
    Без автора, полного текста, предложения, «Коротко», вложений, комментариев и уточнений."""
    out = view(a, user)
    out.update(text=short(a["text"], 200), proposed_solution=None, brief=None, attachments=[], author=None, pending_question=None,
               author_urgency_label=None, author_scope_label=None, director_request_text=None, director_comment=None, points=None,
               can_manage=False, can_request_director=False, limited=True)
    out.pop("allowed_next", None)
    out["events"] = [{**e, "actor": None, "actor_id": None} if e["kind"] == "created" else e for e in out["events"] if e["kind"] in LIMITED_EVENT_KINDS]
    return out


def _first_response(a: dict, actor: dict | None) -> None:
    """Первый ответ — первое действие ответственного (смена статуса, уточнение или комментарий)."""
    if a["first_response_at"] is None and actor and actor["role"] in STAFF:
        db.ex("UPDATE appeals SET first_response_at=? WHERE id=?", (db.now_iso(), a["id"]))


# ---------- действия ответственного ----------

def set_status(appeal_id: int, actor: dict, status: str, text: str | None = None) -> dict:
    a = get(appeal_id)
    if status not in STATUSES:
        raise HTTPException(422, "Неизвестный статус")
    allowed = list(TRANSITIONS[a["status"]])
    if a["type"] == "praise" and a["status"] == "new":
        allowed.append("closed")   # положительный отзыв: Новое → Закрыто с отметкой «передано»
    if status not in allowed:
        raise HTTPException(409, f"Переход «{STATUSES[a['status']]}» → «{STATUSES[status]}» недопустим")
    text = (text or "").strip() or None
    if status == "rejected" and not text:
        raise HTTPException(422, "Отказ требует мотивировки — автор её увидит")
    if status == "done" and not text:
        raise HTTPException(422, "Укажите, что сделано: это увидит автор и лента «Результаты обращений»")
    sets, params = ["status=?"], [status]
    if status in ("done", "rejected"):
        sets.append("resolution_text=?"); params.append(text)
    if status in ("closed", "rejected", "done"):
        sets.append("closed_at=?"); params.append(db.now_iso())
    params.append(appeal_id)
    db.ex(f"UPDATE appeals SET {', '.join(sets)} WHERE id=?", params)
    _first_response(a, actor)
    add_event(appeal_id, actor["id"], "status_changed", {"from": a["status"], "to": status, "text": text})
    if status == "review":
        award(a, "accepted")
    if status == "done":
        award(a, "done")
    touch_news(appeal_id)
    msg = f"{a['number']}: статус «{STATUS_DISPLAY[status]}»" + (f" — {text}" if text else "")
    notify(author_id(appeal_id), msg, f"/app#/appeal/{appeal_id}")
    realtime.publish_roles(("director", "admin"), {"type": "appeal_updated", "id": appeal_id, "status": status})
    return get(appeal_id)


def assign(appeal_id: int, actor: dict, responsible_id: int) -> dict:
    a = get(appeal_id)
    if a["status"] not in OPEN:
        raise HTTPException(409, "Обращение уже закрыто")
    u = db.one("SELECT * FROM users WHERE id=? AND active=1 AND role IN ('responsible','director','admin')", (responsible_id,))
    if not u:
        raise HTTPException(404, "Ответственный не найден")
    db.ex("UPDATE appeals SET responsible_id=? WHERE id=?", (u["id"], appeal_id))
    _first_response(a, actor)
    add_event(appeal_id, actor["id"], "assigned", {"responsible_id": u["id"], "responsible": u["name"], "auto": False})
    if u["id"] != actor["id"]:
        notify(u["id"], f"Вам назначено обращение {a['number']}: {short(a['text'])}", f"/panel#/appeal/{appeal_id}")
    return get(appeal_id)


def comment(appeal_id: int, actor: dict, text: str) -> dict:
    a = get(appeal_id)
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "Пустой комментарий")
    _first_response(a, actor)
    add_event(appeal_id, actor["id"], "comment", {"text": text})
    if actor["id"] != author_id(appeal_id):
        touch_news(appeal_id)
        notify(author_id(appeal_id), f"{a['number']}: комментарий — {short(text, 80)}", f"/app#/appeal/{appeal_id}")
    return get(appeal_id)


def progress(appeal_id: int, actor: dict, text: str) -> dict:
    """«Сообщить о ходе» (по словам собственника): короткая новость автору без смены статуса."""
    a = get(appeal_id)
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "Напишите коротко, что сделано или что дальше")
    if a["status"] not in OPEN:
        raise HTTPException(409, "Обращение уже закрыто")
    _first_response(a, actor)
    add_event(appeal_id, actor["id"], "progress", {"text": text})
    touch_news(appeal_id)
    notify(author_id(appeal_id), f"{a['number']}: как идут дела — {short(text, 90)}", f"/app#/appeal/{appeal_id}")
    return get(appeal_id)


def set_priority(appeal_id: int, actor: dict, priority: str) -> dict:
    a = get(appeal_id)
    if priority not in PRIORITIES:
        raise HTTPException(422, "Приоритет: low, medium или high")
    if priority != a["priority"]:
        db.ex("UPDATE appeals SET priority=?, priority_manual=1 WHERE id=?", (priority, appeal_id))
        add_event(appeal_id, actor["id"], "priority_changed", {"from": a["priority"], "to": priority, "reason": "manual"})
    return get(appeal_id)


def news_days_setting() -> int:
    return int(db.setting("news_days", 7) or 7)


def news_age_days(a: dict) -> float | None:
    """Сколько дней автор без новостей: от последней новости, а если её не было — от создания."""
    last = db.parse(a.get("last_news_at")) or db.parse(a["created_at"])
    return round((db.now() - last).total_seconds() / 86400, 1) if last else None


def check_news() -> int:
    """«В работе» без новостей автору дольше порога → напоминание ответственному «Автор ждёт новостей» (раз в порог)."""
    th = news_days_setting()
    n = 0
    for a in db.q(BASE_SELECT + " WHERE a.status='in_progress' AND a.responsible_id IS NOT NULL"):
        age = news_age_days(a)
        rem = db.parse(a.get("news_reminded_at"))
        if age is not None and age >= th and (rem is None or (db.now() - rem).total_seconds() >= th * 86400):
            db.ex("UPDATE appeals SET news_reminded_at=? WHERE id=?", (db.now_iso(), a["id"]))
            notify(a["responsible_id"], f"Автор ждёт новостей по {a['number']} — {int(age)} дн без вестей. Нажмите «Сообщить о ходе»", f"/panel#/appeal/{a['id']}")
            n += 1
    return n


def no_news_count(th: int | None = None) -> int:
    th = th or news_days_setting()
    return sum(1 for a in db.q(BASE_SELECT + " WHERE a.status='in_progress'") if (news_age_days(a) or 0) >= th)


def thank(appeal_id: int, user: dict) -> int:
    """«Спасибо» под внедрённой идеей: одно на человека, автору уведомление, баллов нет — признание, а не валюта."""
    a = get(appeal_id)
    if a["status"] not in ("done", "closed") or a["type"] == "praise":
        raise HTTPException(409, "«Спасибо» — за реализованные обращения")
    if author_id(appeal_id) == user["id"]:
        raise HTTPException(409, "Это ваше обращение")
    if a["is_anonymous"]:
        raise HTTPException(409, "Автор анонимный")
    if db.one("SELECT 1 FROM thanks WHERE appeal_id=? AND user_id=?", (appeal_id, user["id"])):
        raise HTTPException(409, "Вы уже сказали спасибо")
    db.ex("INSERT INTO thanks(appeal_id, user_id, created_at) VALUES(?,?,?)", (appeal_id, user["id"], db.now_iso()))
    count = db.one("SELECT COUNT(*) AS n FROM thanks WHERE appeal_id=?", (appeal_id,))["n"]
    add_event(appeal_id, None, "thanked", {"count": count})
    notify(author_id(appeal_id), f"{user['name']} говорит спасибо за {a['number']} (всего {count})", f"/app#/appeal/{appeal_id}")
    return count


def set_brief(appeal_id: int, brief: dict | None, engine: str | None) -> None:
    db.ex("UPDATE appeals SET brief=?, brief_engine=?, brief_at=? WHERE id=?",
          (json.dumps(brief, ensure_ascii=False) if brief else None, engine, db.now_iso(), appeal_id))


def request_clarification(appeal_id: int, actor: dict, text: str) -> dict:
    a = get(appeal_id)
    if a["status"] not in ("new", "review"):
        raise HTTPException(409, f"Уточнение можно запросить только из «Новое» или «На рассмотрении» (сейчас «{a['status_label']}»)")
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "Сформулируйте вопрос автору")
    db.ex("UPDATE appeals SET status='clarify' WHERE id=?", (appeal_id,))
    _first_response(a, actor)
    add_event(appeal_id, actor["id"], "clarification_requested", {"text": text, "from": a["status"]})
    notify(author_id(appeal_id), f"{a['number']}: нужно уточнение — {short(text, 80)}", f"/app#/appeal/{appeal_id}")
    return get(appeal_id)


def answer_clarification(appeal_id: int, text: str, actor_id: int | None = None) -> dict:
    a = get(appeal_id)
    if a["status"] != "clarify":
        raise HTTPException(409, "Уточнение не запрошено")
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "Пустой ответ")
    db.ex("UPDATE appeals SET status='review' WHERE id=?", (appeal_id,))
    add_event(appeal_id, actor_id, "clarification_answered", {"text": text})
    notify(a["responsible_id"], f"{a['number']}: автор ответил на уточнение — {short(text, 80)}", f"/panel#/appeal/{appeal_id}")
    realtime.publish_roles(("director", "admin"), {"type": "appeal_updated", "id": appeal_id, "status": "review"})
    return get(appeal_id)


def support(appeal_id: int, user: dict) -> int:
    a = get(appeal_id)
    if a["status"] not in OPEN:
        raise HTTPException(409, "Обращение уже закрыто")
    if author_id(appeal_id) == user["id"]:
        raise HTTPException(409, "Это ваше обращение")
    if db.one("SELECT 1 FROM supports WHERE appeal_id=? AND user_id=?", (appeal_id, user["id"])):
        raise HTTPException(409, "Вы уже поддержали это обращение")
    db.ex("INSERT INTO supports(appeal_id, user_id, created_at) VALUES(?,?,?)", (appeal_id, user["id"], db.now_iso()))
    count = a["supports"] + 1
    add_event(appeal_id, None, "supported", {"count": count})
    notify(author_id(appeal_id), f"{a['number']}: коллега отметил «У меня так же» (всего {count})", f"/app#/appeal/{appeal_id}")
    award(a, "support")
    if count % 3 == 0 and a["priority"] != "high" and not a.get("priority_manual"):   # каждые 3 поддержки — на ступень выше, не выше высокого
        db.ex("UPDATE appeals SET priority=? WHERE id=?", (bump(a["priority"]), appeal_id))
        add_event(appeal_id, None, "priority_changed", {"from": a["priority"], "to": bump(a["priority"]), "reason": "supports", "count": count})
    return count


# ---------- «Нужно решение директора» (ТЗ v2 §2.1) ----------

def request_director(appeal_id: int, actor: dict, text: str) -> dict:
    a = get(appeal_id)
    if a["type"] != "suggestion":
        raise HTTPException(409, "К директору выносятся предложения; проблемы решает ответственный")
    if a["status"] not in OPEN:
        raise HTTPException(409, "Обращение уже закрыто")
    if a["director_decision"] == "pending":
        raise HTTPException(409, "Уже ждёт решения директора")
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "Напишите коротко, что требуется: ресурсы, бюджет, люди")
    db.ex("""UPDATE appeals SET director_request_text=?, director_requested_at=?, director_requested_by=?, director_decision='pending',
             director_comment=NULL, director_decided_at=NULL, director_decided_by=NULL WHERE id=?""", (text, db.now_iso(), actor["id"], appeal_id))
    _first_response(a, actor)
    add_event(appeal_id, actor["id"], "director_requested", {"text": text})
    for d in db.q("SELECT id FROM users WHERE role='director' AND active=1"):
        notify(d["id"], f"На решение: предложение {a['number']} — {short(a['text'], 70)}. Требуется: {short(text, 60)}", "/app#/decisions")
        realtime.publish(d["id"], {"type": "idea_pending", "appeal_id": appeal_id})
    notify(author_id(appeal_id), f"{a['number']}: предложение вынесено на решение директора", f"/app#/appeal/{appeal_id}")
    return get(appeal_id)


def director_decide(appeal_id: int, actor: dict, decision: str, comment: str | None) -> dict:
    a = get(appeal_id)
    if a["director_decision"] != "pending":
        raise HTTPException(409, "Это предложение не ждёт решения директора")
    if decision not in ("accepted", "rejected"):
        raise HTTPException(422, "Решение: accepted или rejected")
    comment = (comment or "").strip()
    if decision == "rejected" and not comment:
        raise HTTPException(422, "Отклонение требует причины — её увидят автор и ответственный")
    db.ex("UPDATE appeals SET director_decision=?, director_comment=?, director_decided_at=?, director_decided_by=? WHERE id=?",
          (decision, comment or None, db.now_iso(), actor["id"], appeal_id))
    add_event(appeal_id, actor["id"], "director_decided", {"decision": decision, "text": comment or None})
    label = "принял" if decision == "accepted" else "отклонил"
    for uid in {a["responsible_id"], author_id(appeal_id), a["director_requested_by"]} - {None, actor["id"]}:
        notify(uid, f"Директор {label} предложение {a['number']}" + (f": {short(comment, 90)}" if comment else ""), f"/app#/appeal/{appeal_id}")
    if decision == "rejected" and a["status"] in OPEN:
        pass   # статус обращения не меняем: ответственный сам закрывает с мотивировкой директора
    return get(appeal_id)


def director_wait_days() -> int:
    return int(db.setting("director_wait_days", 7) or 7)


def director_queue() -> list[dict]:
    """Предложения из обращений, ждущие решения, с возрастом ожидания — объединяются с идеями совещаний в /api/director/ideas."""
    rows = db.q(BASE_SELECT + " WHERE a.director_decision IS NOT NULL ORDER BY CASE a.director_decision WHEN 'pending' THEN 0 ELSE 1 END, a.director_requested_at DESC")
    out = []
    for r in rows:
        req = db.parse(r["director_requested_at"])
        aid = author_id(r["id"])
        au = db.one("SELECT name FROM users WHERE id=?", (aid,)) if aid and not r["is_anonymous"] else None
        out.append({"source": "appeal", "appeal_id": r["id"], "number": r["number"], "text": r["text"], "type": r["type"],
                    "category": r["category"], "category_id": r["category_id"], "branch": city_of(r), "responsible": r["responsible"],
                    "author": au["name"] if au else None, "request": r["director_request_text"], "requested_at": r["director_requested_at"],
                    "wait_days": round((db.now() - req).total_seconds() / 86400, 1) if req else None,
                    "director_decision": r["director_decision"], "director_decision_label": DIRECTOR_DECISIONS.get(r["director_decision"]),
                    "director_comment": r["director_comment"], "decided_at": r["director_decided_at"], "supports": r["supports"]})
    return out


# ---------- просрочка ----------

def check_overdue() -> list[str]:
    """Нет первого ответа дольше SLA категории → метка «Просрочено», уведомление руководителю ответственного, событие escalated."""
    escalated = []
    rows = db.q(BASE_SELECT + " WHERE a.first_response_at IS NULL AND a.escalated_at IS NULL AND a.status IN ('new','review','clarify','in_progress')")
    for a in rows:
        if not is_overdue(a):
            continue
        sla = a["sla"] or DEFAULT_SLA
        resp = db.one("SELECT * FROM users WHERE id=?", (a["responsible_id"],)) if a["responsible_id"] else None
        targets = [resp["manager_id"]] if resp and resp["manager_id"] else admins()
        db.ex("UPDATE appeals SET escalated_at=? WHERE id=?", (db.now_iso(), a["id"]))
        add_event(a["id"], None, "escalated", {"sla_hours": sla, "to": targets, "responsible_id": a["responsible_id"]})
        who = f"ответственный {resp['name']}" if resp else "без ответственного"
        for uid in targets:
            notify(uid, f"Просрочено: {a['number']} без первого ответа {int(a['age_hours'] if 'age_hours' in a else 0)} ч при SLA {sla} ч ({who})",
                   f"/panel#/appeal/{a['id']}")
        escalated.append(a["number"])
    if escalated:
        realtime.publish_roles(("director", "admin"), {"type": "escalated", "numbers": escalated})
    return escalated


# ---------- представления ----------

def view(a: dict, user: dict | None = None, public: bool = False) -> dict:
    """Карточка. Автор отдаётся только если обращение не анонимное; для анонимных — никому, кроме самого автора (is_mine)."""
    aid = author_id(a["id"])
    out = {k: a[k] for k in ("id", "number", "type", "type_label", "category_id", "category", "branch_id", "branch", "branch_code",
                             "department_id", "department", "text", "proposed_solution", "priority", "priority_label", "status",
                             "status_label", "responsible_id", "responsible", "responsible_position", "is_anonymous", "source",
                             "meeting_id", "resolution_text", "created_at", "updated_at", "first_response_at", "closed_at",
                             "escalated_at", "supports", "age_hours", "overdue", "overdue_days", "unassigned", "sla", "first_response_hours", "site_city",
                             "director_request_text", "director_requested_at", "director_decision", "director_comment", "director_decided_at",
                             "author_urgency", "author_scope", "priority_manual", "brief_engine", "brief_at", "last_news_at", "input_mode")}
    out["director_decision_label"] = DIRECTOR_DECISIONS.get(a["director_decision"]) if a["director_decision"] else None
    out["author_urgency_label"] = URGENCY.get(a["author_urgency"]) if a.get("author_urgency") else None
    out["author_scope_label"] = SCOPE.get(a["author_scope"]) if a.get("author_scope") else None
    out["brief"] = brief_of(a)
    out["stage"] = stage_for(a)
    out["news_days"] = news_age_days(a) if a["status"] in OPEN else None
    out["thanks"] = db.one("SELECT COUNT(*) AS n FROM thanks WHERE appeal_id=?", (a["id"],))["n"]
    out["thanked_by_me"] = bool(user and db.one("SELECT 1 FROM thanks WHERE appeal_id=? AND user_id=?", (a["id"], user["id"])))
    out["responsible_avatar"] = avatar_url(a["responsible_id"]) if a["responsible_id"] else None
    out["is_mine"] = bool(user and aid == user["id"])
    out["author"] = None
    if not public and aid and not a["is_anonymous"]:
        u = db.one("SELECT name, position, avatar FROM users WHERE id=?", (aid,))
        out["author"] = {"id": aid, "name": u["name"], "position": u["position"], "avatar": avatar_url(aid, u["avatar"])} if u else None
    events = events_of(a["id"])
    if public or not user or user["role"] not in STAFF:
        events = [e for e in events if e["kind"] in PUBLIC_EVENT_KINDS or (e["kind"] == "points_awarded" and out["is_mine"])]
    if a["is_anonymous"]:
        for e in events:
            if e["kind"] in ("created", "clarification_answered"):
                e["actor"] = None; e["actor_id"] = None
    out["events"] = events
    out["attachments"] = attachments_of(a["id"])
    out["points"] = int(db.one("SELECT COALESCE(SUM(amount),0) AS s FROM points_ledger WHERE appeal_id=?", (a["id"],))["s"]) if out["is_mine"] else None
    out["supported_by_me"] = bool(user and db.one("SELECT 1 FROM supports WHERE appeal_id=? AND user_id=?", (a["id"], user["id"])))
    out["can_support"] = bool(user and not out["is_mine"] and not out["supported_by_me"] and a["status"] in OPEN)
    out["can_thank"] = bool(user and not out["is_mine"] and not out["thanked_by_me"] and a["status"] in ("done", "closed") and a["type"] != "praise" and not a["is_anonymous"])
    out["can_manage"] = bool(user and can_manage(a, user))
    out["can_request_director"] = bool(out["can_manage"] and a["type"] == "suggestion" and a["status"] in OPEN and a["director_decision"] != "pending")
    if out["can_manage"]:
        nxt = list(TRANSITIONS[a["status"]])
        if a["type"] == "praise" and a["status"] == "new":
            nxt.append("closed")
        out["allowed_next"] = [{"code": s, "label": NEXT_LABELS[s]} for s in nxt]
    pending = [e for e in events if e["kind"] == "clarification_requested"]
    out["pending_question"] = pending[-1]["payload"].get("text") if (a["status"] == "clarify" and pending) else None
    return out


def list_for(user: dict, f: dict) -> list[dict]:
    """Очередь панели с фильтрами и ролевой областью видимости."""
    where, params = [], []
    if user["role"] == "responsible":
        where.append("(a.responsible_id=? OR a.department_id=? OR a.responsible_id IN (SELECT id FROM users WHERE manager_id=?) "
                     "OR a.id IN (SELECT appeal_id FROM appeal_authors WHERE user_id=?))")
        params += [user["id"], user["department_id"], user["id"], user["id"]]
    for key, col in (("branch_id", "a.branch_id"), ("department_id", "a.department_id"), ("category_id", "a.category_id"),
                     ("responsible_id", "a.responsible_id"), ("status", "a.status"), ("type", "a.type")):
        if f.get(key):
            vals = [v for v in str(f[key]).split(",") if v] if key == "status" else [f[key]]   # статус — группой: «review,in_progress» = «В работе»
            where.append(f"{col} IN ({','.join('?' * len(vals))})"); params += vals
    if f.get("unassigned"):
        where.append("a.responsible_id IS NULL AND a.status IN ('new','review','clarify','in_progress')")
    if f.get("open") or f.get("attention"):
        where.append("a.status IN ('new','review','clarify','in_progress')")
    if f.get("closed"):
        where.append("a.status IN ('done','closed','rejected')")
    if f.get("days"):
        where.append("a.created_at >= ?"); params.append(db.iso(db.now() - timedelta(days=int(f["days"]))))
    if f.get("q"):
        where.append("(a.number LIKE ? OR a.text LIKE ? OR a.brief LIKE ?)"); params += [f"%{f['q']}%", f"%{f['q']}%", f"%{f['q']}%"]
    if f.get("urgency"):
        where.append("a.author_urgency=?"); params.append(f["urgency"])
    if f.get("site"):   # объект командированных — по городу объекта (13.11)
        where.append("a.site_city=?"); params.append(f["site"])
    if f.get("cluster_id"):
        where.append("a.cluster_id=?"); params.append(int(f["cluster_id"]))
    order = "a.created_at DESC"
    if f.get("sort") == "priority":
        order = "CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, a.created_at DESC"
    sql = BASE_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + order
    rows = [decorate(r) for r in db.q(sql, params)]
    if not f.get("sort"):   # по умолчанию — срочные сверху: просроченные (дольше — выше), «мешает сейчас», высокий приоритет, затем новые
        rows.sort(key=lambda r: (-(r["overdue_days"] or 0), r.get("author_urgency") != "now", r["priority"] != "high"))
    if f.get("overdue"):
        rows = [r for r in rows if r["overdue"]]
    if f.get("attention"):   # этап 9: вкладка «Требуют внимания» — просроченные, без ответственного, «мешают сейчас», ждут уточнения
        rows = [r for r in rows if r["overdue"] or r["unassigned"] or r.get("author_urgency") == "now" or r["status"] == "clarify"]
    keep = ("id", "number", "type", "type_label", "category", "category_id", "branch", "branch_code", "branch_id", "department",
            "status", "status_label", "responsible", "responsible_id", "priority", "priority_label", "created_at", "age_hours",
            "overdue", "overdue_days", "unassigned", "supports", "is_anonymous", "source", "first_response_hours", "text", "site_city", "director_decision")
    out = []
    for r in rows:
        o = {k: r.get(k) for k in keep}
        o["text"] = short(r["text"], 120)
        o["brief_line"] = line(r, 120)
        o["city"] = city_of(r)   # «A-026 · Самара» в очереди (замечание 13.11); объект — его город
        o["author_urgency"] = r.get("author_urgency")
        o["author_urgency_label"] = URGENCY.get(r.get("author_urgency") or "")
        o["news_days"] = news_age_days(r) if r["status"] in OPEN else None
        out.append(o)
    return out


def avatar_url(user_id: int | None, avatar: str | None = "?") -> str | None:
    if not user_id:
        return None
    if avatar == "?":
        u = db.one("SELECT avatar FROM users WHERE id=?", (user_id,))
        avatar = u["avatar"] if u else None
    return f"/api/avatars/{avatar}" if avatar else None


def mine(user: dict) -> list[dict]:
    rows = db.q(BASE_SELECT + " WHERE a.id IN (SELECT appeal_id FROM appeal_authors WHERE user_id=?) ORDER BY a.created_at DESC", (user["id"],))
    out = []
    for r in rows:
        r = decorate(r)
        out.append({k: r.get(k) for k in ("id", "number", "type", "type_label", "category", "status", "status_label", "created_at",
                                            "supports", "is_anonymous", "resolution_text", "responsible")} | {"text": short(r["text"], 120)})
    return out


def changes(limit: int = 50) -> list[dict]:
    """Лента «Результаты обращений»: проблема → что сделали (закрывает A-020 из датасета)."""
    rows = [decorate(r) for r in db.q(BASE_SELECT + " WHERE a.status IN ('done','closed') AND a.resolution_text IS NOT NULL AND a.type != 'praise' "
                                     "ORDER BY COALESCE(a.closed_at, a.updated_at) DESC LIMIT ?", (limit,))]
    out = []
    for r in rows:
        o = {k: r.get(k) for k in ("id", "number", "type", "type_label", "category", "branch", "text", "resolution_text", "closed_at", "supports")}
        aid = author_id(r["id"])
        au = db.one("SELECT id, name, avatar FROM users WHERE id=?", (aid,)) if aid and not r["is_anonymous"] else None
        o["author"] = {"id": au["id"], "name": au["name"], "avatar": avatar_url(au["id"], au["avatar"])} if au else None
        o["thanks"] = db.one("SELECT COUNT(*) AS n FROM thanks WHERE appeal_id=?", (r["id"],))["n"]
        o["brief_line"] = line(r, 140)
        out.append(o)
    return out


def changes_for(user: dict | None, limit: int = 50) -> list[dict]:
    rows = changes(limit)
    for o in rows:
        o["thanked_by_me"] = bool(user and db.one("SELECT 1 FROM thanks WHERE appeal_id=? AND user_id=?", (o["id"], user["id"])))
        o["is_mine"] = bool(user and o["author"] and o["author"]["id"] == user["id"])
    return rows


def summary(user: dict, days: int = 30, branch_id: int | None = None) -> dict:
    """Сводка: открытых, доля рассмотренных, среднее время первого ответа, реализовано за период; разрезы по типам,
    статусам, филиалам и категориям. Количество обращений само по себе филиал не ранжирует (ТЗ v1.1, раздел 1)."""
    rows = [decorate(r) for r in _scope_rows(user, branch_id)]
    since = db.now() - timedelta(days=days)

    def block(items: list[dict]) -> dict:
        total = len(items)
        considered = [r for r in items if r["first_response_at"]]
        resp_hours = [r["first_response_hours"] for r in considered if r["first_response_hours"] is not None]
        return {
            "total": total,
            "open": sum(1 for r in items if r["status"] in OPEN),
            "overdue": sum(1 for r in items if r["overdue"]),
            "unassigned": sum(1 for r in items if r["unassigned"]),
            "considered_share": round(len(considered) / total, 2) if total else None,
            "avg_first_response_hours": round(sum(resp_hours) / len(resp_hours), 1) if resp_hours else None,
            "done_period": sum(1 for r in items if r["status"] in ("done", "closed") and r["type"] != "praise"
                               and r["closed_at"] and db.parse(r["closed_at"]) >= since),
            "done_total": sum(1 for r in items if r["status"] in ("done", "closed") and r["type"] != "praise"),
        }

    by_type = {t: sum(1 for r in rows if r["type"] == t) for t in TYPES}
    by_status = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    branches = db.q("SELECT * FROM branches ORDER BY is_hq DESC, name")
    by_branch = []
    def top_cat(items: list[dict]) -> str | None:
        cats: dict[str, int] = {}
        for r in items:
            if r["status"] in OPEN and r["category"]:
                cats[r["category"]] = cats.get(r["category"], 0) + 1
        return max(cats.items(), key=lambda kv: kv[1])[0] if cats else None

    for b in branches:
        items = [r for r in rows if r["branch_id"] == b["id"]]
        base = {"id": b["id"], "code": b["code"], "name": b["name"], "city": b["city"], "kind": b["kind"], "lat": b["lat"], "lng": b["lng"]}
        if b["kind"] == "field":   # объекты командированных — строкой на каждый объект («Атырау · объект»), а не общей «Объекты» (13.11)
            for site in sorted({r.get("site_city") or "" for r in items}):
                part = [r for r in items if (r.get("site_city") or "") == site]
                by_branch.append({**base, "site": site or None, **block(part), "top_category": top_cat(part)})
            continue
        by_branch.append({**base, **block(items), "top_category": top_cat(items)})
    cat_counts: dict[str, int] = {}
    for r in rows:
        if r["status"] in OPEN and r["category"]:
            cat_counts[r["category"]] = cat_counts.get(r["category"], 0) + 1
    top_categories = sorted(({"category": k, "open": v} for k, v in cat_counts.items()), key=lambda x: -x["open"])[:8]
    return {"period_days": days, **block(rows), "by_type": by_type, "by_status": by_status, "by_branch": by_branch,
            "top_categories": top_categories}


def _scope_rows(user: dict, branch_id: int | None) -> list[dict]:
    where, params = [], []
    if user["role"] == "responsible":
        where.append("(a.responsible_id=? OR a.department_id=? OR a.responsible_id IN (SELECT id FROM users WHERE manager_id=?))")
        params += [user["id"], user["department_id"], user["id"]]
    if branch_id:
        where.append("a.branch_id=?"); params.append(branch_id)
    return db.q(BASE_SELECT + (" WHERE " + " AND ".join(where) if where else ""), params)
