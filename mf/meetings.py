"""Режим совещания (ТЗ v1.1 §6.2, §7, §8): запись или расшифровка → STT → разбор (LLM или запасной) → пункты на проверку
→ отправка: поручения исполнителям, идеи директору «На решение», связанным обращениям — событие discussed_at_meeting
с уведомлением автору и поддержавшим. Имена из расшифровки сопоставляются нечётко (mf/ai/names.py): при сомнении
исполнитель пуст + флаг «нет ответственного». Аудио удаляется сразу после расшифровки — хранится только текст."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from . import appeals, db, realtime
from .ai import fallback, llm, names, stt
from . import config
from .integrations import bitrix

log = logging.getLogger("mf.meetings")

KINDS = {"decision": "Решение", "task": "Поручение", "idea": "Идея", "linked": "Связанное обращение"}
STATUSES = {"processing": "Обрабатывается", "review": "На проверке", "sent": "Отправлено", "failed": "Ошибка"}
STAGES = {"stt": "Расшифровываем…", "analysis": "Разбираем…"}
TASK_STATUSES = {"draft": "Черновик", "assigned": "Назначено", "in_progress": "В работе", "done": "Выполнено"}
DECISIONS = {"pending": "На решении", "accepted": "Принято", "rejected": "Отклонено"}
FLAGS = {"no_due": "нет срока", "no_assignee": "нет ответственного", "unknown_appeal": "обращение не найдено", "no_category": "категория не определена"}

# ---------- сроки из речи ----------

WEEKDAYS = [("понедельник", 0), ("вторник", 1), ("сред", 2), ("четверг", 3), ("пятниц", 4), ("суббот", 5), ("воскресень", 6)]
MONTHS = [("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("мая", 5), ("май", 5), ("июн", 6), ("июл", 7), ("август", 8),
          ("сентябр", 9), ("октябр", 10), ("ноябр", 11), ("декабр", 12)]


def parse_due(text: str | None, base: date) -> str | None:
    """«до пятницы», «к 15 ноября», «завтра», «через неделю», «2026-11-14», «14.11» → ISO-дата или None."""
    if not text:
        return None
    t = text.lower().replace("ё", "е").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", t)
    if m:
        y = int(m[3]) if m[3] else base.year
        y = y + 2000 if y < 100 else y
        try:
            return date(y, int(m[2]), int(m[1])).isoformat()
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})(?:-го)?\s+([а-я]+)", t)
    if m:
        for stem, mon in MONTHS:
            if m[2].startswith(stem):
                y = base.year + (1 if mon < base.month else 0)
                try:
                    return date(y, mon, int(m[1])).isoformat()
                except ValueError:
                    return None
    if "послезавтра" in t:
        return (base + timedelta(days=2)).isoformat()
    if "завтра" in t:
        return (base + timedelta(days=1)).isoformat()
    if "сегодня" in t:
        return base.isoformat()
    m = re.search(r"через\s+(\d+)\s+д", t)
    if m:
        return (base + timedelta(days=int(m[1]))).isoformat()
    if "через недел" in t or "следующей недел" in t or "следующую недел" in t:
        return (base + timedelta(days=7)).isoformat()
    if "через месяц" in t:
        return (base + timedelta(days=30)).isoformat()
    if "конца недели" in t or "концу недели" in t:
        return (base + timedelta(days=(4 - base.weekday()) % 7)).isoformat()   # ближайшая пятница (сегодня, если пятница)
    if "конца месяца" in t or "концу месяца" in t:
        nxt = (base.replace(day=28) + timedelta(days=4)).replace(day=1)
        return (nxt - timedelta(days=1)).isoformat()
    for stem, wd in WEEKDAYS:
        if stem in t:
            delta = (wd - base.weekday()) % 7 or 7
            return (base + timedelta(days=delta)).isoformat()
    return None


# ---------- чтение ----------

def _row(meeting_id: int) -> dict:
    m = db.one("""SELECT m.*, u.name AS creator, b.name AS branch FROM meetings m LEFT JOIN users u ON u.id=m.created_by
                  LEFT JOIN branches b ON b.id=m.branch_id WHERE m.id=?""", (meeting_id,))
    if not m:
        raise HTTPException(404, "Совещание не найдено")
    return m


def can_view(m: dict, user: dict) -> bool:
    return user["role"] in ("director", "admin") or m["created_by"] == user["id"]


def _items(meeting_id: int) -> list[dict]:
    rows = db.q("""SELECT i.*, u.name AS assignee, u.position AS assignee_position, c.name AS category,
                   la.number AS linked_appeal_number, la.text AS linked_appeal_text, la.status AS linked_appeal_status,
                   ca.number AS created_appeal_number
                   FROM meeting_items i LEFT JOIN users u ON u.id=i.assignee_id LEFT JOIN categories c ON c.id=i.category_id
                   LEFT JOIN appeals la ON la.id=i.linked_appeal_id LEFT JOIN appeals ca ON ca.id=i.created_appeal_id
                   WHERE i.meeting_id=? ORDER BY i.sort, i.id""", (meeting_id,))
    for r in rows:
        r["flags"] = json.loads(r["flags"] or "[]")
        r["candidates"] = json.loads(r["candidates"] or "[]")
        r["flag_labels"] = [FLAGS.get(f, f) for f in r["flags"]]
        r["kind_label"] = KINDS.get(r["kind"], r["kind"])
        r["task_status_label"] = TASK_STATUSES.get(r["task_status"]) if r["task_status"] else None
        r["overdue"] = bool(r["kind"] == "task" and r["due_date"] and r["due_date"] < db.now().date().isoformat() and r["task_status"] in ("assigned", "in_progress"))
        r["director_decision_label"] = DECISIONS.get(r["director_decision"]) if r["director_decision"] else None
        if r["linked_appeal_text"]:
            r["linked_appeal_text"] = appeals.short(r["linked_appeal_text"], 100)
    return rows


def view(meeting_id: int, user: dict) -> dict:
    m = _row(meeting_id)
    if not can_view(m, user):
        raise HTTPException(403, "Это совещание вам недоступно")
    items = _items(meeting_id)
    out = {k: m.get(k) for k in ("id", "title", "status", "stage", "created_by", "creator", "branch_id", "branch", "recorded_at",
                                 "duration_sec", "transcript", "summary", "stt_engine", "llm_engine", "error", "sent_at", "language",
                                 "created_at")}
    out["demo"] = bool(m["demo"])
    out["fallback"] = m["llm_engine"] == fallback.ENGINE
    out["status_label"] = STATUSES.get(m["status"], m["status"])
    out["stage_label"] = STAGES.get(m["stage"]) if m["status"] == "processing" else None
    out["open_questions"] = json.loads(m["open_questions"] or "[]")
    out["items"] = items
    out["can_edit"] = m["status"] == "review" and (m["created_by"] == user["id"] or user["role"] in ("director", "admin"))
    out["counts"] = _counts(items)
    return out


def _counts(items: list[dict]) -> dict:
    live = [i for i in items if not i["removed"]]
    tasks = [i for i in live if i["kind"] == "task"]
    ideas = [i for i in live if i["kind"] == "idea"]
    today = db.now().date().isoformat()
    return {"decisions": sum(1 for i in live if i["kind"] == "decision"), "tasks": len(tasks),
            "tasks_done": sum(1 for i in tasks if i["task_status"] == "done"),
            "tasks_overdue": sum(1 for i in tasks if i["due_date"] and i["due_date"] < today and i["task_status"] in ("assigned", "in_progress")), "ideas": len(ideas),
            "ideas_accepted": sum(1 for i in ideas if i["director_decision"] == "accepted"),
            "ideas_pending": sum(1 for i in ideas if i["director_decision"] == "pending"),
            "ideas_rejected": sum(1 for i in ideas if i["director_decision"] == "rejected"),
            "linked": sum(1 for i in live if i["kind"] == "linked"),
            "flags": sum(len(i["flags"]) for i in live if i["kind"] == "task")}


def list_for(user: dict, overdue_only: bool = False) -> list[dict]:
    where, params = "", ()
    if user["role"] == "responsible":
        where, params = " WHERE m.created_by=?", (user["id"],)
    rows = db.q("""SELECT m.*, u.name AS creator, b.name AS branch FROM meetings m LEFT JOIN users u ON u.id=m.created_by
                   LEFT JOIN branches b ON b.id=m.branch_id""" + where + " ORDER BY m.id DESC", params)
    out = []
    for m in rows:
        items = _items(m["id"])
        out.append({"id": m["id"], "title": m["title"], "status": m["status"], "status_label": STATUSES.get(m["status"], m["status"]),
                    "stage": m["stage"], "created_at": m["created_at"], "sent_at": m["sent_at"], "creator": m["creator"], "branch": m["branch"],
                    "summary_line": appeals.short(m["summary"] or "", 140) if m["summary"] else None, "demo": bool(m["demo"]),
                    "fallback": m["llm_engine"] == fallback.ENGINE, "error": m["error"], "counts": _counts(items)})
    if overdue_only:
        out = [m for m in out if m["counts"]["tasks_overdue"]]
    return out


# ---------- создание и обработка ----------

def create(user: dict, title: str | None, *, transcript: str | None = None, audio_path: Path | None = None,
           duration_sec: int | None = None) -> int:
    title = (title or "").strip() or f"Планёрка {db.now().strftime('%d.%m.%Y')}"
    mid = db.ex("""INSERT INTO meetings(title, created_by, branch_id, recorded_at, duration_sec, transcript, status, stage, audio_path, created_at)
                   VALUES(?,?,?,?,?,?,'processing',?,?,?)""",
                (title, user["id"], user["branch_id"], db.now_iso(), duration_sec, (transcript or "").strip() or None,
                 "stt" if audio_path else "analysis", str(audio_path) if audio_path else None, db.now_iso()))
    return mid


def _fail(mid: int, msg: str) -> None:
    db.ex("UPDATE meetings SET status='failed', stage=NULL, error=? WHERE id=?", (msg[:500], mid))
    m = _row(mid)
    realtime.publish(m["created_by"], {"type": "meeting_updated", "id": mid, "status": "failed"})


def process(mid: int) -> None:
    """Синхронно (в threadpool): STT при наличии аудио → разбор → пункты → status=review. Ошибка → status=failed + текст."""
    m = _row(mid)
    transcript = m["transcript"]
    try:
        if m["audio_path"]:
            path = Path(m["audio_path"])
            try:
                r = stt.transcribe(path)
                transcript = r["text"]
                db.ex("UPDATE meetings SET transcript=?, stt_engine=?, language=?, duration_sec=COALESCE(duration_sec, ?), stage='analysis' WHERE id=?",
                      (transcript, r["engine"], r.get("language"), int(r.get("duration") or 0) or None, mid))
                realtime.publish(m["created_by"], {"type": "meeting_updated", "id": mid, "status": "processing", "stage": "analysis"})
            finally:
                path.unlink(missing_ok=True)   # аудио не храним
                db.ex("UPDATE meetings SET audio_path=NULL WHERE id=?", (mid,))
        if not transcript or len(transcript.strip()) < 10:
            raise ValueError("Расшифровка пустая — запись не распознана. Попробуйте ещё раз или вставьте текст.")
        analyze(mid, transcript)
    except Exception as e:   # noqa: BLE001
        log.exception("совещание %s", mid)
        _fail(mid, f"{e}")


def _context():
    users = db.q("""SELECT u.id, u.name, u.role, u.position, b.name AS branch, d.name AS department FROM users u
                    LEFT JOIN branches b ON b.id=u.branch_id LEFT JOIN departments d ON d.id=u.department_id WHERE u.active=1""")
    open_appeals = [{"id": a["id"], "number": a["number"], "text": appeals.short(a["text"], 160)} for a in
                    db.q("SELECT id, number, text FROM appeals WHERE status IN ('new','review','clarify','in_progress') ORDER BY id")]
    categories = db.q("""SELECT c.id, c.name, CASE WHEN u.id IS NULL THEN NULL ELSE u.name || ', ' || COALESCE(u.position, u.role) END AS responsible
                         FROM categories c LEFT JOIN users u ON u.id=c.responsible_user_id AND u.active=1 ORDER BY c.id""")
    return users, open_appeals, categories


def analyze(mid: int, transcript: str) -> None:
    users, open_appeals, categories = _context()
    error = None
    result = None
    if llm.available():
        try:
            result = llm.analyze_meeting(transcript, users, open_appeals, categories)
        except llm.LLMError as e:
            error = f"LLM: {e} — показан запасной разбор"
            log.warning("совещание %s: %s", mid, error)
    if result is None:
        result = fallback.analyze_meeting(transcript, users, open_appeals)
    db.ex("DELETE FROM meeting_items WHERE meeting_id=?", (mid,))
    base = db.now().date()
    sort = 0
    for text in result.get("decisions") or []:
        if isinstance(text, dict):
            text = text.get("text") or ""
        if str(text).strip():
            sort += 1
            db.ex("INSERT INTO meeting_items(meeting_id, kind, text, sort, flags) VALUES(?,?,?,?,'[]')", (mid, "decision", str(text).strip(), sort))
    assignable = [u for u in users if u["role"] in appeals.STAFF or True]   # поручить можно любому сотруднику
    for t in result.get("tasks") or []:
        sort += 1
        m = names.match(t.get("assignee_name"), assignable)
        due_text = t.get("due")
        due = parse_due(due_text, base)
        flags = []
        if not due:
            flags.append("no_due")
        if not m["user"]:
            flags.append("no_assignee")
        db.ex("""INSERT INTO meeting_items(meeting_id, kind, text, assignee_id, assignee_name, candidates, due_date, due_text, quote, flags, task_status, sort)
                 VALUES(?,?,?,?,?,?,?,?,?,?,'draft',?)""",
              (mid, "task", t["text"].strip(), m["user"]["id"] if m["user"] else None, t.get("assignee_name"),
               json.dumps(m["candidates"], ensure_ascii=False), due, due_text, t.get("quote"), json.dumps(flags), sort))
    cat_by_name = {c["name"]: c["id"] for c in categories}
    for i in result.get("ideas") or []:
        sort += 1
        cid = cat_by_name.get(i.get("category") or "")
        flags = []
        if not cid:
            cid = fallback.classify(i["text"], categories)["category_id"]
        if not cid:
            flags.append("no_category")
        typ = i.get("type") if i.get("type") in ("problem", "suggestion") else "suggestion"
        db.ex("""INSERT INTO meeting_items(meeting_id, kind, text, type, category_id, voiced_by, flags, sort) VALUES(?,?,?,?,?,?,?,?)""",
              (mid, "idea", i["text"].strip(), typ, cid, i.get("voiced_by"), json.dumps(flags), sort))
    by_number = {a["number"]: a["id"] for a in open_appeals}
    all_numbers = {a["number"]: a["id"] for a in db.q("SELECT id, number FROM appeals")}
    for la in result.get("linked_appeals") or []:
        sort += 1
        number = str(la.get("number") or "").upper().strip()
        aid = by_number.get(number) or all_numbers.get(number)
        flags = [] if aid else ["unknown_appeal"]
        db.ex("""INSERT INTO meeting_items(meeting_id, kind, text, linked_appeal_id, linked_number, flags, sort) VALUES(?,?,?,?,?,?,?)""",
              (mid, "linked", (la.get("decision") or "Обсуждалось на совещании").strip(), aid, number, json.dumps(flags), sort))
    db.ex("""UPDATE meetings SET summary=?, open_questions=?, llm_engine=?, demo=?, status='review', stage=NULL, error=? WHERE id=?""",
          (result.get("summary") or "", json.dumps(result.get("open_questions") or [], ensure_ascii=False), result.get("engine"),
           1 if result.get("demo") else 0, error, mid))
    m = _row(mid)
    realtime.publish(m["created_by"], {"type": "meeting_updated", "id": mid, "status": "review"})


# ---------- правка пунктов (экран разбора) ----------

def _editable(meeting_id: int, user: dict) -> dict:
    m = _row(meeting_id)
    if not can_view(m, user):
        raise HTTPException(403, "Это совещание вам недоступно")
    if m["status"] != "review":
        raise HTTPException(409, f"Совещание в статусе «{STATUSES.get(m['status'])}» — править нельзя")
    return m


def _item(meeting_id: int, item_id: int) -> dict:
    i = db.one("SELECT * FROM meeting_items WHERE id=? AND meeting_id=?", (item_id, meeting_id))
    if not i:
        raise HTTPException(404, "Пункт не найден")
    return i


def update_item(meeting_id: int, item_id: int, user: dict, patch: dict) -> dict:
    _editable(meeting_id, user)
    i = _item(meeting_id, item_id)
    sets, params = [], []
    if "text" in patch and patch["text"] is not None:
        text = str(patch["text"]).strip()
        if not text:
            raise HTTPException(422, "Пустой текст пункта")
        sets.append("text=?"); params.append(text)
    if "removed" in patch and patch["removed"] is not None:
        sets.append("removed=?"); params.append(1 if patch["removed"] else 0)
    flags = json.loads(i["flags"] or "[]")
    if i["kind"] == "task":
        if "assignee_id" in patch:
            aid = patch["assignee_id"]
            if aid:
                if not db.one("SELECT 1 FROM users WHERE id=? AND active=1", (aid,)):
                    raise HTTPException(404, "Исполнитель не найден")
                flags = [f for f in flags if f != "no_assignee"]
            else:
                aid = None
                if "no_assignee" not in flags:
                    flags.append("no_assignee")
            sets.append("assignee_id=?"); params.append(aid)
        if "due_date" in patch:
            due = (patch["due_date"] or "").strip() or None
            if due:
                try:
                    date.fromisoformat(due)
                except ValueError:
                    raise HTTPException(422, "Срок — дата в формате ГГГГ-ММ-ДД")
                flags = [f for f in flags if f != "no_due"]
            elif "no_due" not in flags:
                flags.append("no_due")
            sets.append("due_date=?"); params.append(due)
    if i["kind"] == "idea" and "category_id" in patch:
        cid = patch["category_id"] or None
        if cid and not db.one("SELECT 1 FROM categories WHERE id=?", (cid,)):
            raise HTTPException(404, "Категория не найдена")
        flags = [f for f in flags if f != "no_category"] if cid else flags + (["no_category"] if "no_category" not in flags else [])
        sets.append("category_id=?"); params.append(cid)
    if i["kind"] == "linked" and "linked_appeal_id" in patch:
        la = patch["linked_appeal_id"] or None
        row = db.one("SELECT number FROM appeals WHERE id=?", (la,)) if la else None
        if la and not row:
            raise HTTPException(404, "Обращение не найдено")
        flags = [f for f in flags if f != "unknown_appeal"] if la else flags
        sets += ["linked_appeal_id=?", "linked_number=?"]; params += [la, row["number"] if row else i["linked_number"]]
    sets.append("flags=?"); params.append(json.dumps(flags))
    params.append(item_id)
    db.ex(f"UPDATE meeting_items SET {', '.join(sets)} WHERE id=?", params)
    return view(meeting_id, user)


def add_item(meeting_id: int, user: dict, kind: str, text: str, **kw) -> dict:
    _editable(meeting_id, user)
    if kind not in KINDS:
        raise HTTPException(422, "Неизвестный тип пункта")
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "Пустой текст пункта")
    sort = (db.one("SELECT COALESCE(MAX(sort),0) AS s FROM meeting_items WHERE meeting_id=?", (meeting_id,))["s"] or 0) + 1
    flags = []
    if kind == "task":
        flags = (["no_due"] if not kw.get("due_date") else []) + (["no_assignee"] if not kw.get("assignee_id") else [])
    item_id = db.ex("""INSERT INTO meeting_items(meeting_id, kind, text, assignee_id, due_date, type, category_id, linked_appeal_id, linked_number, flags, task_status, sort)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (meeting_id, kind, text, kw.get("assignee_id"), kw.get("due_date"), kw.get("type") or ("suggestion" if kind == "idea" else None),
                     kw.get("category_id"), kw.get("linked_appeal_id"),
                     (db.one("SELECT number FROM appeals WHERE id=?", (kw["linked_appeal_id"],)) or {}).get("number") if kw.get("linked_appeal_id") else None,
                     json.dumps(flags), "draft" if kind == "task" else None, sort))
    return view(meeting_id, user)


