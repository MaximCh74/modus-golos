"""Этап 2: ИИ-категория QR-формы (словарь без ключа), режим совещания на текстовой расшифровке §10 запасным разбором,
отправка → поручения, идеи директору, события discussed_at_meeting; «На решение» → принять → обращение у ответственного."""
import os
import time

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mf import db  # noqa: E402
from mf.ai import fallback, names  # noqa: E402
from mf.main import app  # noqa: E402

TRANSCRIPT = """Олег: Коллеги, коротко. Бухгалтерия снова пишет про повторный ввод — одни и те же данные вбивают в две системы.
Ерлан: Могу собрать список таких операций и оценить, что можно синхронизировать.
Олег: Давай, Ерлан, до пятницы собери и покажи.
Айгерим: И ещё: итоговые решения по задачам у нас разбросаны по чатам, потом не найти.
Олег: Решили: итоги фиксируем в одном месте — в системе. Айгерим, подготовь короткое правило для своего отдела.
Айгерим: И идея: сделать шаблон коммерческого предложения с обязательными полями, чтобы не переделывать по три раза.
Олег: Хорошая идея, отправим директору. Всё, спасибо."""


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


def notes(c):
    return [n["text"] for n in c.get("/api/notifications").json()["items"]]


def wait_meeting(c, mid, timeout=30):
    for _ in range(int(timeout * 4)):
        m = c.get(f"/api/meetings/{mid}").json()
        if m["status"] != "processing":
            return m
        time.sleep(0.25)
    raise AssertionError("совещание не обработано за отведённое время")


# ---------- ИИ-категория QR-формы ----------

