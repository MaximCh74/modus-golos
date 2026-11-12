"""Демо-вход «Войти как…» без паролей (ТЗ v1.1, раздел 3; в пилоте — Битрикс24 или корпоративная учётка).
Права проверяются на уровне API, а не только скрытием кнопок."""
from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from . import db

COOKIE = "mf_sid"
FRAME_COOKIE = "mf_frame"   # признак сессии внутри iframe Битрикс24 (партиционированная cookie): для таких запросов разрешаем встраивание
ROLES = ("employee", "responsible", "director", "admin")
STAFF = ("responsible", "director", "admin")
ROLE_LABEL = {"employee": "Сотрудник", "responsible": "Ответственный", "director": "Директор", "admin": "Администратор"}


def display_name(user: dict) -> str:
    """Как система обращается к человеку: к директору — по имени и отчеству, как он записан («Сергей Михайлович»), к остальным — по имени."""
    return user["name"] if user.get("role") == "director" else user["name"].split()[0]


def user_by_id(user_id: int) -> dict | None:
    return db.one("SELECT * FROM users WHERE id=? AND active=1", (user_id,))


def current(request: Request) -> dict | None:
    """Сессия: заголовок Authorization: Bearer (внутри iframe Битрикс24 — cookie третьей стороны может не дойти), параметр ?s= (первое
    открытие во фрейме и SSE, где заголовок не поставить), иначе обычная cookie."""
    token = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    token = token or request.query_params.get("s") or request.cookies.get(COOKIE)
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


def set_cookie(response, token: str, cross_site: bool = False) -> None:
    """Сессионная cookie. cross_site=True — вход из iframe Битрикс24: браузер отдаёт cookie третьей стороне только с SameSite=None; Secure."""
    if cross_site:
        # CHIPS: Partitioned — cookie привязана к паре «наш сайт внутри портала», браузеры (Chrome, Firefox) отдают её во фрейме;
        # Starlette не знает атрибут Partitioned, поэтому заголовок собирается вручную
        age = 30 * 86400
        response.headers.append("set-cookie", f"{COOKIE}={token}; Path=/; Max-Age={age}; HttpOnly; Secure; SameSite=None; Partitioned")
        response.headers.append("set-cookie", f"{FRAME_COOKIE}=1; Path=/; Max-Age={age}; Secure; SameSite=None; Partitioned")
    else:
        response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=30 * 86400, path="/")


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