# ---------- отправка (ТЗ §6.2 п. 5) ----------

def send(meeting_id: int, user: dict) -> dict:
    m = _editable(meeting_id, user)
    items = [i for i in _items(meeting_id) if not i["removed"]]
    if not items:
        raise HTTPException(422, "Нечего отправлять — все пункты убраны")
    directors = [u["id"] for u in db.q("SELECT id FROM users WHERE role='director' AND active=1")]
    title = m["title"]
    sent_tasks = sent_ideas = sent_linked = 0
    for i in items:
        if i["kind"] == "task":
            db.ex("UPDATE meeting_items SET task_status='assigned' WHERE id=?", (i["id"],))
            if i["assignee_id"]:
                due = f" — срок {i['due_date']}" if i["due_date"] else " — срок не назван"
                appeals.notify(i["assignee_id"], f"Поручение с совещания «{title}»: {appeals.short(i['text'], 90)}{due}", "/app#/tasks")
                sent_tasks += 1
                tid = bitrix.create_task(i["assignee_id"], appeals.short(i["text"], 120), f"Поручение с совещания «{title}».\n{i['text']}\n\n{config.PUBLIC_URL}/app#/tasks", i["due_date"])
                if tid:   # по желанию (BITRIX_TASKS=1): поручение → задача Битрикса со ссылкой обратно
                    db.ex("UPDATE meeting_items SET bitrix_task_id=? WHERE id=?", (tid, i["id"]))
        elif i["kind"] == "idea":
            db.ex("UPDATE meeting_items SET director_decision='pending' WHERE id=?", (i["id"],))
            for d in directors:
                appeals.notify(d, f"На решение: идея с совещания «{title}» — {appeals.short(i['text'], 90)}", "/app#/decisions")
                realtime.publish(d, {"type": "idea_pending", "item_id": i["id"], "meeting_id": meeting_id})
            sent_ideas += 1
        elif i["kind"] == "linked" and i["linked_appeal_id"]:
            aid = i["linked_appeal_id"]
            a = appeals.get(aid)
            appeals.add_event(aid, user["id"], "discussed_at_meeting", {"text": i["text"], "meeting_id": meeting_id, "meeting_title": title})
            targets = {appeals.author_id(aid)} | {s["user_id"] for s in db.q("SELECT user_id FROM supports WHERE appeal_id=?", (aid,))}
            for uid in targets - {None, user["id"]}:
                appeals.notify(uid, f"{a['number']} обсудили на совещании: {appeals.short(i['text'], 100)}", f"/app#/appeal/{aid}")
            sent_linked += 1
    db.ex("UPDATE meetings SET status='sent', sent_at=? WHERE id=?", (db.now_iso(), meeting_id))
    realtime.publish_roles(("director", "admin"), {"type": "meeting_sent", "id": meeting_id})
    out = view(meeting_id, user)
    out["sent"] = {"tasks": sent_tasks, "ideas": sent_ideas, "linked": sent_linked}
    return out


