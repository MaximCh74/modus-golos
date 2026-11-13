"""Замечания владельца после теста 13.11: сводка директора списком из фактов (ИИ — только приветствие без чисел), команда «самое давнее
на решении» → открыть это обращение, срок приглашения, баллы только сотрудникам, одно название «Результаты обращений»."""
import re

import pytest
from fastapi.testclient import TestClient

from mf import director
from mf.ai import llm
from mf.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app, client=("127.0.0.1", 50000)) as client:   # ручная точка на карте — администрирование с ноутбука (F-03)
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def test_summary_is_a_list_of_server_numbers(c):
    login(c, 1)
    d = c.get("/api/panel/director-summary?engine=template").json()
    f = d["facts"]
    assert d["greeting"].endswith(", Сергей Михайлович.") and not re.search(r"\d", d["greeting"])
    assert d["period"] == "За 7 дней:"
    texts = [it["text"] for it in d["items"]]
    assert texts[0] == f"Поступило: {f['new']}" and texts[1] == f"Решено: {f['done']}"
    assert texts[2].startswith(f"Открыто: {f['open']}") and (f"из них мешают работать: {f['urgent_open']}" in texts[2]) == bool(f["urgent_open"])
    dec = next(t for t in texts if t.startswith("Ждут вашего решения"))
    assert dec == f"Ждут вашего решения: {f['decisions_pending']}, самое давнее — {f['decision_max_days']} дней" or dec.startswith(f"Ждут вашего решения: {f['decisions_pending']}, самое давнее — {f['decision_max_days']} ")
    theme = next(t for t in texts if t.startswith("Главная тема: "))
    assert f" — {f['cluster']['size']} " in theme and f" из {len(f['cluster']['cities'])} " in theme
    for it in d["items"]:   # каждое число — жирным отдельным сегментом и только из фактов
        bold = [p[0] for p in it["parts"] if p[1]]
        assert bold and all(t.isdigit() for t in bold)
        assert {int(x) for x in re.findall(r"\d+", it["text"])} <= director._allowed_numbers(f)
    spoken = " ".join(s["text"] for s in d["sentences"])   # озвучка — тот же текст
    assert spoken.startswith(d["greeting"] + " За 7 дней:") and all(t in spoken for t in texts)


def test_ai_greeting_phrase_has_no_numbers(monkeypatch):
    f = director.facts()
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "director_greeting", lambda facts: "Спокойная неделя, но есть что решить.")
    assert director.ai_phrase(f) == "Спокойная неделя, но есть что решить."
    for bad in ("Ждут два решения.", "Пришло 12 обращений."):
        assert llm.NUMBER_WORDS.search(bad) or re.search(r"\d", bad)


def test_no_old_name_anywhere():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    for f in list((root / "web").rglob("*.js")) + list((root / "web").glob("*.html")) + list((root / "mf").rglob("*.py")):
        assert "Что изменили" not in f.read_text(encoding="utf-8"), f.name


# ---------- команда: «самая дальняя, которая 12 дней…» — это самое давнее на решении, а не рассылка (фраза владельца 13.11) ----------

OWNER_PHRASE = "самая дальняя, которая 12 дней…"


def _pending(c):
    return c.get("/api/director/ideas").json()["pending"]


def test_owner_phrase_opens_oldest_decision(c):
    login(c, 1)
    oldest = _pending(c)[0]
    assert oldest["number"] == "A-027" and int(oldest["wait_days"]) == 12
    r = c.post("/api/director/command/parse", json={"text": OWNER_PHRASE}).json()
    p = r["plan"]
    assert r["command"]["intent"] == "open_decision" and p["kind"] == "open" and p["item"]["number"] == "A-027"
    assert p["decision"]["appeal_id"] == oldest["appeal_id"] and "recipients" not in p   # никакой рассылки сотрудникам
    assert p["title"] == "A-027 — ждёт решения 12 дней"
    s = c.post(f"/api/director/command/{r['plan_id']}/send", json={}).json()
    assert s["ok"] and s["users"] == 0   # «открыть» ничего не отправляет
    b = c.post("/api/boss/ask", json={"text": OWNER_PHRASE}).json()   # то же в «Директоре в кармане»
    assert b["kind"] == "command" and b["plan"]["kind"] == "open" and b["plan"]["item"]["number"] == "A-027"


