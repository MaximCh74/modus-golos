"""Демо-состояние одной командой (этап 5): снапшот базы в demo/fixtures/mf-demo.db, возврат к нему за секунды без вызовов ИИ
(«Коротко», сводка и векторы кластеров лежат в самом снапшоте) и сдвиг всех дат так, чтобы «сегодня» снапшота стало текущим
днём — возраст ожиданий, сроки и просрочки сохраняют смысл на любую дату выступления."""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

from . import config, db

FIXTURE = Path(__file__).resolve().parent.parent / "demo" / "fixtures" / "mf-demo.db"
# таблица, колонка, формат: iso — "YYYY-MM-DDTHH:MM:SSZ", date — "YYYY-MM-DD"
SHIFT = [
    ("appeals", "created_at", "iso"), ("appeals", "updated_at", "iso"), ("appeals", "first_response_at", "iso"), ("appeals", "closed_at", "iso"),
    ("appeals", "escalated_at", "iso"), ("appeals", "director_requested_at", "iso"), ("appeals", "director_decided_at", "iso"),
    ("appeals", "last_news_at", "iso"), ("appeals", "news_reminded_at", "iso"), ("appeals", "brief_at", "iso"),
    ("appeal_events", "created_at", "iso"), ("supports", "created_at", "iso"), ("thanks", "created_at", "iso"), ("attachments", "created_at", "iso"),
    ("meetings", "recorded_at", "iso"), ("meetings", "created_at", "iso"), ("meetings", "sent_at", "iso"),
    ("meeting_items", "due_date", "date"), ("meeting_items", "decided_at", "iso"), ("meeting_items", "done_at", "iso"),
    ("meeting_items", "reminded_at", "iso"), ("meeting_items", "overdue_at", "iso"),
    ("points_ledger", "created_at", "iso"), ("reward_claims", "created_at", "iso"), ("reward_claims", "decided_at", "iso"),
    ("notifications", "created_at", "iso"), ("notifications", "read_at", "iso"), ("sessions", "created_at", "iso"),
]
TRIGGERS = ("t_events_no_update", "t_events_no_delete", "t_ledger_no_update", "t_ledger_no_delete")


def fingerprint(path: Path | None = None) -> str:
    """Отпечаток состояния: количества обращений, событий, пунктов совещаний, поддержек, «спасибо», совещаний, уведомлений и последний номер
    (без дат — после reset они сдвинуты на «сегодня»)."""
    c = sqlite3.connect(str(path or config.DB_PATH))
    try:
        parts = [c.execute(q).fetchone()[0] for q in (
            "SELECT COUNT(*) FROM appeals", "SELECT COUNT(*) FROM appeal_events", "SELECT COUNT(*) FROM meeting_items",
            "SELECT COUNT(*) FROM supports", "SELECT COUNT(*) FROM thanks", "SELECT COALESCE(MAX(number),'') FROM appeals",
            "SELECT COUNT(*) FROM meetings", "SELECT COUNT(*) FROM notifications")]
    finally:
        c.close()
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


