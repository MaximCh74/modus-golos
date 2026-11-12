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
    with TestClient(app) as client:
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
        bold = [t for t, b in it["parts"] if b]
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
