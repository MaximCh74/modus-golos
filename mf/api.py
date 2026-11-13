"""REST API. Права проверяются в каждом обработчике (auth.require + appeals.can_*), а не скрытием кнопок."""
from __future__ import annotations

import io
import logging
import mimetypes
import secrets
import time
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import ai, appeals, auth, boss, commands, db, demo, director, glossary, images, meetings, posters, realtime, staff, version
from .ai import llm, similar, stt
from .integrations import bitrix
from . import config
from .config import LLM_MODEL, PUBLIC_URL

router = APIRouter()
log = logging.getLogger("mf.api")

MAX_ATTACH = 10 * 1024 * 1024
ALLOWED_MIME = {
    "image/jpeg", "image/png", "image/webp", "application/pdf", "text/plain", "text/csv",
    "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}   # GIF убран (аудит 12.11): декодер GIF в Pillow 12.3.0 уязвим, фото с телефона — JPEG/PNG/WebP
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # старые .doc/.xls


def _content_ok(mime: str, data: bytes) -> bool:
    """F-17: тип по содержимому, а не по заголовку клиента."""
    if mime == "application/pdf":
        return data[:5] == b"%PDF-"
    if mime.endswith("openxmlformats-officedocument.wordprocessingml.document") or mime.endswith("openxmlformats-officedocument.spreadsheetml.sheet"):
        return data[:4] == b"PK\x03\x04"
    if mime in ("application/msword", "application/vnd.ms-excel"):
        return data[:8] == OLE
    if mime in ("text/plain", "text/csv"):
        if b"\x00" in data:
            return False
        for enc in ("utf-8", "cp1251"):
            try:
                data.decode(enc)
                return True
            except UnicodeDecodeError:
                continue
        return False
    return False


class RateLimit:
    """QR-форма без входа: не больше limit обращений с одного IP за window секунд (защита от спама, ТЗ v1.1 §14)."""

    def __init__(self, limit: int, window: int, message: str = "Слишком много обращений подряд — попробуйте через несколько минут",
                 burst: tuple[int, int] | None = None):
        self.limit, self.window, self.hits, self.message, self.burst = limit, window, {}, message, burst

    def check(self, key: str) -> None:
        now = time.time()
        arr = [t for t in self.hits.get(key, []) if now - t < self.window]
        if len(arr) >= self.limit:
            raise HTTPException(429, self.message)
        if self.burst and sum(1 for t in arr if now - t < self.burst[1]) >= self.burst[0]:   # всплеск: не больше burst[0] за burst[1] секунд
            raise HTTPException(429, self.message)
        arr.append(now)
        self.hits[key] = arr
        if len(self.hits) > 5000:   # старые адреса не копятся в памяти
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] >= self.window]:
                self.hits.pop(k, None)


# Площадка хакатона (13.11): телефоны жюри в одном Wi-Fi — для сервера один адрес. Сценарий «10–15 человек, у каждого 1–2 обращения
# голосом за 10 минут» проходит; явный спам (поток с одного адреса) упирается в минутное окно burst. Расход ИИ сверху держит
# суточный лимит вызовов (настройка «Вызовов ИИ в сутки», ai/budget). Тест — tests/test_stage17_venue_limits.py.
qr_limit = RateLimit(60, 600, burst=(30, 60))
stt_limit = RateLimit(120, 600, burst=(60, 60))
similar_limit = RateLimit(120, 600, burst=(60, 60), message="Слишком много запросов подряд — попробуйте через несколько минут")   # F-06: «похожие» без входа
staff_limit = RateLimit(300, 600, burst=(60, 60), message="Слишком много запросов подряд — попробуйте через несколько минут")     # F-06: поиск адресата без входа
ai_user_limit = RateLimit(150, 600, message="Слишком много запросов к ИИ подряд — подождите несколько минут")      # F-07: ИИ для вошедших, на человека
meeting_limit = RateLimit(10, 3600, "Слишком много совещаний подряд — не больше 10 в час")                # F-07: разбор совещаний, на человека
invite_limit = RateLimit(30, 600)   # страница приглашения: токены случайные 256 бит, лимит — гигиена
login_limit = RateLimit(100, 600, burst=(30, 60), message="Слишком много входов подряд — попробуйте через несколько минут")   # F-03: демо-вход


def client_ip(request: Request) -> str:
    """Адрес клиента для лимитов (F-06). X-Forwarded-For сам не читаем — его первый адрес задаёт клиент. За туннелем uvicorn
    (--proxy-headers, доверяет 127.0.0.1) уже подставил в request.client последний адрес, который дописал Cloudflare, — настоящий."""
    return request.client.host if request.client else "?"


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
    mime = (upload.content_type or mimetypes.guess_type(upload.filename)[0] or "application/octet-stream").split(";")[0].strip().lower()
    if mime not in ALLOWED_MIME:
        raise HTTPException(415, "Допустимы фото (JPEG, PNG, WebP), PDF, Word, Excel и текст")
    ext = Path(upload.filename).suffix.lower()[:8]
    if mime.startswith("image/"):
        # F-17: фото пересохраняется без метаданных — EXIF с координатами, временем и моделью телефона мог бы выдать анонимного автора
        data, mime, ext = images.clean_bytes(images.upright(images.open_image(data)))
    elif not _content_ok(mime, data):
        raise HTTPException(415, "Содержимое файла не совпадает с его типом")
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


@router.get("/public/glossary")
async def public_glossary():
    """Единый словарь терминов (пункт 1 очереди 12.11): подсказки «?» и страница «Справка» берут тексты отсюда, промпты ИИ — из той же структуры."""
    return glossary.public()