# ---------- мои поручения ----------

def my_tasks(user: dict) -> list[dict]:
    rows = db.q("""SELECT i.*, m.title AS meeting_title, m.sent_at, mu.name AS meeting_creator FROM meeting_items i
                   JOIN meetings m ON m.id=i.meeting_id LEFT JOIN users mu ON mu.id=m.created_by
                   WHERE i.kind='task' AND i.removed=0 AND i.assignee_id=? AND m.status='sent'
                   ORDER BY CASE i.task_status WHEN 'done' THEN 1 ELSE 0 END, i.due_date IS NULL, i.due_date, i.id DESC""", (user["id"],))
    today = db.now().date().isoformat()
    for r in rows:
        r["flags"] = json.loads(r["flags"] or "[]")
        r["flag_labels"] = [FLAGS.get(f, f) for f in r["flags"]]
        r["task_status_label"] = TASK_STATUSES.get(r["task_status"], r["task_status"])
        r["overdue"] = bool(r["due_date"] and r["due_date"] < today and r["task_status"] != "done")
    return rows


def set_task_status(item_id: int, user: dict, status: str) -> dict:
    i = db.one("SELECT i.*, m.created_by, m.title FROM meeting_items i JOIN meetings m ON m.id=i.meeting_id WHERE i.id=? AND i.kind='task'", (item_id,))
    if not i:
        raise HTTPException(404, "Поручение не найдено")
    if i["assignee_id"] != user["id"] and i["created_by"] != user["id"] and user["role"] not in ("director", "admin"):
        raise HTTPException(403, "Это не ваше поручение")
    if status not in ("assigned", "in_progress", "done"):
        raise HTTPException(422, "Статус: assigned, in_progress или done")
    db.ex("UPDATE meeting_items SET task_status=?, done_at=? WHERE id=?", (status, db.now_iso() if status == "done" else None, item_id))
    if status == "done" and i["created_by"] and i["created_by"] != user["id"]:
        appeals.notify(i["created_by"], f"Поручение выполнено ({user['name']}): {appeals.short(i['text'], 90)}", f"/panel#/meetings/{i['meeting_id']}")
    return {"id": item_id, "task_status": status, "task_status_label": TASK_STATUSES[status]}


