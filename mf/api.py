"""REST API. Права проверяются в каждом обработчике (auth.require + appeals.can_*), а не скрытием кнопок."""
from __future__ import annotations

import io
import mimetypes
import secrets
import time
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import appeals, auth, db, realtime
from .config import PUBLIC_URL, UPLOAD_DIR

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
    (UPLOAD_DIR / stored).write_bytes(data)
    aid = db.ex("INSERT INTO attachments(appeal_id, filename, stored, mime, size, created_at) VALUES(?,?,?,?,?,?)",
                (appeal_id, Path(upload.filename).name[:120], stored, mime, len(data), db.now_iso()))
    return {"id": aid, "filename": upload.filename, "size": len(data)}


# ---------- служебное и публичное (без входа) ----------

@router.get("/health")
async def health():
    return {"ok": True, "time": db.now_iso(), "appeals": db.one("SELECT COUNT(*) AS n FROM appeals")["n"]}


@router.get("/public/branches")
async def public_branches(request: Request):
    base = base_url(request)
    return [{**b, "qr_url": f"{base}/q/{b['code']}", "qr_svg": f"/api/public/qr/{b['code']}.svg"}
            for b in db.q("SELECT id, code, name, city, country FROM branches ORDER BY is_hq DESC, name")]


@router.get("/public/branch/{code}")
async def public_branch(code: str):
    b = db.one("SELECT id, code, name, city, country FROM branches WHERE code=?", (code.upper(),))
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
                        file: UploadFile | None = File(None)):
    """QR-форма: один экран, без входа. Категорию и приоритет ставит ИИ в фоне (этап 3); пока — очередь администратора.
    Если в браузере уже есть демо-вход — обращение привязывается к пользователю и даёт баллы."""
    qr_limit.check(client_ip(request))
    branch = db.one("SELECT * FROM branches WHERE code=?", (branch_code.upper(),))
    if not branch:
        raise HTTPException(404, "Филиал не найден")
    if type not in ("problem", "suggestion"):
        raise HTTPException(422, "Выберите «Проблема» или «Идея»")
    user = auth.current(request)
    a = appeals.create(type=type, text=text, branch_id=branch["id"], author=user, is_anonymous=user is None, source="qr")
    await save_attachment(a["id"], file)
    return {"id": a["id"], "number": a["number"], "tracking_token": a["tracking_token"],
            "track_url": f"/t/{a['tracking_token']}", "logged_in": user is not None}


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
        "branches": db.q("SELECT id, code, name, city, country, lat, lng, is_hq FROM branches ORDER BY is_hq DESC, name"),
        "departments": db.q("SELECT id, name FROM departments ORDER BY id"),
        "statuses": appeals.STATUSES, "types": appeals.TYPES, "priorities": appeals.PRIORITIES, "transitions": appeals.TRANSITIONS,
    }
    if user["role"] in appeals.STAFF:
        out["users"] = db.q("SELECT id, name, role, position, branch_id, department_id, manager_id, active FROM users ORDER BY name")
    return out


# ---------- приложение сотрудника ----------

@router.post("/appeals")
async def create_appeal(request: Request, type: str = Form(...), text: str = Form(...), proposed_solution: str = Form(""),
                        category_id: str = Form(""), priority: str = Form("medium"), is_anonymous: str = Form("0"),
                        file: UploadFile | None = File(None)):
    user = auth.require(request)
    a = appeals.create(type=type, text=text, proposed_solution=proposed_solution, category_id=int(category_id) if category_id else None,
                       priority=priority, author=user, is_anonymous=parse_bool(is_anonymous), source="app")
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
    auth.require(request)
    return appeals.changes()


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
    return FileResponse(UPLOAD_DIR / att["stored"], media_type=att["mime"], filename=att["filename"])


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
              "overdue": parse_bool(p.get("overdue", "")), "unassigned": parse_bool(p.get("unassigned", "")), "open": parse_bool(p.get("open", ""))})
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


@router.get("/panel/summary")
async def panel_summary(request: Request, days: int = 30, branch_id: int | None = None):
    user = auth.require(request, *appeals.STAFF)
    return appeals.summary(user, days=days, branch_id=branch_id)


@router.post("/panel/check-overdue")
async def panel_check_overdue(request: Request):
    auth.require(request, "director", "admin")
    return {"escalated": appeals.check_overdue()}
