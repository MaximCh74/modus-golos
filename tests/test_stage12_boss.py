"""Пункт 2 очереди 12.11 — «Директор в кармане»: доступ только директору; главный экран (четыре цифры, списки, приветствие с проверкой
чисел); вопросы из белого списка — каждый тип, факты считает сервер; сверка чисел в ответе ИИ (лишнее число → шаблон); неизвестный
вопрос → «не знаю» со ссылками; команда → существующий план, ничего не отправляется без подтверждения; озвучка без ключа — 503."""
import pytest
from fastapi.testclient import TestClient

from mf import boss, db
from mf.ai import fallback, llm
from mf.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def test_pages_and_access(c):
    c.cookies.clear()
    r = c.get("/boss")
    assert r.status_code == 200 and "Директор в кармане" in r.text and "/manifest-boss.json" in r.text
    m = c.get("/manifest-boss.json").json()
    assert m["start_url"] == "/boss" and m["scope"] == "/boss" and m["name"].startswith("Модус Голос") and any("boss" in i["src"] for i in m["icons"])
    for src in {i["src"] for i in m["icons"]}:
        assert c.get(src).status_code == 200
    assert c.get("/api/boss/home").status_code == 401
    for uid in (2, 15, 16):   # ответственный, администратор, сотрудник — не директор
        login(c, uid)
        assert c.get("/api/boss/home").status_code == 403
        assert c.post("/api/boss/ask", json={"text": "что нового"}).status_code == 403


def test_home_tiles_lists_and_greeting(c):
    login(c, 1)
    h = c.get("/api/boss/home?period=week").json()
    assert h["period"] == "week" and h["name"] == "Сергей Михайлович"
    t = h["tiles"]
    assert set(t) == {"new", "done", "decisions", "overdue"} and t["decisions"] == 2 and t["new"] >= 1 and t["overdue"] >= 1
    assert len(h["lists"]["decisions"]) == 2 and {x["number"] for x in h["lists"]["decisions"]} == {"A-027", "A-028"}
    assert all({"id", "number", "text", "status"} <= set(x) for x in h["lists"]["new"])
    assert any(x["kind"] == "appeal" and x["overdue"] for x in h["lists"]["overdue"])
    g = h["greeting"]
    # приветствие списком из чисел сервера, как сводка в панели (замечание 13.11): «поступило/решено» — за период, как на плитках
    assert g["engine"] == "template" and g["greeting"].endswith(", Сергей Михайлович.") and g["period"] == "За неделю:"
    items = {it["key"]: it["text"] for it in g["items"]}
    assert items["new"] == f"Поступило: {t['new']}" and items["done"] == f"Решено: {t['done']}" and items["decisions"].startswith("Ждут вашего решения: 2")
    assert g["text"] == " ".join([g["greeting"], g["period"]] + [it["text"] + "." for it in g["items"]])   # озвучка — тот же текст
    today = c.get("/api/boss/home?period=today").json()
    assert today["tiles"]["new"] <= t["new"] and today["tiles"]["decisions"] == 2 and today["greeting"]["period"] == "Сегодня:"
    assert c.get("/api/boss/home?period=nonsense").json()["period"] == "week"


@pytest.mark.parametrize("text,q,must", [
    ("Что нового за неделю?", "whats_new", ("пришло", "решено")),
    ("Что ждёт моего решения?", "my_decisions", ("A-027", "A-028")),
    ("Кто просрочил?", "who_overdue", ("просрочено", "—")),
    ("Какие главные темы?", "main_topics", ("открытых",)),
    ("Что по Омску?", "city", ("Омск: открыто",)),
    ("Что по обращению A-027?", "appeal", ("A-027", "регламент")),
    ("что по а 7", "appeal", ("A-007",)),
    ("Как дела у продаж?", "department", ("Продажи: открыто",)),
])
def test_each_question_type_without_key(c, text, q, must):
    login(c, 1)
    r = c.post("/api/boss/ask", json={"text": text, "period": "week"}).json()
    assert r["kind"] == "question" and r["question"] == q and r["engine"] == "template", r
    for m in must:
        assert m in r["answer"], (m, r["answer"])
    assert r["link"] and r["link"].startswith("/") and r["facts"]
    # ссылка «подробнее на сайте» ведёт на существующую страницу
    assert c.get(r["link"].split("#")[0]).status_code == 200


def test_facts_are_server_numbers(c):
    login(c, 1)
    r = c.post("/api/boss/ask", json={"text": "кто просрочил", "period": "week"}).json()
    f = r["facts"]
    over = db.q("SELECT id FROM appeals WHERE first_response_at IS NULL AND status IN ('new','review','clarify','in_progress')")
    assert f["overdue_appeals"] <= len(over) and f["overdue_appeals"] == sum(x["count"] for x in f["by_responsible"]) or f["overdue_appeals"] > 5
    r = c.post("/api/boss/ask", json={"text": "что по обращению A-027"}).json()
    assert r["facts"]["responsible"] == "Гульнара Сейтжанова" and r["facts"]["stage"] == "Принятие решения" and r["facts"]["age_days"] >= 12