@router.get("/public/config")
async def public_config(request: Request):
    """Что доступно без входа: подключён ли Битрикс24 (кнопка «Войти через Битрикс24»), публичный адрес, версия (подвал) и отпечаток
    сборки (pwa.js перезагружает открытую страницу после обновления)."""
    return {"bitrix": bitrix.configured(), "bitrix_login": "/bitrix/login" if bitrix.configured() else None,
            "bitrix_portal": bitrix.portal() if bitrix.configured() else None, "public_url": base_url(request),
            "demo_login": auth.demo_login_enabled(), "version": version.commit(), "build": version.build()}


@router.get("/public/branches")
async def public_branches(request: Request):
    base = base_url(request)
    return [{**b, "qr_url": f"{base}/q/{b['code']}", "qr_svg": f"/api/public/qr/{b['code']}.svg"}
            for b in db.q("SELECT id, code, name, city, country, kind FROM branches ORDER BY is_hq DESC, kind, name")]


@router.get("/public/changes")
async def public_changes():
    """Лента «Результаты обращений» без входа (этап 7): номер, тип, категория, филиал, суть, что сделали, число «спасибо» — без авторов."""
    out = []
    for r in appeals.changes(50):
        out.append({k: r[k] for k in ("id", "number", "type_label", "category", "branch", "resolution_text", "closed_at", "thanks")} | {"text": r["brief_line"] or r["text"]})
    return out


@router.get("/public/map")
async def public_map(request: Request):
    """Стартовая страница — карта без входа (этап 6 §3)."""
    return director.public_map_data(base_url(request))


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
                        author_scope: str = Form(""), input_mode: str = Form(""), praise_to_user_id: str = Form(""), praise_to_department_id: str = Form(""),
                        is_anonymous: str = Form("")):
    """QR-форма: один экран, без входа. Категорию и приоритет ставит ИИ (mf/ai: LLM, без ключа — словарь ключевых слов);
    «Без ответственного» — только при вакансии категории или если ни ИИ, ни словарь не уверены (ТЗ §7).
    Если в браузере уже есть демо-вход — обращение привязывается к пользователю и даёт баллы."""
    qr_limit.check(client_ip(request))
    branch = db.one("SELECT * FROM branches WHERE code=?", (branch_code.upper(),))
    if not branch:
        raise HTTPException(404, "Филиал не найден")
    if type not in ("problem", "suggestion", "praise"):
        raise HTTPException(422, "Выберите «Проблема», «Идея» или «Спасибо»")
    user = auth.current(request)
    if user and parse_bool(is_anonymous) and type != "praise":
        user = None   # F-08: вошедший сотрудник тоже может отправить по QR анонимно — без связи с ним, только трекинг-ссылка
    cls = await classify(text, type, author_urgency or None, author_scope or None) if type != "praise" else None
    a = appeals.create(type=type, text=text, category_id=cls["category_id"] if cls else None, priority=(cls or {}).get("priority") or "",
                       branch_id=branch["id"], author=user, is_anonymous=user is None, source="qr", ai=cls,
                       site_city=site_city if branch["kind"] == "field" else None, author_urgency=author_urgency or None,
                       author_scope=author_scope or None, input_mode=input_mode or "text",
                       praise_to_user_id=int(praise_to_user_id) if praise_to_user_id.strip().isdigit() else None,
                       praise_to_department_id=int(praise_to_department_id) if praise_to_department_id.strip().isdigit() else None)
    await save_attachment(a["id"], file)
    return {"id": a["id"], "number": a["number"], "tracking_token": a["tracking_token"],
            "track_url": f"/t/{a['tracking_token']}", "logged_in": user is not None,
            "category": a["category"], "responsible": a["responsible"], "priority": a["priority"], "ai_engine": (cls or {}).get("engine"),
            "brief": appeals.brief_of(a), "type": a["type"]}


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
        log.warning("классификация обращения: %s", e)   # F-18: подробности — в журнал, наружу — только «error»
        return {"category_id": None, "category": None, "confidence": 0.0, "priority": appeals.matrix_priority(type_hint or "problem", author_urgency, author_scope) or "medium",
                "brief": None, "engine": "error"}


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
    if not auth.demo_login_enabled():
        raise HTTPException(404, "Демо-вход выключен")
    rows = db.q("""SELECT u.id, u.name, u.role, u.position, """ + appeals.BRANCH_LABEL + """ AS branch, d.name AS department
                   FROM users u LEFT JOIN branches b ON b.id=u.branch_id LEFT JOIN departments d ON d.id=u.department_id
                   WHERE u.active=1 ORDER BY CASE u.role WHEN 'director' THEN 0 WHEN 'admin' THEN 1 WHEN 'responsible' THEN 2 ELSE 3 END, u.id""")
    for r in rows:
        r["role_label"] = auth.ROLE_LABEL[r["role"]]
    return rows


