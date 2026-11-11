"""Modus Feedback — FastAPI-приложение: API (mf/api.py), страницы (web/*.html), статика (web/a)."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

from . import api, appeals, db, meetings, seed
from .ai import stt
from .config import ROOT

log = logging.getLogger("mf")
WEB = ROOT / "web"
# стили и скрипты только из файлов (без inline) — 'unsafe-inline' не нужен; blob: — для записи аудио (этап 2)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; "
       "connect-src 'self'; media-src 'self' blob:; worker-src 'self'; object-src 'none'; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(self), microphone=(self), geolocation=(), payment=(), usb=()",   # микрофон — голосовой ввод
    "Cross-Origin-Opener-Policy": "same-origin",
}
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
                for k, v in SECURITY_HEADERS.items():
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


app = FastAPI(title="Modus Feedback", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
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
