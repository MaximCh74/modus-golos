"""Битрикс24 (этап 6 §1). Написано по документации apidocs.bitrix24.ru (сверено 12.11.2026, ссылки в docs/BITRIX24.md):
- вход: OAuth 2.0 — https://<портал>/oauth/authorize/?client_id&state → code (30 с) → GET https://oauth.bitrix24.tech/oauth/token/
  (grant_type=authorization_code|refresh_token, client_id, client_secret) → access_token (1 ч), refresh_token (180 дней), client_endpoint;
- внутри портала: локальное «серверное приложение с интерфейсом» — Битрикс открывает наш адрес в iframe и POST-ом передаёт
  AUTH_ID, REFRESH_ID, AUTH_EXPIRES, member_id, APPLICATION_TOKEN; в query — DOMAIN, PLACEMENT; страница установки вызывает BX24.installFinish();
- REST: {client_endpoint}{метод}?auth=<token>; уведомления — im.notify.system.add (скоуп im), сотрудник — user.current (скоуп user),
  поручения → tasks.task.add (скоуп task).
Секреты только в .env (BITRIX_PORTAL, BITRIX_CLIENT_ID, BITRIX_CLIENT_SECRET, при желании BITRIX_WEBHOOK_URL, BITRIX_TASKS=1);
токены портала — в папке данных (var/bitrix_tokens.json, в git не попадает). Без настроек модуль неактивен: кнопок входа нет,
уведомления не дублируются. НЕ ПРОВЕРЕНО НА ЖИВОМ ПОРТАЛЕ — ждёт тестовый портал (docs/BITRIX24.md, docs/STATUS.md)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from pathlib import Path

from .. import config, db

log = logging.getLogger("mf.bitrix")
OAUTH_HOST = os.environ.get("BITRIX_OAUTH_HOST", "https://oauth.bitrix24.tech").rstrip("/")
# встраивание в iframe разрешается только порталу из .env: frame-ancestors https://<BITRIX_PORTAL> (mf/main.py)
SCOPES_NEEDED = ("user", "im", "task")   # user (или user_brief) — user.current; im — im.notify.*; task — tasks.task.add (при BITRIX_TASKS=1)
TIMEOUT = 12.0


class BitrixError(Exception):
    pass


# ---------- настройки ----------

def portal() -> str:
    p = (os.environ.get("BITRIX_PORTAL") or "").strip().lower()
    return p.replace("https://", "").replace("http://", "").strip("/")


def client_id() -> str:
    return (os.environ.get("BITRIX_CLIENT_ID") or "").strip()


def client_secret() -> str:
    return (os.environ.get("BITRIX_CLIENT_SECRET") or "").strip()


def webhook_url() -> str:
    return (os.environ.get("BITRIX_WEBHOOK_URL") or "").strip().rstrip("/")


def configured() -> bool:
    """Приложение зарегистрировано в портале: есть адрес портала, client_id и client_secret → вход через Битрикс24 и iframe."""
    return bool(portal() and client_id() and client_secret())


def tasks_enabled() -> bool:
    return os.environ.get("BITRIX_TASKS", "0").strip() == "1"


def notify_available() -> bool:
    """Уведомления можно слать, если есть токены портала (после установки приложения) или входящий вебхук."""
    return bool(webhook_url()) or (configured() and bool(load_tokens()))


def status() -> dict:
    t = load_tokens()
    return {"configured": configured(), "portal": portal() or None, "webhook": bool(webhook_url()), "tokens": bool(t),
            "installed_at": (t or {}).get("installed_at"), "tasks": tasks_enabled(), "frame": configured(),
            "mapped_users": db.one("SELECT COUNT(*) AS n FROM users WHERE bitrix_id IS NOT NULL")["n"] if db.conn() else 0}


# ---------- токены портала (файл в папке данных, не в базе: база уходит в демо-снапшот) ----------

def tokens_path() -> Path:
    return Path(config.DATA_DIR) / "bitrix_tokens.json"


def load_tokens() -> dict | None:
    p = tokens_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def save_tokens(t: dict) -> None:
    keep = {k: t.get(k) for k in ("access_token", "refresh_token", "expires_in", "client_endpoint", "server_endpoint", "member_id", "domain", "scope", "status")}
    keep["saved_at"] = int(time.time())
    keep["installed_at"] = (load_tokens() or {}).get("installed_at") or db.now_iso()
    if not keep.get("client_endpoint"):
        keep["client_endpoint"] = f"https://{portal()}/rest/"
    p = tokens_path()
    p.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


# ---------- HTTP (подменяется в тестах) ----------

def _request(url: str, params: dict | None = None, data: dict | None = None) -> dict:
    """GET (params) или POST (json=data) → JSON. В тестах заменяется фейком через request_fn."""
    import httpx
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(url, params=params, json=data) if data is not None else c.get(url, params=params)
    try:
        j = r.json()
    except ValueError:
        raise BitrixError(f"ответ не JSON (HTTP {r.status_code})")
    if r.status_code >= 400 and not isinstance(j, dict):
        raise BitrixError(f"HTTP {r.status_code}")
    return j


request_fn = _request


def _oauth(params: dict) -> dict:
    j = request_fn(f"{OAUTH_HOST}/oauth/token/", params=params)
    if not isinstance(j, dict) or not j.get("access_token"):
        raise BitrixError(f"oauth: {j.get('error') if isinstance(j, dict) else j}: {j.get('error_description', '') if isinstance(j, dict) else ''}".strip())
    return j


def exchange_code(code: str) -> dict:
    return _oauth({"grant_type": "authorization_code", "client_id": client_id(), "client_secret": client_secret(), "code": code})


def refresh(refresh_token: str) -> dict:
    return _oauth({"grant_type": "refresh_token", "client_id": client_id(), "client_secret": client_secret(), "refresh_token": refresh_token})


def call(method: str, params: dict | None = None, *, token: str | None = None, endpoint: str | None = None, _retry: bool = True):
    """REST-метод: вебхук (если задан и токен не передан) или {client_endpoint}{method}?auth=token. expired_token → обновить токены портала и повторить."""
    params = params or {}
    if token is None and webhook_url():
        j = request_fn(f"{webhook_url()}/{method}", data=params)
    else:
        t = load_tokens() if token is None else None
        if token is None:
            if not t:
                raise BitrixError("нет токенов портала — приложение не установлено")
            token, endpoint = t["access_token"], t.get("client_endpoint")
        endpoint = (endpoint or f"https://{portal()}/rest/").rstrip("/") + "/"
        j = request_fn(f"{endpoint}{method}", params={"auth": token}, data=params)
        if isinstance(j, dict) and j.get("error") == "expired_token" and t and _retry:
            nt = refresh(t["refresh_token"])
            save_tokens(nt)
            return call(method, params, _retry=False)
    if not isinstance(j, dict):
        raise BitrixError("неожиданный ответ")
    if j.get("error"):
        raise BitrixError(f"{j.get('error')}: {j.get('error_description', '')}".strip())
    return j.get("result")


# ---------- вход и сопоставление сотрудников ----------

def _sig(payload: str) -> str:
    return hmac.new(config.secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]


def make_state(next_url: str = "") -> str:
    payload = f"{int(time.time())}|{next_url}"
    raw = f"{payload}|{_sig(payload)}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def check_state(state: str) -> str | None:
    """→ next_url или None, если подпись не сошлась или state старше 10 минут (защита от подмены редиректа)."""
    try:
        raw = base64.urlsafe_b64decode(state + "=" * (-len(state) % 4)).decode()
        ts, next_url, sig = raw.rsplit("|", 2)
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(sig, _sig(f"{ts}|{next_url}")) or time.time() - int(ts) > 600:
        return None
    return next_url


def authorize_url(next_url: str = "") -> str:
    return f"https://{portal()}/oauth/authorize/?client_id={client_id()}&state={make_state(next_url)}"


def user_current(token: str, endpoint: str | None = None) -> dict:
    r = call("user.current", {}, token=token, endpoint=endpoint)
    if not isinstance(r, dict) or not r.get("ID"):
        raise BitrixError("user.current не вернул пользователя")
    return r


def _norm_name(s: str) -> str:
    return " ".join((s or "").replace("ё", "е").lower().split())


def match_user(bx: dict) -> dict | None:
    """Сопоставление с нашим сотрудником: по сохранённому ID Битрикса → по почте → по имени и фамилии (демо-имена на тестовом портале).
    Найденное соответствие запоминается (users.bitrix_id), чтобы дальше работал только ID."""
    try:
        bid = int(bx.get("ID") or 0)
    except (TypeError, ValueError):
        bid = 0
    if not bid:
        return None
    u = db.one("SELECT * FROM users WHERE bitrix_id=? AND active=1", (bid,))
    if u:
        return u
    email = (bx.get("EMAIL") or "").strip().lower()
    if email:
        u = db.one("SELECT * FROM users WHERE lower(email)=? AND active=1", (email,))
    if not u:
        first, last = _norm_name(bx.get("NAME") or ""), _norm_name(bx.get("LAST_NAME") or "")
        if first:
            for row in db.q("SELECT * FROM users WHERE active=1"):
                n = _norm_name(row["name"])
                if n in (f"{first} {last}".strip(), f"{last} {first}".strip()):
                    u = row
                    break
    if u:
        db.ex("UPDATE users SET bitrix_id=? WHERE id=?", (bid, u["id"]))
        if email and not u.get("email"):
            db.ex("UPDATE users SET email=? WHERE id=?", (email, u["id"]))
        log.info("Битрикс24: пользователь %s сопоставлен с %s (#%s)", bid, u["name"], u["id"])
    return u


def login_with_code(code: str) -> dict | None:
    """Внешний вход «Войти через Битрикс24»: code → токены → user.current → наш пользователь. Первые токены сохраняются как токены портала."""
    t = exchange_code(code)
    bx = user_current(t["access_token"], t.get("client_endpoint"))
    if not load_tokens():
        save_tokens(t)
    return match_user(bx)


def login_from_app(form: dict) -> dict | None:
    """Открытие внутри портала: POST с AUTH_ID (token) и т. д. → user.current → наш пользователь."""
    token = form.get("AUTH_ID")
    if not token:
        return None
    endpoint = f"https://{form.get('DOMAIN') or portal()}/rest/"
    bx = user_current(token, endpoint)
    return match_user(bx)


def install_from_form(form: dict) -> dict:
    """Установка локального приложения: сохраняем токены портала из POST (AUTH_ID/REFRESH_ID или auth[access_token]/auth[refresh_token])."""
    t = {"access_token": form.get("AUTH_ID") or form.get("auth[access_token]"), "refresh_token": form.get("REFRESH_ID") or form.get("auth[refresh_token]"),
         "expires_in": form.get("AUTH_EXPIRES") or form.get("auth[expires_in]"), "member_id": form.get("member_id") or form.get("auth[member_id]"),
         "domain": form.get("DOMAIN") or form.get("auth[domain]"), "scope": form.get("APPLICATION_SCOPE") or form.get("auth[scope]"),
         "client_endpoint": form.get("auth[client_endpoint]") or (f"https://{form.get('DOMAIN')}/rest/" if form.get("DOMAIN") else None),
         "server_endpoint": form.get("SERVER_ENDPOINT") or form.get("auth[server_endpoint]"), "status": form.get("status") or form.get("auth[status]")}
    if not t["access_token"]:
        raise BitrixError("в запросе установки нет токена (AUTH_ID)")
    save_tokens(t)
    return {"ok": True, "member_id": t["member_id"], "domain": t["domain"]}


# ---------- уведомления и задачи ----------

def _public_url() -> str:
    return config.PUBLIC_URL or ""


def notify(user_id: int | None, text: str, link: str | None = None) -> None:
    """Дубль уведомления в чат Битрикса (im.notify.system.add) со ссылкой обратно. Не блокирует запрос: отправка в фоне; в тестах — синхронно."""
    if not user_id or not notify_available():
        return
    row = db.one("SELECT bitrix_id FROM users WHERE id=? AND active=1", (user_id,))
    if not row or not row["bitrix_id"]:
        return
    msg = text
    if link:
        msg += f"\n[URL={_public_url()}{link}]Открыть в «Модус Голос»[/URL]"
    if os.environ.get("PYTEST_CURRENT_TEST"):
        _send_notify(row["bitrix_id"], msg)
    else:
        threading.Thread(target=_send_notify, args=(row["bitrix_id"], msg), name="bitrix-notify", daemon=True).start()


def _send_notify(bitrix_user_id: int, message: str) -> None:
    try:
        call("im.notify.system.add", {"USER_ID": int(bitrix_user_id), "MESSAGE": message})
    except Exception as e:   # noqa: BLE001 — внешняя система: ошибка в лог, система работает дальше
        log.warning("Битрикс24: уведомление не ушло (%s): %s", bitrix_user_id, e)


def create_task(assignee_user_id: int, title: str, description: str, due_date: str | None) -> int | None:
    """Поручение с совещания → задача Битрикса (tasks.task.add) со ссылкой обратно; → id задачи или None."""
    if not tasks_enabled() or not notify_available():
        return None
    row = db.one("SELECT bitrix_id FROM users WHERE id=? AND active=1", (assignee_user_id,))
    if not row or not row["bitrix_id"]:
        return None
    fields = {"TITLE": title[:250], "DESCRIPTION": description, "RESPONSIBLE_ID": int(row["bitrix_id"])}
    if due_date:
        fields["DEADLINE"] = f"{due_date}T18:00:00"
    try:
        r = call("tasks.task.add", {"fields": fields})
        tid = int((r or {}).get("task", {}).get("id") or 0) if isinstance(r, dict) else 0
        return tid or None
    except Exception as e:   # noqa: BLE001
        log.warning("Битрикс24: задача не создана: %s", e)
        return None


INSTALL_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Установка · Модус Голос</title>
<link rel="stylesheet" href="/a/style.css"></head><body><div class="wrap"><div class="card card-ok"><div class="h1">Приложение установлено</div>
<p>Токены портала сохранены. Пункт «Модус Голос» появится в левом меню Битрикс24 — откройте его.</p>
<p class="small muted">Если окно не закрылось само — закройте его.</p></div></div>
<script src="https://api.bitrix24.com/api/v1/"></script><script src="/a/bitrix_install.js"></script></body></html>"""