@router.post("/auth/login-as")
async def login_as(body: LoginAs, request: Request, response: Response):
    """Демо-вход «Войти как…» (F-03): сессия помечается как демо; MF_DEMO_LOGIN=0 — выключен; ограничение частоты по адресу."""
    if not auth.demo_login_enabled():
        raise HTTPException(404, "Демо-вход выключен — войдите через Битрикс24 или по личному приглашению")
    login_limit.check(client_ip(request))
    auth.logout(request.cookies.get(auth.COOKIE))
    auth.set_cookie(response, auth.login(body.user_id, demo=True), request=request)
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
    t = meetings.my_tasks_counts(user["id"])   # «Мои поручения» со счётчиком невыполненных (пункт 1 очереди 12.11)
    out["tasks_open"], out["tasks_overdue"] = t["open"], t["overdue"]
    out["demo"] = bool(user.get("demo_restricted"))   # демо-вход снаружи: часть действий администратора закрыта (F-03)
    out["can_admin"] = auth.can_admin(user)   # «Администрирование»: администратор и директор, если не скрыто настройкой (13.11, п. 4)
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
                        file: UploadFile | None = File(None), author_urgency: str = Form(""), author_scope: str = Form(""), input_mode: str = Form(""),
                        praise_to_user_id: str = Form(""), praise_to_department_id: str = Form("")):
    user = auth.require(request)
    cls = None
    if type == "praise":   # короткая форма «Спасибо»: без категории, приоритета, решения и анонимности
        category_id, priority, proposed_solution, is_anonymous = "", "", "", "0"
    if type != "praise":   # один вызов ИИ: категория (если не выбрана), приоритет по ответу автора и «Коротко»
        cls = await classify(text + ("\n" + proposed_solution if proposed_solution else ""), type, author_urgency or None, author_scope or None)
        category_id = category_id or (cls["category_id"] or "")
        if cls.get("engine") != "openai":
            cls = {**cls, "category_id": int(category_id) if category_id else None}
    prio = priority if priority in appeals.PRIORITIES else ((cls or {}).get("priority") or "")   # None от ИИ (F-12) → матрица ответа автора
    a = appeals.create(type=type, text=text, proposed_solution=proposed_solution, category_id=int(category_id) if category_id else None,
                       priority=prio, author=user, is_anonymous=parse_bool(is_anonymous), source="app", ai=cls,
                       author_urgency=author_urgency or None, author_scope=author_scope or None, input_mode=input_mode or "text",
                       praise_to_user_id=int(praise_to_user_id) if praise_to_user_id.strip().isdigit() else None,
                       praise_to_department_id=int(praise_to_department_id) if praise_to_department_id.strip().isdigit() else None)
    await save_attachment(a["id"], file)
    return appeals.view(appeals.get(a["id"]), user)


@router.get("/staff/search")
async def staff_search(request: Request, q: str = ""):
    """«Кому спасибо»: коллега или отдел по началу имени (для вошедших)."""
    auth.require(request)
    return appeals.staff_search(q)


@router.get("/public/staff")
async def public_staff_search(request: Request, q: str = ""):
    """То же для QR-формы без входа: только по запросу от двух символов, не больше восьми совпадений."""
    staff_limit.check(client_ip(request))   # F-06: раньше условие было перевёрнуто — лимит не срабатывал на настоящих запросах
    return appeals.staff_search(q)


@router.get("/appeals/mine")
async def my_appeals(request: Request):
    return appeals.mine(auth.require(request))


@router.get("/appeals/{appeal_id}")
async def get_appeal(appeal_id: int, request: Request):
    user = auth.require(request)
    a = appeals.get(appeal_id)
    if appeals.can_view(a, user):
        return appeals.view(a, user)
    if appeals.supported_by(a, user):
        return appeals.view_limited(a, user)   # F-05: поддержавшему — краткая карточка
    raise HTTPException(403, "Это обращение вам недоступно")


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
    u = db.one("""SELECT u.id, u.name, u.position, u.avatar, u.role, """ + appeals.BRANCH_LABEL + """ AS branch, b.city, d.name AS department FROM users u
                  LEFT JOIN branches b ON b.id=u.branch_id LEFT JOIN departments d ON d.id=u.department_id WHERE u.id=? AND u.active=1""", (user_id,))
    if not u:
        raise HTTPException(404, "Сотрудник не найден")
    implemented = db.q("""SELECT a.id, a.number, a.text, a.resolution_text, a.closed_at FROM appeals a JOIN appeal_authors aa ON aa.appeal_id=a.id
                          WHERE aa.user_id=? AND a.status IN ('done','closed') AND a.type != 'praise' AND a.is_anonymous=0 ORDER BY a.closed_at DESC""", (user_id,))
    for i in implemented:
        i["text"] = appeals.short(i["text"], 120)
    return {"id": u["id"], "name": u["name"], "position": u["position"], "role": u["role"], "branch": u["branch"], "city": u["city"], "department": u["department"],
            "avatar": appeals.avatar_url(u["id"], u["avatar"]), "points": appeals.balance(user_id), "implemented": implemented,
            "thanks": db.one("SELECT COUNT(*) AS n FROM thanks t JOIN appeal_authors aa ON aa.appeal_id=t.appeal_id WHERE aa.user_id=?", (user_id,))["n"]
                      + db.one("SELECT COUNT(*) AS n FROM appeals WHERE type='praise' AND praise_to_user_id=?", (user_id,))["n"],
            "praises": appeals.praises_for(user_id),
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
    from PIL import Image, ImageOps
    img = images.upright(images.open_image(data)).convert("RGB")   # F-19: только JPEG/PNG/WebP, лимит пикселей
    img = ImageOps.fit(img, (256, 256), method=Image.LANCZOS, centering=(0.5, 0.4))
    img.info = {}   # без метаданных исходника (комментарии, ICC)
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
    auth.require_admin_full(request)
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
              "urgency": p.get("urgency") or None, "cluster_id": p.get("cluster_id") or None, "sort": p.get("sort") or None,
              "attention": parse_bool(p.get("attention", "")), "closed": parse_bool(p.get("closed", "")),
              "site": (p.get("site") or "").strip() or None})   # объект командированных: город объекта (клик по метке и строке «Атырау · объект»)
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
    ai_user_limit.check(f"u:{user['id']}")
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
DEMO_MAX_AUDIO = 30 * 1024 * 1024   # F-07: демо-вход снаружи — короткие записи (30–40 с весят доли мегабайта)
VOICE_MAX_AUDIO = 10 * 1024 * 1024   # F-07: голосовой ввод в формах (интерфейс пишет до 3 минут — это 1–3 МБ)
VOICE_MAX_SECONDS = 200              # распознаём не дольше 3 минут 20 секунд, сколько бы ни прислали
MAX_TRANSCRIPT = 60000               # F-07: текстовая расшифровка совещания — около часа речи; длиннее — разбить


