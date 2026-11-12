"""Пункт 1 очереди 12.11: единый словарь терминов (mf/glossary.py) — подсказки «?», страница «Справка» и промпты ИИ берут тексты
из одного источника; у сотрудника в приложении «Мои поручения» со счётчиком невыполненных (/api/me: tasks_open, tasks_overdue)."""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from mf import db, glossary
from mf.ai import llm
from mf.main import app

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANSCRIPT = open(ROOT / "tests" / "test_stage2.py", encoding="utf-8").read().split('TRANSCRIPT = """')[1].split('"""')[0]


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def test_glossary_public_api_without_login(c):
    c.cookies.clear()
    g = c.get("/api/public/glossary").json()
    codes = [s["code"] for s in g["sections"]]
    for must in ("appeals", "roles", "deadlines", "meetings", "points", "league", "bitrix"):   # разделы из ТЗ Марка
        assert must in codes
    assert len(g["terms"]) >= 60
    seen = set()
    for s in g["sections"]:
        assert s["title"] and s["terms"], s
        for k in s["terms"]:
            t = g["terms"][k]
            assert t["section"] == s["code"] and t["label"] and 20 <= len(t["hint"]) <= 240, (k, t)
            seen.add(k)
    assert seen == set(g["terms"])   # каждый термин ровно в одном разделе
    assert glossary.validate() == []   # без жаргона: SLA, кластер, тикет
    for key in ("first_response", "similar", "attention", "brief", "my_tasks", "urgent_now", "decision"):
        assert key in g["terms"]
    assert "SLA" in g["terms"]["first_response"]["also"] and "кластер" in g["terms"]["similar"]["also"]   # жаргон — только как «иначе говорят»


def test_prompt_glossary_built_from_same_terms():
    text = glossary.prompt_text()
    assert llm.GLOSSARY == text and text.startswith("Термины системы — используй только их:")
    for must in ("«мешают работать сейчас» (не «срочные», не «критичные»)", "«На решение»", "«Коротко»", "«обращение» (не «заявка», не «тикет»)",
                 "«поручение» (не «задача»)", "«У меня так же»", "«Проработка»", "«Принятие решения»", "«Реализация»"):
        assert must in text, must
    assert set(llm.FORBIDDEN) >= {"срочн", "критичн", "заявк", "тикет", "задач", "кластер"}
    assert llm.has_forbidden("В очереди три срочных тикета") in ("срочн", "тикет") and llm.has_forbidden("Пришло 12 обращений") is None
    # у каждого термина с ai-формой подсказка и промпт — об одном и том же понятии
    for t in glossary.TERMS.values():
        if t.get("ai") and t["ai"] is not True:
            assert t["label"].lower()[:5] in t["ai"].lower() or t["label"][:4] in t["ai"], t


def test_frontend_help_keys_exist_in_glossary():
    """Каждый helpBtn('ключ') во фронте ссылается на термин словаря; «?» стоит у метрик, «Требуют внимания», настроек и непонятных полей."""
    used = {}
    for f in (ROOT / "web" / "a").glob("*.js"):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"helpBtn\('([a-z_]+)'", src):
            used.setdefault(m.group(1), set()).add(f.name)
        for m in re.finditer(r"'(set_[a-z_]+|similar_threshold|cluster_threshold)'\)", src):   # ключи настроек через num(..., help)
            used.setdefault(m.group(1), set()).add(f.name)
    missing = sorted(k for k in used if k not in glossary.TERMS)
    assert not missing, missing
    for must in ("kpi_open", "kpi_considered", "kpi_first_response", "kpi_done_period", "attention", "set_news_days", "set_director_wait_days",
                 "set_points_accepted", "set_league_done", "first_response", "brief", "priority", "author_assessment", "league", "my_tasks", "decision", "command"):
        assert must in used, must
    js = (ROOT / "web" / "a").glob("*.js")
    code = "\n".join(line.split("//")[0] for f in js for line in f.read_text(encoding="utf-8").splitlines())
    assert "SLA" not in code   # в интерфейсе — «срок первого ответа»


def test_my_tasks_counter_in_me(c):
    login(c, 2)   # Олег записывает планёрку: без ключа — демо-разбор, поручения Ерлану (id 3) и Айгерим (id 4)
    mid = c.post("/api/meetings", data={"title": "Планёрка", "transcript": TRANSCRIPT}).json()["id"]
    m = c.get(f"/api/meetings/{mid}").json()
    tasks = [i for i in m["items"] if i["kind"] == "task"]
    erlan = next(i for i in tasks if i["assignee_id"] == 3)
    aigerim = next(i for i in tasks if i["assignee_id"] == 4)
    c.post(f"/api/meetings/{mid}/items/{aigerim['id']}", json={"due_date": "2026-01-10"})   # срок давно прошёл → просрочено после отправки
    login(c, 3)
    assert c.get("/api/me").json()["tasks_open"] == 0   # до отправки совещания поручений нет
    login(c, 2)
    assert c.post(f"/api/meetings/{mid}/send").status_code == 200
    login(c, 3)
    me = c.get("/api/me").json()
    assert me["tasks_open"] == 1 and me["tasks_overdue"] == 0
    login(c, 4)
    me = c.get("/api/me").json()
    assert me["tasks_open"] == 1 and me["tasks_overdue"] == 1
    assert c.post(f"/api/tasks/{aigerim['id']}/status", json={"status": "done"}).status_code == 200
    me = c.get("/api/me").json()
    assert me["tasks_open"] == 0 and me["tasks_overdue"] == 0
    assert db.one("SELECT task_status FROM meeting_items WHERE id=?", (aigerim["id"],))["task_status"] == "done"
