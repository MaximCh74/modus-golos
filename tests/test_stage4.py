"""Этап 4 (без ключа): оценка автора и матрица приоритета, подъём по поддержкам, «Коротко», стадии автора, «Сообщить о ходе»
и напоминание «автор ждёт новостей», «спасибо», профиль, сводка-шаблон директора, лига, карта, награды, настройки."""
import pytest
from fastapi.testclient import TestClient

from mf import appeals, db, director
from mf.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def notes(c):
    return [n["text"] for n in c.get("/api/notifications").json()["items"]]


def nid(number):
    return db.one("SELECT id FROM appeals WHERE number=?", (number,))["id"]


def test_matrix_priority():
    assert appeals.matrix_priority("problem", "now", "department") == "high"
    assert appeals.matrix_priority("problem", "now", None) == "high"          # проблема: масштаб по умолчанию — отдел
    assert appeals.matrix_priority("suggestion", None, "company") == "high"   # идея: срочность по умолчанию — обхожусь
    assert appeals.matrix_priority("problem", "minor", "me") == "low"
    assert appeals.matrix_priority("problem", "workaround", "me") == "low"
    assert appeals.matrix_priority("problem", None, None) is None


def test_author_answer_and_brief_in_qr(c):
    r = c.post("/api/public/appeals", data={"type": "problem", "text": "Сканер штрихкодов на складе не читает коды, вбиваем артикулы вручную. Прошу заменить сканер.",
                                            "branch_code": "PVL", "author_urgency": "now", "input_mode": "voice"}).json()
    assert r["priority"] == "high" and r["brief"]["gist"].startswith("Сканер штрихкодов") and r["brief"]["note"]
    login(c, 1)
    a = c.get(f"/api/appeals/{r['id']}").json()
    assert a["author_urgency_label"] == "Прямо сейчас мешает" and a["priority"] == "high" and a["input_mode"] == "voice"
    assert a["stage"]["code"] == "accepted" and [s["state"] for s in a["stage"]["steps"]] == ["cur", "future", "future", "future", "future"]
    q = c.get("/api/panel/appeals", params={"urgency": "now", "sort": "priority"}).json()
    assert q and q[0]["priority"] == "high" and all(x["author_urgency"] == "now" for x in q)
    assert next(x for x in q if x["id"] == r["id"])["brief_line"].startswith("Сканер штрихкодов")


def test_supports_bump_priority(c):
    login(c, 6)
    a = c.post("/api/appeals", data={"type": "problem", "text": "Лифт на складе не работает вторую неделю", "category_id": "16", "author_urgency": "minor", "author_scope": "me"}).json()
    assert a["priority"] == "low"
    for uid in (16, 17, 18):
        login(c, uid)
        assert c.post(f"/api/appeals/{a['id']}/support").status_code == 200
    login(c, 6)
    a2 = c.get(f"/api/appeals/{a['id']}").json()
    assert a2["priority"] == "medium" and any(e["kind"] == "priority_changed" and e["payload"]["reason"] == "supports" for e in a2["events"])
    login(c, 11)   # ответственный меняет вручную — событие, дальше поддержки не поднимают
    r = c.post(f"/api/panel/appeals/{a['id']}/priority", json={"priority": "high"}).json()
    assert r["priority"] == "high" and r["priority_manual"] == 1


def test_stages_progress_news_and_thanks(c):
    login(c, 6)
    a = c.post("/api/appeals", data={"type": "suggestion", "text": "Предлагаю повесить расписание уборки на кухне", "category_id": "16", "author_scope": "department"}).json()
    aid = a["id"]
    login(c, 25)   # отдел развития ведёт
    assert c.post(f"/api/panel/appeals/{aid}/status", json={"status": "review"}).status_code == 200
    assert c.post(f"/api/panel/appeals/{aid}/progress", json={"text": " "}).status_code == 422
    r = c.post(f"/api/panel/appeals/{aid}/progress", json={"text": "Согласовали с админами, вешаем на следующей неделе"}).json()
    assert r["stage"]["code"] == "elaboration" and r["news_days"] is not None and r["news_days"] < 1
    login(c, 6)
    assert any("как идут дела" in n for n in notes(c))
    card = c.get(f"/api/appeals/{aid}").json()
    assert any(e["kind"] == "progress" for e in card["events"])
    login(c, 25)
    assert c.post(f"/api/panel/appeals/{aid}/status", json={"status": "in_progress"}).status_code == 200
    s = c.get(f"/api/appeals/{aid}").json()["stage"]
    assert s["code"] == "implementation" and s["steps"][2]["state"] == "skip"   # в работу без директора — стадия «решение» пройдена автоматически
    # напоминание «автор ждёт новостей»: искусственно состарим последнюю новость
    db.ex("UPDATE appeals SET last_news_at='2026-10-01T00:00:00Z' WHERE id=?", (aid,))
    login(c, 1)
    assert c.post("/api/panel/check-news").json()["reminded"] >= 1
    login(c, 25)
    assert any(f"Автор ждёт новостей по {a['number']}" in n for n in notes(c))
    assert appeals.no_news_count() >= 1
    r = c.post(f"/api/panel/appeals/{aid}/status", json={"status": "done", "text": "Расписание повешено"}).json()
    assert r["stage"]["code"] == "done" and r["stage"]["steps"][4]["state"] == "cur"
    login(c, 16)
    assert c.post(f"/api/appeals/{aid}/thank").json()["thanks"] == 1
    assert c.post(f"/api/appeals/{aid}/thank").status_code == 409
    login(c, 6)
    assert c.post(f"/api/appeals/{aid}/thank").status_code == 409   # своё
    assert any("говорит спасибо" in n for n in notes(c))
    pts = c.get("/api/me/points").json()["ledger"]
    assert not any("thank" in (l["reason"] or "") for l in pts)   # баллов за спасибо нет
    ch = next(x for x in c.get("/api/changes").json() if x["id"] == aid)
    assert ch["thanks"] == 1 and ch["author"]["name"] == "Сауле Абишева"
    prof = c.get("/api/users/6/profile").json()
    assert prof["thanks"] >= 1 and any(i["id"] == aid for i in prof["implemented"]) and prof["points"] > 0


