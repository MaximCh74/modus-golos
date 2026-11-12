"""SQLite: соединение, схема, помощники. Журнал событий и журнал баллов — только добавление (триггеры)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS branches (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, city TEXT, country TEXT,
  lat REAL, lng REAL, is_hq INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS departments (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
  branch_id INTEGER, department_id INTEGER, manager_id INTEGER, position TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, responsible_user_id INTEGER, sla_first_response_hours INTEGER NOT NULL DEFAULT 48);

CREATE TABLE IF NOT EXISTS appeals (
  id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, type TEXT NOT NULL,
  category_id INTEGER, branch_id INTEGER, department_id INTEGER,
  text TEXT NOT NULL, proposed_solution TEXT, priority TEXT NOT NULL DEFAULT 'medium', status TEXT NOT NULL DEFAULT 'new',
  responsible_id INTEGER, is_anonymous INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'app',
  meeting_id INTEGER, cluster_id INTEGER, tracking_token TEXT UNIQUE NOT NULL, resolution_text TEXT,
  created_at TEXT NOT NULL, updated_at TEXT, first_response_at TEXT, closed_at TEXT, escalated_at TEXT);
-- связь с автором — отдельно: для анонимных обращений API не отдаёт её никому, кроме самого автора
CREATE TABLE IF NOT EXISTS appeal_authors (appeal_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS appeal_events (
  id INTEGER PRIMARY KEY, appeal_id INTEGER NOT NULL, actor_id INTEGER, kind TEXT NOT NULL, payload TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS supports (appeal_id INTEGER NOT NULL, user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (appeal_id, user_id));
CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY, appeal_id INTEGER NOT NULL, filename TEXT NOT NULL, stored TEXT NOT NULL, mime TEXT, size INTEGER, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS meetings (
  id INTEGER PRIMARY KEY, title TEXT, created_by INTEGER, branch_id INTEGER, recorded_at TEXT, duration_sec INTEGER,
  transcript TEXT, summary TEXT, status TEXT NOT NULL DEFAULT 'processing', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meeting_items (
  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
  assignee_id INTEGER, due_date TEXT, linked_appeal_id INTEGER, created_appeal_id INTEGER,
  task_status TEXT, director_decision TEXT, director_comment TEXT, quote TEXT, flags TEXT, voiced_by TEXT, category_id INTEGER, type TEXT);

CREATE TABLE IF NOT EXISTS points_ledger (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, appeal_id INTEGER, reason TEXT NOT NULL, amount INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rewards (id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT, cost_points INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS reward_claims (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, reward_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'requested', created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS thanks (appeal_id INTEGER NOT NULL, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (appeal_id, user_id));
CREATE TABLE IF NOT EXISTS appeal_embeddings (appeal_id INTEGER PRIMARY KEY, model TEXT NOT NULL, hash TEXT NOT NULL, vec TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, text TEXT NOT NULL, link TEXT, created_at TEXT NOT NULL, read_at TEXT);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL);
-- этап 8 §4: личные одноразовые приглашения для сотрудников без Битрикса (ссылка /i/<token> и QR)
CREATE TABLE IF NOT EXISTS invites (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, token TEXT UNIQUE NOT NULL, created_by INTEGER,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE INDEX IF NOT EXISTS ix_appeals_status ON appeals(status);
CREATE INDEX IF NOT EXISTS ix_appeals_resp ON appeals(responsible_id);
CREATE INDEX IF NOT EXISTS ix_events_appeal ON appeal_events(appeal_id);
CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id, read_at);
CREATE INDEX IF NOT EXISTS ix_ledger_user ON points_ledger(user_id);
CREATE INDEX IF NOT EXISTS ix_invites_user ON invites(user_id);

-- журналы только на добавление (ТЗ v1.1, раздел 14)
CREATE TRIGGER IF NOT EXISTS t_events_no_update BEFORE UPDATE ON appeal_events BEGIN SELECT RAISE(ABORT, 'appeal_events: append-only'); END;
CREATE TRIGGER IF NOT EXISTS t_events_no_delete BEFORE DELETE ON appeal_events BEGIN SELECT RAISE(ABORT, 'appeal_events: append-only'); END;
CREATE TRIGGER IF NOT EXISTS t_ledger_no_update BEFORE UPDATE ON points_ledger BEGIN SELECT RAISE(ABORT, 'points_ledger: append-only'); END;
CREATE TRIGGER IF NOT EXISTS t_ledger_no_delete BEFORE DELETE ON points_ledger BEGIN SELECT RAISE(ABORT, 'points_ledger: append-only'); END;
"""

