"""Обратная связь от клиентов — минимум (решение владельца 13.11, заменяет прошлые задания про клиентов): форма /c без входа —
«Благодарность / Вопрос / Замечание», текст, город или объект, имя и телефон или почта с галочкой согласия, фото; лимиты частоты как у
QR-формы и ловушка для ботов. В панели «От клиентов» (директор и администратор) — список всех сообщений, новые сверху; нажатие — полный
текст и фото. Без статусов, баллов, лиги, счётчиков, строки в /boss и уведомлений. Демо — 3–4 сообщения разных типов в снапшоте."""
import io
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mf import api, db, demo
from mf.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def send(c, **kw):
    data = {"kind": "thanks", "text": "Спасибо бригаде за аккуратный монтаж", "place": "", "name": "", "contact": "", "consent": "", "website": ""}
    data.update({k: v for k, v in kw.items() if k != "files"})
    return c.post("/api/public/client-messages", data=data, files=kw.get("files"))


def png(w=40, h=30) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_page_c_without_login(c):
    c.cookies.clear()
    r = c.get("/c")
    assert r.status_code == 200 and "client.js" in r.text and "обратная связь для клиентов" in r.text


def test_send_and_list_newest_first_for_director_and_admin(c):
    c.cookies.clear()
    n0 = db.one("SELECT COUNT(*) AS n FROM client_messages")["n"]
    assert send(c, kind="question", text="Когда приедет инженер на ТО?", place="Омск").json() == {"ok": True}
    assert send(c, kind="remark", text="Шкаф гудит после пусконаладки", place="Атырау, объект ТЭЦ-2", name="Ерлан", contact="+7 700 000 00 00", consent="1").status_code == 200
    assert db.one("SELECT COUNT(*) AS n FROM client_messages")["n"] == n0 + 2
    for uid in (1, 15):   # директор и администратор
        login(c, uid)
        items = c.get("/api/panel/client-messages").json()["items"]
        assert items[0]["kind"] == "remark" and items[0]["kind_label"] == "замечание" and items[0]["place"] == "Атырау, объект ТЭЦ-2"
        assert items[0]["name"] == "Ерлан" and items[0]["contact"] == "+7 700 000 00 00" and items[0]["photo_url"] is None
        assert items[1]["kind_label"] == "вопрос" and items[1]["contact"] is None
        assert [i["created_at"] for i in items] == sorted((i["created_at"] for i in items), reverse=True)
        assert not {"status", "points", "responsible", "number"} & set(items[0])   # без статусов, баллов и ответственных
    row = db.one("SELECT consent_at FROM client_messages WHERE name='Ерлан'")
    assert row["consent_at"]   # согласие записано вместе с контактом


@pytest.mark.parametrize("uid,code", [(None, 401), (6, 403), (4, 403), (2, 403)])
def test_panel_list_only_director_and_admin(c, uid, code):
    c.cookies.clear()
    if uid:
        login(c, uid)
    assert c.get("/api/panel/client-messages").status_code == code


@pytest.mark.parametrize("kw,msg", [({"kind": "praise"}, "благодарность, вопрос или замечание"), ({"text": "  "}, "несколько слов"),
                                    ({"name": "Ольга"}, "согласие"), ({"contact": "olga@example.com"}, "согласие")])
def test_validation(c, kw, msg):
    c.cookies.clear()
    n0 = db.one("SELECT COUNT(*) AS n FROM client_messages")["n"]
    r = send(c, **kw)
    assert r.status_code == 422 and msg in r.json()["detail"]
    assert db.one("SELECT COUNT(*) AS n FROM client_messages")["n"] == n0


def test_bot_trap_accepts_but_saves_nothing(c):
    c.cookies.clear()
    n0 = db.one("SELECT COUNT(*) AS n FROM client_messages")["n"]
    assert send(c, website="http://spam.example").json() == {"ok": True}
    assert db.one("SELECT COUNT(*) AS n FROM client_messages")["n"] == n0


def test_rate_limit_like_qr_form(c):
    c.cookies.clear()
    assert (api.client_limit.limit, api.client_limit.window, api.client_limit.burst) == (api.qr_limit.limit, api.qr_limit.window, api.qr_limit.burst)
    codes = [send(c, text=f"Спасибо, сообщение {i}").status_code for i in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


def test_photo_cleaned_and_only_for_director_admin(c):
    c.cookies.clear()
    r = send(c, kind="remark", text="Вот фото шкафа", files={"file": ("shkaf.png", png(), "image/png")})
    assert r.status_code == 200
    login(c, 1)
    m = c.get("/api/panel/client-messages").json()["items"][0]
    assert m["text"] == "Вот фото шкафа" and m["photo_url"]
    ph = c.get(m["photo_url"])
    assert ph.status_code == 200 and ph.headers["content-type"].startswith("image/") and ph.content[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0")   # пересохранено без метаданных
    login(c, 6)
    assert c.get(m["photo_url"]).status_code == 403
    c.cookies.clear()
    n0 = db.one("SELECT COUNT(*) AS n FROM client_messages")["n"]
    bad = send(c, files={"file": ("x.png", b"%PDF-1.4 not an image", "image/png")})
    assert bad.status_code == 415 and db.one("SELECT COUNT(*) AS n FROM client_messages")["n"] == n0   # не картинка — сообщение не остаётся


def test_no_notifications_points_or_boss_line(c):
    c.cookies.clear()
    notes = db.one("SELECT COUNT(*) AS n FROM notifications")["n"]
    pts = db.one("SELECT COUNT(*) AS n FROM points_ledger")["n"]
    send(c, kind="remark", text="Замечание без уведомлений директору")
    assert db.one("SELECT COUNT(*) AS n FROM notifications")["n"] == notes and db.one("SELECT COUNT(*) AS n FROM points_ledger")["n"] == pts
    boss = (ROOT / "web" / "a" / "boss.js").read_text(encoding="utf-8")
    assert "client-messages" not in boss and "клиент" not in boss.lower()   # строки «От клиентов» в /boss нет


def test_demo_shift_fingerprint_and_snapshot_has_messages():
    assert ("client_messages", "created_at", "iso") in demo.SHIFT
    before = demo.fingerprint()
    db.ex("INSERT INTO client_messages(kind, text, created_at) VALUES('thanks', 'проверка отпечатка', ?)", (db.now_iso(),))
    assert demo.fingerprint() != before   # сообщение с живого сайта видно в preflight «база = снапшот»
    snap = sqlite3.connect(str(ROOT / "demo" / "fixtures" / "mf-demo.db"))
    try:
        rows = snap.execute("SELECT kind, text, name, contact, consent_at FROM client_messages").fetchall()
    finally:
        snap.close()
    assert 3 <= len(rows) <= 4 and {r[0] for r in rows} == {"thanks", "question", "remark"}
    assert all(r[4] for r in rows if r[2] or r[3])   # контакт в демо — только с согласием
    assert all("example.com" in r[3] or r[3].startswith("+7 700 000") for r in rows if r[3])   # вымышленные контакты
