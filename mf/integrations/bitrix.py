"""Битрикс24 (этап 6 §1). Написано по документации apidocs.bitrix24.ru (сверено 12.11.2026, ссылки в docs/BITRIX24.md):
- вход: OAuth 2.0 — https://<портал>/oauth/authorize/?client_id&state → code (30 с) → GET https://oauth.bitrix24.tech/oauth/token/
  (grant_type=authorization_code|refresh_token, client_id, client_secret) → access_token (1 ч), refresh_token (180 дней), client_endpoint;
- внутри портала: локальное «серверное приложение с интерфейсом» — Битрикс открывает наш адрес в iframe и POST-ом передаёт
  AUTH_ID, REFRESH_ID, AUTH_EXPIRES, member_id, APPLICATION_TOKEN; в query — DOMAIN, PLACEMENT; страница установки вызывает BX24.installFinish();
- REST: {client_endpoint}{метод}?auth=<token>; уведомления — im.notify.system.add (скоуп im), сотрудник — user.current (скоуп user),
  поручения → tasks.task.add (скоуп task).
Секреты только в .env (BITRIX_PORTAL, BITRIX_CLIENT_ID, BITRIX_CLIENT_SECRET, при желании BITRIX_WEBHOOK_URL, BITRIX_TASKS=1);
токены портала — в папке данных (var/bitrix_tokens.json, в git не попадает). Без настроек модуль неактивен: кнопок входа нет,
уведомления не дублируются. Проверено на живом портале владельца 12.11.2026: открытие во фрейме, синхронизация, уведомление в чат
(docs/BITRIX24.md «Статус»). Сотрудники без Битрикса (ручное добавление, импорт, приглашения) — mf/staff.py; склейка с порталом —
match_user по почте и телефону, спорные случаи — merge_issue → отчёт синхронизации (settings bitrix_sync.conflicts).

Проверка запросов портала (аудит безопасности 12.11, F-01/F-02): адрес REST — ТОЛЬКО из BITRIX_PORTAL (поля DOMAIN и client_endpoint из
запроса не используются); member_id сверяется с BITRIX_MEMBER_ID из .env или с запомненным при первой установке; события, кроме установки,
должны нести тот же application_token; токен из запроса проверяется вызовом app.info на нашем портале, прежде чем сохраняться или
опознавать сотрудника. Сопоставление «только по имени» автоматически не делается — администратор указывает ID портала в карточке."""
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
from urllib.parse import urlparse

from .. import config, db

log = logging.getLogger("mf.bitrix")
OAUTH_HOST = os.environ.get("BITRIX_OAUTH_HOST", "https://oauth.bitrix24.tech").rstrip("/")
# встраивание в iframe разрешается только порталу из .env: frame-ancestors https://<BITRIX_PORTAL> (mf/main.py)
SCOPES_NEEDED = ("user", "department", "im", "task")   # user — user.current/user.get; department — названия отделов (sync); im — im.notify.*; task — tasks.task.add
TIMEOUT = 12.0


class BitrixError(Exception):
    pass


class BitrixRejected(BitrixError):
    """Запрос не от нашего портала или не от нашего приложения (чужой member_id, application_token, токен не принят порталом) → 403."""


# ---------- настройки ----------

def portal() -> str:
    p = (os.environ.get("BITRIX_PORTAL") or "").strip().lower()
    return p.replace("https://", "").replace("http://", "").strip("/")


def portal_origin() -> str:
    """Источник портала для frame-ancestors: https://<портал>; http:// — только если так явно записано в .env (локальная проверка фрейма)."""
    raw = (os.environ.get("BITRIX_PORTAL") or "").strip().lower()
    return ("http://" if raw.startswith("http://") else "https://") + portal()


def portal_endpoint() -> str:
    """Адрес REST нашего портала — только из .env (никогда из запроса)."""
    return f"{portal_origin()}/rest/"


def expected_member_id() -> str | None:
    """member_id нашего портала: из .env (BITRIX_MEMBER_ID) или запомненный при первой проверенной установке."""
    return (os.environ.get("BITRIX_MEMBER_ID") or "").strip() or (load_tokens() or {}).get("member_id") or None


