"""REST API. Права проверяются в каждом обработчике (auth.require + appeals.can_*), а не скрытием кнопок."""
from __future__ import annotations

import io
import mimetypes
import secrets
import time
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import ai, appeals, auth, db, director, meetings, realtime
from .ai import llm, similar, stt
from . import config
from .config import LLM_MODEL, PUBLIC_URL

router = APIRouter()

MAX_ATTACH = 10 * 1024 * 1024
ALLOWED_MIME = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf", "text/plain", "text/csv",
    "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class RateLimit:
    """QR-форма без входа: не больше limit обращений с одного IP за window секунд (защита от спама, ТЗ v1.1 §14)."""

    def __init__(self, limit: int, window: int):
        self.limit, self.window, self.hits = limit, window, {}

    def check(self, key: str) -> None:
        now = time.time()
        arr = [t for t in self.hits.get(key, []) if now - t < self.window]
        if len(arr) >= self.limit:
            raise HTTPException(429, "Слишком много обращений подряд — попробуйте через несколько минут")
        arr.append(now)
        self.hits[key] = arr


qr_limit = RateLimit(10, 600)
stt_limit = RateLimit(20, 600)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def base_url(request: Request) -> str:
    return PUBLIC_URL or str(request.base_url).rstrip("/")


def parse_bool(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "on", "yes")


async def save_attachment(appeal_id: int, upload: UploadFile | None) -> dict | None:
    if not upload or not upload.filename:
        return None
    data = await upload.read(MAX_ATTACH + 1)
    if not data:
        return None
    if len(data) > MAX_ATTACH:
        raise HTTPException(413, "Файл больше 10 МБ")
    mime = upload.content_type or mimetypes.guess_type(upload.filename)[0] or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(415, "Допустимы изображения, PDF, Word, Excel и текст")
    ext = Path(upload.filename).suffix.lower()[:8]
    stored = f"{appeal_id}-{secrets.token_hex(8)}{ext}"
    (config.UPLOAD_DIR / stored).write_bytes(data)
    aid = db.ex("INSERT INTO attachments(appeal_id, filename, stored, mime, size, created_at) VALUES(?,?,?,?,?,?)",
                (appeal_id, Path(upload.filename).name[:120], stored, mime, len(data), db.now_iso()))
    return {"id": aid, "filename": upload.filename, "size": len(data)}


# ---------- служебное и публичное (без входа) ----------

@router.get("/health")
async def health():
    return {"ok": True, "time": db.now_iso(), "appeals": db.one("SELECT COUNT(*) AS n FROM appeals")["n"]}


@router.get("/public/rules")
async def public_rules():
    """«Как начисляются баллы» — простыми словами, доступно всем без входа (ТЗ v2 §2.7)."""
    cfg = appeals.points_cfg()
    rewards = db.q("SELECT title, description, cost_points FROM rewards WHERE active=1 ORDER BY id")
    return {"points": cfg, "rewards": rewards, "director_wait_days": appeals.director_wait_days()}


@router.get("/public/branches")
async def public_branches(request: Request):
    base = base_url(request)
    return [{**b, "qr_url": f"{base}/q/{b['code']}", "qr_svg": f"/api/public/qr/{b['code']}.svg"}
            for b in db.q("SELECT id, code, name, city, country, kind FROM branches ORDER BY is_hq DESC, kind, name")]


@router.get("/public/branch/{code}")
async def public_branch(code: str):
    b = db.one("SELECT id, code, name, city, country, kind FROM branches WHERE code=?", (code.upper(),))
    if not b:
        raise HTTPException(404, "Филиал не найден — QR-код не распознан")
    return b


@router.get("/public/qr/{code}.svg")
async def public_qr(code: str, request: Request):
    b = db.one("SELECT code FROM branches WHERE code=?", (code.upper(),))
    if not b:
        raise HTTPException(404, "Филиал не найден")
    img = qrcode.make(f"{base_url(request)}/q/{b['code']}", image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})


@router.post("/public/appeals")
async def public_create(request: Request, type: str = Form(...), text: str = Form(...), branch_code: str = Form(...),
                        file: UploadFile | None = File(None), site_city: str = Form(""), author_urgency: str = Form(""),
                        author_scope: str = Form(""), input_mode: str = Form("")):
    """QR-форма: один экран, без входа. Категорию и приоритет ставит ИИ (mf/ai: LLM, без ключа — словарь ключевых слов);
    «Без ответственного» — только при вакансии категории или если ни ИИ, ни словарь не уверены (ТЗ §7).
    Если в браузере уже есть демо-вход — обращение привязывается к пользователю и даёт баллы."""
    qr_limit.check(client_ip(request))
    branch = db.one("SELECT * FROM branches WHERE code=?", (branch_code.upper(),))
    if not branch:
        raise HTTPException(404, "Филиал не найден")
    if type not in ("problem", "suggestion"):
        raise HTTPException(422, "Выберите «Проблема» или «Идея»")
    user = auth.current(request)
    cls = await classify(text, type, author_urgency or None, author_scope or None)
    a = appeals.create(type=type, text=text, category_id=cls["category_id"], priority=cls.get("priority") or "",
                       branch_id=branch["id"], author=user, is_anonymous=user is None, source="qr", ai=cls,
                       site_city=site_city if branch["kind"] == "field" else None, author_urgency=author_urgency or None,
                       author_scope=author_scope or None, input_mode=input_mode or "text")
    await save_attachment(a["id"], file)
    return {"id": a["id"], "number": a["number"], "tracking_token": a["tracking_token"],
            "track_url": f"/t/{a['tracking_token']}", "logged_in": user is not None,
            "category": a["category"], "responsible": a["responsible"], "priority": a["priority"], "ai_engine": cls.get("engine"),
            "brief": appeals.brief_of(a)}


