"""«Модус Голос» (Modus Golos) — FastAPI-приложение: API (mf/api.py), страницы (web/*.html), статика (web/a)."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

from . import api, appeals, auth, db, meetings, seed
from .ai import stt
from .config import ROOT
from .integrations import bitrix

log = logging.getLogger("mf")
WEB = ROOT / "web"
# стили и скрипты только из файлов (без inline) — 'unsafe-inline' не нужен; blob: — для записи аудио (этап 2)
CSP_BASE = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; "
            "connect-src 'self'; media-src 'self' blob:; worker-src 'self'; object-src 'none'; frame-ancestors {frame}; "
            "base-uri 'self'; form-action 'self'")
CSP = CSP_BASE.format(frame="'none'")
# страница установки приложения Битрикс24 грузит их JS SDK (BX24.installFinish) — только на этом маршруте


def csp_bitrix_install() -> str:
    return CSP_BASE.format(frame=f"'self' https://{bitrix.portal()}").replace("script-src 'self'", "script-src 'self' https://api.bitrix24.com")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(self), microphone=(self), geolocation=(), payment=(), usb=()",   # микрофон — голосовой ввод
    "Cross-Origin-Opener-Policy": "same-origin",
}


def security_headers(scope) -> dict:
    """Встраивание разрешено только порталу из .env (frame-ancestors https://<портал>) и только для /bitrix/* и запросов с сессией
    из iframe (cookie mf_frame, выставляется при входе через портал): X-Frame-Options на них снимается. Остальной сайт — запрет."""
    if not bitrix.configured():
        return SECURITY_HEADERS
    path = scope.get("path", "")
    cookie = b"".join(v for k, v in scope.get("headers", []) if k == b"cookie").decode("latin-1")
    if not (path.startswith("/bitrix/") or f"{auth.FRAME_COOKIE}=1" in cookie):
        return SECURITY_HEADERS
    h = {k: v for k, v in SECURITY_HEADERS.items() if k != "X-Frame-Options"}
    h["Content-Security-Policy"] = CSP_BASE.format(frame=f"'self' https://{bitrix.portal()}")
    h["Cross-Origin-Opener-Policy"] = "unsafe-none"
    return h
PAGES = {"/": "index.html", "/login": "login.html", "/app": "app.html", "/panel": "panel.html"}


class Headers:
    """Заголовки безопасности и no-cache для фронта. Чистый ASGI, чтобы не ломать SSE-поток."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for k, v in security_headers(scope).items():
                    if k not in headers:
                        headers.append(k, v)
                if path.startswith("/a/") or not path.startswith("/api/"):
                    headers["Cache-Control"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_wrapped)


async def overdue_loop():
    while True:
        try:
            escalated = appeals.check_overdue()
            if escalated:
                log.info("просрочка: эскалировано %s", ", ".join(escalated))
            t = meetings.check_tasks()
            if t["reminded"] or t["overdue"]:
                log.info("поручения: напоминаний %s, просрочено %s", t["reminded"], t["overdue"])
            n = appeals.check_news()
            if n:
                log.info("авторы ждут новостей: напоминаний %s", n)
        except Exception:
            log.exception("check_overdue")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    seed.ensure()
    task = asyncio.create_task(overdue_loop())
    if os.environ.get("MF_STT_WARMUP", "1") == "1" and not os.environ.get("PYTEST_CURRENT_TEST"):
        threading.Thread(target=stt.warmup, name="stt-warmup", daemon=True).start()   # модель грузится ~10 с, первая запись не ждёт
    yield
    task.cancel()


app = FastAPI(title="Модус Голос", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(Headers)
app.include_router(api.router, prefix="/api")
app.mount("/a", StaticFiles(directory=WEB / "a"), name="assets")


def page(name: str) -> FileResponse:
    return FileResponse(WEB / name, media_type="text/html")


@app.get("/")
async def index():
    return page("index.html")


@app.get("/login")
async def login_page():
    return page("login.html")


@app.get("/rules")
async def rules_page():
    return page("rules.html")


@app.get("/changes")
async def changes_page():
    """«Что изменили» без входа (этап 7): реализованные обращения без авторов."""
    return page("changes.html")


@app.get("/design")
async def design_page():
    """Живой справочник дизайн-системы: токены и компоненты (этап 7 §1)."""
    return page("design.html")


@app.get("/offline")
async def offline_page():
    return page("offline.html")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(WEB / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(WEB / "sw.js", media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/q/{code}")
async def qr_page(code: str):
    return page("qr.html")


@app.get("/t/{token}")
async def track_page(token: str):
    return page("track.html")


@app.get("/app")
@app.get("/app/{rest:path}")
async def app_page(rest: str = ""):
    return page("app.html")


@app.get("/panel")
@app.get("/panel/{rest:path}")
async def panel_page(rest: str = ""):
    return page("panel.html")


# ---------- Битрикс24 (этап 6 §1): вход OAuth 2.0, приложение внутри портала, установка. Без настроек в .env — 404 ----------

def _bitrix_required() -> None:
    if not bitrix.configured():
        raise HTTPException(404, "Битрикс24 не подключён: нет BITRIX_PORTAL / BITRIX_CLIENT_ID / BITRIX_CLIENT_SECRET в .env")


def _home_for(user: dict) -> str:
    return "/app" if user["role"] == "employee" else "/panel"


async def _form(request: Request) -> dict:
    try:
        f = await request.form()
        return {k: (v if isinstance(v, str) else "") for k, v in f.items()}
    except Exception:   # noqa: BLE001 — не form-data
        return {}


@app.get("/bitrix/login")
async def bitrix_login(next: str = ""):
    """Снаружи: кнопка «Войти через Битрикс24» → страница авторизации портала (redirect_uri задан в настройках приложения: /bitrix/callback)."""
    _bitrix_required()
    return RedirectResponse(bitrix.authorize_url(next if next.startswith("/") else ""), status_code=302)


@app.get("/bitrix/callback")
async def bitrix_callback(request: Request, code: str = "", state: str = ""):
    _bitrix_required()
    next_url = bitrix.check_state(state)
    if next_url is None or not code:
        raise HTTPException(400, "Битрикс24: неверный или устаревший запрос входа — попробуйте ещё раз")
    try:
        user = await _run(bitrix.login_with_code, code)
    except bitrix.BitrixError as e:
        raise HTTPException(502, f"Битрикс24: {e}")
    if not user:
        return HTMLResponse(_not_mapped_page(), status_code=403)
    auth.logout(request.cookies.get(auth.COOKIE))
    resp = RedirectResponse(next_url or _home_for(user), status_code=302)
    auth.set_cookie(resp, auth.login(user["id"]))
    return resp


@app.api_route("/bitrix/app", methods=["GET", "POST"])
async def bitrix_app(request: Request):
    """Внутри портала (iframe): Битрикс открывает этот адрес POST-ом с AUTH_ID → сотрудник опознаётся → сессия по нашему токену
    (в адресе ?s= и заголовке Authorization, cookie — партиционированная, как запасной путь) → та же SPA (приложение или панель),
    но по адресу /bitrix/app, где встраивание разрешено порталу."""
    _bitrix_required()
    form = await _form(request) if request.method == "POST" else {}
    if request.method == "GET" and request.query_params.get("code") and request.query_params.get("state"):
        # для локального приложения redirect_uri OAuth = «Путь обработчика», т. е. этот адрес; логика та же, что в /bitrix/callback
        return await bitrix_callback(request, request.query_params["code"], request.query_params["state"])
    if not form.get("AUTH_ID"):
        user = auth.current(request)
        if user:
            return page("panel.html" if user["role"] != "employee" else "app.html")
        return HTMLResponse("<!doctype html><meta charset='utf-8'><link rel='stylesheet' href='/a/style.css'><div class='wrap'><div class='card card-info'>"
                            "Откройте «Модус Голос» из левого меню Битрикс24 — вход произойдёт автоматически.</div></div>")
    try:
        user = await _run(bitrix.login_from_app, form)
    except bitrix.BitrixError as e:
        raise HTTPException(502, f"Битрикс24: {e}")
    if not user:
        return HTMLResponse(_not_mapped_page(), status_code=403)
    if not bitrix.load_tokens():   # первое открытие: токены портала для уведомлений, если установка до нас не дошла
        try:
            bitrix.install_from_form(form)
        except bitrix.BitrixError:
            pass
    auth.logout(request.cookies.get(auth.COOKIE))
    token = auth.login(user["id"])
    resp = RedirectResponse(f"/bitrix/app?s={token}", status_code=303)
    auth.set_cookie(resp, token, cross_site=True)
    return resp


@app.api_route("/bitrix/install", methods=["GET", "POST"])
async def bitrix_install(request: Request):
    """«Путь для первоначальной установки»: сохраняем токены портала и отвечаем страницей с BX24.installFinish()."""
    _bitrix_required()
    form = await _form(request) if request.method == "POST" else {}
    if form.get("event", "").upper() == "ONAPPINSTALL" or form.get("auth[access_token]"):
        return bitrix.install_from_form(form)   # установка без интерфейса: ответ JSON, installFinish не нужен
    if not form.get("AUTH_ID"):
        raise HTTPException(400, "Этот адрес вызывает портал Битрикс24 при установке приложения")
    bitrix.install_from_form(form)
    try:
        user = await _run(bitrix.login_from_app, form)
    except bitrix.BitrixError:
        user = None
    resp = HTMLResponse(bitrix.INSTALL_PAGE, headers={"Content-Security-Policy": csp_bitrix_install()})
    if user:
        auth.set_cookie(resp, auth.login(user["id"]), cross_site=True)
    return resp


async def _run(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)


def _not_mapped_page() -> str:
    return ("<!doctype html><meta charset='utf-8'><link rel='stylesheet' href='/a/style.css'><div class='wrap'><div class='card card-warn'>"
            "<div class='h1'>Учётная запись Битрикс24 не сопоставлена</div><p>В системе обратной связи нет сотрудника с таким ID, почтой или именем. "
            "Попросите администратора указать почту или ID Битрикса в карточке сотрудника (Панель → Администрирование → Сотрудники).</p>"
            "<a href='/login' class='btn' target='_blank' rel='noopener'>Демо-вход в новом окне</a></div></div>")
