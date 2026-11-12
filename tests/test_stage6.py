"""Этап 6: Битрикс24 — без настроек неактивен, с настройками (HTTP подменён фейком) — вход OAuth, сопоставление сотрудника, дубль
уведомления со ссылкой, вход из iframe, установка; команды директора (без ключа — ключевые слова); публичная карта; интерфейс без эмодзи."""
import os
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from mf import appeals, db
from mf.integrations import bitrix
from mf.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


def notes_count():
    return db.one("SELECT COUNT(*) AS n FROM notifications")["n"]


# ---------- §1 Битрикс24 ----------

def test_bitrix_inactive_without_settings(c):
    for k in ("BITRIX_PORTAL", "BITRIX_CLIENT_ID", "BITRIX_CLIENT_SECRET", "BITRIX_WEBHOOK_URL"):
        os.environ.pop(k, None)
    assert not bitrix.configured() and not bitrix.notify_available()
    assert c.get("/api/public/config").json()["bitrix"] is False
    assert c.get("/bitrix/login", follow_redirects=False).status_code == 404
    r = c.get("/")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
    n = notes_count()
    appeals.notify(3, "проверка", "/app")   # без интеграции — только внутреннее уведомление, ничего не имитируется
    assert notes_count() == n + 1


def test_bitrix_oauth_login_notify_iframe_install(c, monkeypatch):
    monkeypatch.setenv("BITRIX_PORTAL", "modus-test.bitrix24.kz")
    monkeypatch.setenv("BITRIX_CLIENT_ID", "local.abc")
    monkeypatch.setenv("BITRIX_CLIENT_SECRET", "s3cret")
    calls = []

    def fake(url, params=None, data=None):
        calls.append((url, params or {}, data or {}))
        if "/oauth/token/" in url:
            assert params["client_secret"] == "s3cret" and params["grant_type"] == "authorization_code" and params["code"] == "c0de"
            return {"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600, "client_endpoint": "https://modus-test.bitrix24.kz/rest/",
                    "member_id": "m1", "domain": "oauth.bitrix24.tech", "scope": "user,im,task", "status": "L"}
        if url.endswith("/rest/user.current"):
            assert params["auth"] == "at1"
            return {"result": {"ID": "17", "NAME": "Айгерим", "LAST_NAME": "Нурланова", "EMAIL": "aigerim@modus-test.kz", "WORK_POSITION": "Руководитель продаж"}}
        if url.endswith("/rest/im.notify.system.add"):
            return {"result": 101}
        raise AssertionError(url)

    monkeypatch.setattr(bitrix, "request_fn", fake)
    bitrix.tokens_path().unlink(missing_ok=True)
    assert bitrix.configured() and c.get("/api/public/config").json()["bitrix"] is True
    r = c.get("/")   # остальной сайт — по-прежнему запрет встраивания
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
    r = c.get("/bitrix/login", follow_redirects=False)   # /bitrix/* — только портал из .env
    assert "frame-ancestors 'self' https://modus-test.bitrix24.kz;" in r.headers["content-security-policy"] and "x-frame-options" not in r.headers
    r = c.get("/", headers={"cookie": "mf_frame=1"})   # сессия из iframe — встраивание разрешено на любом пути
    assert "https://modus-test.bitrix24.kz" in r.headers["content-security-policy"] and "x-frame-options" not in r.headers
    # снаружи: кнопка → авторизация на портале → code → токены → user.current → наш сотрудник
    r = c.get("/bitrix/login", params={"next": "/app"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://modus-test.bitrix24.kz/oauth/authorize/?client_id=local.abc&state=")
    state = r.headers["location"].split("state=")[1]
    assert c.get("/bitrix/callback", params={"code": "c0de", "state": "bogus"}, follow_redirects=False).status_code == 400
    r = c.get("/bitrix/callback", params={"code": "c0de", "state": state, "domain": "modus-test.bitrix24.kz", "member_id": "m1"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/app" and "mf_sid=" in r.headers.get("set-cookie", "")
    assert c.get("/api/me").json()["name"] == "Айгерим Нурланова"   # по имени и фамилии (демо-имена на тестовом портале); ID запомнен
    u = db.one("SELECT bitrix_id, email FROM users WHERE id=4")
    assert u["bitrix_id"] == 17 and u["email"] == "aigerim@modus-test.kz"
    assert bitrix.load_tokens()["access_token"] == "at1" and bitrix.notify_available()
    # дубль уведомления в чат Битрикса со ссылкой обратно — тем же appeals.notify, что и внутренние уведомления
    calls.clear()
    n = notes_count()
    appeals.notify(4, "A-007: статус «В работе»", "/app#/appeal/7")
    sent = [x for x in calls if x[0].endswith("im.notify.system.add")]
    assert notes_count() == n + 1 and len(sent) == 1 and sent[0][2]["USER_ID"] == 17
    assert "A-007" in sent[0][2]["MESSAGE"] and "/app#/appeal/7" in sent[0][2]["MESSAGE"]
    calls.clear()
    appeals.notify(3, "Ерлан не сопоставлен", "/app")
    assert not [x for x in calls if x[0].endswith("im.notify.system.add")]
    # внутри портала: POST с AUTH_ID → сотрудник опознан → сессия по токену в адресе + партиционированная cookie
    c.cookies.clear()
    r = c.post("/bitrix/app", data={"AUTH_ID": "at1", "REFRESH_ID": "rt1", "member_id": "m1", "PLACEMENT": "DEFAULT"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/bitrix/app?s=")
    cookies = r.headers.get_list("set-cookie")
    assert any("mf_sid=" in x and "SameSite=None" in x and "Partitioned" in x and "Secure" in x for x in cookies) and any("mf_frame=1" in x for x in cookies)
    sid = r.headers["location"].split("s=")[1]
    c.cookies.clear()
    r = c.get(r.headers["location"])   # страница панели по токену, без cookie; встраивание разрешено порталу
    assert r.status_code == 200 and "panel.js" in r.text and "https://modus-test.bitrix24.kz" in r.headers["content-security-policy"]
    assert c.get("/api/me", headers={"Authorization": "Bearer " + sid}).json()["name"] == "Айгерим Нурланова"
    assert c.get("/api/me", params={"s": sid}).status_code == 200 and c.get("/api/me").status_code == 401
    # redirect OAuth на «Путь обработчика» — тот же адрес с code и state
    state2 = c.get("/bitrix/login", follow_redirects=False).headers["location"].split("state=")[1]
    assert c.get("/bitrix/app", params={"code": "c0de", "state": state2}, follow_redirects=False).status_code == 302
    # установка: токены портала + страница с BX24.installFinish и CSP, разрешающим их SDK
    r = c.post("/bitrix/install", data={"AUTH_ID": "at1", "REFRESH_ID": "rt1", "member_id": "m1", "DOMAIN": "modus-test.bitrix24.kz"})
    assert r.status_code == 200 and "bitrix_install.js" in r.text and "https://api.bitrix24.com" in r.headers["content-security-policy"]
    assert bitrix.load_tokens()["member_id"] == "m1"
    st = bitrix.status()
    assert st["configured"] and st["tokens"] and st["mapped_users"] >= 1
    bitrix.tokens_path().unlink(missing_ok=True)
    db.ex("UPDATE users SET bitrix_id=NULL, email=NULL WHERE id=4")


# ---------- §2 команды директора (без ключа — ключевые слова; получателей и текст считает сервер) ----------

def notes(c):
    return [n["text"] for n in c.get("/api/notifications").json()["items"]]


def test_command_rude_phrase_city_filter_and_confirmation(c):
    login(c, 1)
    n0 = notes_count()
    r = c.post("/api/director/command/parse", json={"text": "Срочно всех бездельников в Омске заставь отчитаться по обращениям в работе до 18:00!!!"}).json()
    cmd, plan = r["command"], r["plan"]
    assert cmd["intent"] == "request_progress" and cmd["filters"]["branch"] == "Омск" and cmd["deadline"]["time"] == "18:00" and cmd["engine"] == "keywords"
    assert plan["kind"] == "send" and plan["counts"]["users"] >= 1 and plan["counts"]["appeals"] >= 1, plan
    assert plan["title"].startswith("Отправить запрос новостей")
    omsk = db.one("SELECT id FROM branches WHERE code='OMSK'")["id"]
    expected = {(a["responsible_id"], a["id"]) for a in db.q("SELECT id, responsible_id FROM appeals WHERE status='in_progress' AND branch_id=? AND responsible_id IS NOT NULL AND responsible_id != 1", (omsk,))}
    got = {(rec["user_id"], it["id"]) for rec in plan["recipients"] for it in rec["items"]}
    assert got == expected and expected   # фильтр по городу: только обращения филиала Омск
    for rec in plan["recipients"]:
        m = rec["message"]
        assert m.startswith("Виктор просит сегодня до 18:00 сообщить о ходе работ по обращени"), m
        assert "бездельник" not in m.lower() and "срочно" not in m.lower() and "заставь" not in m.lower() and "!" not in m
    assert notes_count() == n0   # экран подтверждения: без [Отправить] ничего не ушло
    r2 = c.post(f"/api/director/command/{r['plan_id']}/send", json={}).json()
    assert r2["ok"] and r2["users"] == plan["counts"]["users"] and r2["appeals"] == plan["counts"]["appeals"]
    assert r2["reply"].startswith("Отправил запрос новостей") and notes_count() == n0 + r2["users"]
    rec = plan["recipients"][0]
    ev = [e for e in c.get(f"/api/appeals/{rec['items'][0]['id']}").json()["events"] if e["kind"] == "director_requested_news"]
    assert ev and ev[-1]["payload"]["deadline"] == "сегодня до 18:00" and ev[-1]["actor"] == "Виктор Орлов"
    assert c.post(f"/api/director/command/{r['plan_id']}/send", json={}).status_code == 409   # повторно тот же план не уходит
    assert c.get(f"/api/director/command/{r['plan_id']}/audio").status_code == 503             # без ключа — голос браузера
    login(c, rec["user_id"])
    assert any(n == rec["message"] for n in notes(c))
    login(c, 6)
    assert c.post("/api/director/command/parse", json={"text": "прочитай сводку"}).status_code == 403   # только директор и администратор


def test_command_unknown_lists_abilities_and_sends_nothing(c):
    login(c, 1)
    n0 = notes_count()
    r = c.post("/api/director/command/parse", json={"text": "закажи пиццу в офис"}).json()
    assert r["command"]["intent"] is None and r["plan"]["kind"] == "unknown" and r["plan"]["title"].startswith("Не понял команду")
    assert len(r["plan"]["help"]) == 5 and any("сводку" in x for x in r["plan"]["help"])
    assert c.post(f"/api/director/command/{r['plan_id']}/send", json={}).status_code == 422 and notes_count() == n0
    h = c.get("/api/director/command/help").json()
    assert [i["intent"] for i in h["intents"]] == ["remind_overdue_tasks", "request_progress", "remind_no_response", "open_decision", "read_briefing"]


def test_command_no_response_person_filter_and_edited_text(c):
    login(c, 1)
    r = c.post("/api/director/command/parse", json={"text": "Напомни Ерлану об обращениях без ответа до пятницы"}).json()
    cmd, plan = r["command"], r["plan"]
    assert cmd["intent"] == "remind_no_response" and cmd["filters"]["person"] == "Ерлан Жумабеков" and cmd["deadline"]["label"].startswith("до пятницы")
    assert [x["user_id"] for x in plan["recipients"]] == [3] and plan["recipients"][0]["items"]
    assert all(db.one("SELECT first_response_at FROM appeals WHERE id=?", (i["id"],))["first_response_at"] is None for i in plan["recipients"][0]["items"])
    assert "дать первый ответ автору" in plan["recipients"][0]["message"]
    edited = "Ерлан, прошу до пятницы ответить авторам по " + ", ".join(i["number"] for i in plan["recipients"][0]["items"]) + "."
    r2 = c.post(f"/api/director/command/{r['plan_id']}/send", json={"messages": {"3": edited}}).json()
    assert r2["users"] == 1
    login(c, 3)
    assert edited in notes(c)


def test_command_overdue_tasks_open_decision_briefing(c):
    from tests.test_stage2 import TRANSCRIPT
    login(c, 2)
    mid = c.post("/api/meetings", data={"title": "Планёрка для команд", "transcript": TRANSCRIPT}).json()["id"]
    assert c.post(f"/api/meetings/{mid}/send").status_code == 200
    db.ex("UPDATE meeting_items SET due_date='2026-11-01' WHERE meeting_id=? AND kind='task' AND assignee_id=3", (mid,))
    login(c, 1)
    r = c.post("/api/director/command/parse", json={"text": "Поторопи всех, у кого просрочены поручения, сегодня"}).json()
    plan = r["plan"]
    assert r["command"]["intent"] == "remind_overdue_tasks" and plan["counts"]["tasks"] >= 1
    erlan = next(x for x in plan["recipients"] if x["user_id"] == 3)
    assert "сообщить о статусе поручени" in erlan["message"] and "срок был 01.11" in erlan["message"] and erlan["message"].startswith("Виктор просит сегодня")
    r2 = c.post(f"/api/director/command/{r['plan_id']}/send", json={}).json()
    assert r2["tasks"] >= 1 and r2["reply"].startswith("Отправил напоминания")
    # «На решение» с выбранной идеей: только открыть, ничего не отправляется и не решается
    n0 = notes_count()
    r = c.post("/api/director/command/parse", json={"text": "Прими идею про регламент 1С"}).json()
    assert r["command"]["intent"] == "open_decision" and r["plan"]["kind"] == "open" and r["plan"]["item"]["number"] == "A-027"
    r2 = c.post(f"/api/director/command/{r['plan_id']}/send", json={}).json()
    assert r2["href"] == "#/decisions" and notes_count() == n0
    assert db.one("SELECT director_decision FROM appeals WHERE number='A-027'")["director_decision"] == "pending"   # решение — только кнопкой
    r = c.post("/api/director/command/parse", json={"text": "открой на решение A-028"}).json()
    assert r["plan"]["item"]["number"] == "A-028"
    # сводка
    r = c.post("/api/director/command/parse", json={"text": "прочитай сводку"}).json()
    assert r["plan"]["kind"] == "briefing" and r["plan"]["sentences"] and r["plan"]["engine"] == "template"


# ---------- §3 публичная карта на стартовой (без входа) и §4 интерфейс без эмодзи ----------

def test_public_map_without_login(c):
    c.cookies.clear()
    m = c.get("/api/public/map").json()
    assert {b["code"] for b in m["branches"]} == {"OMSK", "SAM", "TMN", "AST", "PVL"} and m["field"]["code"] == "FIELD"
    pvl = next(b for b in m["branches"] if b["code"] == "PVL")
    assert pvl["kind_label"] == "производство" and pvl["qr_url"].endswith("/q/PVL") and pvl["form_url"] == "/q/PVL" and pvl["lat"]
    assert {"open", "done_month", "top_category", "qr_svg"} <= set(pvl) and "overdue" not in pvl and "unassigned" not in pvl   # служебное наружу не отдаём
    assert all({"city", "lat", "lng", "open"} == set(s) for s in m["sites"])   # без номеров обращений
    assert c.get("/api/panel/map").status_code == 401
    assert c.get(pvl["qr_svg"]).headers["content-type"].startswith("image/svg")


EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿■-◿←-⇿⌀-⏿•✓-✘️]")


def test_no_emoji_in_frontend():
    """§4: никаких эмодзи и символов-заменителей в интерфейсе — один набор SVG-иконок (web/a/icons.js). Комментарии не считаются."""
    web = pathlib.Path(__file__).resolve().parent.parent / "web"
    bad = []
    for f in list(web.glob("*.html")) + list((web / "a").glob("*.js")) + [web / "a" / "style.css"]:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//")[0] if f.suffix == ".js" and not line.lstrip().startswith("//") else ("" if f.suffix == ".js" else line)
            if f.suffix == ".js" and line.lstrip().startswith("//"):
                code = ""
            if EMOJI.search(code):
                bad.append(f"{f.name}:{n}: {line.strip()[:80]}")
    assert not bad, bad
    assert (web / "a" / "icons" / "LICENSE").is_file()


def test_command_demo_phrase_without_key(c):
    """Фраза из DEMO.md (без грубостей) должна разбираться и без ключа: город, срок словами, вежливый текст."""
    login(c, 1)
    r = c.post("/api/director/command/parse", json={"text": "Пусть Омск до шести вечера расскажет, что по обращениям в работе"}).json()
    cmd = r["command"]
    assert cmd["intent"] == "request_progress" and cmd["filters"]["branch"] == "Омск" and cmd["deadline"]["time"] == "18:00" and cmd["deadline"]["label"] == "сегодня до 18:00"
    assert r["plan"]["recipients"] and r["plan"]["recipients"][0]["message"].startswith("Виктор просит сегодня до 18:00 сообщить о ходе работ по обращени")
    from mf import commands
    assert commands.parse_time("к часу") == "13:00" and commands.parse_time("до пяти") == "17:00" and commands.parse_time("к девяти утра") == "09:00" and commands.parse_time("до 18 ноября") is None


# ---------- этап 7, шаг 1: дизайн-система (цвета только токенами), главная, /design, «Что изменили» без входа ----------

def test_css_colors_only_in_tokens():
    """§4 этапа 7: нет «сырых» hex-цветов вне блока токенов :root (кроме data-URI иконок в url())."""
    css = (pathlib.Path(__file__).resolve().parent.parent / "web" / "a" / "style.css").read_text(encoding="utf-8")
    root = re.search(r":root \{(.*?)\n\}", css, re.S).group(1)
    rest = css.replace(root, "")
    rest = re.sub(r"url\([^)]*\)", "", rest)
    rest = re.sub(r"/\*.*?\*/", "", rest, flags=re.S)
    raw = sorted(set(re.findall(r"#[0-9a-fA-F]{3,6}\b", rest)))
    assert not raw, raw
    assert "--navy: #082742" in root and "--red: #e40000" in root


def test_design_changes_pages_and_public_changes(c):
    c.cookies.clear()
    for path in ("/design", "/changes", "/"):
        r = c.get(path)
        assert r.status_code == 200 and "Модус Голос" in r.text
    rows = c.get("/api/public/changes").json()
    assert rows and all({"number", "type_label", "text", "resolution_text", "closed_at", "thanks"} <= set(r) for r in rows)
    assert all("author" not in r for r in rows)   # без входа авторов не показываем
    assert any(r["number"] == "A-004" for r in rows)