async def classify(text: str, type_hint: str | None, author_urgency: str | None = None, author_scope: str | None = None,
                   supports: int = 0, clarifications: list | None = None) -> dict:
    """ИИ: категория, приоритет и «Коротко» одним вызовом (LLM в threadpool); без ключа — словарь, матрица и первые два предложения.
    Любая ошибка → без категории, не 500."""
    import asyncio
    cats = db.q("""SELECT c.id, c.name, CASE WHEN u.id IS NULL THEN NULL ELSE u.name || ', ' || COALESCE(u.position, u.role) END AS responsible
                   FROM categories c LEFT JOIN users u ON u.id=c.responsible_user_id AND u.active=1 ORDER BY c.id""")
    try:
        return await asyncio.to_thread(ai.classify_appeal, text, cats, type_hint, author_urgency, author_scope, supports, clarifications)
    except Exception as e:   # noqa: BLE001
        return {"category_id": None, "category": None, "confidence": 0.0, "priority": appeals.matrix_priority(type_hint or "problem", author_urgency, author_scope) or "medium",
                "brief": None, "engine": f"error: {e}"[:120]}


class BriefQ(BaseModel):
    text: str
    type: str | None = None


@router.post("/public/brief")
async def public_brief(body: BriefQ, request: Request):
    """«Мы поняли так: …» в QR-форме после голосового ввода — не блокирует отправку."""
    stt_limit.check(client_ip(request) + ":brief")
    text = (body.text or "").strip()
    if len(text) < 8:
        raise HTTPException(422, "Слишком короткий текст")
    cls = await classify(text, body.type)
    return {"brief": cls.get("brief"), "category": cls.get("category"), "engine": cls.get("engine")}


@router.get("/public/track/{token}")
async def public_track(token: str, request: Request):
    a = appeals.by_token(token)
    return appeals.view(a, user=auth.current(request), public=True)


class Text(BaseModel):
    text: str


@router.post("/public/track/{token}/answer")
async def public_answer(token: str, body: Text, request: Request):
    a = appeals.by_token(token)
    user = auth.current(request)
    actor = user["id"] if user and appeals.author_id(a["id"]) == user["id"] and not a["is_anonymous"] else None
    appeals.answer_clarification(a["id"], body.text, actor_id=actor)
    return {"ok": True}


# ---------- вход ----------

class LoginAs(BaseModel):
    user_id: int


@router.get("/auth/users")
async def auth_users():
    rows = db.q("""SELECT u.id, u.name, u.role, u.position, b.name AS branch, d.name AS department
                   FROM users u LEFT JOIN branches b ON b.id=u.branch_id LEFT JOIN departments d ON d.id=u.department_id
                   WHERE u.active=1 ORDER BY CASE u.role WHEN 'director' THEN 0 WHEN 'admin' THEN 1 WHEN 'responsible' THEN 2 ELSE 3 END, u.id""")
    for r in rows:
        r["role_label"] = auth.ROLE_LABEL[r["role"]]
    return rows


@router.post("/auth/login-as")
async def login_as(body: LoginAs, request: Request, response: Response):
    auth.logout(request.cookies.get(auth.COOKIE))
    token = auth.login(body.user_id)
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", max_age=30 * 86400, path="/")
    return auth.public(auth.user_by_id(body.user_id))


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    user = auth.require(request)
    out = auth.public(user)
    out["unread"] = db.one("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND read_at IS NULL", (user["id"],))["n"]
    out["points"] = appeals.balance(user["id"])
    return out


@router.get("/dicts")
async def dicts(request: Request):
    user = auth.require(request)
    out = {
        "categories": db.q("SELECT c.id, c.name, c.responsible_user_id, c.sla_first_response_hours AS sla, u.name AS responsible "
                           "FROM categories c LEFT JOIN users u ON u.id=c.responsible_user_id ORDER BY c.id"),
        "branches": db.q("SELECT id, code, name, city, country, lat, lng, is_hq, kind FROM branches ORDER BY is_hq DESC, kind, name"),
        "departments": db.q("SELECT id, name FROM departments ORDER BY id"),
        "statuses": appeals.STATUSES, "types": appeals.TYPES, "priorities": appeals.PRIORITIES, "transitions": appeals.TRANSITIONS,
    }
    if user["role"] in appeals.STAFF:
        out["users"] = db.q("SELECT id, name, role, position, branch_id, department_id, manager_id, active FROM users ORDER BY name")
    return out


