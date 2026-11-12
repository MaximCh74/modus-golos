"""Сотрудники без Битрикса (этап 8 §4): рабочие, производство, командированные.
Принцип: подать обращение по QR может любой без аккаунта — это остаётся. Аккаунт нужен для «Моих обращений», баллов, наград
и профиля. Администратор заводит таких людей вручную или списком (CSV/Excel по шаблону) и выдаёт каждому личное приглашение:
ссылка /i/<token> и QR, одноразовая, со сроком (settings.invite_days, по умолчанию 14 дней). Сотрудник открывает её на телефоне,
нажимает «Войти» — сессия долгая, паролей нет. «Выдать заново» отзывает прежнюю ссылку сразу и выходит с прежнего устройства.
Деактивация: сотрудник не входит (ни по приглашению, ни по старой сессии), обращения и история остаются.
Карточка-приглашение для печати (PDF, 4 на лист A4, в стиле плакатов tools/make_qr_posters.py): имя, город, QR и одна строка
«Откройте камерой — и вы в системе». Если человек есть и в Битриксе — один профиль: склейка по почте и телефону при синхронизации
(mf/integrations/bitrix.py: match_user, merge_candidates, merge_issue)."""
from __future__ import annotations

import csv
import io
import re
import secrets
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException

from . import db
from .config import ROOT

DEFAULT_INVITE_DAYS = 14
# Аудит 12.11, F-15: в базе — только хэш токена приглашения. Сама ссылка (для QR, WhatsApp, карточки PDF) живёт в памяти процесса
# час после выдачи; потом — «Выдать заново». Так ссылку нельзя достать из копии базы или демо-снапшота.
FRESH_TTL = 3600
_FRESH: dict[int, tuple[str, float]] = {}
_fresh_lock = threading.Lock()


def _remember(invite_id: int, token: str) -> None:
    with _fresh_lock:
        now = time.time()
        for k in [k for k, (_, at) in _FRESH.items() if now - at > FRESH_TTL]:
            _FRESH.pop(k, None)
        _FRESH[invite_id] = (token, now)


def fresh_token(invite_id: int) -> str | None:
    v = _FRESH.get(invite_id)
    return v[0] if v and time.time() - v[1] <= FRESH_TTL else None
ROLES_IMPORT = {"сотрудник": "employee", "employee": "employee", "работник": "employee", "рабочий": "employee",
                "ответственный": "responsible", "responsible": "responsible", "руководитель": "responsible"}
ROLE_WORD = {"employee": "Сотрудник", "responsible": "Ответственный"}
TEMPLATE_HEADER = ["Имя", "Город", "Отдел", "Роль", "Телефон", "Должность", "Почта"]
TEMPLATE_ROWS = [
    ["Марат Ибраев", "Павлодар", "Производство", "Сотрудник", "+7 701 000 00 01", "Оператор участка", ""],
    ["Асель Мусина", "Объект", "Проектирование", "Сотрудник", "+7 702 000 00 02", "Инженер", "asel@example.kz"],
]
# заголовки, которые понимаем в загруженном файле (регистр и лишние пробелы не важны)
ALIASES = {
    "name": ("имя", "фио", "ф.и.о.", "ф.и.о", "сотрудник", "имя фамилия", "фамилия имя", "name", "full name"),
    "city": ("город", "филиал", "город/филиал", "город или филиал", "city", "branch"),
    "department": ("отдел", "подразделение", "department", "dept"),
    "role": ("роль", "role"),
    "phone": ("телефон", "тел", "тел.", "мобильный", "phone", "mobile"),
    "position": ("должность", "position"),
    "email": ("почта", "e-mail", "email", "эл. почта", "электронная почта"),
}
STATUS_TEXT = {
    "missing": "Такого приглашения нет. Проверьте ссылку или попросите администратора выдать новую.",
    "used": "Эта ссылка уже использована — она работает один раз. Если входили не вы, попросите администратора выдать новое приглашение.",
    "expired": "Срок действия приглашения истёк. Попросите администратора выдать новое.",
    "revoked": "Приглашение отозвано: администратор выдал новое. Откройте свежую ссылку или карточку.",
    "deactivated": "Учётная запись отключена. Обратитесь к администратору.",
}