# ---------- «На решение» у директора ----------

def director_ideas(user: dict) -> dict:
    rows = db.q("""SELECT i.*, m.title AS meeting_title, m.sent_at, mu.name AS meeting_creator, c.name AS category, ca.number AS created_appeal_number,
                   du.name AS decided_by_name
                   FROM meeting_items i JOIN meetings m ON m.id=i.meeting_id LEFT JOIN users mu ON mu.id=m.created_by
                   LEFT JOIN categories c ON c.id=i.category_id LEFT JOIN appeals ca ON ca.id=i.created_appeal_id LEFT JOIN users du ON du.id=i.decided_by
                   WHERE i.kind='idea' AND i.removed=0 AND i.director_decision IS NOT NULL AND m.status='sent'
                   ORDER BY CASE i.director_decision WHEN 'pending' THEN 0 ELSE 1 END, i.id DESC""")
    for r in rows:
        r["source"] = "meeting"
        r["flags"] = json.loads(r["flags"] or "[]")
        r["flag_labels"] = [FLAGS.get(f, f) for f in r["flags"]]
        r["director_decision_label"] = DECISIONS.get(r["director_decision"], r["director_decision"])
        cat = db.one("SELECT u.name FROM categories c LEFT JOIN users u ON u.id=c.responsible_user_id WHERE c.id=?", (r["category_id"],)) if r["category_id"] else None
        r["category_responsible"] = cat["name"] if cat else None
        sent = db.parse(r["sent_at"])
        r["wait_days"] = round((db.now() - sent).total_seconds() / 86400, 1) if sent and r["director_decision"] == "pending" else None
    items = rows + appeals.director_queue()   # ТЗ v2: предложения из обращений («Нужно решение директора») — в той же очереди
    th = appeals.director_wait_days()
    for r in items:
        r["over_threshold"] = bool(r.get("wait_days") is not None and r["wait_days"] >= th)
    pending = sorted([r for r in items if r["director_decision"] == "pending"], key=lambda r: -(r.get("wait_days") or 0))
    decided = sorted([r for r in items if r["director_decision"] != "pending"], key=lambda r: r.get("decided_at") or "", reverse=True)[:30]
    return {"pending": pending, "decided": decided, "threshold_days": th, "over_threshold": sum(1 for r in pending if r["over_threshold"])}


