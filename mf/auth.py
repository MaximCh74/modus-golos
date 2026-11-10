"""Демо-вход «Войти как…» без паролей (ТЗ v1.1, раздел 3; в пилоте — Битрикс24 или корпоративная учётка).
Права проверяются на уровне API, а не только скрытием кнопок."""
from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from . import db

COOKIE = "mf_sid"
ROLES = ("employee", "responsible", "director", "admin")
STAFF = ("responsible", "director", "admin")
ROLE_LABEL = {"employee": "Сотрудник", "responsible": "Ответственный", "director": "Директор", "admin": "Администратор"}


def user_by_id(user_id: int) -> dict | None:
    return db.one("SELECT * FROM users WHERE id=? AND active=1", (user_id,))


def current(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    return db.one("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token=? AND u.active=1", (token,))


def require(request: Request, *roles: str) -> dict:
    user = current(request)
    if not user:
        raise HTTPException(401, "Нужно войти")
    if roles and user["role"] not in roles:
        raise HTTPException(403, "Недостаточно прав")
    return user


def login(user_id: int) -> str:
    if not user_by_id(user_id):
        raise HTTPException(404, "Пользователь не найден")
    token = secrets.token_urlsafe(32)
    db.ex("INSERT INTO sessions(token, user_id, created_at) VALUES(?, ?, ?)", (token, user_id, db.now_iso()))
    return token


def logout(token: str | None) -> None:
    if token:
        db.ex("DELETE FROM sessions WHERE token=?", (token,))


def public(user: dict) -> dict:
    out = {k: user[k] for k in ("id", "name", "role", "branch_id", "department_id", "position")}
    out["role_label"] = ROLE_LABEL.get(user["role"], user["role"])
    b = db.one("SELECT name FROM branches WHERE id=?", (user["branch_id"],))
    d = db.one("SELECT name FROM departments WHERE id=?", (user["department_id"],))
    out["branch"] = b["name"] if b else None
    out["department"] = d["name"] if d else None
    return out