# ---------- телефон и почта ----------

def phone_key(s) -> str:
    """Ключ сравнения — последние 10 цифр (как в bitrix._digits): +7 701 000-11-22 и 8 (701) 000 11 22 — один номер."""
    return re.sub(r"\D", "", str(s or ""))[-10:]


def norm_phone(s) -> str | None:
    """Как храним: только цифры с ведущим «+» для полных номеров; 8 701 … → +7 701 …; пусто → None."""
    digits = re.sub(r"\D", "", str(s or ""))
    if not digits:
        return None
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return ("+" + digits) if len(digits) >= 11 else digits


def norm_email(s) -> str | None:
    e = (s or "").strip().lower()
    return e or None


def find_by_phone(phone: str | None, exclude_id: int | None = None) -> dict | None:
    key = phone_key(phone)
    if not key:
        return None
    for r in db.q("SELECT * FROM users WHERE phone IS NOT NULL AND phone != '' ORDER BY active DESC, id"):
        if phone_key(r["phone"]) == key and r["id"] != exclude_id:
            return r
    return None


def find_by_email(email: str | None, exclude_id: int | None = None) -> dict | None:
    if not email:
        return None
    return db.one("SELECT * FROM users WHERE lower(email)=? AND id != ? ORDER BY active DESC, id", (email.lower(), exclude_id or 0))


# ---------- приглашения ----------

