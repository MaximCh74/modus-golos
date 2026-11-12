"""Безопасность (аудит 12.11.2026, docs/SECURITY.md): каждая находка аудита — тест, что атака отклоняется, и тесты того, что работало.
Сеть не используется: Битрикс24 — фейковый HTTP (bitrix.request_fn), портал вымышленный; ключа OpenAI нет (conftest), ИИ подменяется."""
import io
import json
import os
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from mf import db
from mf.integrations import bitrix
from mf.main import app

ROOT = Path(__file__).resolve().parent.parent
PORTAL = "modus-audit.bitrix24.kz"
EVIL = "evil.example"
CLIENT_ID = "local.audit.1"


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:   # «снаружи» (как через туннель): демо-сессиям закрыто опасное
        yield client


class FakeHTTP:
    """Фейковый Битрикс24: наш портал, сервер злоумышленника и OAuth-сервер. Любой другой хост — ошибка теста (сети нет).
    Наш портал принимает только известные ему токены; чужие — invalid_token, как настоящий."""

    def __init__(self):
        self.calls = []
        self.portal_tokens = {"at-legit": {"ID": "5", "NAME": "Тест", "LAST_NAME": "Портала"}, "at-new": {"ID": "5", "NAME": "Тест", "LAST_NAME": "Портала"}}
        self.evil_user = {"ID": "777", "NAME": "Сергей", "LAST_NAME": "Михайлович"}
        self.portal_users = {EVIL: [{"ID": "900", "NAME": "Подставной", "LAST_NAME": "Сотрудник", "ACTIVE": True}], PORTAL: []}
        self.oauth = {"access_token": "at-legit", "refresh_token": "rt", "expires_in": 3600, "client_endpoint": f"https://{PORTAL}/rest/", "member_id": "m-legit"}

    def __call__(self, url, params=None, data=None):
        host = urlparse(url).netloc
        params = params or {}
        self.calls.append({"host": host, "url": url, "params": params, "data": data or {}})
        if host not in (PORTAL, EVIL, "oauth.bitrix24.tech"):
            raise AssertionError("неожиданный хост в тесте: " + host)
        if "/oauth/token/" in url:
            return dict(self.oauth)
        if host == EVIL:   # сервер злоумышленника отвечает «как надо»
            if url.endswith("/user.current"):
                return {"result": self.evil_user}
            return {"result": {"CODE": CLIENT_ID} if url.endswith("/app.info") else self.portal_users[EVIL] if url.endswith("/user.get") else 1}
        tok = params.get("auth")
        if tok not in self.portal_tokens:
            return {"error": "invalid_token", "error_description": "The access token provided is invalid"}
        if url.endswith("/user.current"):
            return {"result": self.portal_tokens[tok]}
        if url.endswith("/app.info"):
            return {"result": {"ID": 2, "CODE": CLIENT_ID, "STATUS": "L", "INSTALLED": True}}
        if url.endswith("/department.get"):
            return {"result": []}
        if url.endswith("/user.get"):
            return {"result": self.portal_users[PORTAL]}
        return {"result": 1}

    def to(self, host, method=None):
        return [x for x in self.calls if x["host"] == host and (method is None or x["url"].endswith("/" + method))]