# ---------- приложение сотрудника ----------

@router.post("/appeals")
async def create_appeal(request: Request, type: str = Form(...), text: str = Form(...), proposed_solution: str = Form(""),
                        category_id: str = Form(""), priority: str = Form(""), is_anonymous: str = Form("0"),
                        file: UploadFile | None = File(None), author_urgency: str = Form(""), author_scope: str = Form(""), input_mode: str = Form("")):
    user = auth.require(request)
    cls = None
    if type != "praise":   # один вызов ИИ: категория (если не выбрана), приоритет по ответу автора и «Коротко»
        cls = await classify(text + ("\n" + proposed_solution if proposed_solution else ""), type, author_urgency or None, author_scope or None)
        category_id = category_id or (cls["category_id"] or "")
        if cls.get("engine") != "openai":
            cls = {**cls, "category_id": int(category_id) if category_id else None}
    prio = priority if priority in appeals.PRIORITIES else ((cls or {}).get("priority") or "")
    a = appeals.create(type=type, text=text, proposed_solution=proposed_solution, category_id=int(category_id) if category_id else None,
                       priority=prio, author=user, is_anonymous=parse_bool(is_anonymous), source="app", ai=cls,
                       author_urgency=author_urgency or None, author_scope=author_scope or None, input_mode=input_mode or "text")
    await save_attachment(a["id"], file)
    return appeals.view(appeals.get(a["id"]), user)


@router.get("/appeals/mine")
async def my_appeals(request: Request):
    return appeals.mine(auth.require(request))


@router.get("/appeals/{appeal_id}")
async def get_appeal(appeal_id: int, request: Request):
    user = auth.require(request)
    a = appeals.get(appeal_id)
    if not appeals.can_view(a, user):
        raise HTTPException(403, "Это обращение вам недоступно")
    return appeals.view(a, user)


@router.post("/appeals/{appeal_id}/support")
async def support(appeal_id: int, request: Request):
    user = auth.require(request)
    return {"supports": appeals.support(appeal_id, user)}


@router.post("/appeals/{appeal_id}/answer")
async def answer(appeal_id: int, body: Text, request: Request):
    user = auth.require(request)
    a = appeals.get(appeal_id)
    if appeals.author_id(appeal_id) != user["id"]:
        raise HTTPException(403, "Ответить на уточнение может только автор")
    appeals.answer_clarification(appeal_id, body.text, actor_id=None if a["is_anonymous"] else user["id"])
    return appeals.view(appeals.get(appeal_id), user)


@router.get("/changes")
async def changes(request: Request):
    return appeals.changes_for(auth.require(request))


@router.post("/appeals/{appeal_id}/thank")
async def thank(appeal_id: int, request: Request):
    return {"thanks": appeals.thank(appeal_id, auth.require(request))}


# ---------- профиль и аватарки (витрина вклада, этап 4) ----------

@router.get("/users/{user_id}/profile")
async def profile(user_id: int, request: Request):
    auth.require(request)
    u = db.one("""SELECT u.id, u.name, u.position, u.avatar, u.role, b.name AS branch, b.city, d.name AS department FROM users u
                  LEFT JOIN branches b ON b.id=u.branch_id LEFT JOIN departments d ON d.id=u.department_id WHERE u.id=? AND u.active=1""", (user_id,))
    if not u:
        raise HTTPException(404, "Сотрудник не найден")
    implemented = db.q("""SELECT a.id, a.number, a.text, a.resolution_text, a.closed_at FROM appeals a JOIN appeal_authors aa ON aa.appeal_id=a.id
                          WHERE aa.user_id=? AND a.status IN ('done','closed') AND a.type != 'praise' AND a.is_anonymous=0 ORDER BY a.closed_at DESC""", (user_id,))
    for i in implemented:
        i["text"] = appeals.short(i["text"], 120)
    return {"id": u["id"], "name": u["name"], "position": u["position"], "role": u["role"], "branch": u["branch"], "city": u["city"], "department": u["department"],
            "avatar": appeals.avatar_url(u["id"], u["avatar"]), "points": appeals.balance(user_id), "implemented": implemented,
            "thanks": db.one("SELECT COUNT(*) AS n FROM thanks t JOIN appeal_authors aa ON aa.appeal_id=t.appeal_id WHERE aa.user_id=?", (user_id,))["n"],
            "supported": db.one("SELECT COUNT(*) AS n FROM supports WHERE user_id=?", (user_id,))["n"],
            "appeals": db.one("SELECT COUNT(*) AS n FROM appeal_authors aa JOIN appeals a ON a.id=aa.appeal_id WHERE aa.user_id=? AND a.is_anonymous=0", (user_id,))["n"]}


AVATAR_MAX = 3 * 1024 * 1024