def invite_days() -> int:
    try:
        return max(1, int(db.setting("invite_days", DEFAULT_INVITE_DAYS) or DEFAULT_INVITE_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_INVITE_DAYS


def status_of(i: dict, now=None) -> str:
    if i.get("revoked_at"):
        return "revoked"
    if i.get("used_at"):
        return "used"
    exp = db.parse(i.get("expires_at"))
    if exp and exp < (now or db.now()):
        return "expired"
    return "active"


def _decorate(i: dict | None) -> dict | None:
    if not i:
        return None
    u = db.one("""SELECT u.id, u.name, u.active, u.bitrix_id, u.position, b.city, b.name AS branch, b.kind, d.name AS department
                  FROM users u LEFT JOIN branches b ON b.id=u.branch_id LEFT JOIN departments d ON d.id=u.department_id WHERE u.id=?""", (i["user_id"],))
    out = {k: v for k, v in i.items() if k != "token"}   # хэш наружу не отдаём
    out["token"] = fresh_token(i["id"])   # ссылка — только час после выдачи (F-15)
    out["fresh"] = out["token"] is not None
    out["status"] = status_of(i) if (u and u["active"]) else "deactivated"
    out["user"] = {"id": u["id"], "name": u["name"], "position": u["position"], "city": u["city"] or ("Объект" if (u["kind"] == "field") else None),
                   "branch": u["branch"], "department": u["department"], "active": bool(u["active"]), "bitrix_id": u["bitrix_id"]} if u else None
    return out


def get(invite_id: int) -> dict | None:
    return _decorate(db.one("SELECT * FROM invites WHERE id=?", (invite_id,)))


def by_token(token: str) -> dict | None:
    if not token or len(token) < 20:
        return None
    return _decorate(db.one("SELECT * FROM invites WHERE token=?", (db.token_hash(token),)))


def latest_by_user() -> dict[int, dict]:
    """Последнее приглашение каждого сотрудника (для списка у администратора): статус, срок, когда вошёл."""
    now = db.now()
    out = {}
    for i in db.q("SELECT * FROM invites WHERE id IN (SELECT MAX(id) FROM invites GROUP BY user_id)"):
        out[i["user_id"]] = {"id": i["id"], "status": status_of(i, now), "expires_at": i["expires_at"], "used_at": i["used_at"],
                             "revoked_at": i["revoked_at"], "created_at": i["created_at"], "fresh": fresh_token(i["id"]) is not None}
    return out


def url_for(token: str, base: str) -> str:
    return f"{base.rstrip('/')}/i/{token}"


def issue(user_id: int, actor_id: int | None = None, days: int | None = None) -> dict:
    """Выдать (или выдать заново) личное приглашение: прежние ссылки отзываются сразу, прежние устройства выходят
    (потерян или сменён телефон), токен — длинный случайный (256 бит)."""
    u = db.one("SELECT id, active FROM users WHERE id=?", (user_id,))
    if not u:
        raise HTTPException(404, "Сотрудник не найден")
    if not u["active"]:
        raise HTTPException(409, "Сотрудник отключён — сначала включите его")
    now = db.now()
    had = db.one("SELECT 1 FROM invites WHERE user_id=?", (user_id,))
    db.ex("UPDATE invites SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (db.iso(now), user_id))
    if had:
        db.ex("DELETE FROM sessions WHERE user_id=?", (user_id,))   # «Выдать заново»: прежний телефон больше не в системе
    token = secrets.token_urlsafe(32)
    iid = db.ex("INSERT INTO invites(user_id, token, created_by, created_at, expires_at) VALUES(?,?,?,?,?)",
                (user_id, db.token_hash(token), actor_id, db.iso(now), db.iso(now + timedelta(days=days or invite_days()))))
    _remember(iid, token)
    return get(iid)


def revoke(invite_id: int) -> dict:
    i = get(invite_id)
    if not i:
        raise HTTPException(404, "Приглашение не найдено")
    if not i["revoked_at"]:
        db.ex("UPDATE invites SET revoked_at=? WHERE id=?", (db.now_iso(), invite_id))
    return get(invite_id)


def check(token: str, current_user: dict | None = None) -> tuple[str, dict | None]:
    """Состояние ссылки для страницы /i/<token>: active | used | expired | revoked | deactivated | missing | already_in
    (already_in — устройство уже вошло этим приглашением: показываем «Открыть приложение», а не «ссылка использована»)."""
    i = by_token(token)
    if not i:
        return "missing", None
    st = i["status"]
    if st == "used" and current_user and current_user["id"] == i["user_id"]:
        return "already_in", i
    return st, i


def accept(token: str) -> dict:
    """Вход по приглашению — ровно один раз: отметка used_at ставится атомарно, второй переход получает «использована»."""
    st, i = check(token)
    if st != "active":
        raise HTTPException(404 if st == "missing" else 403 if st == "deactivated" else 410, STATUS_TEXT.get(st, "Приглашение недействительно"))
    cur = db.conn().execute("UPDATE invites SET used_at=? WHERE id=? AND used_at IS NULL AND revoked_at IS NULL", (db.now_iso(), i["id"]))
    db.conn().commit()
    if cur.rowcount != 1:
        raise HTTPException(410, STATUS_TEXT["used"])
    u = db.one("SELECT * FROM users WHERE id=? AND active=1", (i["user_id"],))
    if not u:
        raise HTTPException(403, STATUS_TEXT["deactivated"])
    return u


# ---------- активность сотрудника ----------

def set_active(user_id: int, active: bool, actor: dict | None = None) -> dict:
    """Отключить: сотрудник больше не входит (сессии удаляются, приглашения отзываются), обращения, баллы и история остаются.
    Включить обратно можно в любой момент — приглашение придётся выдать заново."""
    u = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    if not u:
        raise HTTPException(404, "Сотрудник не найден")
    if not active and actor and actor["id"] == user_id:
        raise HTTPException(409, "Нельзя отключить себя")
    db.ex("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))
    if not active:
        on_deactivated(user_id)
    return db.one("SELECT id, name, active FROM users WHERE id=?", (user_id,))


def on_deactivated(user_id: int) -> None:
    db.ex("DELETE FROM sessions WHERE user_id=?", (user_id,))
    db.ex("UPDATE invites SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND used_at IS NULL", (db.now_iso(), user_id))


# ---------- шаблон и импорт списка ----------

def template_csv() -> bytes:
    """Шаблон для Excel: UTF-8 с BOM, разделитель «;», CRLF — открывается двойным щелчком с кириллицей и колонками."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(TEMPLATE_HEADER)
    for r in TEMPLATE_ROWS:
        w.writerow(r)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _norm_header(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower()).strip(" :")


def parse_table(data: bytes, filename: str = "") -> list[list[str]]:
    """Строки файла как списки строк: .xlsx/.xlsm — первый лист (openpyxl), иначе CSV (UTF-8 с BOM или cp1251; разделитель ; , или таб)."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")) or data[:4] == b"PK\x03\x04":
        try:
            import openpyxl
        except ImportError as e:   # pragma: no cover
            raise HTTPException(415, "Excel не поддерживается на этом сервере — сохраните файл как CSV") from e
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [["" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)).strip() for v in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1251", errors="replace")
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max((";", ",", "\t"), key=first.count) if first else ";"
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=delim)]