def check_member(member_id: str | None) -> None:
    exp = expected_member_id()
    if exp and member_id and str(member_id).strip() != exp:
        raise BitrixRejected("запрос от другого портала (member_id не совпадает)")


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
            "mapped_users": db.one("SELECT COUNT(*) AS n FROM users WHERE bitrix_id IS NOT NULL")["n"] if db.conn() else 0,
            "sync": db.setting("bitrix_sync")}


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
    prev = load_tokens() or {}
    keep = {k: t.get(k) for k in ("access_token", "refresh_token", "expires_in", "member_id", "scope", "status", "application_token")}
    keep["member_id"] = keep["member_id"] or prev.get("member_id")
    keep["application_token"] = keep["application_token"] or prev.get("application_token")
    keep["client_endpoint"] = portal_endpoint()   # адрес REST не берём из ответа или запроса — только наш портал
    keep["domain"] = portal()
    keep["saved_at"] = int(time.time())
    keep["installed_at"] = prev.get("installed_at") or db.now_iso()
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


def call_full(method: str, params: dict | None = None) -> dict:
    """Как call(), но возвращает весь ответ ({result, next, total}) — для постраничных user.get / department.get."""
    params = params or {}
    if webhook_url():
        j = request_fn(f"{webhook_url()}/{method}", data=params)
    else:
        t = load_tokens()
        if not t:
            raise BitrixError("нет токенов портала — приложение не установлено")
        endpoint = portal_endpoint()
        j = request_fn(f"{endpoint}{method}", params={"auth": t["access_token"]}, data=params)
        if isinstance(j, dict) and j.get("error") == "expired_token":
            save_tokens(refresh(t["refresh_token"]))
            t = load_tokens()
            j = request_fn(f"{endpoint}{method}", params={"auth": t["access_token"]}, data=params)
    if not isinstance(j, dict):
        raise BitrixError("неожиданный ответ")
    if j.get("error"):
        raise BitrixError(f"{j.get('error')}: {j.get('error_description', '')}".strip())
    return j


def _pages(method: str, params: dict | None = None) -> list:
    """Все страницы ответа (Битрикс отдаёт по 50, дальше — next)."""
    out, start = [], 0
    for _ in range(200):
        j = call_full(method, {**(params or {}), "start": start})
        res = j.get("result") or []
        out.extend(res if isinstance(res, list) else [res])
        if j.get("next") is None:
            break
        start = j["next"]
    return out


def _digits(s) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())[-10:]


def sync_users() -> dict:
    """Этап 8 §3: сотрудники и отделы из портала → наши пользователи. Сопоставление по ID Битрикса (match_user: ID → почта → телефон →
    имя), новые заводятся как «Сотрудник», отдел — по названию, уволенные (ACTIVE=false или пропавшие из списка) деактивируются,
    их обращения и история остаются. Спорные склейки (почта или телефон совпали у разных наших людей) — в отчёт администратору."""
    deps = {}
    try:
        for d in _pages("department.get"):
            deps[str(d.get("ID"))] = d.get("NAME")
    except BitrixError as e:
        log.warning("Битрикс24: department.get: %s", e)
    ours_deps = {(r["name"] or "").strip().lower(): r["id"] for r in db.q("SELECT id, name FROM departments")}
    rows = _pages("user.get", {"filter": {"USER_TYPE": "employee"}})
    seen, created, updated, deactivated, conflicts = set(), 0, 0, 0, []
    for bx in rows:
        try:
            bid = int(bx.get("ID") or 0)
        except (TypeError, ValueError):
            continue
        if not bid:
            continue
        seen.add(bid)
        active = bx.get("ACTIVE") not in (False, "false", "N", 0, "0")
        if not active:
            u = db.one("SELECT id, active FROM users WHERE bitrix_id=?", (bid,))
            if u and u["active"]:
                db.ex("UPDATE users SET active=0 WHERE id=?", (u["id"],)); deactivated += 1
            continue
        before = db.one("SELECT COUNT(*) AS n FROM users")["n"]
        email = (bx.get("EMAIL") or "").strip().lower()
        phone = _digits(bx.get("PERSONAL_MOBILE") or bx.get("WORK_PHONE"))
        known = db.one("SELECT id FROM users WHERE bitrix_id=?", (bid,))
        cands = merge_candidates(email, phone) if not known else {}   # первая склейка: кто из наших без ID совпал по почте/телефону
        u = match_user({**bx, "PHONE": phone}, create=True)
        if not u:
            twin = namesake(bx) if not known else None
            if twin and active:
                conflicts.append({"bitrix_id": bid, "bitrix_name": " ".join(x for x in ((bx.get("NAME") or "").strip(), (bx.get("LAST_NAME") or "").strip()) if x),
                                  "name": twin["name"], "user_id": twin["id"], "reason": "same_name", "candidates": [{"id": twin["id"], "name": twin["name"], "by": "имя"}]})
            continue
        if db.one("SELECT COUNT(*) AS n FROM users")["n"] > before:
            created += 1
        else:
            updated += 1
        dep_ids = bx.get("UF_DEPARTMENT") or []
        dep_name = deps.get(str(dep_ids[0])) if dep_ids else None
        our_dep = ours_deps.get((dep_name or "").strip().lower())
        sets = {"active": 1}
        if our_dep and not u.get("department_id"):
            sets["department_id"] = our_dep
        if bx.get("WORK_POSITION") and not u.get("position"):
            sets["position"] = bx["WORK_POSITION"].strip()
        if phone and not u.get("phone"):
            sets["phone"] = phone
        db.ex("UPDATE users SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE id=?", (*sets.values(), u["id"]))
        if not known:
            issue = merge_issue(bid, u, bx, cands)
            if issue:
                conflicts.append(issue)
    if rows:   # полный список получен — пропавшие из портала (с нашим bitrix_id) считаем уволенными
        for r in db.q("SELECT id, bitrix_id FROM users WHERE bitrix_id IS NOT NULL AND active=1"):
            if r["bitrix_id"] not in seen:
                db.ex("UPDATE users SET active=0 WHERE id=?", (r["id"],)); deactivated += 1
    report = {"at": db.now_iso(), "portal_users": len(rows), "departments": len(deps), "created": created, "updated": updated, "deactivated": deactivated, "conflicts": conflicts}
    db.set_setting("bitrix_sync", report)
    log.info("Битрикс24: синхронизация — %s", report)
    return report