@router.post("/meetings")
async def create_meeting(request: Request, background: BackgroundTasks, title: str = Form(""), transcript: str = Form(""),
                         duration_sec: str = Form(""), audio: UploadFile | None = File(None)):
    """Аудио (MediaRecorder / файл) или текстовая расшифровка → processing; обработка в фоне, фронт опрашивает GET /meetings/{id}."""
    user = auth.require(request, *appeals.STAFF)
    meeting_limit.check(f"u:{user['id']}")
    audio_path = None
    cap = DEMO_MAX_AUDIO if user.get("demo_restricted") else MAX_AUDIO
    if not (audio and audio.filename) and len(transcript) > MAX_TRANSCRIPT:
        raise HTTPException(413, f"Расшифровка длиннее {MAX_TRANSCRIPT // 1000} тыс. знаков — разбейте совещание на части")
    if audio and audio.filename:
        data = await audio.read(cap + 1)
        if len(data) > cap:
            raise HTTPException(413, f"Запись больше {cap // (1024 * 1024)} МБ — разбейте на части")
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


# ---------- этап 6: команды директора голосом или текстом (голос → /api/stt → текст → сюда) ----------

class CommandText(BaseModel):
    text: str


class CommandSend(BaseModel):
    messages: dict[str, str] | None = None   # правки текста по получателям {user_id: текст} с экрана подтверждения


@router.get("/director/command/help")
async def command_help(request: Request):
    auth.require(request, "director")   # F-21: команды (рассылки от имени руководства) — только директору
    return {"intents": [{"intent": k, "what": v, "example": commands.EXAMPLES[k]} for k, v in commands.INTENTS.items()], "llm": llm.available()}


@router.post("/director/command/parse")
async def command_parse(body: CommandText, request: Request):
    """Разбор + план для экрана подтверждения. НИЧЕГО не отправляет: план лежит в памяти под случайным id до [Отправить]."""
    user = auth.require(request, "director")
    ai_user_limit.check(f"u:{user['id']}")
    import asyncio
    cmd = await asyncio.to_thread(commands.parse, body.text, user)
    plan = await asyncio.to_thread(commands.build_plan, cmd, user)
    pid = commands.remember(plan, cmd, user)
    return {"plan_id": pid, "command": cmd, "plan": plan}


@router.post("/director/command/{plan_id}/send")
async def command_send(plan_id: str, body: CommandSend, request: Request):
    user = auth.require(request, "director")
    return commands.execute(plan_id, user, body.messages)


@router.get("/director/command/{plan_id}/audio")
async def command_audio(plan_id: str, request: Request):
    """Короткий голосовой ответ после отправки («Отправил напоминания четырём сотрудникам…») — OpenAI TTS с кэшем; без ключа 503."""
    user = auth.require(request, "director")
    p = commands.get_plan(plan_id, user)
    if not p["sent"]:
        raise HTTPException(409, "Команда ещё не отправлена")
    if not llm.available():
        raise HTTPException(503, "Озвучка через OpenAI недоступна без ключа — используется голос браузера")
    import asyncio
    try:
        audio, src = await asyncio.to_thread(director.tts_cached, p["sent"]["reply"])
    except Exception as e:   # noqa: BLE001
        raise HTTPException(503, f"Озвучка недоступна: {e}"[:200])
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store", "X-TTS-Source": src})


# ---------- «Директор в кармане» (пункт 2 очереди 12.11): только директор; вопросы — чтение, команды — через план с подтверждением ----------

class AskBody(BaseModel):
    text: str
    period: str | None = None


@router.get("/boss/home")
async def boss_home(request: Request, period: str = "week"):
    user = auth.require(request, "director")
    import asyncio
    return await asyncio.to_thread(boss.home, user, period)


@router.post("/boss/ask")
async def boss_ask(body: AskBody, request: Request):
    """Вопрос или команда голосом/текстом (голос → /api/stt → текст). Вопрос: факты считает сервер, ИИ пересказывает, числа сверяются.
    Команда: план в памяти, ничего не отправляется до POST /api/director/command/{plan_id}/send."""
    user = auth.require(request, "director")
    ai_user_limit.check(f"u:{user['id']}")
    import asyncio
    return await asyncio.to_thread(boss.ask, body.text, user, body.period)


@router.get("/boss/greeting/audio")
async def boss_greeting_audio(request: Request, period: str = "week"):
    """Озвучка приветствия /boss — тот же текст списком, что на экране (OpenAI TTS с кэшем); без ключа — 503, фронт читает голосом браузера."""
    user = auth.require(request, "director")
    if not llm.available():
        raise HTTPException(503, "Озвучка через OpenAI недоступна без ключа")
    import asyncio
    try:
        audio, src = await asyncio.to_thread(boss.greeting_audio, user, period)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(503, f"Озвучка недоступна: {e}"[:200])
    return Response(audio, media_type="audio/mpeg", headers={"X-TTS-Source": src, "Cache-Control": "no-store"})


@router.get("/boss/answer/{answer_id}/audio")
async def boss_answer_audio(answer_id: str, request: Request):
    """Нейтральный голос (OpenAI TTS с кэшем), не клонирование; без ключа — 503, фронт читает голосом браузера или молчит."""
    user = auth.require(request, "director")
    if not llm.available():
        raise HTTPException(503, "Озвучка через OpenAI недоступна без ключа")
    import asyncio
    try:
        audio, src = await asyncio.to_thread(boss.answer_audio, answer_id, user)
    except HTTPException:
        raise
    except Exception as e:   # noqa: BLE001
        raise HTTPException(503, f"Озвучка недоступна: {e}"[:200])
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store", "X-TTS-Source": src})