def _map_header(row: list[str]) -> dict[str, int] | None:
    cols = {}
    for idx, cell in enumerate(row):
        h = _norm_header(cell)
        for key, names in ALIASES.items():
            if h in names and key not in cols:
                cols[key] = idx
    return cols if "name" in cols else None


def resolve_branch(text: str, branches: list[dict]) -> dict | None:
    t = re.sub(r"\s+", " ", (text or "").strip().lower().replace("ё", "е"))
    if not t:
        return None
    for b in branches:
        if t == (b["code"] or "").lower():
            return b
    for b in branches:
        if b["city"] and t == b["city"].lower().replace("ё", "е"):
            return b
    if t in ("объект", "командировка", "объект (командировка)", "поле", "field"):
        return next((b for b in branches if b["kind"] == "field"), None)
    for b in branches:
        n = (b["name"] or "").lower().replace("ё", "е")
        if t in n or (b["city"] and b["city"].lower().replace("ё", "е") in t):
            return b
    return None


def resolve_department(text: str, departments: list[dict]) -> dict | None:
    t = re.sub(r"\s+", " ", (text or "").strip().lower().replace("ё", "е"))
    if not t:
        return None
    return next((d for d in departments if (d["name"] or "").lower().replace("ё", "е") == t), None) or \
        next((d for d in departments if t in (d["name"] or "").lower().replace("ё", "е")), None)


def import_rows(rows: list[list[str]], actor_id: int | None = None, invite: bool = True) -> dict:
    """Импорт списком: ошибочная строка — в отчёт, остальные заводятся. Повторы по телефону или почте (или по имени в том же
    городе) не плодят дублей — существующий профиль дополняется пустыми полями. Приглашения — новым сотрудникам."""
    branches = db.q("SELECT id, code, name, city, kind FROM branches")
    departments = db.q("SELECT id, name FROM departments")
    cities = ", ".join([b["city"] for b in branches if b["city"]] + ["Объект"])
    out = {"created": 0, "updated": 0, "errors": [], "users": [], "invites": []}
    cols = {"name": 0, "city": 1, "department": 2, "role": 3, "phone": 4, "position": 5, "email": 6}
    start = 0
    for n, row in enumerate(rows):
        if any(c.strip() for c in row):
            mapped = _map_header(row)
            if mapped:
                cols, start = mapped, n + 1
            break
    for n, row in enumerate(rows):
        if n < start or not any(c.strip() for c in row):
            continue
        line = n + 1

        def cell(key):
            i = cols.get(key)
            return row[i].strip() if i is not None and i < len(row) else ""

        name = " ".join(cell("name").split())
        errs = []
        if len(name) < 3:
            errs.append("нет имени")
        b = resolve_branch(cell("city"), branches)
        if not b:
            errs.append(f"город «{cell('city')}» не найден — допустимы: {cities}" if cell("city") else f"не указан город — допустимы: {cities}")
        dep = None
        if cell("department"):
            dep = resolve_department(cell("department"), departments)
            if not dep:
                errs.append(f"отдел «{cell('department')}» не найден — допустимы: " + ", ".join(d["name"] for d in departments))
        role = "employee"
        if cell("role"):
            role = ROLES_IMPORT.get(cell("role").strip().lower())
            if not role:
                errs.append(f"роль «{cell('role')}» — допустимы Сотрудник или Ответственный")
        phone = None
        if cell("phone"):
            phone = norm_phone(cell("phone"))
            if not phone or len(phone_key(phone)) < 10:
                errs.append(f"телефон «{cell('phone')}» некорректен")
        email = norm_email(cell("email"))
        if email and ("@" not in email or " " in email):
            errs.append(f"почта «{cell('email')}» некорректна")
        if errs:
            out["errors"].append({"row": line, "name": name or None, "text": "; ".join(c for c in row if c)[:120], "error": "; ".join(errs)})
            continue
        position = " ".join(cell("position").split()) or None
        existing = find_by_phone(phone) or find_by_email(email)
        if not existing:
            existing = next((r for r in db.q("SELECT * FROM users WHERE branch_id=?", (b["id"],)) if " ".join(r["name"].lower().split()) == name.lower()), None)
        if existing:
            sets = {}
            if dep and not existing.get("department_id"):
                sets["department_id"] = dep["id"]
            if position and not existing.get("position"):
                sets["position"] = position
            if phone and not existing.get("phone"):
                sets["phone"] = phone
            if email and not existing.get("email"):
                sets["email"] = email
            if sets:
                db.ex("UPDATE users SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE id=?", (*sets.values(), existing["id"]))
            out["updated"] += 1
            out["users"].append({"row": line, "id": existing["id"], "name": existing["name"], "action": "updated", "active": bool(existing["active"])})
            continue
        uid = db.ex("INSERT INTO users(name, role, position, branch_id, department_id, manager_id, active, email, phone) VALUES(?,?,?,?,?,NULL,1,?,?)",
                    (name, role, position, b["id"], dep["id"] if dep else None, email, phone))
        out["created"] += 1
        out["users"].append({"row": line, "id": uid, "name": name, "action": "created", "active": True})
        if invite:
            inv = issue(uid, actor_id)
            out["invites"].append({"id": inv["id"], "user_id": uid, "name": name, "expires_at": inv["expires_at"]})
    return out