def merge_candidates(email: str, phone: str) -> dict[int, str]:
    """Этап 8 §4/§5: наши сотрудники без ID Битрикса, у которых совпала почта или телефон (последние 10 цифр): id → чем совпали.
    Так человек, заведённый администратором вручную или импортом, при синхронизации становится одним профилем с учёткой портала."""
    out: dict[int, str] = {}
    if email:
        for r in db.q("SELECT id FROM users WHERE bitrix_id IS NULL AND lower(email)=?", (email,)):
            out[r["id"]] = "почта"
    if phone:
        for r in db.q("SELECT id, phone FROM users WHERE bitrix_id IS NULL AND phone IS NOT NULL AND phone != ''"):
            if _digits(r["phone"]) == phone:
                out[r["id"]] = "почта и телефон" if r["id"] in out else "телефон"
    return out


def merge_issue(bid: int, u: dict, bx: dict, cands: dict[int, str]) -> dict | None:
    """Спорная склейка — показать администратору: почта или телефон совпали у нескольких наших людей, либо склеили по почте/телефону,
    а имена не похожи (ни одного общего слова). Склейка при этом выполняется — по почте и телефону, как договорились в ТЗ."""
    bx_name = " ".join(x for x in ((bx.get("NAME") or "").strip(), (bx.get("LAST_NAME") or "").strip()) if x)
    base = {"bitrix_id": bid, "bitrix_name": bx_name, "name": u["name"], "user_id": u["id"]}
    if len(cands) > 1:
        names = {r["id"]: r["name"] for r in db.q("SELECT id, name FROM users WHERE id IN (%s)" % ",".join("?" * len(cands)), tuple(cands))}
        return {**base, "reason": "several", "candidates": [{"id": i, "name": names.get(i), "by": by} for i, by in sorted(cands.items())]}
    if u["id"] in cands:
        ours, theirs = set(_norm_name(u["name"]).split()), set(_norm_name(bx_name).split())
        if theirs and not (ours & theirs):
            return {**base, "reason": "name", "candidates": [{"id": u["id"], "name": u["name"], "by": cands[u["id"]]}]}
    return None