# Колонки, добавленные после этапа 1: базы, созданные раньше, доводятся ALTER TABLE при старте (без пересоздания).
MIGRATIONS = [
    ("meetings", "stage", "TEXT"), ("meetings", "stt_engine", "TEXT"), ("meetings", "llm_engine", "TEXT"), ("meetings", "error", "TEXT"),
    ("meetings", "sent_at", "TEXT"), ("meetings", "open_questions", "TEXT"), ("meetings", "language", "TEXT"),
    ("meetings", "demo", "INTEGER NOT NULL DEFAULT 0"), ("meetings", "audio_path", "TEXT"),
    ("meeting_items", "assignee_name", "TEXT"), ("meeting_items", "due_text", "TEXT"), ("meeting_items", "removed", "INTEGER NOT NULL DEFAULT 0"),
    ("meeting_items", "sort", "INTEGER NOT NULL DEFAULT 0"), ("meeting_items", "candidates", "TEXT"), ("meeting_items", "decided_at", "TEXT"),
    ("meeting_items", "decided_by", "INTEGER"), ("meeting_items", "done_at", "TEXT"), ("meeting_items", "linked_number", "TEXT"),
    ("meeting_items", "reminded_at", "TEXT"), ("meeting_items", "overdue_at", "TEXT"),
    # ТЗ v2 (кастдев): командированные, путь предложения к директору
    ("branches", "kind", "TEXT NOT NULL DEFAULT 'office'"), ("appeals", "site_city", "TEXT"),
    ("categories", "suggestion_responsible_user_id", "INTEGER"),
    ("appeals", "director_request_text", "TEXT"), ("appeals", "director_requested_at", "TEXT"), ("appeals", "director_requested_by", "INTEGER"),
    ("appeals", "director_decision", "TEXT"), ("appeals", "director_comment", "TEXT"), ("appeals", "director_decided_at", "TEXT"),
    ("appeals", "director_decided_by", "INTEGER"),
    # этап 4: оценка автора, «Коротко», новости автору, аватарки, заявки на награды
    ("appeals", "author_urgency", "TEXT"), ("appeals", "author_scope", "TEXT"), ("appeals", "priority_manual", "INTEGER NOT NULL DEFAULT 0"),
    ("appeals", "brief", "TEXT"), ("appeals", "brief_engine", "TEXT"), ("appeals", "brief_at", "TEXT"),
    ("appeals", "last_news_at", "TEXT"), ("appeals", "news_reminded_at", "TEXT"), ("appeals", "input_mode", "TEXT"),
    ("users", "avatar", "TEXT"),
    ("reward_claims", "comment", "TEXT"), ("reward_claims", "decided_at", "TEXT"), ("reward_claims", "decided_by", "INTEGER"),
    # этап 6: Битрикс24 (сопоставление сотрудников по ID или почте, поручение → задача), команды директора
    ("users", "bitrix_id", "INTEGER"), ("users", "email", "TEXT"), ("meeting_items", "bitrix_task_id", "INTEGER"),
    ("users", "login", "TEXT"),   # этап 8: внутренний логин демо-директора (sergey)
    ("users", "phone", "TEXT"),   # этап 8: телефон (ручное добавление, склейка с Битриксом по телефону)
]

_conn: sqlite3.Connection | None = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(now())


def parse(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            if col not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        c.commit()
        _conn = c
    return _conn


def reset() -> None:
    """Снести базу целиком (повторный seed): журналы append-only, DELETE по ним запрещён триггерами."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
    for suffix in ("", "-wal", "-shm"):
        p = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
        if p.exists():
            p.unlink()


def use(data_dir) -> None:
    """Переключиться на другую папку данных (тесты): закрыть соединение, дальше conn() откроет новую базу."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
    config.set_data_dir(data_dir)


def q(sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, params).fetchall()]


def one(sql: str, params=()) -> dict | None:
    r = conn().execute(sql, params).fetchone()
    return dict(r) if r else None


def ex(sql: str, params=()) -> int:
    cur = conn().execute(sql, params)
    conn().commit()
    return cur.lastrowid


def setting(key: str, default=None):
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value) -> None:
    ex("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, json.dumps(value, ensure_ascii=False)))