@router.post("/me/avatar")
async def upload_avatar(request: Request, file: UploadFile = File(...)):
    """Своя картинка: квадратная обрезка по центру, 256×256 JPEG; хранится в папке данных, в базе — имя файла."""
    user = auth.require(request)
    data = await file.read(AVATAR_MAX + 1)
    if len(data) > AVATAR_MAX:
        raise HTTPException(413, "Картинка больше 3 МБ")
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img = ImageOps.fit(img, (256, 256), method=Image.LANCZOS, centering=(0.5, 0.4))
    except Exception:   # noqa: BLE001
        raise HTTPException(415, "Нужна картинка (JPEG, PNG, WebP)")
    name = f"u{user['id']}-{secrets.token_hex(6)}.jpg"
    img.save(config.AVATAR_DIR / name, "JPEG", quality=85)
    old = db.one("SELECT avatar FROM users WHERE id=?", (user["id"],))["avatar"]
    db.ex("UPDATE users SET avatar=? WHERE id=?", (name, user["id"]))
    if old:
        (config.AVATAR_DIR / old).unlink(missing_ok=True)
    return {"avatar": f"/api/avatars/{name}"}


@router.get("/avatars/{name}")
async def avatar_file(name: str):
    if "/" in name or ".." in name or not name.endswith(".jpg"):
        raise HTTPException(404)
    path = config.AVATAR_DIR / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/admin/users/{user_id}/avatar/remove")
async def remove_avatar(user_id: int, request: Request):
    """Администратор убирает неуместную аватарку."""
    auth.require(request, "admin", "director")
    old = db.one("SELECT avatar FROM users WHERE id=?", (user_id,))
    if old and old["avatar"]:
        (config.AVATAR_DIR / old["avatar"]).unlink(missing_ok=True)
        db.ex("UPDATE users SET avatar=NULL WHERE id=?", (user_id,))
    return {"ok": True}


@router.get("/me/points")
async def my_points(request: Request):
    user = auth.require(request)
    ledger = db.q("""SELECT l.id, l.amount, l.reason, l.created_at, a.number, a.id AS appeal_id FROM points_ledger l
                     LEFT JOIN appeals a ON a.id=l.appeal_id WHERE l.user_id=? ORDER BY l.id DESC LIMIT 100""", (user["id"],))
    for r in ledger:
        r["reason_label"] = appeals.POINT_REASONS.get(r["reason"], r["reason"])
    return {"balance": appeals.balance(user["id"]), "ledger": ledger, "rules": appeals.points_cfg()}


@router.get("/notifications")
async def notifications(request: Request):
    user = auth.require(request)
    rows = db.q("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50", (user["id"],))
    return {"items": rows, "unread": sum(1 for r in rows if not r["read_at"])}


class ReadBody(BaseModel):
    ids: list[int] | None = None


