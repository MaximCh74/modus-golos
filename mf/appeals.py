"""Обращения: создание и маршрутизация, статусы и журнал, уточнения, поддержка «У меня так же», баллы, просрочка.
Правила — docs/TZ_v1.1.md, раздел 5."""
from __future__ import annotations

import json
import secrets
from datetime import timedelta

from fastapi import HTTPException

from . import db, realtime

STATUSES = {
    "new": "Новое", "review": "На рассмотрении", "clarify": "Ожидает уточнения", "in_progress": "В работе",
    "done": "Реализовано", "closed": "Закрыто", "rejected": "Отклонено",
}
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
PUBLIC_EVENT_KINDS = ("created", "assigned", "status_changed", "comment", "clarification_requested",
                      "clarification_answered", "discussed_at_meeting", "supported")

BASE_SELECT = """SELECT a.*, c.name AS category, c.sla_first_response_hours AS sla,
  b.name AS branch, b.code AS branch_code, d.name AS department,
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


def decorate(a: dict) -> dict:
    """Производные поля для списков и карточки."""
    created = db.parse(a["created_at"])
    a["age_hours"] = round((db.now() - created).total_seconds() / 3600, 1)
    a["overdue"] = is_overdue(a)
    a["unassigned"] = a["responsible_id"] is None and a["status"] in OPEN
    a["status_label"] = STATUSES.get(a["status"], a["status"])
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


def notify(user_id: int | None, text: str, link: str | None = None) -> None:
    if not user_id:
        return
    nid = db.ex("INSERT INTO notifications(user_id, text, link, created_at) VALUES(?,?,?,?)", (user_id, text, link, db.now_iso()))
    realtime.publish(user_id, {"type": "notification", "id": nid, "text": text, "link": link})


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


def route(a: dict, actor_id: int | None = None) -> dict | None:
    """Ответственный своей категории; если его нет или он неактивен — очередь администратора с меткой «Без ответственного»."""
    resp = None
    cat = db.one("SELECT * FROM categories WHERE id=?", (a["category_id"],)) if a["category_id"] else None
    if cat and cat["responsible_user_id"]:
        resp = db.one("SELECT * FROM users WHERE id=? AND active=1", (cat["responsible_user_id"],))
    if resp:
        db.ex("UPDATE appeals SET responsible_id=? WHERE id=?", (resp["id"], a["id"]))
        add_event(a["id"], actor_id, "assigned", {"responsible_id": resp["id"], "responsible": resp["name"], "auto": actor_id is None})
        notify(resp["id"], f"Новое обращение {a['number']}: {short(a['text'])}", f"/panel#/appeal/{a['id']}")
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
           ai: dict | None = None) -> dict:
    """ai — результат mf.ai.classify_appeal (категория подставлена ИИ или словарём): пишется событием ai_classified до маршрутизации."""
    if type not in TYPES:
        raise HTTPException(422, "Неверный тип обращения")
    if priority not in PRIORITIES:
        priority = "medium"
    if source not in SOURCES:
        source = "app"
    text = (text or "").strip()
    if len(text) < 5:
        raise HTTPException(422, "Опишите проблему или идею хотя бы в нескольких словах")
    if category_id and not db.one("SELECT 1 FROM categories WHERE id=?", (category_id,)):
        raise HTTPException(422, "Категория не найдена")
    if branch_id and not db.one("SELECT 1 FROM branches WHERE id=?", (branch_id,)):
        raise HTTPException(422, "Филиал не найден")
    if author:
        branch_id = branch_id or author["branch_id"]
        department_id = department_id or author["department_id"]
    number = next_number()
    aid = db.ex("""INSERT INTO appeals(number, type, category_id, branch_id, department_id, text, proposed_solution, priority,
                   status, is_anonymous, source, meeting_id, tracking_token, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,'new',?,?,?,?,?,?)""",
                (number, type, category_id, branch_id, department_id, text, (proposed_solution or "").strip() or None, priority,
                 1 if is_anonymous else 0, source, meeting_id, secrets.token_urlsafe(24), db.now_iso(), db.now_iso()))
    if author:
        db.ex("INSERT INTO appeal_authors(appeal_id, user_id) VALUES(?,?)", (aid, author["id"]))
    actor = None if (is_anonymous or not author) else author["id"]
    add_event(aid, actor, "created", {"source": source, "type": type, "anonymous": bool(is_anonymous)})
    if ai:
        add_event(aid, None, "ai_classified", {"engine": ai.get("engine"), "category_id": ai.get("category_id"), "category": ai.get("category"),
                                               "confidence": ai.get("confidence"), "priority": ai.get("priority"), "summary": ai.get("summary")})
    a = get(aid)
    route(a)
    realtime.publish_roles(("director", "admin"), {"type": "appeal_created", "id": aid, "number": number,
                                                   "branch_id": branch_id, "branch_code": a.get("branch_code")})
    return get(aid)


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
    if can_manage(a, user):
        return True
    if author_id(a["id"]) == user["id"]:
        return True
    if db.one("SELECT 1 FROM supports WHERE appeal_id=? AND user_id=?", (a["id"], user["id"])):
        return True
    return a["status"] == "done"   # лента «Что изменили» — открыта всем сотрудникам


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
        raise HTTPException(422, "Укажите, что сделано: это увидит автор и лента «Что изменили»")
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
    msg = f"{a['number']}: статус «{STATUSES[status]}»" + (f" — {text}" if text else "")
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
        notify(author_id(appeal_id), f"{a['number']}: комментарий — {short(text, 80)}", f"/app#/appeal/{appeal_id}")
    return get(appeal_id)


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
    return count


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
                             "escalated_at", "supports", "age_hours", "overdue", "unassigned", "sla", "first_response_hours")}
    out["is_mine"] = bool(user and aid == user["id"])
    out["author"] = None
    if not public and aid and not a["is_anonymous"]:
        u = db.one("SELECT name, position FROM users WHERE id=?", (aid,))
        out["author"] = {"id": aid, "name": u["name"], "position": u["position"]} if u else None
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
    out["can_manage"] = bool(user and can_manage(a, user))
    if out["can_manage"]:
        nxt = list(TRANSITIONS[a["status"]])
        if a["type"] == "praise" and a["status"] == "new":
            nxt.append("closed")
        out["allowed_next"] = [{"code": s, "label": STATUSES[s]} for s in nxt]
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
            where.append(f"{col}=?"); params.append(f[key])
    if f.get("unassigned"):
        where.append("a.responsible_id IS NULL AND a.status IN ('new','review','clarify','in_progress')")
    if f.get("open"):
        where.append("a.status IN ('new','review','clarify','in_progress')")
    if f.get("days"):
        where.append("a.created_at >= ?"); params.append(db.iso(db.now() - timedelta(days=int(f["days"]))))
    if f.get("q"):
        where.append("(a.number LIKE ? OR a.text LIKE ?)"); params += [f"%{f['q']}%", f"%{f['q']}%"]
    sql = BASE_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY a.created_at DESC"
    rows = [decorate(r) for r in db.q(sql, params)]
    if f.get("overdue"):
        rows = [r for r in rows if r["overdue"]]
    keep = ("id", "number", "type", "type_label", "category", "category_id", "branch", "branch_code", "branch_id", "department",
            "status", "status_label", "responsible", "responsible_id", "priority", "priority_label", "created_at", "age_hours",
            "overdue", "unassigned", "supports", "is_anonymous", "source", "first_response_hours", "text")
    out = []
    for r in rows:
        o = {k: r.get(k) for k in keep}
        o["text"] = short(r["text"], 120)
        out.append(o)
    return out


def mine(user: dict) -> list[dict]:
    rows = db.q(BASE_SELECT + " WHERE a.id IN (SELECT appeal_id FROM appeal_authors WHERE user_id=?) ORDER BY a.created_at DESC", (user["id"],))
    out = []
    for r in rows:
        r = decorate(r)
        out.append({k: r.get(k) for k in ("id", "number", "type", "type_label", "category", "status", "status_label", "created_at",
                                            "supports", "is_anonymous", "resolution_text", "responsible")} | {"text": short(r["text"], 120)})
    return out


def changes(limit: int = 50) -> list[dict]:
    """Лента «Что изменили»: проблема → что сделали (закрывает A-020 из датасета)."""
    rows = db.q(BASE_SELECT + " WHERE a.status IN ('done','closed') AND a.resolution_text IS NOT NULL AND a.type != 'praise' "
                "ORDER BY COALESCE(a.closed_at, a.updated_at) DESC LIMIT ?", (limit,))
    return [{k: r.get(k) for k in ("id", "number", "type", "type_label", "category", "branch", "text", "resolution_text",
                                    "closed_at", "supports")} for r in rows]


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
    for b in branches:
        items = [r for r in rows if r["branch_id"] == b["id"]]
        cats: dict[str, int] = {}
        for r in items:
            if r["status"] in OPEN and r["category"]:
                cats[r["category"]] = cats.get(r["category"], 0) + 1
        top = max(cats.items(), key=lambda kv: kv[1])[0] if cats else None
        by_branch.append({"id": b["id"], "code": b["code"], "name": b["name"], "lat": b["lat"], "lng": b["lng"], **block(items), "top_category": top})
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