def test_rejected_stage(c):
    s = appeals.stage_for({"status": "rejected", "director_decision": None})
    assert s["code"] == "rejected" and s["steps"][4]["label"] == "Не принято"
    s = appeals.stage_for({"status": "review", "director_decision": "pending"})
    assert s["code"] == "decision" and s["note"] == "ждёт решения директора"


def test_director_summary_template_and_lines(c):
    login(c, 1)
    d = c.get("/api/panel/director-summary").json()
    assert d["engine"] == "template" and d["sentences"][0]["text"].endswith(", Сергей Михайлович.")
    f = d["facts"]
    assert f["period_days"] == 7 and f["decisions_pending"] >= 2 and f["decision_max_days"] >= 12
    assert any("решения" in s["text"] and s["href"] == "/panel#/decisions" for s in d["sentences"])
    assert d["lines"]["decisions_over_threshold"] >= 2 and "urgent_open" in d["lines"]
    d2 = c.get("/api/panel/director-summary").json()
    assert d2["at"] == d["at"]   # кэш
    assert c.get("/api/panel/director-summary", params={"refresh": 1}).json()["at"] >= d["at"]
    assert director._numbers("За 7 дней пришло 14 обращений, решено 9.") == {7, 14, 9}


def test_league_map_rewards_settings(c):
    login(c, 1)
    lg = c.get("/api/panel/league").json()
    assert lg["items"][0]["rank"] == 1 and {x["code"] for x in lg["items"]} == {"OMSK", "SAM", "TMN", "AST", "PVL"}
    assert lg["top"] and lg["top"][0]["points"] >= lg["top"][-1]["points"]
    m = c.get("/api/panel/map").json()
    assert len(m["branches"]) == 5 and all(b["lat"] for b in m["branches"])
    site = next(s for s in m["sites"] if s["city"] == "Атырау")
    assert site["lat"] and "A-025" in site["numbers"]
    login(c, 6)
    rw = c.get("/api/rewards").json()
    assert rw["items"][0]["title"] == "Премия за внедрённую идею"
    cheap = min(rw["items"], key=lambda r: r["cost_points"])
    before = rw["balance"]
    r = c.post(f"/api/rewards/{cheap['id']}/claim")
    assert r.status_code in (200, 409)
    if r.status_code == 200:
        login(c, 15)
        claims = c.get("/api/admin/reward-claims").json()
        cl = next(x for x in claims if x["id"] == r.json()["id"])
        assert c.post(f"/api/admin/reward-claims/{cl['id']}/decide", json={"decision": "approved"}).status_code == 200
        login(c, 6)
        assert c.get("/api/rewards").json()["balance"] == before - cheap["cost_points"]
    login(c, 15)
    st = c.get("/api/admin/settings").json()
    assert st["settings"]["director_wait_days"] == 7 and len(st["categories"]) == 19
    assert c.post("/api/admin/settings", json={"settings": {"news_days": 10, "bogus": 1}}).json()["settings"]["news_days"] == 10
    assert appeals.news_days_setting() == 10
    r = c.post("/api/admin/categories/17", json={"responsible_user_id": 11, "sla": 36}).json()
    assert r["responsible_user_id"] == 11 and r["sla"] == 36
    login(c, 6)
    assert c.get("/api/admin/settings").status_code == 403


def test_rebrief_without_key(c):
    login(c, 7)
    aid = nid("A-005")
    r = c.post(f"/api/panel/appeals/{aid}/rebrief").json()
    assert r["brief"]["gist"] and r["brief_engine"] == "keywords" and any(e["kind"] == "rebriefed" for e in r["events"])


def test_summary_audio_without_key(c):
    login(c, 1)
    r = c.get("/api/panel/director-summary/audio")
    assert r.status_code == 503 and "голос браузера" in r.json()["detail"]
