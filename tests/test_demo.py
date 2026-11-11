"""Этап 5: демо-состояние одной командой — reset → прогон сценария DEMO.md через API → reset → прогон снова: результат одинаковый.
Без ключа (conftest) — заскриптованные разборы и словарь, как в запасном режиме на площадке."""
import pytest
from fastapi.testclient import TestClient

from mf import db, demo
from mf.main import app

pytestmark = pytest.mark.skipif(not demo.FIXTURE.is_file(), reason="нет снапшота demo/fixtures/mf-demo.db")

TRANSCRIPT = open("tests/test_stage2.py", encoding="utf-8").read().split('TRANSCRIPT = """')[1].split('"""')[0]


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def run_scenario(c) -> dict:
    """Шаги DEMO.md 1, 2, 3, 4 и петля статуса — через API. Возвращает факты, которые должны совпасть между прогонами."""
    out = {}
    pre = demo.is_demo_state()
    assert pre["ok"], pre["checks"]
    # 1. QR + «голос»: жюри без входа
    r = c.post("/api/public/appeals", data={"type": "problem", "text": "На складе сканер штрихкодов не читает этикетки номенклатуры из 1С, артикулы вбиваем вручную. Прошу заменить сканер.",
                                            "branch_code": "PVL", "author_urgency": "now", "input_mode": "voice"}).json()
    out["number"] = r["number"]; out["category"] = r["category"]; out["priority"] = r["priority"]; out["brief"] = r["brief"]["gist"]
    assert r["number"] == pre["next_number"]
    # 2. планёрка ведущего (текст — запасной ход), отправка
    login(c, 2)
    mid = c.post("/api/meetings", data={"title": "Планёрка на защите", "transcript": TRANSCRIPT}).json()["id"]
    m = c.get(f"/api/meetings/{mid}").json()
    assert m["status"] == "review"
    out["meeting_items"] = sorted(i["kind"] for i in m["items"])
    sent = c.post(f"/api/meetings/{mid}/send").json()
    out["sent"] = sent["sent"]
    # 3. «Сообщить о ходе» по обращению жюри + петля статуса на странице по ссылке
    login(c, 1)
    aid = r["id"]
    assert c.post(f"/api/panel/appeals/{aid}/status", json={"status": "review"}).status_code == 200
    p = c.post(f"/api/panel/appeals/{aid}/progress", json={"text": "Сканер заказан, поставка в среду"}).json()
    out["stage"] = p["stage"]["code"]
    t = c.get(f"/api/public/track/{r['tracking_token']}").json()
    out["track_stage"] = t["stage"]["label"]; out["track_events"] = [e["kind"] for e in t["events"]]
    # 4. сводка и «На решение»: принять старое предложение и идею с планёрки
    s = c.get("/api/panel/director-summary?refresh=1").json()
    out["summary_engine"] = s["engine"]; out["summary_lines"] = s["lines"]
    q = c.get("/api/director/ideas").json()
    out["pending_before"] = sorted(x.get("number") or x["text"][:20] for x in q["pending"])
    a27 = next(x for x in q["pending"] if x.get("number") == "A-027")
    assert c.post(f"/api/director/appeals/{a27['appeal_id']}/decide", json={"decision": "accepted", "comment": "Выделяем специалиста на две недели"}).status_code == 200
    idea = next(x for x in q["pending"] if x["source"] == "meeting")
    acc = c.post(f"/api/director/ideas/{idea['id']}/accept", json={}).json()
    out["idea_appeal_responsible"] = acc["appeal"]["responsible"]
    out["pending_after"] = len(c.get("/api/director/ideas").json()["pending"])
    # 5. спасибо и профиль
    login(c, 16)
    a8 = db.one("SELECT id FROM appeals WHERE number='A-008'")["id"]
    th = c.post(f"/api/appeals/{a8}/thank")
    out["thanks_status"] = th.status_code
    out["profile"] = {k: c.get("/api/users/6/profile").json()[k] for k in ("points", "thanks")}
    return out


def test_scenario_twice_identical(c):
    first = demo.reset()
    assert first["ok"] and first["appeals"] >= 29
    a = run_scenario(c)
    second = demo.reset()
    assert second["fingerprint"] == first["fingerprint"]
    b = run_scenario(c)
    assert a == b, {k: (a[k], b[k]) for k in a if a[k] != b.get(k)}
    assert a["category"] in ("Номенклатура и спецификации", "1С и автоматизация", "Интеграции и IT") and a["priority"] == "high"
    assert a["sent"] == {"tasks": 2, "ideas": 1, "linked": 2} and a["stage"] == "elaboration" and a["track_stage"] == "Проработка"
    assert "progress" in a["track_events"] and a["summary_engine"] == "template" and a["idea_appeal_responsible"] == "Айгерим Нурланова"
    assert a["pending_after"] == len(a["pending_before"]) - 2 and a["thanks_status"] in (200, 409)


def test_reset_shifts_dates_to_today(c):
    demo.reset()
    st = demo.is_demo_state()
    assert st["ok"], st["checks"]
    pend = db.q("SELECT number, director_requested_at FROM appeals WHERE director_decision='pending'")
    ages = {r["number"]: (db.now() - db.parse(r["director_requested_at"])).days for r in pend}
    assert ages["A-027"] == 12 and ages["A-028"] == 9   # возраст ожидания сохраняется на любую дату выступления
    newest = db.one("SELECT MAX(created_at) AS m FROM appeals")["m"]
    assert (db.now() - db.parse(newest)).days <= 1
