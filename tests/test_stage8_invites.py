"""Этап 8 §4 — сотрудники без Битрикса (рабочие, производство, командированные). Без ключа и без сети (Битрикс — фейковый HTTP):
ручное добавление с телефоном; личное приглашение входит ровно один раз и даёт долгую сессию; «выдать заново» отзывает старую
ссылку и выходит с прежнего устройства; истёкшее не входит; деактивированный не входит, история остаётся; импорт CSV/Excel с
ошибочной строкой показывает ошибку и не роняет остальное; карточки PDF пачкой; склейка с Битриксом по телефону и почте,
спорные случаи — администратору."""
import io

import pytest
from fastapi.testclient import TestClient

from mf import auth, db, staff
from mf.integrations import bitrix
from mf.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app, client=("127.0.0.1", 50000)) as client:   # импорт, правка сотрудников и приглашения — с ноутбука: демо-сессиям снаружи закрыто (F-03)
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def branch(code):
    return db.one("SELECT * FROM branches WHERE code=?", (code,))


def users_count():
    return db.one("SELECT COUNT(*) AS n FROM users")["n"]


def test_add_worker_with_phone_invite_enters_once(c):
    login(c, 15)
    r = c.post("/api/admin/users", json={"name": "Асхат Бекжанов", "role": "employee", "position": "Сварщик", "branch_id": branch("PVL")["id"],
                                         "department_id": 12, "phone": "8 (701) 555-66-77", "invite": True})
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["phone"] == "+77015556677" and u["invite"]["status"] == "active" and "/i/" in u["invite"]["url"] and u["invite"]["card_url"].endswith("cards.pdf?ids=" + str(u["invite"]["id"]))
    token = u["invite"]["token"]
    assert len(token) >= 40 and u["invite"]["url"].endswith("/i/" + token)
    # один человек — один профиль: тот же телефон у другого не заводится
    assert c.post("/api/admin/users", json={"name": "Другой Человек", "role": "employee", "phone": "+7 701 555 66 77"}).status_code == 409
    assert c.post("/api/admin/users", json={"name": "Кривой Телефон", "role": "employee", "phone": "12-34"}).status_code == 422
    adm = c.get("/api/admin/settings").json()
    assert adm["invites"][str(u["id"])]["status"] == "active" and adm["invite_days"] == 14 and adm["settings"]["invite_days"] == 14
    assert next(x for x in adm["users"] if x["id"] == u["id"])["phone"] == "+77015556677"
    # страница приглашения без входа: кто приглашён → «Войти» один раз → долгая сессия
    c.cookies.clear()
    assert c.get(f"/i/{token}").status_code == 200 and "invite.js" in c.get(f"/i/{token}").text
    info = c.get(f"/api/public/invite/{token}").json()
    assert info["status"] == "active" and info["user"]["first_name"] == "Асхат" and info["user"]["city"] == "Павлодар" and info["user"]["department"] == "Производство"
    r = c.post(f"/api/public/invite/{token}/accept")
    assert r.status_code == 200 and r.json()["name"] == "Асхат Бекжанов" and r.json()["home"] == "/app"
    assert "mf_sid=" in r.headers["set-cookie"] and "Max-Age=31536000" in r.headers["set-cookie"]   # устройство помнит год
    me = c.get("/api/me").json()
    assert me["id"] == u["id"] and me["points"] == 0 and me["branch"] == "Павлодар"   # только город (13.11)
    assert c.get(f"/api/public/invite/{token}").json()["status"] == "already_in"   # то же устройство открыло ссылку снова
    assert db.one("SELECT used_at FROM invites WHERE token=?", (db.token_hash(token),))["used_at"]   # в базе — хэш (аудит 12.11, F-15)
    assert not db.one("SELECT 1 FROM invites WHERE token=?", (token,))
    # другое устройство — ссылка уже использована
    c.cookies.clear()
    assert c.get(f"/api/public/invite/{token}").json()["status"] == "used"
    assert c.post(f"/api/public/invite/{token}/accept").status_code == 410
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/public/invite/" + "x" * 43).json()["status"] == "missing"
    assert c.post("/api/public/invite/" + "x" * 43 + "/accept").status_code == 404