def call(method: str, params: dict | None = None, *, token: str | None = None, _retry: bool = True):
    """REST-метод: вебхук (если задан и токен не передан) или https://<BITRIX_PORTAL>/rest/{method}?auth=token — адрес только из .env.
    expired_token → обновить токены портала и повторить."""
    params = params or {}
    if token is None and webhook_url():
        j = request_fn(f"{webhook_url()}/{method}", data=params)
    else:
        t = load_tokens() if token is None else None
        if token is None:
            if not t:
                raise BitrixError("нет токенов портала — приложение не установлено")
            token = t["access_token"]
        j = request_fn(f"{portal_endpoint()}{method}", params={"auth": token}, data=params)
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
    return f"{portal_origin()}/oauth/authorize/?client_id={client_id()}&state={make_state(next_url)}"


def user_current(token: str) -> dict:
    """Кто владелец токена — спрашиваем только НАШ портал: токен другого портала здесь не работает → BitrixRejected."""
    try:
        r = call("user.current", {}, token=token)
    except BitrixError as e:
        raise BitrixRejected(f"портал {portal()} не принял токен: {e}") from e
    if not isinstance(r, dict) or not r.get("ID"):
        raise BitrixRejected("user.current не вернул пользователя")
    return r


def verify_app_token(token: str) -> dict:
    """Токен из запроса установки — действительно от нашего приложения на нашем портале: app.info на адресе из .env.
    Код приложения (CODE) у локального приложения совпадает с client_id — если оба известны и различаются, это чужое приложение."""
    try:
        info = call("app.info", {}, token=token)
    except BitrixError as e:
        raise BitrixRejected(f"портал {portal()} не принял токен установки: {e}") from e
    info = info if isinstance(info, dict) else {}
    code = str(info.get("CODE") or info.get("code") or "")
    if code and client_id() and code.startswith("local.") and client_id().startswith("local.") and code != client_id():
        raise BitrixRejected("токен другого приложения портала")
    return info


def _norm_name(s: str) -> str:
    return " ".join((s or "").replace("ё", "е").lower().split())


def match_user(bx: dict, create: bool = True) -> dict | None:
    """Сопоставление с нашим сотрудником: по сохранённому ID Битрикса → по почте → по телефону. Найденное соответствие запоминается
    (users.bitrix_id), дальше работает только ID. Совпадение ТОЛЬКО по имени автоматически не склеивается (аудит 12.11, F-02): если у нас
    есть тёзка без ID портала, возвращается None — администратор указывает ID портала в карточке сотрудника (sync_users пишет это в отчёт).
    Незнакомый сотрудник портала без тёзки (create=True) заводится у нас как «Сотрудник» с именем, должностью и почтой из Битрикса;
    город, отдел и роль администратор уточняет в «Сотрудниках»."""
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
    phone = _digits(bx.get("PHONE") or bx.get("PERSONAL_MOBILE") or bx.get("WORK_PHONE"))
    if not u and phone:
        u = next((r for r in db.q("SELECT * FROM users WHERE active=1 AND phone IS NOT NULL AND phone != ''") if _digits(r["phone"]) == phone), None)
    if u:
        db.ex("UPDATE users SET bitrix_id=? WHERE id=?", (bid, u["id"]))
        if email and not u.get("email"):
            db.ex("UPDATE users SET email=? WHERE id=?", (email, u["id"]))
        log.info("Битрикс24: пользователь %s сопоставлен с %s (#%s)", bid, u["name"], u["id"])
        return u
    if not create or bx.get("ACTIVE") is False:
        return None
    if namesake(bx):
        log.warning("Битрикс24: пользователь %s совпал с нашим сотрудником только по имени — не склеиваем, нужен ID в карточке", bid)
        return None
    name = " ".join(x.strip() for x in (bx.get("NAME") or "", bx.get("LAST_NAME") or "") if x and x.strip()) or f"Сотрудник Битрикс24 {bid}"
    uid = db.ex("INSERT INTO users(name, role, position, branch_id, department_id, manager_id, active, email, bitrix_id) VALUES(?,?,?,?,?,?,1,?,?)",
                (name, "employee", (bx.get("WORK_POSITION") or "").strip() or None, None, None, None, email or None, bid))
    log.info("Битрикс24: заведён сотрудник %s (#%s) из портала, ID %s", name, uid, bid)
    return db.one("SELECT * FROM users WHERE id=?", (uid,))