# ---------- этап 3: голос, черновик ИИ, похожие обращения, кластеры ----------

async def _transcribe_upload(audio: UploadFile | None, language: str | None) -> dict:
    """Голосовой ввод в формах → текст тем же адаптером, что и совещания; файл живёт только на время расшифровки.
    Потолки (F-07): до 10 МБ и не дольше 200 секунд распознавания."""
    if not audio or not audio.filename:
        raise HTTPException(422, "Нет аудио")
    data = await audio.read(VOICE_MAX_AUDIO + 1)
    if len(data) > VOICE_MAX_AUDIO:
        raise HTTPException(413, "Голосовая запись больше 10 МБ — запишите короче (до 3 минут)")
    if len(data) < 1000:
        raise HTTPException(422, "Запись пустая — попробуйте ещё раз")
    mime = (audio.content_type or "").split(";")[0].strip()
    ext = AUDIO_EXT.get(mime) or Path(audio.filename).suffix.lower()[:6] or ".bin"
    path = config.AUDIO_DIR / f"v-{secrets.token_hex(8)}{ext}"
    path.write_bytes(data)
    import asyncio
    try:
        r = await asyncio.to_thread(stt.transcribe, path, (language or "").strip() or None, VOICE_MAX_SECONDS)
    except stt.STTError as e:
        raise HTTPException(503, f"Распознавание речи недоступно: {e}")
    finally:
        path.unlink(missing_ok=True)
    return {"text": r["text"].replace("\n", " ").strip(), "language": r.get("language"), "engine": r["engine"], "seconds": r.get("seconds")}


@router.post("/stt")
async def stt_app(request: Request, audio: UploadFile | None = File(None), language: str = Form("")):
    user = auth.require(request)
    ai_user_limit.check(f"u:{user['id']}")
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
    ai_user_limit.check(f"u:{auth.require(request)['id']}")
    text = (body.text or "").strip()
    if len(text) < 5:
        raise HTTPException(422, "Напишите хотя бы несколько слов")
    return await classify(text, body.type)


class SimilarQ(BaseModel):
    text: str
    exclude_id: int | None = None


@router.post("/ai/similar")
async def ai_similar(body: SimilarQ, request: Request):
    ai_user_limit.check(f"u:{auth.require(request)['id']}")
    import asyncio
    return await asyncio.to_thread(similar.similar, body.text, body.exclude_id)


@router.post("/public/similar")
async def public_similar(body: SimilarQ, request: Request):
    """«Похоже, об этом уже сообщали» в QR-форме: номер и короткий текст, без авторов; максимум два."""
    similar_limit.check(client_ip(request))
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


@router.get("/panel/director-summary/audio")
async def director_summary_audio(request: Request):
    """Озвучка сводки через OpenAI TTS (кэш); без ключа — 503, фронт переключается на голос браузера."""
    user = auth.require(request, *appeals.STAFF)
    if not llm.available():
        raise HTTPException(503, "Озвучка через OpenAI недоступна без ключа — используется голос браузера")
    import asyncio
    try:
        audio, src = await asyncio.to_thread(director.summary_audio, user)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(503, f"Озвучка недоступна: {e}"[:200])
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store", "X-TTS-Source": src})


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
    auth.require_admin(request)
    return db.q("""SELECT c.*, r.title, r.cost_points, u.name AS user_name FROM reward_claims c JOIN rewards r ON r.id=c.reward_id JOIN users u ON u.id=c.user_id
                   ORDER BY CASE c.status WHEN 'requested' THEN 0 ELSE 1 END, c.id DESC LIMIT 100""")


@router.post("/admin/reward-claims/{claim_id}/decide")
async def decide_claim(claim_id: int, body: ClaimDecision, request: Request):
    user = auth.require_admin(request)
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


SETTING_KEYS = ("points", "director_wait_days", "news_days", "similar_threshold", "cluster_threshold", "league_weights", "dev_department_head_id", "tz_offset_hours", "invite_days",
                "ai_daily_limit", "director_admin")


@router.get("/admin/settings")
async def admin_settings(request: Request):
    auth.require_admin(request)
    from .ai import budget
    return {"settings": {**{k: db.setting(k) for k in SETTING_KEYS}, "ai_daily_limit": budget.limit(), "director_admin": auth.director_admin()}, "ai_usage": budget.usage(),
            "categories": db.q("""SELECT c.id, c.name, c.responsible_user_id, c.suggestion_responsible_user_id, c.sla_first_response_hours AS sla,
                                  u.name AS responsible, s.name AS suggestion_responsible, (SELECT COUNT(*) FROM appeals a WHERE a.category_id=c.id) AS appeals
                                  FROM categories c LEFT JOIN users u ON u.id=c.responsible_user_id LEFT JOIN users s ON s.id=c.suggestion_responsible_user_id ORDER BY c.id"""),
            "users": db.q("SELECT id, name, role, position, branch_id, department_id, manager_id, active, avatar, email, bitrix_id, phone FROM users ORDER BY active DESC, name"),
            "invites": staff.latest_by_user(),   # этап 8 §4: последнее приглашение каждого (статус, срок)
            "invite_days": staff.invite_days(),
            "bitrix": bitrix.status(),
            "branches": [{**b, "kind_label": posters.kind_label(b["kind"]), "form_url": f"{base_url(request)}/q/{b['code']}", "qr_svg": f"/api/public/qr/{b['code']}.svg",
                          "poster_url": f"/api/admin/branches/{b['code']}/poster.pdf"} for b in db.q("SELECT id, code, name, city, kind FROM branches ORDER BY is_hq DESC, kind, name")],
            "departments": db.q("SELECT id, name FROM departments ORDER BY id"),
            "rewards": db.q("SELECT * FROM rewards ORDER BY active DESC, id")}