def snapshot(dest: Path = FIXTURE) -> dict:
    """Снять снапшот текущей базы (безопасно при работающем сервере — через sqlite backup). Аудио в базе нет — только текст."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = db.conn()
    now = db.now_iso()
    src.execute("INSERT INTO meta(key, value) VALUES('snapshot_at', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now,))
    src.commit()
    out = sqlite3.connect(str(dest))
    try:
        src.backup(out)
        out.execute("DELETE FROM sessions")   # чужие демо-сессии в снапшот не нужны
        out.commit()
    finally:
        out.close()
    return {"path": str(dest), "snapshot_at": now, "fingerprint": fingerprint(dest), "size_kb": dest.stat().st_size // 1024}


def _shift_dates(c: sqlite3.Connection, delta: timedelta) -> int:
    n = 0
    for t in TRIGGERS:
        c.execute(f"DROP TRIGGER IF EXISTS {t}")
    for table, col, kind in SHIFT:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            continue
        rows = c.execute(f"SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL").fetchall()
        for rowid, val in rows:
            try:
                if kind == "iso":
                    nv = db.iso(db.parse(val) + delta)
                else:
                    from datetime import date
                    nv = (date.fromisoformat(val) + timedelta(days=round(delta.total_seconds() / 86400))).isoformat()
            except (ValueError, TypeError):
                continue
            c.execute(f"UPDATE {table} SET {col}=? WHERE rowid=?", (nv, rowid))
            n += 1
    c.executescript(db.SCHEMA)   # вернуть триггеры append-only
    return n


def reset(src: Path = FIXTURE, shift: bool = True) -> dict:
    """Вернуть базу в демо-состояние: закрыть соединение, подменить файл снапшотом, сдвинуть даты на «сегодня», открыть заново.
    Без вызовов ИИ: «Коротко», сводка и эмбеддинги лежат в снапшоте."""
    if not src.is_file():
        raise FileNotFoundError(f"нет снапшота {src} — сначала tools/demo_snapshot.sh")
    db.reset()   # закрывает соединение и удаляет mf.db, -wal, -shm
    shutil.copy(src, config.DB_PATH)
    c = sqlite3.connect(str(config.DB_PATH))
    try:
        snap_at = c.execute("SELECT value FROM meta WHERE key='snapshot_at'").fetchone()
        shifted = 0
        if shift and snap_at:
            delta = db.now() - db.parse(snap_at[0])
            shifted = _shift_dates(c, delta)
            c.execute("UPDATE meta SET value=? WHERE key='snapshot_at'", (db.now_iso(),))
        c.execute("DELETE FROM sessions")
        c.commit()
    finally:
        c.close()
    db.conn()
    return {"ok": True, "fingerprint": fingerprint(), "shifted": shifted, "appeals": db.one("SELECT COUNT(*) AS n FROM appeals")["n"]}


def is_demo_state() -> dict:
    """Проверка «перед выступлением»: база совпадает со снапшотом и живые шаги сценария выполнимы с нуля."""
    checks = []
    fp_db = fingerprint()
    fp_fx = fingerprint(FIXTURE) if FIXTURE.is_file() else None
    checks.append({"name": "база = снапшот", "ok": fp_fx is not None and fp_db == fp_fx, "detail": f"{fp_db} / снапшот {fp_fx or 'нет'}"})
    a7 = db.one("SELECT id FROM appeals WHERE number='A-007'")
    sup = bool(a7 and db.one("SELECT 1 FROM supports WHERE appeal_id=? AND user_id=6", (a7["id"],)))
    checks.append({"name": "Сауле ещё не поддержала A-007", "ok": not sup, "detail": "поддержка уже есть" if sup else "ок"})
    pending = db.q("SELECT number, director_requested_at FROM appeals WHERE director_decision='pending'")
    ages = [(db.now() - db.parse(r["director_requested_at"])).days for r in pending]
    checks.append({"name": "в «На решение» есть предложения старше порога", "ok": any(a >= 7 for a in ages), "detail": ", ".join(f"{r['number']}: {a} дн" for r, a in zip(pending, ages)) or "пусто"})
    last = db.one("SELECT number FROM appeals ORDER BY id DESC LIMIT 1")["number"]
    nxt = f"A-{int(last.split('-')[1]) + 1:03d}"
    checks.append({"name": "следующий номер предсказуем", "ok": True, "detail": nxt})
    meet = db.one("SELECT COUNT(*) AS n FROM meetings WHERE status='sent'")["n"]
    checks.append({"name": "есть разобранная планёрка для показа", "ok": meet >= 1, "detail": f"{meet} шт."})
    # этап 8 §2: собственник не должен увидеть «решено 0»
    week = db.iso(db.now() - timedelta(days=7)); month = db.iso(db.now() - timedelta(days=30))
    d7 = db.one("SELECT COUNT(*) AS n FROM appeals WHERE status IN ('done','closed') AND type != 'praise' AND closed_at >= ?", (week,))["n"]
    checks.append({"name": "решено за 7 дней > 0", "ok": d7 > 0, "detail": f"{d7}"})
    per_city = db.q("""SELECT b.city, COUNT(a.id) AS n FROM branches b LEFT JOIN appeals a ON a.branch_id=b.id AND a.status IN ('done','closed') AND a.type != 'praise' AND a.closed_at >= ?
                       WHERE b.kind != 'field' GROUP BY b.id ORDER BY b.id""", (month,))
    checks.append({"name": "у каждого города решено за месяц > 0", "ok": all(r["n"] > 0 for r in per_city), "detail": ", ".join(f"{r['city']} {r['n']}" for r in per_city)})
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "next_number": nxt}