# ---------- карточки-приглашения для печати (PDF) ----------

FONT = ROOT / "web" / "a" / "fonts" / "Montserrat.ttf"
RED, NAVY, INK, MUTED, FRAME = (0.894, 0, 0), (0.031, 0.153, 0.259), (0.196, 0.227, 0.278), (0.392, 0.455, 0.553), (0.82, 0.86, 0.9)
_FONTS: dict[str, str] | None = None


def _fonts() -> dict[str, str]:
    """reportlab не понимает оси вариативного шрифта — один раз на процесс делаем статические начертания Montserrat (fontTools)."""
    global _FONTS
    if _FONTS:
        return _FONTS
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from . import brand
    d = Path(tempfile.mkdtemp(prefix="mf-invite-fonts-"))
    out = {}
    for key, name, w in (("regular", "MG-Regular", 400), ("semibold", "MG-SemiBold", 600), ("extrabold", "MG-ExtraBold", 800)):
        pdfmetrics.registerFont(TTFont(name, str(brand.static_font(w, name, d / f"{name}.ttf"))))   # у каждого начертания своё имя
        out[key] = name
    _FONTS = out
    return out


def _logo():
    """Фирменный блок «логотип | черта | МОДУС ГОЛОС» (mf/brand.py, как шапка сайта) → PNG; без cairosvg — текстовая марка."""
    try:
        from . import brand
        return brand.lockup_png(160)
    except Exception:   # noqa: BLE001
        return None


def _fit(c, text: str, font: str, size: float, max_w: float, min_size: float = 8) -> float:
    from reportlab.pdfbase import pdfmetrics
    while size > min_size and pdfmetrics.stringWidth(text, font, size) > max_w:
        size -= 0.5
    return size


def local_date(iso: str | None) -> str:
    dt = db.parse(iso)
    if not dt:
        return ""
    dt = dt + timedelta(hours=int(db.setting("tz_offset_hours", 5) or 5))
    return dt.strftime("%d.%m.%Y")