@router.get("/admin/branches/posters.pdf")
async def admin_posters_all(request: Request):
    """Все QR-плакаты филиалов одним PDF (A4 на филиал) — из «Администрирование → Филиалы и QR»."""
    auth.require_admin(request)
    import asyncio
    pdf = await asyncio.to_thread(posters.posters_pdf, posters.branches_for_posters(), base_url(request))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": "inline; filename=\"modus_golos_qr_posters.pdf\""})


@router.get("/admin/branches/{code}/poster.pdf")
async def admin_poster_one(code: str, request: Request):
    auth.require_admin(request)
    rows = posters.branches_for_posters(code)
    if not rows:
        raise HTTPException(404, "Филиал не найден")
    import asyncio
    pdf = await asyncio.to_thread(posters.posters_pdf, rows, base_url(request))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename=\"modus_golos_qr_{rows[0]['code']}.pdf\""})


class SettingsBody(BaseModel):
    settings: dict


# ---------- точки объектов на карте (замечание владельца 13.11): справочник городов + ручные точки администратора ----------

class GeoPointBody(BaseModel):
    city: str
    lat: float | None = None
    lng: float | None = None


@router.get("/admin/geo")
async def admin_geo(request: Request):
    """Объекты «без метки» (город из QR не найден в справочнике) и точки, поставленные вручную."""
    auth.require_admin(request)
    from . import geo
    md = director.map_data()
    return {"unplaced": md["unplaced"], "points": [{"key": k, **v} for k, v in geo.manual_points().items()],
            "frame": {"lon0": 45.0, "lon1": 82.0, "lat0": 46.5, "lat1": 60.5}}


@router.post("/admin/geo/points")
async def admin_geo_point(body: GeoPointBody, request: Request):
    auth.require_admin_full(request)
    from . import geo
    if body.lat is None or body.lng is None:
        raise HTTPException(422, "Нужны координаты точки")
    try:
        return geo.set_point(body.city, body.lat, body.lng)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/admin/geo/points/remove")
async def admin_geo_point_remove(body: GeoPointBody, request: Request):
    auth.require_admin_full(request)
    from . import geo
    geo.remove_point(body.city)
    return {"ok": True}


@router.post("/admin/settings")
async def admin_settings_save(body: SettingsBody, request: Request):
    auth.require_admin(request)
    if "director_admin" in body.settings:   # кто видит администрирование — решение не для демо-входа снаружи (F-03): только с ноутбука
        body.settings["director_admin"] = bool(body.settings["director_admin"])
        if body.settings["director_admin"] != auth.director_admin():
            auth.require_admin_full(request)
    for k, v in body.settings.items():
        if k in SETTING_KEYS:
            db.set_setting(k, v)
    return {"ok": True, "settings": {**{k: db.setting(k) for k in SETTING_KEYS}, "director_admin": auth.director_admin()}}


class CategoryBody(BaseModel):
    responsible_user_id: int | None = None
    suggestion_responsible_user_id: int | None = None
    sla: int | None = None
    name: str | None = None


@router.post("/admin/categories/{category_id}")
async def admin_category(category_id: int, body: CategoryBody, request: Request):
    auth.require_admin(request)
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


# ---------- этап 5: минимальное редактирование наград и пользователей ----------

class RewardBody(BaseModel):
    id: int | None = None
    title: str
    description: str | None = None
    cost_points: int
    active: bool = True


@router.post("/admin/rewards")
async def admin_reward(body: RewardBody, request: Request):
    """Витрину наград заполняет компания: добавить, изменить, отключить."""
    auth.require_admin(request)
    title = body.title.strip()
    if not title or body.cost_points <= 0:
        raise HTTPException(422, "Название и положительная стоимость обязательны")
    if body.id:
        if not db.one("SELECT 1 FROM rewards WHERE id=?", (body.id,)):
            raise HTTPException(404, "Награда не найдена")
        db.ex("UPDATE rewards SET title=?, description=?, cost_points=?, active=? WHERE id=?", (title, (body.description or "").strip() or None, body.cost_points, 1 if body.active else 0, body.id))
        rid = body.id
    else:
        rid = db.ex("INSERT INTO rewards(title, description, cost_points, active) VALUES(?,?,?,?)", (title, (body.description or "").strip() or None, body.cost_points, 1 if body.active else 0))
    return db.one("SELECT * FROM rewards WHERE id=?", (rid,))


class UserBody(BaseModel):
    id: int | None = None
    name: str
    role: str
    position: str | None = None
    branch_id: int | None = None
    department_id: int | None = None
    manager_id: int | None = None
    active: bool = True
    email: str | None = None
    bitrix_id: int | None = None
    phone: str | None = None
    invite: bool = False   # этап 8 §4: сразу выдать личное приглашение (для тех, кого нет в Битриксе)


USER_FIELDS = "id, name, role, position, branch_id, department_id, manager_id, active, email, bitrix_id, phone"


