"""ТЗ v2 по кастдеву: реальные города и «Объект», отдел развития и путь предложения к директору, «Нужно решение директора»,
возраст ожидания и порог, категория «1С и автоматизация»."""
import pytest
from fastapi.testclient import TestClient

from mf import db
from mf.ai import fallback
from mf.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def notes(c):
    return [n["text"] for n in c.get("/api/notifications").json()["items"]]


def test_cities_and_field_qr(c):
    codes = {b["code"]: b for b in c.get("/api/public/branches").json()}
    assert set(codes) == {"OMSK", "SAM", "TMN", "AST", "PVL", "FIELD"} and codes["PVL"]["kind"] == "production" and codes["FIELD"]["kind"] == "field"
    r = c.post("/api/public/appeals", data={"type": "problem", "text": "На объекте нет актуальной схемы, рисуем заново", "branch_code": "FIELD", "site_city": "Атырау"})
    assert r.status_code == 200, r.text
    a = db.one("SELECT site_city, branch_id FROM appeals WHERE id=?", (r.json()["id"],))
    assert a["site_city"] == "Атырау" and a["branch_id"] == codes["FIELD"]["id"]
    r = c.post("/api/public/appeals", data={"type": "problem", "text": "Принтер в офисе Самары не печатает накладные", "branch_code": "SAM", "site_city": "x"})
    assert db.one("SELECT site_city FROM appeals WHERE id=?", (r.json()["id"],))["site_city"] is None   # город объекта — только для «Объекта»
    login(c, 1)
    row = next(x for x in c.get("/api/panel/appeals", params={"q": "Атырау"}).json())
    assert row["site_city"] == "Атырау" and row["branch_code"] == "FIELD"


def test_categories_after_custdev(c):
    login(c, 6)
    cats = {x["name"]: x for x in c.get("/api/dicts").json()["categories"]}
    assert "1С и автоматизация" in cats and cats["1С и автоматизация"]["responsible"] == "Бауыржан Сапаров"
    assert "Номенклатура и спецификации" in cats and "Каталог и данные" not in cats
    assert db.one("SELECT c.name FROM appeals a JOIN categories c ON c.id=a.category_id WHERE a.number='A-003'")["name"] == "Номенклатура и спецификации"
    r = fallback.classify("Отчёт в 1С не выгружается после обновления конфигурации, автоматизация встала", list(cats.values()))
    assert r["category"] == "1С и автоматизация"
    r = fallback.classify("В справочнике номенклатуры дубли артикулов, в спецификации попадают не те позиции", list(cats.values()))
    assert r["category"] == "Номенклатура и спецификации"


def test_suggestion_path_to_director(c):
    login(c, 6)   # Сауле подаёт предложение → отдел развития, копия её руководителю Марине
    a = c.post("/api/appeals", data={"type": "suggestion", "text": "Предлагаю купить сканер штрихкодов для склада, чтобы не вбивать артикулы вручную", "category_id": "19"}).json()
    assert a["responsible"] == "Гульнара Сейтжанова" and a["can_request_director"] is False
    login(c, 7)
    assert any("подал предложение" in n and a["number"] in n for n in notes(c))
    login(c, 25)  # отдел развития: нужны ресурсы → к директору
    assert c.post(f"/api/panel/appeals/{a['id']}/director", json={"text": " "}).status_code == 422
    r = c.post(f"/api/panel/appeals/{a['id']}/director", json={"text": "Нужен бюджет 300 тыс. на сканеры"})
    assert r.status_code == 200 and r.json()["director_decision"] == "pending" and r.json()["can_request_director"] is False
    assert c.post(f"/api/panel/appeals/{a['id']}/director", json={"text": "ещё раз"}).status_code == 409
    login(c, 1)   # директор: общая очередь с идеями совещаний, возраст и порог
    q = c.get("/api/director/ideas").json()
    assert q["threshold_days"] == 7 and q["over_threshold"] >= 2
    mine = next(x for x in q["pending"] if x.get("source") == "appeal" and x["number"] == a["number"])
    assert mine["request"].startswith("Нужен бюджет") and mine["wait_days"] < 1 and mine["over_threshold"] is False
    old = next(x for x in q["pending"] if x.get("number") == "A-027")
    assert old["wait_days"] >= 11 and old["over_threshold"] is True
    assert q["pending"][0]["wait_days"] >= q["pending"][-1]["wait_days"]
    assert any("На решение: предложение " + a["number"] in n for n in notes(c))
    assert c.post(f"/api/director/appeals/{a['id']}/decide", json={"decision": "rejected"}).status_code == 422   # причина обязательна
    r = c.post(f"/api/director/appeals/{a['id']}/decide", json={"decision": "accepted", "comment": "Бюджет выделен из резерва"})
    assert r.status_code == 200 and r.json()["director_decision"] == "accepted"
    assert any(e["kind"] == "director_decided" for e in r.json()["events"])
    assert c.post(f"/api/director/appeals/{a['id']}/decide", json={"decision": "accepted"}).status_code == 409
    login(c, 6)
    assert any("Директор принял предложение " + a["number"] in n for n in notes(c))
    login(c, 25)
    assert any("Директор принял предложение " + a["number"] in n for n in notes(c))
    r = c.post(f"/api/director/appeals/{db.one('SELECT id FROM appeals WHERE number=?', ('A-028',))['id']}/decide", json={"decision": "rejected", "comment": "Сначала регламент, потом доработка"})
    assert r.status_code == 403   # отдел развития решения директора не принимает


def test_problem_not_escalated(c):
    login(c, 3)
    aid = db.one("SELECT id FROM appeals WHERE number='A-007'")["id"]
    assert c.post(f"/api/panel/appeals/{aid}/director", json={"text": "x"}).status_code == 409
