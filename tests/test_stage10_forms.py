"""Правки по отзыву владельца 12.11 (после этапа 9): «Спасибо» — короткая форма с адресатом (коллега или отдел → уведомление адресату и
его руководителю, запись в профиле адресата), в QR-форме тоже; поиск адресата; плакаты филиалов PDF из администрирования; филиалы
по-русски; вход внутри фрейма Битрикса: страница /bitrix/app без сессии, встраивание разрешено порталу на всех путях."""
import os

import pytest
from fastapi.testclient import TestClient

from mf import db
from mf.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def notes(c):
    return [n["text"] for n in c.get("/api/notifications").json()["items"]]


def test_praise_short_form_to_colleague_notifies_her_and_manager(c):
    login(c, 6)   # Сауле (PVL, бухгалтерия) говорит спасибо Айгерим (id 4, руководитель 2 — Олег)
    r = c.post("/api/appeals", data={"type": "praise", "text": "Айгерим, спасибо за быстрый договор по Атырау — клиент подписал в тот же день",
                                     "praise_to_user_id": "4", "category_id": "5", "priority": "high", "is_anonymous": "1", "proposed_solution": "x"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["type"] == "praise" and a["category_id"] is None and a["priority"] == "medium" and not a["is_anonymous"] and not a["proposed_solution"]
    assert any(e["kind"] == "praise_addressed" and e["payload"]["user"] == "Айгерим Нурланова" for e in a["events"])
    row = db.one("SELECT praise_to_user_id, praise_to_department_id FROM appeals WHERE id=?", (a["id"],))
    assert row == {"praise_to_user_id": 4, "praise_to_department_id": None}
    login(c, 4)
    assert any("Сауле Абишева говорит вам спасибо" in n for n in notes(c))
    login(c, 2)
    assert any(n.startswith("Айгерим Нурланова: спасибо от коллеги") for n in notes(c))
    p = c.get("/api/users/4/profile").json()
    assert p["praises"] and p["praises"][0]["from"] == "Сауле Абишева" and p["praises"][0]["number"] == a["number"] and p["thanks"] >= 1
    # поиск адресата: по части имени и по отделу, минимум два символа
    s = c.get("/api/staff/search?q=айге").json()
    assert [u["name"] for u in s["users"]] == ["Айгерим Нурланова"] and s["departments"] == []
    s = c.get("/api/staff/search?q=бухг").json()
    assert s["users"] == [] and [d["name"] for d in s["departments"]] == ["Бухгалтерия"]
    assert c.get("/api/staff/search?q=а").json() == {"users": [], "departments": []}


def test_praise_to_department_from_qr_without_login(c):
    c.cookies.clear()
    bux = db.one("SELECT id FROM departments WHERE name='Бухгалтерия'")["id"]
    members = [u["id"] for u in db.q("SELECT id FROM users WHERE department_id=? AND active=1", (bux,))]
    assert len(members) >= 2
    r = c.post("/api/public/appeals", data={"type": "praise", "text": "Бухгалтерия, спасибо — закрыли авансовый отчёт за день", "branch_code": "PVL", "praise_to_department_id": str(bux)})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["type"] == "praise" and j["category"] is None and j["ai_engine"] is None
    for uid in members:
        login(c, uid)
        assert any("Отделу «Бухгалтерия» говорят спасибо" in n for n in notes(c))
    c.cookies.clear()
    assert c.get("/api/public/staff?q=проект").json()["departments"][0]["name"] in ("Проектирование", "Проектный офис")
    assert c.post("/api/public/appeals", data={"type": "wrong", "text": "x", "branch_code": "PVL"}).status_code == 422


def test_branches_posters_and_russian_labels(c):
    login(c, 15)
    adm = c.get("/api/admin/settings").json()
    b = next(x for x in adm["branches"] if x["code"] == "PVL")
    assert b["kind_label"] == "производство" and b["form_url"].endswith("/q/PVL") and b["poster_url"] == "/api/admin/branches/PVL/poster.pdf"
    assert {x["kind_label"] for x in adm["branches"]} == {"офис", "производство", "объекты"}
    one = c.get("/api/admin/branches/PVL/poster.pdf")
    assert one.status_code == 200 and one.headers["content-type"] == "application/pdf" and one.content.startswith(b"%PDF")
    allp = c.get("/api/admin/branches/posters.pdf")
    assert allp.status_code == 200 and len(allp.content) > len(one.content)
    assert c.get("/api/admin/branches/NOPE/poster.pdf").status_code == 404
    c.cookies.clear()
    assert c.get("/api/admin/branches/posters.pdf").status_code == 401


def test_frame_login_pages_and_headers(c, monkeypatch):
    for k in ("BITRIX_PORTAL", "BITRIX_CLIENT_ID", "BITRIX_CLIENT_SECRET"):
        os.environ.pop(k, None)
    c.cookies.clear()
    r = c.get("/")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"   # без портала — запрет везде
    monkeypatch.setenv("BITRIX_PORTAL", "modus-test.bitrix24.kz"); monkeypatch.setenv("BITRIX_CLIENT_ID", "local.abc"); monkeypatch.setenv("BITRIX_CLIENT_SECRET", "s3cret")
    for path in ("/", "/app", "/panel", "/login", "/bitrix/app"):
        r = c.get(path)
        assert r.status_code == 200 and "frame-ancestors 'self' https://modus-test.bitrix24.kz;" in r.headers["content-security-policy"] and "x-frame-options" not in r.headers, path
    assert "bitrix_app.js" in c.get("/bitrix/app").text   # без сессии — страница восстановления входа из sessionStorage фрейма
    login(c, 6)
    assert "/a/app.js" in c.get("/bitrix/app").text       # с сессией — приложение сотрудника