@router.post("/admin/users")
async def admin_user(body: UserBody, request: Request):
    """Сотрудники: добавить, изменить, отключить. Этап 8 §4: телефон (ручное добавление рабочих, склейка с Битриксом по номеру),
    телефон и почта не могут принадлежать двум людям, отключение гасит сессии и приглашения, история остаётся."""
    user = auth.require_admin_full(request)
    name = " ".join(body.name.split())
    if len(name) < 3 or body.role not in auth.ROLES:
        raise HTTPException(422, "Имя и роль обязательны")
    if body.id == user["id"] and not body.active:
        raise HTTPException(409, "Нельзя отключить себя")
    email = staff.norm_email(body.email)
    phone = staff.norm_phone(body.phone)
    if phone and len(staff.phone_key(phone)) < 10:
        raise HTTPException(422, "Телефон некорректен — нужен номер с кодом, например +7 701 000 00 00")
    dup = staff.find_by_phone(phone, exclude_id=body.id)
    if dup:
        raise HTTPException(409, f"Этот телефон уже у сотрудника «{dup['name']}» — один человек должен быть одним профилем")
    dup = staff.find_by_email(email, exclude_id=body.id)
    if dup:
        raise HTTPException(409, f"Эта почта уже у сотрудника «{dup['name']}»")
    vals = (name, body.role, (body.position or "").strip() or None, body.branch_id, body.department_id, body.manager_id, 1 if body.active else 0, email, body.bitrix_id or None, phone)
    if body.id:
        prev = db.one("SELECT active FROM users WHERE id=?", (body.id,))
        if not prev:
            raise HTTPException(404, "Сотрудник не найден")
        db.ex("UPDATE users SET name=?, role=?, position=?, branch_id=?, department_id=?, manager_id=?, active=?, email=?, bitrix_id=?, phone=? WHERE id=?", (*vals, body.id))
        uid = body.id
        if prev["active"] and not body.active:
            staff.on_deactivated(uid)
    else:
        uid = db.ex("INSERT INTO users(name, role, position, branch_id, department_id, manager_id, active, email, bitrix_id, phone) VALUES(?,?,?,?,?,?,?,?,?,?)", vals)
    out = db.one(f"SELECT {USER_FIELDS} FROM users WHERE id=?", (uid,))
    if body.invite and out["active"]:
        inv = staff.issue(uid, user["id"])
        out["invite"] = _invite_out(inv, request)
    return out


# ---------- этап 8 §4: сотрудники без Битрикса — отключение, импорт списком, личные приглашения, карточки для печати ----------

class ActiveBody(BaseModel):
    active: bool


@router.post("/admin/users/{user_id:int}/active")
async def admin_user_active(user_id: int, body: ActiveBody, request: Request):
    """Отключить (сессии и приглашения гаснут, обращения и история остаются) или включить обратно."""
    user = auth.require_admin_full(request)
    return staff.set_active(user_id, body.active, user)


@router.get("/admin/users/template.csv")
async def admin_users_template(request: Request):
    auth.require_admin(request)
    return Response(staff.template_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=\"modus_golos_staff_template.csv\"; filename*=UTF-8''%D1%81%D0%BE%D1%82%D1%80%D1%83%D0%B4%D0%BD%D0%B8%D0%BA%D0%B8_%D1%88%D0%B0%D0%B1%D0%BB%D0%BE%D0%BD.csv"})


@router.post("/admin/users/import")
async def admin_users_import(request: Request, file: UploadFile = File(...), invite: str = Form("1")):
    """Импорт из CSV или Excel по шаблону: ошибочная строка — в отчёт, остальные заводятся; новым — приглашения (invite=1)."""
    user = auth.require_admin_full(request)
    data = await file.read(5 * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(422, "Файл пустой")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Файл больше 5 МБ")
    rows = staff.parse_table(data, file.filename or "")
    r = staff.import_rows(rows, user["id"], invite=parse_bool(invite))
    base = base_url(request)
    for inv in r["invites"]:
        inv["card_url"] = f"/api/admin/invites/cards.pdf?ids={inv['id']}"
    r["cards_url"] = ("/api/admin/invites/cards.pdf?ids=" + ",".join(str(i["id"]) for i in r["invites"])) if r["invites"] else None
    r["base"] = base
    return r


class InviteBody(BaseModel):
    user_id: int


INVITE_GONE = "Ссылку, QR и карточку можно получить только в течение часа после выдачи — в базе хранится не сама ссылка. Нажмите «Выдать заново»"


def _invite_out(inv: dict, request: Request) -> dict:
    """Ссылка, QR и карточка — только пока токен в памяти (час после выдачи, F-15); потом — «Выдать заново»."""
    fresh = bool(inv.get("token"))
    return {**inv, "url": staff.url_for(inv["token"], base_url(request)) if fresh else None,
            "qr_svg": f"/api/admin/invites/{inv['id']}/qr.svg" if fresh else None,
            "card_url": f"/api/admin/invites/cards.pdf?ids={inv['id']}" if fresh else None, "note": None if fresh else INVITE_GONE}


@router.post("/admin/invites")
async def admin_invite_issue(body: InviteBody, request: Request):
    """Выдать личное приглашение (или выдать заново: прежняя ссылка сразу перестаёт работать, прежнее устройство выходит)."""
    user = auth.require_admin_full(request)
    return _invite_out(staff.issue(body.user_id, user["id"]), request)


@router.get("/admin/invites/cards.pdf")
async def admin_invite_cards(request: Request, ids: str = "", all: str = ""):
    """Карточки-приглашения для печати: ?ids=1,2,3 (например, весь импорт) или ?all=1 — все действующие."""
    auth.require_admin(request)
    if parse_bool(all):
        rows = [staff.get(r["id"]) for r in db.q("SELECT id FROM invites WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at > ? ORDER BY id", (db.now_iso(),))]
    else:
        try:
            want = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(422, "ids — номера приглашений через запятую")
        rows = [staff.get(i) for i in want]
    rows = [r for r in rows if r and r["user"] and r["token"]]   # F-15: печатаются только выданные за последний час
    if not rows:
        raise HTTPException(404, "Нет приглашений для печати. " + INVITE_GONE)
    import asyncio
    pdf = await asyncio.to_thread(staff.cards_pdf, rows, base_url(request))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": "inline; filename=\"modus_golos_invites.pdf\""})