@pytest.mark.parametrize("text, number, kind", [
    ("самое давнее на решении", "A-027", "open"), ("открой самую старую", "A-027", "open"), ("первая, которая ждёт", "A-027", "open"),
    ("A-028", "A-028", "open"), ("а-28 на решении", "A-028", "open"), ("та, которая двенадцать дней", "A-027", "open"),
    ("та, которая 11 дней ждёт", "A-027", "clarify"), ("а та, что ждёт решения?", "A-027", "clarify"),
])
def test_decision_references(c, text, number, kind):
    login(c, 1)
    p = c.post("/api/director/command/parse", json={"text": text}).json()["plan"]
    assert p["kind"] == kind and p["item"]["number"] == number, (text, p.get("kind"), p.get("title"))
    if kind == "clarify":
        assert p["title"].startswith(f"Вы про {number} (ждёт решения") and p["title"].endswith("? Открыть?")


@pytest.mark.parametrize("text, intent", [
    ("Запроси новости по обращениям в работе в Омске до 18:00", "request_progress"),
    ("Напомни об обращениях без ответа дольше 3 дней", "remind_no_response"),
    ("Напомни про просроченные поручения", "remind_overdue_tasks"),
])
def test_other_commands_not_hijacked(c, text, intent):
    login(c, 1)
    r = c.post("/api/director/command/parse", json={"text": text}).json()
    assert r["command"]["intent"] == intent and r["plan"]["kind"] != "clarify"


# ---------- карта директора: справочник городов объектов, «без метки», ручная точка администратора (замечание 13.11) ----------

def _field_appeal(c, city, text):
    c.cookies.clear()
    r = c.post("/api/public/appeals", data={"type": "problem", "text": text, "branch_code": "FIELD", "site_city": city})
    assert r.status_code == 200, r.text


def _site(c, city):
    login(c, 1)
    m = c.get("/api/panel/map").json()
    return next((s for s in m["sites"] if s["city"] == city), None), m


def test_object_from_new_known_city_appears_on_map(c):
    _field_appeal(c, "г. Караганда, промплощадка", "На объекте в Караганде нет актуальной схемы щита, рисуем заново")
    s, m = _site(c, "Караганда")
    assert s and abs(s["lat"] - 49.80) < 0.1 and abs(s["lng"] - 73.11) < 0.1 and s["open"] >= 1
    assert all(u["city"] != "Караганда" for u in m["unplaced"])
    _field_appeal(c, "Өскемен", "Объект в Усть-Каменогорске: не пришла спецификация на кабель")   # казахское название
    s, _ = _site(c, "Усть-Каменогорск")
    assert s and abs(s["lat"] - 49.95) < 0.1


def test_unknown_city_unplaced_then_admin_point(c):
    _field_appeal(c, "Новоишимка", "На объекте в Новоишимке нет связи с офисом по заявкам")
    s, m = _site(c, "Новоишимка")
    assert s and "lat" not in s and any(u["city"] == "Новоишимка" for u in m["unplaced"])
    login(c, 15)
    assert any(u["city"] == "Новоишимка" for u in c.get("/api/admin/geo").json()["unplaced"])
    with TestClient(app) as outside:   # снаружи (как через туннель) демо-сессии ставить точки не могут
        assert outside.post("/api/auth/login-as", json={"user_id": 15}).status_code == 200
        assert outside.post("/api/admin/geo/points", json={"city": "Новоишимка", "lat": 53.2, "lng": 66.8}).status_code == 403
    assert c.post("/api/admin/geo/points", json={"city": "Новоишимка", "lat": 53.2, "lng": 66.8}).status_code == 200
    assert c.post("/api/admin/geo/points", json={"city": "Где-то", "lat": 10, "lng": 10}).status_code == 422   # вне KZ и RU
    s, m = _site(c, "Новоишимка")
    assert s["lat"] == 53.2 and s["lng"] == 66.8 and all(u["city"] != "Новоишимка" for u in m["unplaced"])
    login(c, 15)
    c.post("/api/admin/geo/points/remove", json={"city": "Новоишимка"})
    s, _ = _site(c, "Новоишимка")
    assert "lat" not in s


def test_director_map_two_colors_data(c):
    """Данные для двух цветов: у филиалов и объектов есть «просрочено»; зелёная — 0, красная — больше 0."""
    login(c, 1)
    m = c.get("/api/panel/map").json()
    assert all("overdue" in b and "open" in b for b in m["branches"]) and all("overdue" in s for s in m["sites"])