@pytest.fixture(autouse=True)
def fake_bitrix(monkeypatch):
    monkeypatch.setenv("BITRIX_PORTAL", PORTAL)
    monkeypatch.setenv("BITRIX_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("BITRIX_CLIENT_SECRET", "audit-secret")
    for k in ("BITRIX_WEBHOOK_URL", "BITRIX_MEMBER_ID"):
        monkeypatch.delenv(k, raising=False)
    fake = FakeHTTP()
    monkeypatch.setattr(bitrix, "request_fn", fake)
    yield fake
    bitrix.tokens_path().unlink(missing_ok=True)
    db.ex("UPDATE users SET active=1 WHERE id BETWEEN 1 AND 28")
    db.ex("UPDATE users SET bitrix_id=NULL WHERE id BETWEEN 1 AND 28")


def legit_tokens():
    bitrix.save_tokens({"access_token": "at-legit", "refresh_token": "rt-legit", "member_id": "m-legit", "application_token": "apptok-legit"})


def login(c, uid):
    c.cookies.clear()
    r = c.post("/api/auth/login-as", json={"user_id": uid})
    assert r.status_code == 200, r.text
    return r


def anon(c):
    c.cookies.clear()


# ---------- F-01: установка приложения Битрикс24 только с нашего портала ----------

def test_F01_foreign_install_event_rejected_tokens_kept(c, fake_bitrix):
    legit_tokens()
    anon(c)
    r = c.post("/bitrix/install", data={"event": "ONAPPINSTALL", "auth[access_token]": "evil-at", "auth[refresh_token]": "evil-rt",
                                        "auth[client_endpoint]": f"https://{EVIL}/rest/", "auth[member_id]": "m-evil", "auth[domain]": EVIL})
    assert r.status_code == 403
    t = bitrix.load_tokens()
    assert t["access_token"] == "at-legit" and t["client_endpoint"] == f"https://{PORTAL}/rest/" and t["member_id"] == "m-legit"
    assert not fake_bitrix.to(EVIL)   # к серверу злоумышленника не обращались
    # тот же member_id, но токен не наш (портал его не знает) — тоже отказ: app.info на нашем портале
    r = c.post("/bitrix/install", data={"event": "ONAPPINSTALL", "auth[access_token]": "evil-at", "auth[member_id]": "m-legit"})
    assert r.status_code == 403 and bitrix.load_tokens()["access_token"] == "at-legit"
    # событие (не установка) без верного application_token — отказ
    r = c.post("/bitrix/install", data={"event": "ONAPPUPDATE", "auth[access_token]": "at-new", "auth[member_id]": "m-legit", "auth[application_token]": "wrong"})
    assert r.status_code == 403


def test_F01_notifications_and_sync_never_reach_foreign_endpoint(c, fake_bitrix):
    """Даже если в файле токенов чужой адрес (до исправления), запросы идут только на портал из .env."""
    legit_tokens()
    p = bitrix.tokens_path()
    t = json.loads(p.read_text(encoding="utf-8"))
    t["client_endpoint"] = f"https://{EVIL}/rest/"
    p.write_text(json.dumps(t), encoding="utf-8")
    db.ex("UPDATE users SET bitrix_id=1 WHERE id=1")
    anon(c)
    c.post("/api/public/appeals", data={"type": "praise", "text": "Спасибо за помощь со складом, конфиденциально", "branch_code": "PVL", "praise_to_user_id": "1"})
    bitrix.sync_users()
    assert not fake_bitrix.to(EVIL) and fake_bitrix.to(PORTAL, "im.notify.system.add")
    assert db.one("SELECT active FROM users WHERE id=1")["active"] == 1


def test_ok_legit_install_saves_tokens_and_application_token(c, fake_bitrix):
    anon(c)
    r = c.post("/bitrix/install", data={"event": "ONAPPINSTALL", "auth[access_token]": "at-new", "auth[refresh_token]": "rt-new",
                                        "auth[member_id]": "m-legit", "auth[application_token]": "apptok-1", "auth[client_endpoint]": f"https://{EVIL}/rest/"})
    assert r.status_code == 200, r.text
    t = bitrix.load_tokens()
    assert t["access_token"] == "at-new" and t["member_id"] == "m-legit" and t["application_token"] == "apptok-1" and t["client_endpoint"] == f"https://{PORTAL}/rest/"
    assert fake_bitrix.to(PORTAL, "app.info") and not fake_bitrix.to(EVIL)
    # повторная установка с другого портала после этого — отказ по member_id
    r = c.post("/bitrix/install", data={"event": "ONAPPINSTALL", "auth[access_token]": "at-legit", "auth[member_id]": "m-other"})
    assert r.status_code == 403
    # BITRIX_MEMBER_ID в .env имеет приоритет
    os.environ["BITRIX_MEMBER_ID"] = "m-pinned"
    try:
        assert c.post("/bitrix/install", data={"event": "ONAPPINSTALL", "auth[access_token]": "at-legit", "auth[member_id]": "m-legit"}).status_code == 403
    finally:
        os.environ.pop("BITRIX_MEMBER_ID", None)


# ---------- F-02: вход «из портала» только с токеном нашего портала; без склейки по имени ----------

def test_F02_foreign_domain_cannot_log_in(c, fake_bitrix):
    legit_tokens()
    anon(c)
    r = c.post("/bitrix/app", data={"AUTH_ID": "anything", "DOMAIN": EVIL, "member_id": "m-evil"}, follow_redirects=False)
    assert r.status_code == 403
    r = c.post("/bitrix/app", data={"AUTH_ID": "anything", "DOMAIN": EVIL, "member_id": "m-legit"}, follow_redirects=False)
    assert r.status_code == 403   # DOMAIN не используется: наш портал токен не знает
    assert not fake_bitrix.to(EVIL) and db.one("SELECT bitrix_id FROM users WHERE id=1")["bitrix_id"] is None


def test_F02b_first_open_does_not_save_foreign_tokens(c, fake_bitrix):
    bitrix.tokens_path().unlink(missing_ok=True)
    anon(c)
    c.post("/bitrix/app", data={"AUTH_ID": "evil-at", "REFRESH_ID": "evil-rt", "DOMAIN": EVIL, "member_id": "m-evil"}, follow_redirects=False)
    assert bitrix.load_tokens() is None


def test_F02c_name_only_match_is_not_glued(c, fake_bitrix):
    """Сотрудник портала с тем же именем, что у нашего директора, но без ID/почты/телефона — не входит директором и не заводится дублем."""
    legit_tokens()
    fake_bitrix.portal_tokens["at-namesake"] = {"ID": "777", "NAME": "Сергей", "LAST_NAME": "Михайлович"}
    anon(c)
    r = c.post("/bitrix/app", data={"AUTH_ID": "at-namesake", "member_id": "m-legit"}, follow_redirects=False)
    assert r.status_code == 403 and "не сопоставлена" in r.text
    assert db.one("SELECT bitrix_id FROM users WHERE id=1")["bitrix_id"] is None and db.one("SELECT id FROM users WHERE bitrix_id=777") is None
    # синхронизация: тёзка — в отчёт «спорных», не склеен и не заведён
    fake_bitrix.portal_users[PORTAL] = [{"ID": "777", "NAME": "Сергей", "LAST_NAME": "Михайлович", "ACTIVE": True}]
    rep = bitrix.sync_users()
    assert rep["created"] == 0 and rep["conflicts"] and rep["conflicts"][0]["reason"] == "same_name" and rep["conflicts"][0]["user_id"] == 1


def test_ok_portal_user_logs_in_via_frame(c, fake_bitrix):
    legit_tokens()
    db.ex("UPDATE users SET bitrix_id=5 WHERE id=4")
    anon(c)
    r = c.post("/bitrix/app", data={"AUTH_ID": "at-legit", "member_id": "m-legit", "DOMAIN": EVIL}, follow_redirects=False)
    assert r.status_code == 303
    sid = parse_qs(urlparse(r.headers["location"]).query)["s"][0]
    assert c.get("/api/me", headers={"Authorization": "Bearer " + sid}).json()["id"] == 4
    assert not fake_bitrix.to(EVIL)


def test_F02_oauth_code_from_other_portal_rejected(c, fake_bitrix):
    legit_tokens()
    db.ex("UPDATE users SET bitrix_id=5 WHERE id=4")
    anon(c)
    state = parse_qs(urlparse(c.get("/bitrix/login", headers={"Sec-Fetch-Dest": "document"}, follow_redirects=False).headers["location"]).query)["state"][0]
    fake_bitrix.oauth = {**fake_bitrix.oauth, "member_id": "m-other", "client_endpoint": "https://other.bitrix24.kz/rest/"}
    assert c.get("/bitrix/callback", params={"code": "c", "state": state}, follow_redirects=False).status_code == 403
    fake_bitrix.oauth = {**fake_bitrix.oauth, "member_id": "m-legit", "client_endpoint": f"https://{PORTAL}/rest/"}
    state = parse_qs(urlparse(c.get("/bitrix/login", headers={"Sec-Fetch-Dest": "document"}, follow_redirects=False).headers["location"]).query)["state"][0]
    r = c.get("/bitrix/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert r.status_code == 302 and c.get("/api/me").json()["id"] == 4


def test_ok_frame_ancestors_only_portal(c):
    csp = c.get("/panel").headers["content-security-policy"]
    assert re.search(r"frame-ancestors ([^;]+)", csp).group(1).split() == ["'self'", f"https://{PORTAL}"]


# ---------- F-03: демо-вход («Войти как…») — вариант А ----------

def test_F03_demo_session_from_outside_cannot_do_dangerous_admin_actions(c, monkeypatch):
    from mf import demo
    called = []
    monkeypatch.setattr(demo, "snapshot", lambda *a, **k: called.append("snapshot") or {"ok": True})
    monkeypatch.setattr(demo, "reset", lambda *a, **k: called.append("reset") or {"ok": True})
    login(c, 15)   # администратор через демо-вход, запрос «снаружи»
    assert c.get("/api/me").json()["demo"] is True
    for url, body in (("/api/admin/demo-snapshot", None), ("/api/admin/demo-reset", None), ("/api/admin/bitrix/sync", None),
                      ("/api/admin/users", {"name": "Взломщик Тестов", "role": "admin"}), ("/api/admin/users/6/active", {"active": False}),
                      ("/api/admin/invites", {"user_id": 6}), ("/api/admin/invites/1/revoke", None), ("/api/admin/users/6/avatar/remove", None)):
        r = c.post(url, json=body if body is not None else {})
        assert r.status_code == 403 and "демо" in r.json()["detail"], (url, r.status_code)
    r = c.post("/api/admin/users/import", files={"file": ("a.csv", "Имя;Город\nТест Тестов;Омск\n".encode("utf-8"), "text/csv")})
    assert r.status_code == 403
    assert c.get("/api/admin/preflight").status_code == 403
    assert called == [] and db.one("SELECT active FROM users WHERE id=6")["active"] == 1
    # смотреть можно: настройки и списки
    assert c.get("/api/admin/settings").status_code == 200


def test_ok_demo_session_from_laptop_keeps_admin_tools(monkeypatch):
    from mf import demo
    called = []
    monkeypatch.setattr(demo, "reset", lambda *a, **k: called.append("reset") or {"ok": True})
    with TestClient(app, client=("127.0.0.1", 50000)) as local:
        login(local, 15)
        assert local.get("/api/me").json()["demo"] is False
        assert local.post("/api/admin/demo-reset").status_code == 200 and called == ["reset"]
        # тот же адрес петли, но с заголовком Cloudflare — это запрос через туннель, снаружи
        assert local.post("/api/admin/demo-reset", headers={"CF-Connecting-IP": "203.0.113.9"}).status_code == 403


def test_F03_demo_actions_are_not_duplicated_to_bitrix(c, fake_bitrix):
    legit_tokens()
    db.ex("UPDATE users SET bitrix_id=1 WHERE id=1")
    login(c, 6)   # сотрудник через демо-вход говорит «спасибо» директору
    r = c.post("/api/appeals", data={"type": "praise", "text": "Спасибо за помощь с отчётом", "praise_to_user_id": "1"})
    assert r.status_code == 200
    assert not fake_bitrix.to(PORTAL, "im.notify.system.add")
    assert db.one("SELECT COUNT(*) AS n FROM notifications WHERE user_id=1 AND text LIKE '%Спасибо за помощь с отчётом%'")["n"] == 1   # внутри системы — есть


def test_F03_demo_login_rate_limited_and_switch_off(c, monkeypatch):
    from mf import api
    anon(c)
    codes = [c.post("/api/auth/login-as", json={"user_id": 6}).status_code for _ in range(35)]
    assert codes.count(429) >= 1
    api.login_limit.hits.clear()
    monkeypatch.setenv("MF_DEMO_LOGIN", "0")
    anon(c)
    assert c.post("/api/auth/login-as", json={"user_id": 1}).status_code == 404
    assert c.get("/api/auth/users").status_code == 404 and c.get("/api/public/config").json()["demo_login"] is False


# ---------- F-04: текст сотрудника уходит в Битрикс24 без BB-кодов ----------

def test_F04_bbcode_from_anonymous_qr_is_neutralized(c, fake_bitrix):
    legit_tokens()
    db.ex("UPDATE users SET bitrix_id=1 WHERE id=1")
    anon(c)
    evil = "Спасибо! [URL=https://evil.example/login]Подтвердите вход в Битрикс24[/URL] [IMG]https://evil.example/x.png[/IMG]"
    assert c.post("/api/public/appeals", data={"type": "praise", "text": evil, "branch_code": "PVL", "praise_to_user_id": "1"}).status_code == 200
    msg = fake_bitrix.to(PORTAL, "im.notify.system.add")[-1]["data"]["MESSAGE"]
    assert "[URL=https://evil" not in msg and "[IMG]" not in msg and "［URL=https://evil.example/login］" in msg
    assert msg.count("[URL=") == 1 and "]Открыть в «Модус Голос»[/URL]" in msg   # наша ссылка обратно работает


# ---------- F-19: картинки — только JPEG/PNG/WebP, с лимитом пикселей ----------

def _img(fmt, size=(64, 64)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (1, 2, 3)).save(buf, fmt)
    return buf.getvalue()


def test_F19_avatar_rejects_exotic_formats(c):
    login(c, 6)
    for fmt in ("TIFF", "BMP", "GIF", "PPM"):
        r = c.post("/api/me/avatar", files={"file": ("a.jpg", _img(fmt), "image/jpeg")})
        assert r.status_code == 415, fmt
    for fmt in ("JPEG", "PNG", "WEBP"):
        assert c.post("/api/me/avatar", files={"file": ("a." + fmt.lower(), _img(fmt), "image/" + fmt.lower())}).status_code == 200, fmt


def test_F19_avatar_rejects_decompression_bomb(c):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("L", (9000, 9000), 0).save(buf, "PNG", optimize=True)   # 81 Мп, файл — десятки килобайт
    assert len(buf.getvalue()) < 3 * 1024 * 1024
    login(c, 6)
    assert c.post("/api/me/avatar", files={"file": ("bomb.png", buf.getvalue(), "image/png")}).status_code == 415