def _idea(item_id: int) -> dict:
    i = db.one("SELECT i.*, m.created_by, m.title, m.status AS meeting_status FROM meeting_items i JOIN meetings m ON m.id=i.meeting_id WHERE i.id=? AND i.kind='idea'", (item_id,))
    if not i:
        raise HTTPException(404, "Идея не найдена")
    if i["director_decision"] != "pending":
        raise HTTPException(409, "По этой идее решение уже принято")
    return i


def accept_idea(item_id: int, user: dict, category_id: int | None = None) -> dict:
    """Принять → обращение type=suggestion/problem, source=meeting, автор — кто озвучил (если распознан), иначе ведущий совещания;
    маршрутизация по категории как у обычного обращения (ответственный получает уведомление)."""
    i = _idea(item_id)
    cid = category_id or i["category_id"]
    if not cid:
        raise HTTPException(422, "Укажите категорию — по ней обращение уйдёт ответственному")
    users = db.q("SELECT id, name FROM users WHERE active=1")
    voiced = names.match(i["voiced_by"], users)["user"] if i["voiced_by"] else None
    author = db.one("SELECT * FROM users WHERE id=?", (voiced["id"] if voiced else i["created_by"],))
    a = appeals.create(type=i["type"] or "suggestion", text=i["text"], category_id=cid, author=author, source="meeting", meeting_id=i["meeting_id"],
                       route_by_category=True)   # директор уже решил — сразу исполнителю по категории, минуя отдел развития
    db.ex("UPDATE meeting_items SET director_decision='accepted', decided_at=?, decided_by=?, created_appeal_id=?, category_id=? WHERE id=?",
          (db.now_iso(), user["id"], a["id"], cid, item_id))
    appeals.add_event(a["id"], user["id"], "comment", {"text": f"Идея принята директором на совещании «{i['title']}»"})
    for uid in {i["created_by"], author["id"]} - {user["id"], None}:
        appeals.notify(uid, f"Директор принял идею с совещания «{i['title']}» → обращение {a['number']} у {a['responsible'] or 'администратора'}", f"/app#/appeal/{a['id']}")
    return {"item_id": item_id, "decision": "accepted", "appeal": appeals.view(appeals.get(a["id"]), user)}