@router.get("/admin/invites/{invite_id:int}")
async def admin_invite_get(invite_id: int, request: Request):
    auth.require_admin(request)
    inv = staff.get(invite_id)
    if not inv:
        raise HTTPException(404, "Приглашение не найдено")
    return _invite_out(inv, request)


@router.post("/admin/invites/{invite_id:int}/revoke")
async def admin_invite_revoke(invite_id: int, request: Request):
    auth.require_admin_full(request)
    return _invite_out(staff.revoke(invite_id), request)


@router.get("/admin/invites/{invite_id:int}/qr.svg")
async def admin_invite_qr(invite_id: int, request: Request):
    auth.require_admin(request)
    inv = staff.get(invite_id)
    if not inv:
        raise HTTPException(404, "Приглашение не найдено")
    if not inv["token"]:
        raise HTTPException(404, INVITE_GONE)
    img = qrcode.make(staff.url_for(inv["token"], base_url(request)), image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO(); img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.get("/public/invite/{token}")
async def public_invite_info(token: str, request: Request):
    """Страница /i/<token>: кому приглашение и можно ли войти. Токен не раскрывает ничего, кроме имени и города приглашённого."""
    invite_limit.check(client_ip(request))
    st, inv = staff.check(token, auth.current(request))
    out = {"status": st, "text": staff.STATUS_TEXT.get(st)}
    if inv and inv["user"]:
        u = inv["user"]
        out["user"] = {"name": u["name"], "first_name": u["name"].split()[0], "city": u["city"], "branch": u["branch"], "department": u["department"], "position": u["position"]}
        out["expires_at"] = inv["expires_at"]
        out["home"] = "/app"
    return out


@router.post("/public/invite/{token}/accept")
async def public_invite_accept(token: str, request: Request, response: Response):
    """Вход по личному приглашению — один раз; дальше устройство помнит сотрудника (долгая cookie), паролей нет."""
    invite_limit.check(client_ip(request))
    u = staff.accept(token)
    auth.logout(request.cookies.get(auth.COOKIE))
    auth.set_cookie(response, auth.login(u["id"]), days=365, request=request)
    out = auth.public(u)
    out["home"] = "/app" if u["role"] == "employee" else "/panel"
    return out


# ---------- этап 5: демо-состояние и проверка перед выходом ----------

@router.post("/admin/bitrix/sync")
async def admin_bitrix_sync(request: Request):
    """Этап 8 §3: сотрудники и отделы из Битрикс24 → наши пользователи (кнопка у администратора; автоматически — раз в сутки)."""
    auth.require_admin_full(request)
    if not bitrix.notify_available():
        raise HTTPException(503, "Битрикс24 не подключён или приложение ещё не установлено (нет токенов портала)")
    import asyncio
    try:
        return await asyncio.to_thread(bitrix.sync_users)
    except bitrix.BitrixError as e:
        raise HTTPException(502, f"Битрикс24: {e}")


@router.post("/admin/demo-snapshot")
async def admin_demo_snapshot(request: Request):
    auth.require_admin_full(request)
    return demo.snapshot()


@router.post("/admin/demo-reset")
async def admin_demo_reset(request: Request):
    """Вернуть базу в демо-состояние за секунды, без вызовов ИИ. Сессии сбрасываются — войти заново."""
    auth.require_admin_full(request)
    r = demo.reset()
    realtime.publish_all({"type": "demo_reset"})
    return r


@router.get("/admin/preflight")
async def admin_preflight(request: Request, stt_test: str = "1"):
    """Проверка «за час до выхода»: ключ, STT на GPU, база в демо-состоянии. Внешний туннель и батарею проверяет tools/preflight.sh."""
    auth.require_admin_full(request)   # тратит вызовы ИИ и GPU — только с ноутбука или из настоящего входа
    import asyncio
    out = {"checks": []}
    # ключ OpenAI — короткий вызов
    if llm.available():
        try:
            t = await asyncio.to_thread(lambda: llm.chat_json("Отвечай JSON.", 'Верни {"ok": true}', lambda d: None, max_tokens=20))
            out["checks"].append({"name": "ключ OpenAI", "ok": bool(t.get("ok")), "detail": LLM_MODEL})
        except Exception as e:   # noqa: BLE001
            out["checks"].append({"name": "ключ OpenAI", "ok": False, "detail": str(e)[:160] + " → без ключа работает запасной режим"})
    else:
        out["checks"].append({"name": "ключ OpenAI", "ok": False, "detail": "ключа нет — запасной режим (демо-разбор, словарь, шаблон сводки)"})
    # STT
    st = stt.available()
    if parse_bool(stt_test) and st["local"]:
        wav = Path(__file__).resolve().parent.parent / "demo" / "fixtures" / "test_ru.wav"
        if wav.is_file():
            try:
                r = await asyncio.to_thread(stt.transcribe, wav, "ru")
                ok = "систем" in r["text"].lower() or "ерлан" in r["text"].lower()
                out["checks"].append({"name": "STT на GPU", "ok": ok, "detail": f"{r['engine']}, {r['seconds']} с: «{r['text'][:70]}»"})
            except Exception as e:   # noqa: BLE001
                out["checks"].append({"name": "STT на GPU", "ok": False, "detail": str(e)[:160]})
        else:
            out["checks"].append({"name": "STT на GPU", "ok": st["loaded"], "detail": "модель " + ("загружена" if st["loaded"] else "не загружена") + ", тестового wav нет"})
    else:
        out["checks"].append({"name": "STT", "ok": st["local"] or st["openai"], "detail": f"режим {st['mode']}, локально: {st['local']}, облако: {st['openai']}"})
    ds = demo.is_demo_state()
    out["checks"] += [{"name": "БД: " + c["name"], "ok": c["ok"], "detail": c["detail"]} for c in ds["checks"]]
    out["ok"] = all(c["ok"] for c in out["checks"])
    return out
