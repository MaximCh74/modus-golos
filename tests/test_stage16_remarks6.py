"""Шестой список замечаний владельца 13.11: свежая версия у всех (отпечатки в ссылках на статику, версия в подвале), очередь без
«Возраста» (точка у номера, «просрочено на N дн», срочные сверху), совещания и лига по линейке, директор видит администрирование,
одна главная кнопка у сотрудника, нижняя панель приложения на телефоне."""
import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mf import version
from mf.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


# ---------- п. 0: после обновления у всех подтягивается само ----------

@pytest.mark.parametrize("path", ["/", "/app", "/panel", "/boss", "/login", "/q/OMSK-HQ", "/changes", "/rules"])
def test_pages_link_static_with_content_hash(c, path):
    html = c.get(path).text
    refs = re.findall(r'(?:src|href)="/a/([^"]+)"', html)
    assert refs
    for ref in refs:
        name, _, query = ref.partition("?")
        assert query.startswith("v="), ref   # без отпечатка Cloudflare и браузер держат старый файл до 4 часов
        assert query[2:] == hashlib.md5((ROOT / "web" / "a" / name).read_bytes()).hexdigest()[:10], ref
    build = re.search(r'<meta name="mf-build" content="([0-9a-f]{10})">', html).group(1)
    assert build == c.get("/api/public/config").json()["build"]


def test_sw_cache_named_by_build_and_revalidates(c):
    js = c.get("/sw.js").text
    cfg = c.get("/api/public/config").json()
    assert f"const CACHE = 'mf-shell-{cfg['build']}'" in js and "__BUILD__" not in js
    assert "cache: 'no-cache'" in js and "ignoreSearch" in js
    pwa = (ROOT / "web" / "a" / "pwa.js").read_text(encoding="utf-8")
    assert "updateViaCache: 'none'" in pwa and "mf-build" in pwa and "location.reload()" in pwa


def test_version_in_config_and_footers(c):
    cfg = c.get("/api/public/config").json()
    assert cfg["version"] == version.commit() and (cfg["version"] == "dev" or re.fullmatch(r"[0-9a-f]{7}", cfg["version"]))
    for f in ("index.js", "app.js", "panel.js", "boss.js"):
        assert "versionTag()" in (ROOT / "web" / "a" / f).read_text(encoding="utf-8"), f


def test_build_changes_when_static_changes(tmp_path, monkeypatch):
    web = tmp_path / "web"; (web / "a").mkdir(parents=True)
    (web / "a" / "x.js").write_text("1"); (web / "p.html").write_text('<head>\n<meta charset="utf-8">\n<script src="/a/x.js"></script>')
    monkeypatch.setattr(version, "WEB", web)
    b1, p1 = version.build(), version.page("p.html")
    (web / "a" / "x.js").write_text("22")
    assert version.build() != b1 and version.page("p.html") != p1 and "/a/x.js?v=" in p1


# ---------- п. 1: очередь ----------

def test_queue_overdue_days_and_urgent_first(c):
    login(c, 1)
    rows = c.get("/api/panel/appeals?open=1").json()
    od = [r for r in rows if r["overdue"]]
    assert od and all(r["overdue_days"] >= 1 for r in od) and all(r["overdue_days"] is None for r in rows if not r["overdue"])
    assert rows[:len(od)] == od   # срочные сверху: сначала просроченные
    days = [r["overdue_days"] for r in od]
    assert days == sorted(days, reverse=True)   # дольше просрочено — выше
    new = c.get("/api/panel/appeals?open=1&sort=new").json()
    created = [r["created_at"] for r in new]
    assert created == sorted(created, reverse=True)
    card = c.get(f"/api/appeals/{od[0]['id']}").json()
    assert card["overdue_days"] == od[0]["overdue_days"]


def test_queue_has_no_age_column():
    js = (ROOT / "web" / "a" / "panel.js").read_text(encoding="utf-8")
    assert "'Возраст'" not in js and "q-age" not in js
    assert "'просрочено на ' + r.overdue_days + ' дн'" in js and "overdueDot(r), h('span', { class: 'num' }" in js