def test_ai_answer_numbers_are_checked(c, monkeypatch):
    """ИИ придумал число → ответ отбрасывается, идёт шаблон; ИИ со всеми числами из фактов → принимается; запрещённый синоним → шаблон."""
    login(c, 1)
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse_boss", lambda text, ctx: fallback.parse_boss(text, ctx))
    monkeypatch.setattr(llm, "boss_answer", lambda question, what, facts: "Вашего решения ждут 99 предложений.")
    r = c.post("/api/boss/ask", json={"text": "что ждёт моего решения"}).json()
    assert r["engine"] == "template" and "99" not in r["answer"] and "A-027" in r["answer"]
    monkeypatch.setattr(llm, "boss_answer", lambda question, what, facts: f"Вашего решения ждут {facts['count']} предложения, оба дольше {facts['threshold_days']} дней.")
    r = c.post("/api/boss/ask", json={"text": "что ждёт моего решения"}).json()
    assert r["engine"] == "openai" and r["answer"].startswith("Вашего решения ждут 2 предложения")
    monkeypatch.setattr(llm, "boss_answer", lambda question, what, facts: "У вас 2 срочных тикета.")
    r = c.post("/api/boss/ask", json={"text": "что ждёт моего решения"}).json()
    assert r["engine"] == "template"
    # приветствие: ИИ — только фраза без чисел (замечание 13.11); фраза с числами отбрасывается, числа — только из списка сервера
    monkeypatch.setattr(llm, "director_greeting", lambda facts: (_ for _ in ()).throw(llm.LLMError("в фразе есть числа")))
    db.ex("DELETE FROM settings WHERE key LIKE 'boss_greeting:%'")
    g = c.get("/api/boss/home?period=week").json()["greeting"]
    assert g["engine"] == "template" and "500" not in g["text"]
    monkeypatch.setattr(llm, "director_greeting", lambda facts: "Есть что решить по обращениям.")
    db.ex("DELETE FROM settings WHERE key LIKE 'boss_greeting:%'")
    g = c.get("/api/boss/home?period=week").json()["greeting"]
    assert g["engine"] == "openai" and g["greeting"].startswith("Добр") and g["greeting"].endswith("Есть что решить по обращениям.")


def test_unknown_question_and_unknown_city(c):
    login(c, 1)
    r = c.post("/api/boss/ask", json={"text": "Закажи пиццу в офис"}).json()
    assert r["kind"] == "unknown" and r["answer"].startswith("Не знаю") and len(r["links"]) >= 3 and all(l["href"].startswith("/panel") for l in r["links"]) and r["can"]
    r = c.post("/api/boss/ask", json={"text": "что по Караганде, как там дела в городе"}).json()
    assert r["kind"] == "question" and r["question"] == "city" and r["answer"].startswith("Не понял, какой город") and "Омск" in r["answer"]
    r = c.post("/api/boss/ask", json={"text": "что по обращению A-999"}).json()
    assert r["question"] == "appeal" and "не нашёл" in r["answer"]
    assert c.post("/api/boss/ask", json={"text": " "}).status_code == 422


def test_command_goes_through_plan_with_confirmation(c):
    login(c, 1)
    before = db.one("SELECT COUNT(*) AS n FROM notifications")["n"]
    r = c.post("/api/boss/ask", json={"text": "Запроси новости по обращениям в работе в Омске до 18:00"}).json()
    assert r["kind"] == "command" and r["plan_id"] and r["plan"]["kind"] == "send" and r["command"]["intent"] == "request_progress" and r["needs_confirmation"]
    assert db.one("SELECT COUNT(*) AS n FROM notifications")["n"] == before   # ничего не отправлено
    s = c.post(f"/api/director/command/{r['plan_id']}/send", json={}).json()
    assert s["ok"] and s["users"] >= 1 and db.one("SELECT COUNT(*) AS n FROM notifications")["n"] > before
    r = c.post("/api/boss/ask", json={"text": "Прочитай сводку"}).json()
    assert r["kind"] == "command" and r["plan"]["kind"] == "briefing" and not r["needs_confirmation"]


def test_audio_without_key_and_answer_ownership(c):
    login(c, 1)
    r = c.post("/api/boss/ask", json={"text": "что нового"}).json()
    assert r["audio"] is False
    assert c.get(f"/api/boss/answer/{r['id']}/audio").status_code == 503
    assert boss.period_since("today") > boss.period_since("week")
