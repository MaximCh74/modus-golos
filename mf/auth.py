"""Демо-вход «Войти как…» без паролей (ТЗ v1.1, раздел 3; в пилоте — Битрикс24 или корпоративная учётка).
Права проверяются на уровне API, а не только скрытием кнопок."""
from __future__ import annotations

import contextvars
import os
import secrets

from fastapi import HTTPException, Request

from . import db

COOKIE = "mf_sid"
FRAME_COOKIE = "mf_frame"   # признак сессии внутри iframe Битрикс24 (партиционированная cookie): для таких запросов разрешаем встраивание
ROLES = ("employee", "responsible", "director", "admin")
STAFF = ("responsible", "director", "admin")
ROLE_LABEL = {"employee": "Сотрудник", "responsible": "Ответственный", "director": "Директор", "admin": "Администратор"}
# Аудит 12.11, F-03 (вариант А): «Войти как…» остаётся для жюри, но такие сессии помечены как демо. Снаружи (через туннель) им закрыты
# сброс и снапшот демо-базы, синхронизация Битрикса, импорт и правка сотрудников, приглашения, предпроверка; их действия не дублируются
# в Битрикс24. С ноутбука ведущего (http://localhost:8070, без заголовков Cloudflare) — всё как раньше. MF_DEMO_LOGIN=0 — демо-входа нет (пилот).
DEMO_REQUEST = contextvars.ContextVar("mf_demo_request", default=False)
DEMO_DENIED = ("В демо-входе это недоступно: сброс и снапшот демо-базы, Битрикс24, импорт и правка сотрудников, приглашения — "
               "только с ноутбука ведущего (http://localhost:8070) или после входа через Битрикс24")


def demo_login_enabled() -> bool:
    return os.environ.get("MF_DEMO_LOGIN", "1").strip() != "0"


def is_local(request: Request) -> bool:
    """Запрос с самого ноутбука: адрес петли и без заголовков Cloudflare (туннель добавляет их всегда, снаружи их не убрать)."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        return False
    hd = request.headers
    return not (hd.get("cf-connecting-ip") or hd.get("cf-ray") or hd.get("cdn-loop"))


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
    row = db.one("SELECT u.*, s.demo AS session_demo FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token=? AND u.active=1", (token,))
    if not row:
        return None
    demo = bool(row.pop("session_demo"))
    row["demo_restricted"] = demo and not is_local(request)
    if row["demo_restricted"]:
        DEMO_REQUEST.set(True)   # уведомления этого запроса не дублируются в Битрикс24 (bitrix.notify, bitrix.create_task)
    return row


def require(request: Request, *roles: str) -> dict:
    user = current(request)
    if not user:
        raise HTTPException(401, "Нужно войти")
    if roles and user["role"] not in roles:
        raise HTTPException(403, "Недостаточно прав")
    return user


def require_full(request: Request, *roles: str) -> dict:
    """Как require, но демо-сессии снаружи — 403 (опасные действия: сброс демо, Битрикс, импорт и правка сотрудников, приглашения)."""
    user = require(request, *roles)
    if user.get("demo_restricted"):
        raise HTTPException(403, DEMO_DENIED)
    return user


def login(user_id: int, demo: bool = False) -> str:
    if not user_by_id(user_id):
        raise HTTPException(404, "Пользователь не найден")
    token = secrets.token_urlsafe(32)
    db.ex("INSERT INTO sessions(token, user_id, created_at, demo) VALUES(?, ?, ?, ?)", (token, user_id, db.now_iso(), 1 if demo else 0))
    return token


def set_cookie(response, token: str, cross_site: bool = False, days: int = 30, request: Request | None = None) -> None:
    """Сессионная cookie (days — срок; вход по личному приглашению ставит долгую, устройство помнит сотрудника).
    cross_site=True — вход из iframe Битрикс24: браузер отдаёт cookie третьей стороне только с SameSite=None; Secure.
    По https (туннель: uvicorn берёт схему из X-Forwarded-Proto) cookie — с Secure (аудит 12.11, F-11); на http://localhost — без."""
    if cross_site:
        # CHIPS: Partitioned — cookie привязана к паре «наш сайт внутри портала», браузеры (Chrome, Firefox) отдают её во фрейме;
        # Starlette не знает атрибут Partitioned, поэтому заголовок собирается вручную
        age = 30 * 86400
        response.headers.append("set-cookie", f"{COOKIE}={token}; Path=/; Max-Age={age}; HttpOnly; Secure; SameSite=None; Partitioned")
        response.headers.append("set-cookie", f"{FRAME_COOKIE}=1; Path=/; Max-Age={age}; Secure; SameSite=None; Partitioned")
    else:
        response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=days * 86400, path="/",
                            secure=bool(request is not None and request.url.scheme == "https"))


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
