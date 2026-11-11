"""Этап 3 (без ключа): голосовой ввод через API (STT выключен → честная ошибка), черновик по словарю, похожие обращения
по ключевым словам, «У меня так же» вместо дубля, кластеры «Повторяющиеся темы»."""
import os
import tempfile

os.environ["MF_DATA_DIR"] = tempfile.mkdtemp(prefix="mf-test3-")
os.environ["MF_STT"] = "off"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mf import db  # noqa: E402
from mf.main import app  # noqa: E402

os.environ.pop("OPENAI_API_KEY", None)


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def number_id(number):
    return db.one("SELECT id FROM appeals WHERE number=?", (number,))["id"]


def test_similar_public_finds_a007(c):
    r = c.post("/api/public/similar", json={"text": "Повторный ввод одних и тех же сведений в разных рабочих системах, какие операции можно синхронизировать"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["engine"] == "keywords" and j["logged_in"] is False
    assert "A-007" in [i["number"] for i in j["items"]] and "supports" not in j["items"][0]   # база общая с test_core: там есть ещё одно похожее
    r = c.post("/api/public/similar", json={"text": "Кофемашина сломалась на кухне"}).json()
    assert r["items"] == []


def test_support_instead_of_duplicate(c):
    login(c, 6)   # Сауле: похожее найдено → «У меня так же» → нового обращения нет, поддержка учтена
    before = c.get("/api/health").json()["appeals"]
    r = c.post("/api/ai/similar", json={"text": "вбиваем одно и то же в две системы"}).json()
    hit = next(i for i in r["items"] if i["number"] == "A-007")
    assert hit["id"] == number_id("A-007") and "supports" in hit
    assert c.post(f"/api/appeals/{hit['id']}/support").status_code in (200, 409)
    assert c.get("/api/health").json()["appeals"] == before
    assert db.one("SELECT 1 FROM supports WHERE appeal_id=? AND user_id=6", (number_id("A-007"),))


def test_draft_without_key_uses_keywords(c):
    login(c, 6)
    d = c.post("/api/ai/draft", json={"text": "В общих папках не найти актуальную редакцию инструкции", "type": "problem"}).json()
    assert d["engine"] == "keywords" and d["category"] == "Хранение документов" and d["priority"] == "medium"
    assert c.post("/api/ai/draft", json={"text": "x"}).status_code == 422


def test_stt_off_is_honest(c):
    login(c, 6)
    r = c.post("/api/stt", files={"audio": ("v.webm", b"\x1aE\xdf\xa3" + b"0" * 2000, "audio/webm")})
    assert r.status_code == 503 and "MF_STT=off" in r.json()["detail"]
    assert c.post("/api/stt", files={"audio": ("v.webm", b"12", "audio/webm")}).status_code == 422
    r = c.post("/api/public/stt", files={"audio": ("v.webm", b"\x1aE\xdf\xa3" + b"0" * 2000, "audio/webm")})
    assert r.status_code == 503


def test_clusters_keywords(c):
    login(c, 6)
    a = c.post("/api/appeals", data={"type": "problem", "text": "Повторный ввод одних и тех же данных в двух системах отнимает время, нужна синхронизация", "category_id": "7"}).json()
    login(c, 1)
    k = c.get("/api/panel/clusters").json()
    assert k["engine"] == "keywords" and k["open_total"] >= 17
    cl = next((x for x in k["clusters"] if any(i["number"] == "A-007" for i in x["items"])), None)
    assert cl and cl["size"] >= 2 and any(i["number"] == a["number"] for i in cl["items"]) and cl["category"] == "Интеграции и IT"
    assert db.one("SELECT cluster_id FROM appeals WHERE number='A-007'")["cluster_id"] == cl["id"]
    login(c, 6)
    assert c.get("/api/panel/clusters").status_code == 403