@router.post("/notifications/read")
async def notifications_read(body: ReadBody, request: Request):
    user = auth.require(request)
    if body.ids:
        for i in body.ids:
            db.ex("UPDATE notifications SET read_at=? WHERE id=? AND user_id=? AND read_at IS NULL", (db.now_iso(), i, user["id"]))
    else:
        db.ex("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (db.now_iso(), user["id"]))
    return {"ok": True}


@router.get("/events/stream")
async def events_stream(request: Request):
    user = auth.require(request)
    return StreamingResponse(realtime.stream(user, request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/attachments/{att_id}")
async def attachment(att_id: int, request: Request, t: str | None = None):
    """Вложение отдаётся только после проверки прав: сотрудник с доступом к обращению или владелец трекинг-ссылки."""
    att = db.one("SELECT * FROM attachments WHERE id=?", (att_id,))
    if not att:
        raise HTTPException(404, "Файл не найден")
    a = appeals.get(att["appeal_id"])
    user = auth.current(request)
    allowed = (t and secrets.compare_digest(t, a["tracking_token"])) or (user and appeals.can_view(a, user))
    if not allowed:
        raise HTTPException(403, "Нет доступа к файлу")
    return FileResponse(config.UPLOAD_DIR / att["stored"], media_type=att["mime"], filename=att["filename"])


# ---------- панель ----------

def _manage(appeal_id: int, user: dict) -> dict:
    a = appeals.get(appeal_id)
    if not appeals.can_manage(a, user):
        raise HTTPException(403, "Обращение вне вашей зоны ответственности")
    return a


@router.get("/panel/appeals")
async def panel_list(request: Request):
    user = auth.require(request, *appeals.STAFF)
    p = request.query_params
    f = {k: (int(p[k]) if p.get(k) else None) for k in ("branch_id", "department_id", "category_id", "responsible_id", "days")}
    f.update({"status": p.get("status") or None, "type": p.get("type") or None, "q": (p.get("q") or "").strip() or None,
              "overdue": parse_bool(p.get("overdue", "")), "unassigned": parse_bool(p.get("unassigned", "")), "open": parse_bool(p.get("open", "")),
              "urgency": p.get("urgency") or None, "cluster_id": p.get("cluster_id") or None, "sort": p.get("sort") or None})
    return appeals.list_for(user, f)


class Assign(BaseModel):
    responsible_id: int


class StatusChange(BaseModel):
    status: str
    text: str | None = None


@router.post("/panel/appeals/{appeal_id}/assign")
async def panel_assign(appeal_id: int, body: Assign, request: Request):
    user = auth.require(request, *appeals.STAFF)
    _manage(appeal_id, user)
    return appeals.view(appeals.assign(appeal_id, user, body.responsible_id), user)


@router.post("/panel/appeals/{appeal_id}/status")
async def panel_status(appeal_id: int, body: StatusChange, request: Request):
    user = auth.require(request, *appeals.STAFF)
    _manage(appeal_id, user)
    return appeals.view(appeals.set_status(appeal_id, user, body.status, body.text), user)


@router.post("/panel/appeals/{appeal_id}/comment")
async def panel_comment(appeal_id: int, body: Text, request: Request):
    user = auth.require(request, *appeals.STAFF)
    _manage(appeal_id, user)
    return appeals.view(appeals.comment(appeal_id, user, body.text), user)


@router.post("/panel/appeals/{appeal_id}/clarify")
async def panel_clarify(appeal_id: int, body: Text, request: Request):
    user = auth.require(request, *appeals.STAFF)
    _manage(appeal_id, user)
    return appeals.view(appeals.request_clarification(appeal_id, user, body.text), user)


class Priority(BaseModel):
    priority: str


@router.post("/panel/appeals/{appeal_id}/priority")
async def panel_priority(appeal_id: int, body: Priority, request: Request):
    user = auth.require(request, *appeals.STAFF)
    _manage(appeal_id, user)
    return appeals.view(appeals.set_priority(appeal_id, user, body.priority), user)


@router.post("/panel/appeals/{appeal_id}/progress")
async def panel_progress(appeal_id: int, body: Text, request: Request):
    """«Сообщить о ходе»: новость автору без смены статуса (по словам собственника)."""
    user = auth.require(request, *appeals.STAFF)
    _manage(appeal_id, user)
    return appeals.view(appeals.progress(appeal_id, user, body.text), user)


@router.post("/panel/appeals/{appeal_id}/rebrief")
async def panel_rebrief(appeal_id: int, request: Request):
    """«Пересказать заново» — с учётом ответов автора на уточнения."""
    user = auth.require(request, *appeals.STAFF)
    a = _manage(appeal_id, user)
    events = appeals.events_of(appeal_id)
    qa, q = [], None
    for e in events:
        if e["kind"] == "clarification_requested":
            q = e["payload"].get("text")
        elif e["kind"] == "clarification_answered" and q:
            qa.append({"q": q, "a": e["payload"].get("text")}); q = None
    cls = await classify(a["text"], a["type"], a.get("author_urgency"), a.get("author_scope"), a["supports"], qa or None)
    if cls.get("brief"):
        appeals.set_brief(appeal_id, cls["brief"], cls.get("engine"))
        appeals.add_event(appeal_id, user["id"], "rebriefed", {"engine": cls.get("engine"), "clarifications": len(qa)})
    return appeals.view(appeals.get(appeal_id), user)


@router.post("/panel/appeals/{appeal_id}/director")
async def panel_request_director(appeal_id: int, body: Text, request: Request):
    """«Нужно решение директора» (ТЗ v2 §2.1): предложение попадает в «На решение» вместе с идеями совещаний."""
    user = auth.require(request, *appeals.STAFF)
    _manage(appeal_id, user)
    return appeals.view(appeals.request_director(appeal_id, user, body.text), user)


class DirectorDecision(BaseModel):
    decision: str
    comment: str | None = None


@router.post("/director/appeals/{appeal_id}/decide")
async def director_decide(appeal_id: int, body: DirectorDecision, request: Request):
    user = auth.require(request, "director", "admin")
    return appeals.view(appeals.director_decide(appeal_id, user, body.decision, body.comment), user)


@router.get("/panel/summary")
async def panel_summary(request: Request, days: int = 30, branch_id: int | None = None):
    user = auth.require(request, *appeals.STAFF)
    return appeals.summary(user, days=days, branch_id=branch_id)


@router.post("/panel/check-overdue")
async def panel_check_overdue(request: Request):
    auth.require(request, "director", "admin")
    return {"escalated": appeals.check_overdue()}


# ---------- ИИ: что реально доступно (честная плашка в интерфейсе) ----------

@router.get("/ai/status")
async def ai_status(request: Request):
    auth.require(request)
    return {"llm": llm.available(), "llm_model": LLM_MODEL if llm.available() else None, "stt": stt.available(),
            "fallback": not llm.available(), "classifier": "openai" if llm.available() else "keywords"}


# ---------- совещания (ТЗ §6.2) ----------

AUDIO_EXT = {"audio/webm": ".webm", "video/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "video/mp4": ".mp4", "audio/mpeg": ".mp3",
             "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/x-m4a": ".m4a", "audio/aac": ".aac", "audio/flac": ".flac", "audio/3gpp": ".3gp",
             "video/quicktime": ".mov", "video/x-matroska": ".mkv", "video/x-msvideo": ".avi"}   # записи видеозвонков: берём звуковую дорожку
MAX_AUDIO = 300 * 1024 * 1024   # видеозвонок на час — сотни мегабайт; удаляется сразу после расшифровки


@router.post("/meetings")
async def create_meeting(request: Request, background: BackgroundTasks, title: str = Form(""), transcript: str = Form(""),
                         duration_sec: str = Form(""), audio: UploadFile | None = File(None)):
    """Аудио (MediaRecorder / файл) или текстовая расшифровка → processing; обработка в фоне, фронт опрашивает GET /meetings/{id}."""
    user = auth.require(request, *appeals.STAFF)
    audio_path = None
    if audio and audio.filename:
        data = await audio.read(MAX_AUDIO + 1)
        if len(data) > MAX_AUDIO:
            raise HTTPException(413, "Запись больше 300 МБ — разбейте на части")
        if len(data) < 1000:
            raise HTTPException(422, "Запись пустая — попробуйте ещё раз")
        mime = (audio.content_type or "").split(";")[0].strip()
        ext = AUDIO_EXT.get(mime) or Path(audio.filename).suffix.lower()[:6] or ".bin"
        audio_path = config.AUDIO_DIR / f"{secrets.token_hex(8)}{ext}"
        audio_path.write_bytes(data)
    elif len(transcript.strip()) < 20:
        raise HTTPException(422, "Нужна запись или текст расшифровки (хотя бы пара фраз)")
    mid = meetings.create(user, title, transcript=transcript if not audio_path else None, audio_path=audio_path,
                          duration_sec=int(duration_sec) if duration_sec.isdigit() else None)
    background.add_task(meetings.process, mid)
    return {"id": mid, "status": "processing", "stage": "stt" if audio_path else "analysis"}


@router.get("/meetings")
async def list_meetings(request: Request, overdue: str = ""):
    return meetings.list_for(auth.require(request, *appeals.STAFF), overdue_only=parse_bool(overdue))


@router.get("/tasks/overdue")
async def tasks_overdue(request: Request):
    return meetings.overdue_summary(auth.require(request, *appeals.STAFF))


@router.post("/panel/check-tasks")
async def panel_check_tasks(request: Request):
    auth.require(request, "director", "admin")
    return meetings.check_tasks()


@router.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: int, request: Request):
    return meetings.view(meeting_id, auth.require(request, *appeals.STAFF))


class ItemPatch(BaseModel):
    text: str | None = None
    removed: bool | None = None
    assignee_id: int | None = None
    due_date: str | None = None
    category_id: int | None = None
    linked_appeal_id: int | None = None


@router.post("/meetings/{meeting_id}/items/{item_id}")
async def patch_item(meeting_id: int, item_id: int, body: ItemPatch, request: Request):
    user = auth.require(request, *appeals.STAFF)
    return meetings.update_item(meeting_id, item_id, user, body.model_dump(exclude_unset=True))


class ItemNew(BaseModel):
    kind: str
    text: str
    assignee_id: int | None = None
    due_date: str | None = None
    type: str | None = None
    category_id: int | None = None
    linked_appeal_id: int | None = None


@router.post("/meetings/{meeting_id}/items")
async def new_item(meeting_id: int, body: ItemNew, request: Request):
    user = auth.require(request, *appeals.STAFF)
    d = body.model_dump()
    return meetings.add_item(meeting_id, user, d.pop("kind"), d.pop("text"), **d)


@router.post("/meetings/{meeting_id}/send")
async def send_meeting(meeting_id: int, request: Request):
    return meetings.send(meeting_id, auth.require(request, *appeals.STAFF))


# ---------- мои поручения ----------

@router.get("/tasks/mine")
async def my_tasks(request: Request):
    return meetings.my_tasks(auth.require(request))


class TaskStatus(BaseModel):
    status: str


@router.post("/tasks/{item_id}/status")
async def task_status(item_id: int, body: TaskStatus, request: Request):
    return meetings.set_task_status(item_id, auth.require(request), body.status)


# ---------- «На решение» у директора (общий API для /app и /panel) ----------

@router.get("/director/ideas")
async def director_ideas(request: Request):
    return meetings.director_ideas(auth.require(request, "director", "admin"))


class Accept(BaseModel):
    category_id: int | None = None


class Reject(BaseModel):
    reason: str


@router.post("/director/ideas/{item_id}/accept")
async def accept_idea(item_id: int, body: Accept, request: Request):
    return meetings.accept_idea(item_id, auth.require(request, "director", "admin"), body.category_id)


@router.post("/director/ideas/{item_id}/reject")
async def reject_idea(item_id: int, body: Reject, request: Request):
    return meetings.reject_idea(item_id, auth.require(request, "director", "admin"), body.reason)


# ---------- этап 3: голос, черновик ИИ, похожие обращения, кластеры ----------

async def _transcribe_upload(audio: UploadFile | None, language: str | None) -> dict:
    """Аудио → текст тем же адаптером, что и совещания; файл живёт только на время расшифровки."""
    if not audio or not audio.filename:
        raise HTTPException(422, "Нет аудио")
    data = await audio.read(MAX_AUDIO + 1)
    if len(data) > MAX_AUDIO:
        raise HTTPException(413, "Запись больше 300 МБ")
    if len(data) < 1000:
        raise HTTPException(422, "Запись пустая — попробуйте ещё раз")
    mime = (audio.content_type or "").split(";")[0].strip()
    ext = AUDIO_EXT.get(mime) or Path(audio.filename).suffix.lower()[:6] or ".bin"
    path = config.AUDIO_DIR / f"v-{secrets.token_hex(8)}{ext}"
    path.write_bytes(data)
    import asyncio
    try:
        r = await asyncio.to_thread(stt.transcribe, path, (language or "").strip() or None)
    except stt.STTError as e:
        raise HTTPException(503, f"Распознавание речи недоступно: {e}")
    finally:
        path.unlink(missing_ok=True)
    return {"text": r["text"].replace("\n", " ").strip(), "language": r.get("language"), "engine": r["engine"], "seconds": r.get("seconds")}


@router.post("/stt")
async def stt_app(request: Request, audio: UploadFile | None = File(None), language: str = Form("")):
    auth.require(request)
    return await _transcribe_upload(audio, language)


@router.post("/public/stt")
async def stt_public(request: Request, audio: UploadFile | None = File(None), language: str = Form("")):
    """Голосовой ввод в QR-форме без входа: ограничение частоты по IP, аудио удаляется сразу."""
    stt_limit.check(client_ip(request))
    return await _transcribe_upload(audio, language)


class Draft(BaseModel):
    text: str
    type: str | None = None


@router.post("/ai/draft")
async def ai_draft(body: Draft, request: Request):
    """Черновик ИИ по схеме «Структурирование обращения» (ТЗ §7); без ключа — словарь: категория есть, сути и вопроса нет."""
    auth.require(request)
    text = (body.text or "").strip()
    if len(text) < 5:
        raise HTTPException(422, "Напишите хотя бы несколько слов")
    return await classify(text, body.type)


class SimilarQ(BaseModel):
    text: str
    exclude_id: int | None = None


@router.post("/ai/similar")
async def ai_similar(body: SimilarQ, request: Request):
    auth.require(request)
    import asyncio
    return await asyncio.to_thread(similar.similar, body.text, body.exclude_id)


@router.post("/public/similar")
async def public_similar(body: SimilarQ, request: Request):
    """«Похоже, об этом уже сообщали» в QR-форме: номер и короткий текст, без авторов; максимум два."""
    import asyncio
    r = await asyncio.to_thread(similar.similar, body.text, None, 2)
    for i in r["items"]:
        i.pop("supports", None)
    r["logged_in"] = auth.current(request) is not None
    return r


@router.get("/panel/clusters")
async def panel_clusters(request: Request):
    auth.require(request, *appeals.STAFF)
    import asyncio
    return await asyncio.to_thread(similar.clusters)


# ---------- этап 4: главная директора, лига, карта, награды, настройки ----------

@router.get("/panel/director-summary")
async def director_summary(request: Request, refresh: str = "", engine: str = ""):
    """engine=template — показать шаблон без ИИ (для сравнения на демо)."""
    user = auth.require(request, *appeals.STAFF)
    import asyncio
    return await asyncio.to_thread(director.summary, user, parse_bool(refresh), engine == "template")


@router.get("/panel/map")
async def panel_map(request: Request):
    auth.require(request, *appeals.STAFF)
    return director.map_data()


@router.get("/panel/league")
async def panel_league(request: Request):
    auth.require(request)
    return {**director.league(), "top": director.top_employees()}


@router.get("/rewards")
async def rewards(request: Request):
    user = auth.require(request)
    items = db.q("SELECT id, title, description, cost_points FROM rewards WHERE active=1 ORDER BY id")
    claims = db.q("""SELECT c.id, c.reward_id, c.status, c.created_at, c.comment, r.title, r.cost_points FROM reward_claims c JOIN rewards r ON r.id=c.reward_id
                     WHERE c.user_id=? ORDER BY c.id DESC""", (user["id"],))
    return {"balance": appeals.balance(user["id"]), "items": items, "claims": claims}


@router.post("/rewards/{reward_id}/claim")
async def claim_reward(reward_id: int, request: Request):
    """Заявка на награду: баллы списываются при одобрении администратором или директором (журнал баллов — только на добавление)."""
    user = auth.require(request)
    r = db.one("SELECT * FROM rewards WHERE id=? AND active=1", (reward_id,))
    if not r:
        raise HTTPException(404, "Награда не найдена")
    if appeals.balance(user["id"]) < r["cost_points"]:
        raise HTTPException(409, f"Не хватает баллов: нужно {r['cost_points']}, у вас {appeals.balance(user['id'])}")
    if db.one("SELECT 1 FROM reward_claims WHERE user_id=? AND reward_id=? AND status='requested'", (user["id"], reward_id)):
        raise HTTPException(409, "Заявка уже подана")
    cid = db.ex("INSERT INTO reward_claims(user_id, reward_id, status, created_at) VALUES(?,?,'requested',?)", (user["id"], reward_id, db.now_iso()))
    for uid in appeals.admins() + [d["id"] for d in db.q("SELECT id FROM users WHERE role='director' AND active=1")]:
        appeals.notify(uid, f"Заявка на награду «{r['title']}» от {user['name']} ({r['cost_points']} баллов)", "/panel#/admin")
    return {"id": cid, "status": "requested"}


class ClaimDecision(BaseModel):
    decision: str
    comment: str | None = None


@router.get("/admin/reward-claims")
async def reward_claims(request: Request):
    auth.require(request, "admin", "director")
    return db.q("""SELECT c.*, r.title, r.cost_points, u.name AS user_name FROM reward_claims c JOIN rewards r ON r.id=c.reward_id JOIN users u ON u.id=c.user_id
                   ORDER BY CASE c.status WHEN 'requested' THEN 0 ELSE 1 END, c.id DESC LIMIT 100""")


@router.post("/admin/reward-claims/{claim_id}/decide")
async def decide_claim(claim_id: int, body: ClaimDecision, request: Request):
    user = auth.require(request, "admin", "director")
    c = db.one("SELECT c.*, r.title, r.cost_points FROM reward_claims c JOIN rewards r ON r.id=c.reward_id WHERE c.id=?", (claim_id,))
    if not c or c["status"] != "requested":
        raise HTTPException(409, "Заявка не найдена или уже решена")
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(422, "approved или rejected")
    if body.decision == "approved":
        if appeals.balance(c["user_id"]) < c["cost_points"]:
            raise HTTPException(409, "У сотрудника уже не хватает баллов")
        db.ex("INSERT INTO points_ledger(user_id, appeal_id, reason, amount, created_at) VALUES(?,?,?,?,?)",
              (c["user_id"], None, f"reward:{c['title']}", -c["cost_points"], db.now_iso()))
    db.ex("UPDATE reward_claims SET status=?, comment=?, decided_at=?, decided_by=? WHERE id=?", (body.decision, (body.comment or "").strip() or None, db.now_iso(), user["id"], claim_id))
    appeals.notify(c["user_id"], f"Награда «{c['title']}»: " + ("одобрена — поздравляем!" if body.decision == "approved" else "отклонена" + (f": {body.comment}" if body.comment else "")), "/app#/rewards")
    return {"ok": True}


SETTING_KEYS = ("points", "director_wait_days", "news_days", "similar_threshold", "cluster_threshold", "league_weights", "dev_department_head_id", "tz_offset_hours")


@router.get("/admin/settings")
async def admin_settings(request: Request):
    auth.require(request, "admin", "director")
    return {"settings": {k: db.setting(k) for k in SETTING_KEYS},
            "categories": db.q("""SELECT c.id, c.name, c.responsible_user_id, c.suggestion_responsible_user_id, c.sla_first_response_hours AS sla,
                                  u.name AS responsible, s.name AS suggestion_responsible, (SELECT COUNT(*) FROM appeals a WHERE a.category_id=c.id) AS appeals
                                  FROM categories c LEFT JOIN users u ON u.id=c.responsible_user_id LEFT JOIN users s ON s.id=c.suggestion_responsible_user_id ORDER BY c.id"""),
            "users": db.q("SELECT id, name, role, position, active, avatar FROM users ORDER BY name"),
            "branches": db.q("SELECT id, code, name, city, kind FROM branches ORDER BY is_hq DESC, name"),
            "rewards": db.q("SELECT * FROM rewards ORDER BY id")}


class SettingsBody(BaseModel):
    settings: dict


@router.post("/admin/settings")
async def admin_settings_save(body: SettingsBody, request: Request):
    auth.require(request, "admin", "director")
    for k, v in body.settings.items():
        if k in SETTING_KEYS:
            db.set_setting(k, v)
    return {"ok": True, "settings": {k: db.setting(k) for k in SETTING_KEYS}}


class CategoryBody(BaseModel):
    responsible_user_id: int | None = None
    suggestion_responsible_user_id: int | None = None
    sla: int | None = None
    name: str | None = None


@router.post("/admin/categories/{category_id}")
async def admin_category(category_id: int, body: CategoryBody, request: Request):
    auth.require(request, "admin", "director")
    if not db.one("SELECT 1 FROM categories WHERE id=?", (category_id,)):
        raise HTTPException(404, "Категория не найдена")
    d = body.model_dump(exclude_unset=True)
    if "responsible_user_id" in d:
        db.ex("UPDATE categories SET responsible_user_id=? WHERE id=?", (d["responsible_user_id"], category_id))
    if "suggestion_responsible_user_id" in d:
        db.ex("UPDATE categories SET suggestion_responsible_user_id=? WHERE id=?", (d["suggestion_responsible_user_id"], category_id))
    if d.get("sla"):
        db.ex("UPDATE categories SET sla_first_response_hours=? WHERE id=?", (int(d["sla"]), category_id))
    if d.get("name"):
        db.ex("UPDATE categories SET name=? WHERE id=?", (d["name"].strip(), category_id))
    return db.one("SELECT c.id, c.name, c.responsible_user_id, c.suggestion_responsible_user_id, c.sla_first_response_hours AS sla FROM categories c WHERE c.id=?", (category_id,))


@router.post("/panel/check-news")
async def panel_check_news(request: Request):
    auth.require(request, "director", "admin")
    return {"reminded": appeals.check_news()}