def test_reissue_revokes_old_link_and_device_expiry_and_setting(c):
    login(c, 15)
    uid = db.one("SELECT id FROM users WHERE name='Асхат Бекжанов'")["id"]
    from mf import staff
    old = staff.fresh_token(db.one("SELECT id FROM invites WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,))["id"])   # ссылка — в памяти час после выдачи
    assert old and len(old) >= 40
    sid = auth.login(uid)   # «телефон, который потеряли»: живая сессия
    assert c.get("/api/me", headers={"Authorization": "Bearer " + sid}).status_code == 200
    r = c.post("/api/admin/invites", json={"user_id": uid}).json()
    assert r["status"] == "active" and r["token"] != old and r["user"]["name"] == "Асхат Бекжанов"
    assert c.get("/api/me", headers={"Authorization": "Bearer " + sid}).status_code == 401   # прежнее устройство вышло
    c.cookies.clear()
    assert c.get(f"/api/public/invite/{old}").json()["status"] == "revoked" and c.post(f"/api/public/invite/{old}/accept").status_code == 410
    assert c.post(f"/api/public/invite/{r['token']}/accept").status_code == 200 and c.get("/api/me").json()["id"] == uid
    # истёкшее не входит
    login(c, 15)
    r2 = c.post("/api/admin/invites", json={"user_id": uid}).json()
    db.ex("UPDATE invites SET expires_at='2020-01-01T00:00:00Z' WHERE id=?", (r2["id"],))
    c.cookies.clear()
    assert c.get(f"/api/public/invite/{r2['token']}").json()["status"] == "expired" and c.post(f"/api/public/invite/{r2['token']}/accept").status_code == 410
    # срок — из настроек; отозвать без перевыпуска; QR и карточка
    login(c, 15)
    assert c.post("/api/admin/settings", json={"settings": {"invite_days": 3}}).status_code == 200
    r3 = c.post("/api/admin/invites", json={"user_id": uid}).json()
    assert 2.9 < (db.parse(r3["expires_at"]) - db.now()).total_seconds() / 86400 <= 3.01
    c.post("/api/admin/settings", json={"settings": {"invite_days": 14}})
    assert c.get(f"/api/admin/invites/{r3['id']}/qr.svg").headers["content-type"].startswith("image/svg")
    assert c.get(f"/api/admin/invites/{r3['id']}").json()["url"] == r3["url"]
    assert c.post(f"/api/admin/invites/{r3['id']}/revoke").json()["status"] == "revoked"
    c.cookies.clear()
    assert c.post(f"/api/public/invite/{r3['token']}/accept").status_code == 410
    assert c.post("/api/admin/invites", json={"user_id": uid}).status_code == 401   # только администратор и директор


def test_deactivated_does_not_enter_history_stays(c):
    login(c, 15)
    uid = db.one("SELECT id FROM users WHERE name='Асхат Бекжанов'")["id"]
    inv = c.post("/api/admin/invites", json={"user_id": uid}).json()
    sid = auth.login(uid)
    a = c.post("/api/appeals", data={"type": "problem", "text": "В цехе над сборочным столом второй день мигает свет, прошу проверить проводку"}, headers={"Authorization": "Bearer " + sid})
    assert a.status_code == 200
    r = c.post(f"/api/admin/users/{uid}/active", json={"active": False}).json()
    assert r["active"] == 0
    assert c.get("/api/me", headers={"Authorization": "Bearer " + sid}).status_code == 401   # старая сессия погашена
    c.cookies.clear()
    assert c.get(f"/api/public/invite/{inv['token']}").json()["status"] == "deactivated"
    assert c.post(f"/api/public/invite/{inv['token']}/accept").status_code == 403
    login(c, 15)
    assert c.get(f"/api/appeals/{a.json()['id']}").json()["number"] == a.json()["number"]   # обращение и история остались
    assert db.one("SELECT COUNT(*) AS n FROM appeal_authors WHERE user_id=?", (uid,))["n"] == 1
    assert c.post("/api/admin/users/15/active", json={"active": False}).status_code == 409   # себя нельзя
    assert c.post("/api/admin/invites", json={"user_id": uid}).status_code == 409           # отключённому не выдать
    assert c.get("/api/admin/settings").json()["invites"][str(uid)]["status"] == "revoked"
    assert c.post(f"/api/admin/users/{uid}/active", json={"active": True}).json()["active"] == 1
    assert c.post("/api/admin/invites", json={"user_id": uid}).status_code == 200
    # отключение через общую карточку сотрудника — тот же эффект
    sid2 = auth.login(uid)
    u = next(x for x in c.get("/api/admin/settings").json()["users"] if x["id"] == uid)
    assert c.post("/api/admin/users", json={**{k: u[k] for k in ("id", "name", "role", "position", "branch_id", "department_id", "manager_id", "email", "bitrix_id", "phone")}, "active": False}).status_code == 200
    assert c.get("/api/me", headers={"Authorization": "Bearer " + sid2}).status_code == 401
    c.post(f"/api/admin/users/{uid}/active", json={"active": True})


CSV = ("Имя;Город;Отдел;Роль;Телефон;Должность;Почта\r\n"
       "Марат Ибраев;Павлодар;Производство;Сотрудник;+7 701 000 00 01;Оператор участка;\r\n"
       "Ошибочная Строка;Караганда;Производство;Сотрудник;;;\r\n"
       "Асель Мусина;Объект;Проектирование;Сотрудник;+7 702 000 00 02;Инженер;asel@example.kz\r\n"
       ";;;\r\n"
       "Тимур Без Отдела;Астана;Нет такого отдела;Директор;12345;;\r\n")


def test_import_csv_bad_rows_reported_rest_imported(c):
    login(c, 15)
    t = c.get("/api/admin/users/template.csv")
    assert t.status_code == 200 and t.content.startswith("﻿".encode("utf-8")) and "Имя;Город;Отдел;Роль;Телефон;Должность;Почта" in t.text and "text/csv" in t.headers["content-type"]
    n0 = users_count()
    r = c.post("/api/admin/users/import", files={"file": ("staff.csv", CSV.encode("utf-8-sig"), "text/csv")}, data={"invite": "1"}).json()
    assert r["created"] == 2 and r["updated"] == 0 and [e["row"] for e in r["errors"]] == [3, 6], r
    assert "Караганда" in r["errors"][0]["error"] and "Омск" in r["errors"][0]["error"]
    e2 = r["errors"][1]["error"]
    assert "отдел" in e2 and "роль" in e2 and "телефон" in e2
    assert users_count() == n0 + 2 and {u["name"] for u in r["users"]} == {"Марат Ибраев", "Асель Мусина"}
    assert len(r["invites"]) == 2 and r["cards_url"].startswith("/api/admin/invites/cards.pdf?ids=")
    asel = db.one("SELECT * FROM users WHERE name='Асель Мусина'")
    assert asel["branch_id"] == branch("FIELD")["id"] and asel["email"] == "asel@example.kz" and asel["role"] == "employee" and asel["phone"] == "+77020000002" and asel["department_id"] == 3
    # повтор того же файла — дублей нет, приглашения заново не выдаются
    r2 = c.post("/api/admin/users/import", files={"file": ("staff.csv", CSV.encode("cp1251"), "text/csv")}, data={"invite": "1"}).json()
    assert r2["created"] == 0 and r2["updated"] == 2 and r2["invites"] == [] and users_count() == n0 + 2
    # Excel (openpyxl), запятая как разделитель и без заголовка — тоже читается
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Имя", "Город", "Отдел", "Телефон"]); ws.append(["Данияр Excel", "Тюмень", "Сервис", 77012223344])
    buf = io.BytesIO(); wb.save(buf)
    r3 = c.post("/api/admin/users/import", files={"file": ("staff.xlsx", buf.getvalue(), "application/octet-stream")}, data={"invite": "0"}).json()
    assert r3["created"] == 1 and r3["invites"] == [] and db.one("SELECT phone, branch_id FROM users WHERE name='Данияр Excel'") == {"phone": "+77012223344", "branch_id": branch("TMN")["id"]}
    r4 = c.post("/api/admin/users/import", files={"file": ("no_header.csv", "Жанар Позиционная,Самара,Продажи,,+7 703 000 00 03\n".encode("utf-8"), "text/csv")}, data={"invite": "0"}).json()
    assert r4["created"] == 1 and db.one("SELECT department_id FROM users WHERE name='Жанар Позиционная'")["department_id"] == 1
    assert c.post("/api/admin/users/import", files={"file": ("empty.csv", b"", "text/csv")}).status_code == 422
    # карточки для печати: пачкой на импорт, все действующие, одна
    pdf = c.get(r["cards_url"])
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF") and len(pdf.content) > 20000
    assert c.get("/api/admin/invites/cards.pdf?all=1").status_code == 200 and c.get(f"/api/admin/invites/cards.pdf?ids={r['invites'][0]['id']}").status_code == 200
    assert c.get("/api/admin/invites/cards.pdf?ids=999999").status_code == 404 and c.get("/api/admin/invites/cards.pdf?ids=abc").status_code == 422
    c.cookies.clear()
    assert c.get("/api/admin/users/template.csv").status_code == 401 and c.post("/api/admin/users/import", files={"file": ("x.csv", b"a", "text/csv")}).status_code == 401


def test_bitrix_merge_by_phone_and_email_conflicts_reported(c, monkeypatch):
    """Человек есть и в списке, и в портале → один профиль (склейка по телефону/почте); спорные случаи — в отчёт синхронизации."""
    monkeypatch.setenv("BITRIX_PORTAL", "modus-test.bitrix24.kz"); monkeypatch.setenv("BITRIX_CLIENT_ID", "local.abc"); monkeypatch.setenv("BITRIX_CLIENT_SECRET", "s3cret")
    bitrix.save_tokens({"access_token": "at1", "refresh_token": "rt1", "client_endpoint": "https://modus-test.bitrix24.kz/rest/", "member_id": "m1"})
    login(c, 15)
    marat = db.one("SELECT * FROM users WHERE name='Марат Ибраев'"); asel = db.one("SELECT * FROM users WHERE name='Асель Мусина'")
    n0 = users_count()
    portal = {"users": []}

    def fake(url, params=None, data=None):
        if url.endswith("/rest/department.get"):
            return {"result": [{"ID": "3", "NAME": "Производство"}]}
        if url.endswith("/rest/user.get"):
            return {"result": portal["users"]}
        raise AssertionError(url)
    monkeypatch.setattr(bitrix, "request_fn", fake)
    # 1) Марат заведён администратором с телефоном, в портале тот же номер в другом формате → один профиль, не дубль
    #    «Совсем Другой» с почтой Асель → склеено по почте, но имя не похоже → спорный случай администратору
    portal["users"] = [{"ID": "61", "NAME": "Марат", "LAST_NAME": "Ибраев", "ACTIVE": True, "PERSONAL_MOBILE": "8 701 000-00-01", "UF_DEPARTMENT": [3]},
                       {"ID": "62", "NAME": "Совсем", "LAST_NAME": "Другой", "ACTIVE": True, "EMAIL": "asel@example.kz"}]
    r = c.post("/api/admin/bitrix/sync").json()
    assert r["created"] == 0 and r["updated"] == 2 and users_count() == n0
    assert db.one("SELECT bitrix_id FROM users WHERE id=?", (marat["id"],))["bitrix_id"] == 61 and db.one("SELECT COUNT(*) AS n FROM users WHERE name LIKE 'Марат%'")["n"] == 1
    assert db.one("SELECT bitrix_id FROM users WHERE id=?", (asel["id"],))["bitrix_id"] == 62
    assert [x["reason"] for x in r["conflicts"]] == ["name"] and r["conflicts"][0]["bitrix_name"] == "Совсем Другой" and r["conflicts"][0]["name"] == "Асель Мусина"
    assert r["conflicts"][0]["candidates"] == [{"id": asel["id"], "name": "Асель Мусина", "by": "почта"}]
    assert c.get("/api/admin/settings").json()["bitrix"]["sync"]["conflicts"][0]["reason"] == "name"
    # 2) в портале человек с почтой Асель и телефоном Марата → совпали двое: спорная склейка с обоими кандидатами
    db.ex("UPDATE users SET bitrix_id=NULL WHERE bitrix_id IN (61, 62)")
    portal["users"] = [{"ID": "60", "NAME": "Асель", "LAST_NAME": "Мусина", "ACTIVE": True, "EMAIL": "asel@example.kz", "PERSONAL_MOBILE": "+7 701 000 00 01"}]
    r = c.post("/api/admin/bitrix/sync").json()
    assert r["created"] == 0 and users_count() == n0 and len(r["conflicts"]) == 1 and r["conflicts"][0]["reason"] == "several"
    assert {(k["name"], k["by"]) for k in r["conflicts"][0]["candidates"]} == {("Асель Мусина", "почта"), ("Марат Ибраев", "телефон")}
    assert db.one("SELECT bitrix_id FROM users WHERE id=?", (asel["id"],))["bitrix_id"] == 60   # склеено по почте — первой в правиле
    db.ex("UPDATE users SET bitrix_id=NULL WHERE bitrix_id IS NOT NULL")
    bitrix.tokens_path().unlink(missing_ok=True)


def test_seed_demo_worker_has_invite_and_phone(c):
    """Демо-рабочий без Битрикса (id 28, Павлодар — производство) заведён seed с телефоном и действующим приглашением — запасной ход показа."""
    from mf import seed
    u = db.one("SELECT * FROM users WHERE id=?", (seed.DEMO_WORKER,))
    assert u["name"] == "Нурлан Серикбаев" and u["role"] == "employee" and u["phone"] == seed.DEMO_WORKER_PHONE and u["branch_id"] == branch("PVL")["id"] and u["department_id"] == 12
    inv = staff.latest_by_user()[seed.DEMO_WORKER]
    assert inv["status"] == "active" and 13 < (db.parse(inv["expires_at"]) - db.now()).total_seconds() / 86400 <= 14.01
    assert seed.add_demo_worker() is None   # повторно не плодит