def cards_pdf(invites: list[dict], base: str) -> bytes:
    """Карточки 4 на лист A4 (A6 каждая) с метками реза: логотип, «МОДУС ГОЛОС · ПРИГЛАШЕНИЕ», имя, город · отдел, QR,
    «Откройте камерой — и вы в системе», срок действия. Отдаётся по запросу, в demo/ не хранится."""
    import qrcode
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    fonts = _fonts()
    logo = _logo()
    W, H = A4
    cw, ch = W / 2, H / 2
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Приглашения — «Модус Голос»")

    def rgb(col):
        c.setFillColorRGB(*col); c.setStrokeColorRGB(*col)

    def card(x0: float, y0: float, inv: dict) -> None:
        u = inv["user"] or {}
        name = u.get("name") or ""
        city = u.get("city") or u.get("branch") or ""
        sub = " · ".join(x for x in (city, u.get("department"), u.get("position")) if x)
        url = url_for(inv["token"], base)
        pad = 12 * mm
        # шапка: фирменный блок «логотип | черта | МОДУС ГОЛОС» (или текстовая марка) и сетка красных точек — как на плакатах
        if logo is not None:
            c.drawImage(ImageReader(logo), x0 + pad, y0 + ch - pad - 7 * mm, width=logo.width / logo.height * 7 * mm, height=7 * mm, mask="auto")
        else:
            rgb(NAVY); c.setFont(fonts["extrabold"], 11); c.drawString(x0 + pad, y0 + ch - pad - 5 * mm, "МОДУС ТРЕЙД")
        rgb(RED)
        for i in range(4):
            for j in range(3):
                c.circle(x0 + cw - pad - 14 * mm + i * 4 * mm, y0 + ch - pad - 1 * mm - j * 4 * mm, 0.7 * mm, fill=1, stroke=0)
        c.setLineWidth(0.9); c.line(x0 + pad, y0 + ch - 26 * mm, x0 + pad + 7 * mm, y0 + ch - 26 * mm)
        rgb(NAVY)   # подпись тёмно-синяя, красная только черта
        c.setFont(fonts["semibold"], 7.5); c.drawString(x0 + pad + 9 * mm, y0 + ch - 27 * mm, "МОДУС ГОЛОС · ЛИЧНОЕ ПРИГЛАШЕНИЕ")
        rgb(NAVY)
        size = _fit(c, name, fonts["extrabold"], 17, cw - 2 * pad)
        c.setFont(fonts["extrabold"], size); c.drawString(x0 + pad, y0 + ch - 36 * mm, name)
        rgb(MUTED)
        size = _fit(c, sub, fonts["regular"], 9, cw - 2 * pad, 6.5)
        c.setFont(fonts["regular"], size); c.drawString(x0 + pad, y0 + ch - 42 * mm, sub)
        # QR
        q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=1)
        q.add_data(url); q.make(fit=True)
        img = q.make_image(fill_color="#082742", back_color="white").convert("RGB")
        qs = 54 * mm
        qx, qy = x0 + (cw - qs) / 2, y0 + ch - 48 * mm - qs
        rgb(FRAME); c.setLineWidth(0.6); c.roundRect(qx - 3 * mm, qy - 3 * mm, qs + 6 * mm, qs + 6 * mm, 3 * mm, stroke=1, fill=0)
        c.drawImage(ImageReader(img), qx, qy, width=qs, height=qs)
        rgb(NAVY); c.setFont(fonts["semibold"], 10.5); c.drawCentredString(x0 + cw / 2, qy - 10 * mm, "Откройте камерой — и вы в системе")
        rgb(MUTED); c.setFont(fonts["regular"], 7)
        until = local_date(inv.get("expires_at"))
        if not until and inv.get("created_at"):   # страховка: срока нет в данных — считаем от выдачи (замечание владельца 13.11: дата была пустой)
            until = local_date(db.iso(db.parse(inv["created_at"]) + timedelta(days=invite_days())))
        c.drawCentredString(x0 + cw / 2, qy - 15.5 * mm, "Ссылка личная, вход один раз · " + (f"действует до {until} · " if until else "") + "паролей нет")
        c.setFont(fonts["regular"], 6.5); c.drawCentredString(x0 + cw / 2, y0 + 9 * mm, "ГК «Модус Трейд» · «Модус Голос» — каждый голос услышан")

    def marks() -> None:
        rgb(FRAME); c.setLineWidth(0.4); c.setDash(2, 3)
        c.line(cw, 6 * mm, cw, H - 6 * mm); c.line(6 * mm, ch, W - 6 * mm, ch)
        c.setDash()

    for k, inv in enumerate(invites):
        slot = k % 4
        if slot == 0:
            marks()
        x0 = 0 if slot in (0, 2) else cw
        y0 = ch if slot in (0, 1) else 0
        card(x0, y0, inv)
        if slot == 3 or k == len(invites) - 1:
            c.showPage()
    if not invites:
        c.showPage()
    c.save()
    return buf.getvalue()