def namesake(bx: dict) -> dict | None:
    """Наш активный сотрудник без ID портала с тем же именем и фамилией — кандидат на РУЧНУЮ склейку (не автоматическую)."""
    first, last = _norm_name(bx.get("NAME") or ""), _norm_name(bx.get("LAST_NAME") or "")
    if not first:
        return None
    for row in db.q("SELECT * FROM users WHERE active=1 AND bitrix_id IS NULL"):
        if _norm_name(row["name"]) in (f"{first} {last}".strip(), f"{last} {first}".strip()):
            return row
    return None


def login_with_code(code: str) -> dict | None:
    """Внешний вход «Войти через Битрикс24»: code → токены (OAuth-сервер Битрикса, наш client_secret) → проверка, что портал наш
    (member_id, client_endpoint) → user.current на НАШЕМ портале → наш пользователь. Первые токены сохраняются как токены портала."""
    t = exchange_code(code)
    check_member(t.get("member_id"))
    host = urlparse(t.get("client_endpoint") or "").netloc.lower()
    if host and host != portal():
        raise BitrixRejected("код входа выдан другим порталом")
    bx = user_current(t["access_token"])
    if not load_tokens():
        save_tokens(t)
    return match_user(bx)


def login_from_app(form: dict) -> dict | None:
    """Открытие внутри портала: POST с AUTH_ID и member_id → сверка member_id → user.current на НАШЕМ портале (DOMAIN из запроса
    не используется) → наш пользователь."""
    token = form.get("AUTH_ID")
    if not token:
        return None
    check_member(form.get("member_id"))
    return match_user(user_current(token))


def install_from_form(form: dict) -> dict:
    """Установка локального приложения (страница установки с AUTH_ID или событие ONAPPINSTALL с auth[...]): сверка member_id; событие,
    кроме установки, — только с тем же application_token; токен проверяется app.info на нашем портале; только потом сохраняется."""
    token = form.get("AUTH_ID") or form.get("auth[access_token]")
    if not token:
        raise BitrixError("в запросе установки нет токена (AUTH_ID)")
    member = form.get("member_id") or form.get("auth[member_id]")
    app_token = form.get("auth[application_token]") or form.get("APPLICATION_TOKEN")
    event = (form.get("event") or "").upper()
    check_member(member)
    saved = load_tokens() or {}
    if event and event != "ONAPPINSTALL" and (not saved.get("application_token") or app_token != saved.get("application_token")):
        raise BitrixRejected("событие без верного application_token")
    verify_app_token(token)
    t = {"access_token": token, "refresh_token": form.get("REFRESH_ID") or form.get("auth[refresh_token]"),
         "expires_in": form.get("AUTH_EXPIRES") or form.get("auth[expires_in]"), "member_id": member,
         "scope": form.get("APPLICATION_SCOPE") or form.get("auth[scope]"), "status": form.get("status") or form.get("auth[status]"),
         "application_token": app_token}
    save_tokens(t)
    return {"ok": True, "member_id": member or saved.get("member_id"), "domain": portal()}


# ---------- уведомления и задачи ----------

def plain(text: str) -> str:
    """Текст сотрудника → в Битрикс24 без разметки: квадратные скобки заменяются похожими, [URL=…], [IMG], [USER=…] не срабатывают."""
    return (text or "").replace("[", "［").replace("]", "］")


def _demo_request() -> bool:
    """Действие из демо-входа снаружи (F-03): в настоящий Битрикс24 не дублируем."""
    from .. import auth
    return auth.DEMO_REQUEST.get()


def _public_url() -> str:
    return config.PUBLIC_URL or ""


def notify(user_id: int | None, text: str, link: str | None = None) -> None:
    """Дубль уведомления в чат Битрикса (im.notify.system.add) со ссылкой обратно. Не блокирует запрос: отправка в фоне; в тестах — синхронно."""
    if not user_id or not notify_available() or _demo_request():
        return
    row = db.one("SELECT bitrix_id FROM users WHERE id=? AND active=1", (user_id,))
    if not row or not row["bitrix_id"]:
        return
    msg = plain(text)   # F-04: текст пишут сотрудники (в том числе анонимно) — BB-коды Битрикса в нём не работают
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
    if not tasks_enabled() or not notify_available() or _demo_request():
        return None
    row = db.one("SELECT bitrix_id FROM users WHERE id=? AND active=1", (assignee_user_id,))
    if not row or not row["bitrix_id"]:
        return None
    fields = {"TITLE": plain(title)[:250], "DESCRIPTION": plain(description), "RESPONSIBLE_ID": int(row["bitrix_id"])}
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
