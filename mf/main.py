"""«Модус Голос» (Modus Golos) — FastAPI-приложение: API (mf/api.py), страницы (web/*.html), статика (web/a)."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from urllib.parse import urlparse
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

from . import api, appeals, auth, db, meetings, seed
from .ai import stt
from .config import PUBLIC_URL, ROOT
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
    return CSP_BASE.format(frame=f"'self' {bitrix.portal_origin()}").replace("script-src 'self'", "script-src 'self' https://api.bitrix24.com")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(self), microphone=(self), geolocation=(), payment=(), usb=()",   # микрофон — голосовой ввод
    "Cross-Origin-Opener-Policy": "same-origin",
}


def security_headers(scope) -> dict:
    """Встраивание разрешено только порталу из .env (frame-ancestors 'self' https://<портал>): без настроек — запрет везде.
    С настроенным порталом разрешено на всех путях — внутри фрейма сотрудник переходит между /bitrix/app, /app, /panel и /login,
    а партиционированную cookie (mf_frame) часть браузеров не отдаёт (Safari, мобильное приложение Битрикс24)."""
    if not bitrix.configured():
        return SECURITY_HEADERS
    h = {k: v for k, v in SECURITY_HEADERS.items() if k != "X-Frame-Options"}
    h["Content-Security-Policy"] = CSP_BASE.format(frame=f"'self' {bitrix.portal_origin()}")
    h["Cross-Origin-Opener-Policy"] = "unsafe-none"
    return h
PAGES = {"/": "index.html", "/login": "login.html", "/app": "app.html", "/panel": "panel.html"}
HSTS = "max-age=31536000"


def safe_next(n) -> str:
    """Куда вернуть после входа — только путь своего сайта (аудит 12.11, F-13): «/app#/x» да, «//evil.example», «https://…», «/\\evil» — нет."""
    n = n if isinstance(n, str) else ""
    return n if re.fullmatch(r"/(?![/\\])[^\s\\]*", n) else ""


def _header(scope, name: bytes) -> str:
    for k, v in scope.get("headers") or []:
        if k == name:
            return v.decode("latin-1")
    return ""


def cross_origin(scope) -> bool:
    """Изменяющий запрос к /api с чужой страницы (аудит 12.11, F-20; защита в глубину к SameSite=Lax и JSON). Origin должен совпасть
    с Host запроса или адресом MF_PUBLIC_URL; без Origin — отказ только при Sec-Fetch-Site: cross-site. curl и сервисы без браузера — проходят."""
    if scope.get("method") not in ("POST", "PUT", "PATCH", "DELETE") or not scope.get("path", "").startswith("/api/"):
        return False
    origin = _header(scope, b"origin")
    if not origin:
        return _header(scope, b"sec-fetch-site").lower() == "cross-site"
    if origin == "null":
        return True
    o = urlparse(origin).netloc.lower()
    ok = {_header(scope, b"host").lower()}
    if PUBLIC_URL:
        ok.add(urlparse(PUBLIC_URL).netloc.lower())
    return o not in ok


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
                if scope.get("scheme") == "https" and "strict-transport-security" not in headers:
                    headers.append("Strict-Transport-Security", HSTS)   # F-11: через туннель (https) — только https
                if path.startswith("/a/") or not path.startswith("/api/"):
                    headers["Cache-Control"] = "no-cache"
            await send(message)

        if cross_origin(scope):
            return await JSONResponse({"detail": "Запрос с чужой страницы отклонён"}, status_code=403)(scope, receive, send_wrapped)
        await self.app(scope, receive, send_wrapped)


def _daily_bitrix_sync() -> None:
    """Раз в сутки — синхронизация сотрудников из портала, если интеграция установлена (этап 8 §3)."""
    try:
        if not bitrix.notify_available():
            return
        last = (db.setting("bitrix_sync") or {}).get("at")
        if last and (db.now() - db.parse(last)).total_seconds() < 86400:
            return
        bitrix.sync_users()
    except Exception:   # noqa: BLE001
        log.exception("bitrix sync")


async def overdue_loop():
    tick = 0
    while True:
        try:
            tick += 1
            if tick % 10 == 1:   # раз в 10 минут проверяем, не пора ли суточная синхронизация
                threading.Thread(target=_daily_bitrix_sync, name="bitrix-sync", daemon=True).start()
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


def cleanup_audio() -> int:
    """Аудит 12.11, F-16: голос не должен оставаться на диске. Обработка совещания идёт в фоне этого процесса и перезапуск не
    переживает — значит, всё, что лежит в var/audio при старте, осиротело: удалить, а совещания «обрабатывается» пометить ошибкой."""
    from . import config
    n = 0
    for f in config.AUDIO_DIR.glob("*"):
        if f.is_file():
            f.unlink(missing_ok=True)
            n += 1
    db.ex("UPDATE meetings SET status='failed', stage=NULL, audio_path=NULL, error=? WHERE status='processing'",
          ("Обработка прервана перезапуском сервера — загрузите запись или текст заново",))
    if n:
        log.info("удалено осиротевших аудиофайлов: %s", n)
    return n


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    seed.ensure()
    cleanup_audio()
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
    """«Результаты обращений» без входа (этап 7): реализованные обращения без авторов."""
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


@app.get("/.well-known/assetlinks.json")
async def assetlinks():
    """Digital Asset Links для Android-приложений (TWA, пункт 5 очереди 12.11): подтверждает, что APK «Модус Голос» и «Директор»
    принадлежат этому домену — тогда приложение открывается без адресной строки. Отпечаток — ключ подписи demo/android."""
    return FileResponse(WEB / ".well-known" / "assetlinks.json", media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/manifest-boss.json")
async def manifest_boss():
    """Отдельная PWA «Модус Голос · Директор» (пункт 2 очереди 12.11): start_url и scope — /boss, своя иконка."""
    return FileResponse(WEB / "manifest-boss.json", media_type="application/manifest+json")


@app.get("/boss")
@app.get("/boss/{rest:path}")
async def boss_page(rest: str = ""):
    """«Директор в кармане»: один экран без прокрутки на телефоне; доступ к данным — только директору (API проверяет роль)."""
    return page("boss.html")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(WEB / "sw.js", media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/q/{code}")
async def qr_page(code: str):
    return page("qr.html")


@app.get("/t/{token}")
async def track_page(token: str):
    return page("track.html")


@app.get("/i/{token}")
async def invite_page(token: str):
    """Личное приглашение сотрудника без Битрикса (этап 8 §4): одна кнопка «Войти», ссылка одноразовая."""
    return page("invite.html")


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
async def bitrix_login(request: Request, next: str = ""):
    """Снаружи: кнопка «Войти через Битрикс24» → страница авторизации портала (redirect_uri задан в настройках приложения: /bitrix/callback).
    Внутри фрейма портала (Sec-Fetch-Dest: iframe) OAuth не запускаем: auth2.bitrix24.net запрещает встраивание и Firefox показывал ошибку —
    вместо этого страница, которая подхватит сессию из sessionStorage или попросит открыть пункт меню заново (вход там автоматический)."""
    _bitrix_required()
    dest = request.headers.get("sec-fetch-dest", "").lower()
    url = bitrix.authorize_url(safe_next(next))
    if dest == "iframe":
        return page("bitrix_app.html")
    if dest == "document":   # обычная вкладка — сразу на портал
        return RedirectResponse(url, status_code=302)
    # заголовка нет (старый браузер, переход скриптом): решает страница — во фрейме восстановление, в окне переход на портал
    html = (WEB / "bitrix_login.html").read_text(encoding="utf-8").replace("__AUTHORIZE__", url.replace("&", "&amp;").replace('"', "&quot;"))
    return HTMLResponse(html)


@app.get("/bitrix/callback")
async def bitrix_callback(request: Request, code: str = "", state: str = ""):
    _bitrix_required()
    next_url = bitrix.check_state(state)
    if next_url is None or not code:
        raise HTTPException(400, "Битрикс24: неверный или устаревший запрос входа — попробуйте ещё раз")
    try:
        user = await _run(bitrix.login_with_code, code)
    except bitrix.BitrixRejected as e:
        raise HTTPException(403, f"Битрикс24: {e}")
    except bitrix.BitrixError as e:
        raise HTTPException(502, f"Битрикс24: {e}")
    if not user:
        return HTMLResponse(_not_mapped_page(), status_code=403)
    auth.logout(request.cookies.get(auth.COOKIE))
    resp = RedirectResponse(safe_next(next_url) or _home_for(user), status_code=302)
    auth.set_cookie(resp, auth.login(user["id"]), request=request)
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
        return page("bitrix_app.html")   # сессии в cookie нет: страница сама подхватит токен из sessionStorage фрейма или попросит открыть из меню
    try:
        user = await _run(bitrix.login_from_app, form)
    except bitrix.BitrixRejected as e:
        raise HTTPException(403, f"Битрикс24: {e}")
    except bitrix.BitrixError as e:
        raise HTTPException(502, f"Битрикс24: {e}")
    if not user:
        return HTMLResponse(_not_mapped_page(), status_code=403)
    if not bitrix.load_tokens():   # первое открытие: токены портала для уведомлений, если установка до нас не дошла (с той же проверкой)
        try:
            await _run(bitrix.install_from_form, form)
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
    try:
        if form.get("event", "").upper() == "ONAPPINSTALL" or form.get("auth[access_token]"):
            return await _run(bitrix.install_from_form, form)   # установка без интерфейса: ответ JSON, installFinish не нужен
        if not form.get("AUTH_ID"):
            raise HTTPException(400, "Этот адрес вызывает портал Битрикс24 при установке приложения")
        await _run(bitrix.install_from_form, form)
    except bitrix.BitrixRejected as e:
        raise HTTPException(403, f"Битрикс24: {e}")
    except bitrix.BitrixError as e:
        raise HTTPException(502, f"Битрикс24: {e}")
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