def test_qr_ai_category_routes_to_responsible(c):
    r = c.post("/api/public/appeals", data={"type": "problem", "text": "Приходится вбивать одно и то же в две системы", "branch_code": "PVL"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["category"] == "Интеграции и IT" and j["responsible"] == "Ерлан Жумабеков" and j["ai_engine"] == "keywords"
    t = c.get(f"/api/public/track/{j['tracking_token']}").json()
    assert t["responsible"] == "Ерлан Жумабеков" and t["unassigned"] is False
    login(c, 3)   # Ерлан получил уведомление и видит событие ai_classified в истории
    assert any(j["number"] in n for n in notes(c))
    kinds = [e["kind"] for e in c.get(f"/api/appeals/{j['id']}").json()["events"]]
    assert kinds[:3] == ["created", "ai_classified", "assigned"]


def test_qr_unsure_stays_unassigned(c):
    r = c.post("/api/public/appeals", data={"type": "problem", "text": "Всё плохо, помогите разобраться", "branch_code": "AST"}).json()
    assert r["category"] is None and r["responsible"] is None
    r = c.post("/api/public/appeals", data={"type": "problem", "text": "В общих папках не найти актуальную редакцию инструкции", "branch_code": "AST"}).json()
    assert r["category"] == "Хранение документов" and r["responsible"] is None   # реальная вакансия (A-019)
    r = c.post("/api/public/appeals", data={"type": "suggestion", "text": "Навести порядок в общих папках: правила именования и архив старых версий", "branch_code": "AST"}).json()
    assert r["category"] == "Хранение документов" and r["responsible"] == "Гульнара Сейтжанова"   # предложение → отдел развития (ТЗ v2)


def test_keyword_dictionary_against_dataset():
    from mf.seed import APPEALS, CATEGORIES
    cats = [{"id": x[0], "name": x[1]} for x in CATEGORIES]
    wrong = [a[0] for a in APPEALS if (fallback.classify(a[7] + " " + (a[8] or ""), cats)["category_id"] or a[2]) != a[2]]
    hit = sum(1 for a in APPEALS if fallback.classify(a[7] + " " + (a[8] or ""), cats)["category_id"] == a[2])
    assert wrong == [] and hit >= 16   # словарь либо угадывает, либо честно молчит


def test_app_form_without_category_gets_ai_category(c):
    login(c, 6)
    a = c.post("/api/appeals", data={"type": "problem", "text": "Принтер в бухгалтерии не печатает, в 1С не выгрузить акты", "category_id": ""}).json()
    assert a["category"] == "1С и автоматизация" and a["responsible_id"] == 26   # по кастдеву: 1С — отдельная категория


# ---------- нечёткие имена ----------

def test_fuzzy_names():
    users = db.q("SELECT id, name FROM users")
    assert names.match("Ерлану", users)["user"]["id"] == 3
    assert names.match("Айгерин", users)["user"]["id"] == 4          # искажение STT
    assert names.match("Жумабеков", users)["user"]["id"] == 3
    assert names.match("кто-то из IT", users)["user"] is None
    assert names.match("", users)["user"] is None


# ---------- режим совещания ----------

def test_meeting_text_transcript_fallback_and_send(c):
    aid7, aid12 = number_id("A-007"), number_id("A-012")
    login(c, 6)                                     # Сауле поддерживает A-007 (в seed поддержки нет — создаём в тесте)
    assert c.post(f"/api/appeals/{aid7}/support").status_code == 200
    assert c.post("/api/meetings", data={"title": "x", "transcript": TRANSCRIPT}).status_code == 403   # сотрудник не ведёт планёрки

    login(c, 2)                                     # Олег ведёт планёрку
    r = c.post("/api/meetings", data={"title": "Планёрка по повторному вводу", "transcript": TRANSCRIPT})
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    m = wait_meeting(c, mid)
    assert m["status"] == "review" and m["fallback"] is True and m["demo"] is True   # без ключа — честно помечено
    items = {i["kind"]: [x for x in m["items"] if x["kind"] == i["kind"]] for i in m["items"]}
    tasks = items["task"]
    erlan = next(t for t in tasks if t["assignee_id"] == 3)
    assert erlan["due_date"] and "no_due" not in erlan["flags"]
    aigerim = next(t for t in tasks if t["assignee_id"] == 4)
    assert aigerim["due_date"] is None and "no_due" in aigerim["flags"]
    assert any(i["linked_appeal_id"] == aid7 for i in items["linked"]) and any(i["linked_appeal_id"] == aid12 for i in items["linked"])
    idea = items["idea"][0]
    assert idea["category"] == "Задачи и коммуникации" and idea["director_decision"] is None
    assert len(items["decision"]) == 1 and m["summary"]

    # правка: Айгерим ставим срок — флаг снимается; пустой текст — 422; убрать решение
    r = c.post(f"/api/meetings/{mid}/items/{aigerim['id']}", json={"due_date": "2026-11-20"})
    assert r.status_code == 200 and "no_due" not in next(i for i in r.json()["items"] if i["id"] == aigerim["id"])["flags"]
    assert c.post(f"/api/meetings/{mid}/items/{aigerim['id']}", json={"text": "  "}).status_code == 422
    assert c.post(f"/api/meetings/{mid}/items/{items['decision'][0]['id']}", json={"removed": True}).status_code == 200
    login(c, 13)                                    # чужой ответственный не видит совещание
    assert c.get(f"/api/meetings/{mid}").status_code == 403

    login(c, 2)
    r = c.post(f"/api/meetings/{mid}/send")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent" and r.json()["sent"] == {"tasks": 2, "ideas": 1, "linked": 2}
    assert c.post(f"/api/meetings/{mid}/send").status_code == 409   # повторно нельзя

    # петля закрыта (ТЗ §11 п. 7)
    for uid in (19, 6):                             # Павел — автор A-007, Сауле — поддержала
        login(c, uid)
        card = c.get(f"/api/appeals/{aid7}").json()
        assert any(e["kind"] == "discussed_at_meeting" and "Ерлан" in e["payload"]["text"] for e in card["events"])
        assert any("A-007 обсудили на совещании" in n for n in notes(c))
    login(c, 21)                                    # Максим — автор A-012
    assert any("A-012 обсудили на совещании" in n for n in notes(c))
    login(c, 3)                                     # Ерлан — поручение со сроком
    tasks = c.get("/api/tasks/mine").json()
    assert len(tasks) == 1 and tasks[0]["due_date"] and tasks[0]["task_status"] == "assigned"
    assert any("Поручение с совещания" in n and "срок 2026" in n for n in notes(c))
    assert c.post(f"/api/tasks/{tasks[0]['id']}/status", json={"status": "done"}).status_code == 200
    login(c, 4)                                     # Айгерим — поручение (срок поставлен при проверке)
    t = c.get("/api/tasks/mine").json()
    assert len(t) == 1 and t[0]["due_date"] == "2026-11-20"
    login(c, 2)                                     # Олегу пришло «поручение выполнено»
    assert any("Поручение выполнено" in n for n in notes(c))
    lst = c.get("/api/meetings").json()
    row = next(x for x in lst if x["id"] == mid)
    assert row["counts"]["tasks"] == 2 and row["counts"]["tasks_done"] == 1 and row["counts"]["ideas_pending"] == 1 and row["fallback"] is True


def test_director_ideas_accept_and_reject(c):
    login(c, 1)                                     # Виктор — директор
    assert any("На решение" in n for n in notes(c))
    ideas = c.get("/api/director/ideas").json()
    meeting_ideas = [x for x in ideas["pending"] if x["source"] == "meeting"]   # в очереди ещё предложения из обращений (seed, ТЗ v2)
    assert len(meeting_ideas) == 1
    idea = meeting_ideas[0]
    assert "шаблон" in idea["text"].lower() and idea["category_responsible"] == "Айгерим Нурланова"
    assert c.post(f"/api/director/ideas/{idea['id']}/reject", json={"reason": " "}).status_code == 422   # причина обязательна
    r = c.post(f"/api/director/ideas/{idea['id']}/accept", json={})
    assert r.status_code == 200, r.text
    a = r.json()["appeal"]
    assert a["type"] == "suggestion" and a["source"] == "meeting" and a["responsible_id"] == 4 and a["category"] == "Задачи и коммуникации"
    assert a["author"]["id"] == 4                   # озвучила Айгерим — она автор и получит баллы
    assert c.post(f"/api/director/ideas/{idea['id']}/accept", json={}).status_code == 409
    assert [x for x in c.get("/api/director/ideas").json()["pending"] if x["source"] == "meeting"] == []
    login(c, 4)                                     # Айгерим: новое обращение назначено ей по категории
    assert any(a["number"] in n for n in notes(c))
    login(c, 6)
    assert c.get("/api/director/ideas").status_code == 403

    # отклонение с причиной — второе совещание с идеей
    login(c, 2)
    mid = c.post("/api/meetings", data={"title": "Короткая", "transcript": "Олег: Есть идея: предлагаю ввести дежурного по чатам.\nОлег: Решили подумать."}).json()["id"]
    m = wait_meeting(c, mid)
    assert m["status"] == "review" and m["demo"] is False and m["fallback"] is True
    assert c.post(f"/api/meetings/{mid}/send").status_code == 200
    login(c, 1)
    pending = [x for x in c.get("/api/director/ideas").json()["pending"] if x["source"] == "meeting"]
    assert len(pending) == 1
    r = c.post(f"/api/director/ideas/{pending[0]['id']}/reject", json={"reason": "Дежурный не решит проблему разрозненных чатов"})
    assert r.status_code == 200 and r.json()["decision"] == "rejected"
    login(c, 2)
    assert any("отклонил идею" in n for n in notes(c))


def test_meeting_without_audio_and_text_fails(c):
    login(c, 2)
    assert c.post("/api/meetings", data={"title": "x", "transcript": "мало"}).status_code == 422
    s = c.get("/api/ai/status").json()
    assert s["llm"] is False and s["fallback"] is True and s["classifier"] == "keywords"
