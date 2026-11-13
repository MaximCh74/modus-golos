"""Площадка хакатона (замечание владельца 13.11): телефоны жюри в одном Wi-Fi — для сервера один адрес. Сценарий «15 человек
одновременно, у каждого 2 обращения голосом» проходит целиком: голос → «Мы поняли так» → «Похоже, об этом уже сообщали» →
отправка через QR-форму; вошедшие одной демо-учёткой — голос, черновик и «похожие» в приложении. Явный спам с одного адреса
по-прежнему упирается в лимит (минутное окно)."""
import time

import pytest
from fastapi.testclient import TestClient

from mf import api
from mf.ai import stt
from mf.main import app

AUDIO = b"\x1a\x45\xdf\xa3" + b"\x00" * 4000   # «webm»: больше порога пустой записи; расшифровку подменяем
PEOPLE, EACH = 15, 2


@pytest.fixture()
def venue(monkeypatch):
    monkeypatch.setattr(stt, "transcribe", lambda path, language=None, max_seconds=None: {"text": "На складе в Павлодаре нет габаритов в карточках 1С, комплектация вручную",
                                                                                          "engine": "fake", "language": "ru", "seconds": 4})
    with TestClient(app, client=("203.0.113.7", 40000)) as c:   # один адрес на всех — Wi-Fi площадки за NAT
        yield c


def test_jury_wifi_fifteen_people_two_voice_appeals_each(venue):
    c = venue
    ok = 0
    for person in range(PEOPLE):
        for n in range(EACH):
            for attempt in range(2):   # кто-то перезаписывает голос — второй раз
                r = c.post("/api/public/stt", files={"audio": ("voice.webm", AUDIO, "audio/webm")})
                assert r.status_code == 200, (person, n, r.text)
            text = r.json()["text"] + f" (жюри {person}.{n})"
            assert c.post("/api/public/brief", json={"text": text, "type": "problem"}).status_code == 200
            assert c.post("/api/public/similar", json={"text": text}).status_code == 200
            r = c.post("/api/public/appeals", data={"type": "problem", "text": text, "branch_code": "PVL", "input_mode": "voice"})
            assert r.status_code == 200, (person, n, r.text)
            ok += 1
    assert ok == PEOPLE * EACH


def test_jury_logged_in_with_one_demo_account(venue):
    c = venue
    for person in range(PEOPLE):   # каждый телефон входит сам (демо-вход «Войти как…»), все — как один сотрудник
        assert c.post("/api/auth/login-as", json={"user_id": 17}).status_code == 200
    for i in range(PEOPLE * EACH):
        assert c.post("/api/stt", files={"audio": ("voice.webm", AUDIO, "audio/webm")}).status_code == 200
        assert c.post("/api/ai/draft", json={"text": f"Нет габаритов в карточках 1С, обращение {i}", "type": "problem"}).status_code == 200
        assert c.post("/api/ai/similar", json={"text": f"Нет габаритов в карточках 1С, обращение {i}"}).status_code == 200


def test_obvious_spam_from_one_address_still_blocked(venue, monkeypatch):
    c = venue
    codes = [c.post("/api/public/appeals", data={"type": "problem", "text": f"Спам {i} про парковку", "branch_code": "PVL"}).status_code for i in range(35)]
    assert codes[:30] == [200] * 30 and 429 in codes[30:]   # больше 30 в минуту с адреса — спам
    api.qr_limit.hits.clear()
    now = time.time()   # и за 10 минут не больше 60, даже если растянуть по минутам
    api.qr_limit.hits["203.0.113.7"] = [now - 590 + i * 9 for i in range(60)]
    assert c.post("/api/public/appeals", data={"type": "problem", "text": "Ещё спам", "branch_code": "PVL"}).status_code == 429
    assert 429 in [c.post("/api/public/stt", files={"audio": ("v.webm", AUDIO, "audio/webm")}).status_code for _ in range(65)]
