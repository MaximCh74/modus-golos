"""Замечания владельца после теста с телефона (12.11): голос помощника, «Директор в кармане» — вопрос не превращается в команду,
ответы сходятся с плитками, ссылки открываются внутри /boss."""
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from mf import db
from mf.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    c.cookies.clear()
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")
def test_tts_speed_up_ten_percent(tmp_path):
    from mf.ai import llm
    src = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-b:a", "64k", str(src)], check=True)
    out = tmp_path / "b.mp3"
    out.write_bytes(llm.faster(src.read_bytes(), 1.1))
    dur = lambda p: float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)
    assert 4.4 < dur(out) < 4.7 and llm.TTS_SPEED == 1.1


MARK_QUESTION = "скажи, что у нас по задачам, кто просрачивает, кто просрочил и что конкретно по Павлодару происходит"


def test_owner_question_is_answered_not_turned_into_command(c):
    """Дословный вопрос владельца с телефона: ответ про просрочки (число как на плитке) и коротко по Павлодару, без экрана подтверждения."""
    login(c, 1)
    tile = c.get("/api/boss/home?period=week").json()["tiles"]["overdue"]
    r = c.post("/api/boss/ask", json={"text": MARK_QUESTION, "period": "week"}).json()
    assert r["kind"] == "question" and "plan_id" not in r and "plan" not in r, r
    assert [p["question"] for p in r["parts"]] == ["who_overdue", "city"] and r["parts"][1]["facts"]["city"] == "Павлодар"
    assert f"просрочено {tile}" in r["answer"] and "Павлодар" in r["answer"]
    assert r["answer"].index("просрочено") < r["answer"].index("Павлодар")   # по очереди, как спрошено
    assert "обращени" in r["parts"][0]["answer"] and r["parts"][0]["facts"]["total_overdue"] == tile
    lst = r["parts"][0]["list"]
    assert lst and len(lst["items"]) == min(tile, 30) and all({"number", "text", "status"} <= set(i) or i["kind"] == "task" for i in lst["items"])


@pytest.mark.parametrize("text,kind", [
    ("Кто просрочил?", "question"), ("Сколько обращений пришло за неделю?", "question"), ("Как дела в Омске?", "question"),
    ("Скажи, кто тянет с ответами", "question"), ("Что по напоминаниям?", "not_command"),
    ("Напомни про просроченные поручения", None), ("Попроси Олега сообщить о ходе работ", None), ("Пусть отчитаются по обращениям в работе", None),
    ("Отправь напоминание тем, кто не ответил", None),
])
def test_command_only_with_explicit_action_verb(c, text, kind):
    login(c, 1)
    r = c.post("/api/boss/ask", json={"text": text}).json()
    if kind == "not_command":
        assert r["kind"] in ("question", "unknown"), (text, r["kind"])
    elif kind:
        assert r["kind"] == kind, (text, r["kind"])
    else:
        assert r["kind"] in ("command", "answer"), (text, r["kind"])   # «answer» — если отправлять некому


def test_nobody_to_send_is_plain_answer_without_card(c):
    login(c, 1)
    db.ex("UPDATE meeting_items SET task_status='done' WHERE kind='task'")   # просроченных поручений нет
    r = c.post("/api/boss/ask", json={"text": "Напомни про просроченные поручения"}).json()
    assert r["kind"] == "answer" and "plan_id" not in r and "Некому" not in r["answer"] and r["answer"].startswith("Напоминать не о чем")
    # и в панели команд — тот же человеческий текст
    p = c.post("/api/director/command/parse", json={"text": "Напомни про просроченные поручения"}).json()["plan"]
    assert p["empty"] and p["title"].startswith("Напоминать не о чем")


def test_negation_check_is_per_sentence():
    from mf.ai import llm
    f = {"overdue_appeals": 7, "overdue_tasks": 0, "total_overdue": 7}
    assert llm.negates_nonzero("Просрочено 7 обращений. Просроченных поручений с совещаний нет.", f) is None
    assert llm.negates_nonzero("Просрочек нет.", f) == "просроч"
    assert llm.negates_nonzero("Просроченных обращений нет, поручения в срок.", f) == "просроч"
    assert llm.negates_nonzero("Просроченных поручений нет.", {"overdue_appeals": 0, "overdue_tasks": 2}) == "просроч"


def test_duplicate_parts_collapsed(c, monkeypatch):
    from mf.ai import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse_boss", lambda text, ctx: {"kind": "question", "question": "who_overdue", "city": None, "department": None, "number": None, "period": None,
                                                             "parts": [{"question": "who_overdue"}, {"question": "who_overdue"}, {"question": "city", "city": "Павлодар"}]})
    monkeypatch.setattr(llm, "boss_answer", lambda q, what, facts: (_ for _ in ()).throw(llm.LLMError("нет")))
    login(c, 1)
    r = c.post("/api/boss/ask", json={"text": MARK_QUESTION}).json()
    assert [p["question"] for p in r["parts"]] == ["who_overdue", "city"]


def test_llm_parts_normalized_city_not_glued_to_overdue(c, monkeypatch):
    """Живой прогон: модель вернула «кто просрочил» с городом и лишние «темы» — получалось «в Павлодаре просрочено 7» (по всей компании)."""
    from mf.ai import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse_boss", lambda text, ctx: {"kind": "question", "question": "who_overdue", "city": None, "department": None, "number": None, "period": None,
                                                             "parts": [{"question": "who_overdue"}, {"question": "who_overdue", "city": "Павлодар"}, {"question": "main_topics"}]})
    monkeypatch.setattr(llm, "boss_answer", lambda q, what, facts: (_ for _ in ()).throw(llm.LLMError("нет")))
    login(c, 1)
    r = c.post("/api/boss/ask", json={"text": MARK_QUESTION}).json()
    assert [(p["question"], p["facts"].get("city")) for p in r["parts"]] == [("who_overdue", None), ("city", "Павлодар")]