def reject_idea(item_id: int, user: dict, reason: str) -> dict:
    i = _idea(item_id)
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(422, "Отклонение требует причины — её увидит ведущий совещания")
    db.ex("UPDATE meeting_items SET director_decision='rejected', director_comment=?, decided_at=?, decided_by=? WHERE id=?",
          (reason, db.now_iso(), user["id"], item_id))
    users = db.q("SELECT id, name FROM users WHERE active=1")
    voiced = names.match(i["voiced_by"], users)["user"] if i["voiced_by"] else None
    for uid in {i["created_by"], voiced["id"] if voiced else None} - {user["id"], None}:
        appeals.notify(uid, f"Директор отклонил идею с совещания «{i['title']}»: {appeals.short(reason, 100)}", f"/panel#/meetings/{i['meeting_id']}")
    return {"item_id": item_id, "decision": "rejected", "reason": reason}


# ---------- контроль поручений (ТЗ v2 §2.4) ----------

def check_tasks() -> dict:
    """Раз в минуту из фонового цикла: за день до срока — напоминание исполнителю; после срока — метка «Просрочено»
    и уведомление тому, кто проводил совещание. Каждое поручение напоминается и помечается один раз."""
    today = db.now().date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    reminded = overdue = 0
    rows = db.q("""SELECT i.*, m.title, m.created_by FROM meeting_items i JOIN meetings m ON m.id=i.meeting_id
                   WHERE i.kind='task' AND i.removed=0 AND m.status='sent' AND i.due_date IS NOT NULL AND i.task_status IN ('assigned','in_progress')""")
    for t in rows:
        if t["due_date"] == tomorrow and not t["reminded_at"] and t["assignee_id"]:
            db.ex("UPDATE meeting_items SET reminded_at=? WHERE id=?", (db.now_iso(), t["id"]))
            appeals.notify(t["assignee_id"], f"Завтра срок поручения с совещания «{t['title']}»: {appeals.short(t['text'], 90)}", "/app#/tasks")
            reminded += 1
        if t["due_date"] < today.isoformat() and not t["overdue_at"]:
            db.ex("UPDATE meeting_items SET overdue_at=? WHERE id=?", (db.now_iso(), t["id"]))
            who = db.one("SELECT name FROM users WHERE id=?", (t["assignee_id"],)) if t["assignee_id"] else None
            appeals.notify(t["created_by"], f"Просрочено поручение ({who['name'] if who else 'без исполнителя'}, срок {t['due_date']}): {appeals.short(t['text'], 80)}",
                           f"/panel#/meetings/{t['meeting_id']}")
            if t["assignee_id"]:
                appeals.notify(t["assignee_id"], f"Поручение просрочено (срок {t['due_date']}): {appeals.short(t['text'], 90)}", "/app#/tasks")
            overdue += 1
    if overdue:
        realtime.publish_roles(("director", "admin"), {"type": "tasks_overdue", "count": overdue})
    return {"reminded": reminded, "overdue": overdue}


def overdue_summary(user: dict) -> dict:
    """Строка для главной директора: «Поручения с совещаний: просрочено N» (ответственному — по его совещаниям)."""
    today = db.now().date().isoformat()
    where = "" if user["role"] in ("director", "admin") else " AND m.created_by=?"
    params = () if not where else (user["id"],)
    row = db.one(f"""SELECT COUNT(*) AS n FROM meeting_items i JOIN meetings m ON m.id=i.meeting_id
                     WHERE i.kind='task' AND i.removed=0 AND m.status='sent' AND i.task_status IN ('assigned','in_progress') AND i.due_date < ?{where}""",
                 (today, *params))
    total = db.one(f"""SELECT COUNT(*) AS n FROM meeting_items i JOIN meetings m ON m.id=i.meeting_id
                       WHERE i.kind='task' AND i.removed=0 AND m.status='sent' AND i.task_status IN ('assigned','in_progress'){where}""", params)
    return {"overdue": row["n"], "open": total["n"]}
