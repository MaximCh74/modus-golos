"""Этап 1: ядро без ИИ — проверочные сценарии датасета 1–6 и правила ТЗ v1.1 §5."""
import os
import tempfile

os.environ["MF_DATA_DIR"] = tempfile.mkdtemp(prefix="mf-test-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mf import db  # noqa: E402
from mf.main import app  # noqa: E402


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    r = c.post("/api/auth/login-as", json={"user_id": uid})
    assert r.status_code == 200, r.text
    return r.json()


def number_id(number):
    return db.one("SELECT id FROM appeals WHERE number=?", (number,))["id"]


def test_seed_matches_dataset(c):
    assert c.get("/api/health").json()["appeals"] == 20
    a17 = db.one("SELECT * FROM appeals WHERE number='A-017'")
    assert a17["status"] == "rejected" and "помещения" in a17["resolution_text"]
    assert db.one("SELECT COUNT(*) AS n FROM categories")["n"] == 18
    assert db.one("SELECT responsible_id FROM appeals WHERE number='A-019'")["responsible_id"] is None


def test_qr_anonymous_and_tracking(c):
    # текст без ключевых слов: ни ИИ (без ключа), ни словарь категорию не дают → очередь администратора «Без ответственного»
    r = c.post("/api/public/appeals", data={"type": "problem", "text": "Нужна помощь, непонятно к кому обращаться", "branch_code": "PVL"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["number"] == "A-021" and j["logged_in"] is False
    t = c.get(f"/api/public/track/{j['tracking_token']}").json()
    assert t["status"] == "new" and t["author"] is None and t["is_anonymous"] == 1 and t["unassigned"] is True
    assert c.get("/api/public/track/nope").status_code == 404
    login(c, 15)   # администратор: очередь «Без ответственного», автор не раскрывается
    q = c.get("/api/panel/appeals", params={"unassigned": 1}).json()
    assert any(x["number"] == "A-021" for x in q)
    card = c.get(f"/api/appeals/{j['id']}").json()
    assert card["author"] is None and card["is_anonymous"] == 1


def test_routing_by_category(c):
    login(c, 6)   # Сауле
    r = c.post("/api/appeals", data={"type": "problem", "text": "Вбиваем одни и те же данные в 1С и Битрикс", "category_id": "7"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["responsible_id"] == 3 and a["responsible"] == "Ерлан Жумабеков"
    r = c.post("/api/appeals", data={"type": "suggestion", "text": "Навести порядок в общих папках с инструкциями", "category_id": "17"})
    assert r.json()["responsible_id"] is None and r.json()["unassigned"] is True


def test_status_flow_rejection_and_points(c):
    login(c, 6)
    a = c.post("/api/appeals", data={"type": "suggestion", "text": "Сделать шаблон КП с обязательными полями", "category_id": "7"}).json()
    before = c.get("/api/me/points").json()["balance"]
    login(c, 3)   # Ерлан
    assert c.post(f"/api/panel/appeals/{a['id']}/status", json={"status": "done"}).status_code == 409   # не из «Новое»
    r = c.post(f"/api/panel/appeals/{a['id']}/status", json={"status": "review"})
    assert r.status_code == 200 and r.json()["first_response_at"]
    assert c.post(f"/api/panel/appeals/{a['id']}/status", json={"status": "rejected"}).status_code == 422   # без мотивировки нельзя
    r = c.post(f"/api/panel/appeals/{a['id']}/status", json={"status": "in_progress"})
    assert r.status_code == 200
    assert c.post(f"/api/panel/appeals/{a['id']}/status", json={"status": "done"}).status_code == 422   # без «что сделано» нельзя
    r = c.post(f"/api/panel/appeals/{a['id']}/status", json={"status": "done", "text": "Шаблон КП выложен в общую папку"})
    assert r.status_code == 200 and r.json()["resolution_text"].startswith("Шаблон")
    login(c, 6)
    assert c.get("/api/me/points").json()["balance"] == before + 10 + 50
    assert any(x["number"] == a["number"] for x in c.get("/api/changes").json())
    kinds = [e["kind"] for e in c.get(f"/api/appeals/{a['id']}").json()["events"]]
    assert kinds.count("points_awarded") == 2 and "status_changed" in kinds


def test_rejection_with_reason_visible_to_author(c):
    login(c, 6)
    a = c.post("/api/appeals", data={"type": "suggestion", "text": "Поставить кофемашину на третьем этаже", "category_id": "16"}).json()
    before = c.get("/api/me/points").json()["balance"]
    login(c, 11)   # Сергей, административный руководитель
    r = c.post(f"/api/panel/appeals/{a['id']}/status", json={"status": "rejected", "text": "Бюджет на этот год исчерпан"})
    assert r.status_code == 200
    login(c, 6)
    card = c.get(f"/api/appeals/{a['id']}").json()
    assert card["status"] == "rejected" and card["resolution_text"] == "Бюджет на этот год исчерпан"
    assert c.get("/api/me/points").json()["balance"] == before   # за отклонённое баллов нет


def test_clarification_roundtrip(c):
    login(c, 6)
    a = c.post("/api/appeals", data={"type": "problem", "text": "Долго согласуются документы между отделами", "category_id": "5"}).json()
    login(c, 7)   # Марина
    r = c.post(f"/api/panel/appeals/{a['id']}/clarify", json={"text": "Какие именно документы?"})
    assert r.status_code == 200 and r.json()["status"] == "clarify" and r.json()["pending_question"] == "Какие именно документы?"
    login(c, 6)
    r = c.post(f"/api/appeals/{a['id']}/answer", json={"text": "Счета и акты по проектам"})
    assert r.status_code == 200 and r.json()["status"] == "review"
    kinds = [e["kind"] for e in r.json()["events"]]
    assert "clarification_requested" in kinds and "clarification_answered" in kinds
    login(c, 7)
    assert any("ответил на уточнение" in n["text"] for n in c.get("/api/notifications").json()["items"])


def test_support_points_and_cap(c):
    aid = number_id("A-007")
    login(c, 19)   # Павел — автор A-007
    before = c.get("/api/me/points").json()["balance"]
    assert c.post(f"/api/appeals/{aid}/support").status_code == 409   # своё поддержать нельзя
    login(c, 6)
    assert c.post(f"/api/appeals/{aid}/support").json()["supports"] == 3
    assert c.post(f"/api/appeals/{aid}/support").status_code == 409   # повторно нельзя
    login(c, 19)
    assert c.get("/api/me/points").json()["balance"] == before + 2
    card = c.get(f"/api/appeals/{aid}").json()
    assert card["supports"] == 3


def test_overdue_escalation(c):
    login(c, 1)
    c.post("/api/panel/check-overdue")
    a1 = c.get(f"/api/appeals/{number_id('A-001')}").json()
    assert a1["overdue"] is True and any(e["kind"] == "escalated" for e in a1["events"])
    login(c, 2)   # Олег — руководитель Дмитрия (ответственный A-001)
    assert any("Просрочено: A-001" in n["text"] for n in c.get("/api/notifications").json()["items"])
    q = c.get("/api/panel/appeals", params={"overdue": 1}).json()
    assert {x["number"] for x in q} >= {"A-001", "A-007", "A-011"}


def test_permissions(c):
    login(c, 6)   # сотрудник
    assert c.get("/api/panel/appeals").status_code == 403
    assert c.get(f"/api/appeals/{number_id('A-001')}").status_code == 403   # чужое открытое
    assert c.get(f"/api/appeals/{number_id('A-004')}").status_code == 200   # чужое реализованное — лента «Что изменили»
    login(c, 13)  # Руслан (договоры, Астана) — обращение бухгалтерии не его
    assert c.post(f"/api/panel/appeals/{number_id('A-005')}/comment", json={"text": "x"}).status_code == 403
    c.post("/api/auth/logout")
    assert c.get("/api/me").status_code == 401


def test_summary(c):
    login(c, 1)
    s = c.get("/api/panel/summary").json()
    assert s["open"] > 0 and s["considered_share"] is not None and len(s["by_branch"]) == 4
    assert s["done_total"] >= 2
