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


# ---------- п. 2: совещания ----------

def test_meetings_city_and_help_on_every_column(c):
    from mf import glossary
    login(c, 1)
    c.post("/api/meetings", data={"title": "Планёрка п. 2", "transcript": "Решили обновить справочник. Олег, до пятницы."})
    rows = c.get("/api/meetings").json()
    assert rows and all(" — " not in (r["branch"] or "") and (r["branch"] == r["city"] or r["branch"] == "объект") for r in rows)   # только город
    js = (ROOT / "web" / "a" / "panel.js").read_text(encoding="utf-8")
    cols = re.search(r"const cols = (\[\['Дата'.*?\]\]);", js, re.S).group(1)
    keys = re.findall(r"\['[^']+', '([a-z_]+)'", cols)
    assert len(keys) == 8 and all(k in glossary.TERMS for k in keys), keys
    assert "h('th', {}, t, helpBtn(key))" in js and "m.city || m.branch" in js
    assert "Уточнение" in glossary.TERMS["status"]["hint"] and "На рассмотрении" not in glossary.TERMS["status"]["hint"]   # пять статусов


def test_branch_is_city_everywhere(c):
    login(c, 1)
    s = c.get("/api/panel/summary?days=30").json()
    assert {b["city"] for b in s["by_branch"] if b["city"]} >= {"Омск", "Астана", "Павлодар"}
    from mf import appeals
    assert appeals.city_of({"branch": "Омск — головной офис", "branch_city": "Омск"}) == "Омск"
    assert appeals.city_of({"branch": "Объект (командировка)", "branch_city": None, "site_city": "Атырау"}) == "Атырау"
    for d in c.get("/api/director/ideas").json().get("pending", []):
        assert " — " not in (d.get("branch") or "")


# ---------- п. 3: лига ----------

def test_league_city_and_shared_layout(c):
    login(c, 1)
    d = c.get("/api/panel/league").json()
    assert all(u.get("city") for u in d["top"] if u.get("branch") and "Объект" not in u["branch"])
    ui = (ROOT / "web" / "a" / "ui.js").read_text(encoding="utf-8")
    for fn in ("function leagueBranches(", "function leagueTop(", "function leagueSplit("):
        assert fn in ui, fn
    assert "'Филиалы'], ['top', 'Сотрудники']" in ui and "lg-place" in ui
    for f in ("panel.js", "app.js"):
        assert "...leagueSplit(" in (ROOT / "web" / "a" / f).read_text(encoding="utf-8"), f
    css = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.lg-place \{[^}]*text-align: right;[^}]*tabular-nums", css)   # «#» по правому краю, моноширинные цифры
    assert re.search(r"\.lg-emp \{ display: grid; grid-template-columns: 28px ", css)   # место фиксированной ширины


# ---------- п. 4: директор видит «Администрирование» ----------

def test_director_admin_by_default_toggle_only_from_laptop(c):
    login(c, 1)   # директор через демо-вход «снаружи» (TestClient без адреса петли)
    me = c.get("/api/me").json()
    assert me["can_admin"] is True and me["demo"] is True
    assert c.get("/api/admin/settings").json()["settings"]["director_admin"] is True
    assert c.post("/api/admin/settings", json={"settings": {"director_admin": False}}).status_code == 403   # скрыть — только с ноутбука
    assert c.post("/api/admin/settings", json={"settings": {"director_admin": True}}).status_code == 200    # без изменения — можно
    assert c.post("/api/admin/demo-reset").status_code == 403 and c.post("/api/admin/invites", json={"user_id": 6}).status_code == 403   # F-03 сохранён
    with TestClient(app, client=("127.0.0.1", 50001)) as local:
        login(local, 1)
        assert local.post("/api/admin/settings", json={"settings": {"director_admin": False}}).status_code == 200
        assert local.get("/api/me").json()["can_admin"] is False
        assert local.get("/api/admin/settings").status_code == 403 and local.post("/api/admin/settings", json={"settings": {"director_admin": True}}).status_code == 403
        login(local, 15)   # вернуть может администратор
        assert local.get("/api/me").json()["can_admin"] is True
        assert local.post("/api/admin/settings", json={"settings": {"director_admin": True}}).status_code == 200
        login(local, 1)
        assert local.get("/api/me").json()["can_admin"] is True and local.get("/api/admin/settings").status_code == 200
    login(c, 2)   # ответственному раздел не положен
    assert c.get("/api/me").json()["can_admin"] is False and c.get("/api/admin/settings").status_code == 403
    js = (ROOT / "web" / "a" / "panel.js").read_text(encoding="utf-8")
    assert "Директору этот раздел можно скрыть в настройках" in js and "'Директор видит администрирование'" in js and "if (ME.can_admin) nav.push" in js


# ---------- п. 5: одна главная кнопка у сотрудника ----------

def test_employee_home_single_main_button():
    js = (ROOT / "web" / "a" / "app.js").read_text(encoding="utf-8")
    assert "'Есть идея или проблема?'" in js and "href: '#/new', class: 'btn btn-primary btn-big home-cta'" in js
    for old in ("'Сообщить о проблеме'", "'Предложить улучшение'", "href: '#/new?type=praise', class: 'btn btn-sm' }, 'Сказать спасибо'"):
        assert old not in js, old
    assert "[['problem', 'Проблема'], ['suggestion', 'Идея'], ['praise', 'Спасибо']]" in js   # переключатель в форме, как в QR-форме
    css = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
    assert ".type-switch.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }" in css


# ---------- дополнительно: пять статусов везде ----------

def test_no_old_statuses_on_screen():
    ui = (ROOT / "web" / "a" / "ui.js").read_text(encoding="utf-8")
    tracker = ui.split("function tracker(")[1].split("\n}\n")[0]
    assert "'Новое'" in tracker and "'Решено'" in tracker and "'Уточнение'" in tracker and "'Отклонено'" in tracker
    for old in ("Рассмотрение", "Реализовано", "Закрыто"):
        assert old not in tracker, old
    labels = re.search(r"const STATUS = \{(.*?)\};", ui, re.S).group(1)
    assert set(re.findall(r"\['([^']+)', 'st-", labels)) == {"Новое", "В работе", "Уточнение", "Решено", "Отклонено"}


# ---------- седьмой список 13.11: администрирование, колокольчик, баллы ----------

def test_admin_lands_in_administration():
    from mf.main import _home_for
    assert _home_for({"role": "admin"}) == "/panel#/admin" and _home_for({"role": "employee"}) == "/app" and _home_for({"role": "director"}) == "/panel"
    assert "me.role === 'admin' ? '/panel#/admin'" in (ROOT / "web" / "a" / "login.js").read_text(encoding="utf-8")
    js = (ROOT / "web" / "a" / "panel.js").read_text(encoding="utf-8")   # стартовая роли — startHash() (ТЗ 13.11: директор — «Сводка»)
    assert "ME.role === 'director' ? '#/summary' : ME.role === 'admin' ? '#/admin' : '#/queue'" in js
    assert "if (['', '#', '#/'].includes(location.hash) && startHash() !== '#/queue') { location.replace(startHash()); return; }" in js


def test_admin_tables_numbered_and_help_everywhere():
    from mf import glossary
    assert not glossary.validate()
    panel = (ROOT / "web" / "a" / "panel.js").read_text(encoding="utf-8")
    staff = (ROOT / "web" / "a" / "staff.js").read_text(encoding="utf-8")
    admin = panel.split("async function adminScreen()")[1].split("// ---------- «Справка»")[0] + staff
    keys = set(re.findall(r"helpBtn\('([a-z_]+)'", admin)) | set(re.findall(r"thHelp\('[^']*', '([a-z_]+)'\)", admin))
    assert keys and all(k in glossary.TERMS for k in keys), sorted(k for k in keys if k not in glossary.TERMS)
    assert "h('th', {}, t)" not in admin and ".map(t => h('th'" not in admin   # каждый заголовок колонки — через thHelp (с «?»)
    assert admin.count("rowNumTh()") >= 4 and admin.count("rowNumSpan(") >= 3   # сотрудники, категории, награды, заявки; филиалы, объекты (аватарки — сетка фото без номеров, 13.11)
    assert "colgroup([40, null, '28%', '15%', '21%', 56])" in staff   # имя уже, остальные шире, без пустой середины
    css = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.rownum \{[^}]*tabular-nums", css)


def test_boss_has_bell_with_counter():
    js = (ROOT / "web" / "a" / "boss.js").read_text(encoding="utf-8")
    assert "class: 'btn btn-sm btn-ghost bell'" in js and "ME.unread ? h('span', { class: 'n' }" in js


# ---------- восьмой список 13.11: карта, «Уточнение», без значка ИИ, только город ----------

def test_no_ai_mark_anywhere_help_says_it():
    from mf import glossary
    js = "\n".join(f.read_text(encoding="utf-8") for f in (ROOT / "web" / "a").glob("*.js"))
    assert "aiMark(" not in js and "aiBadge(" not in js and "ai-ic" not in (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
    t = glossary.TERMS
    assert t["repeated_topics"]["hint"].startswith("Темы находит ИИ по смыслу обращений") and t["brief"]["hint"].startswith("Коротко — пересказ ИИ, исходный текст ниже")
    for k in ("boss_greeting", "boss_answer", "command_result", "draft", "meeting_analysis"):
        assert "ИИ" in t[k]["hint"], k
    for k in ("repeated_topics", "brief", "summary", "similar", "meeting_title", "boss_greeting"):
        assert not re.search(r"порог|\d[.,]\d|эмбедд|gpt|модел", t[k]["hint"], re.I), k   # без технических параметров
    assert "Значок" not in t["meeting_title"]["hint"] and "значком" not in t["without_ai"]["hint"]


def test_clarify_chip_without_question_icon():
    css = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
    assert ".st-clarify::before" not in css and ".st-rejected::before" in css   # «Отклонено» с «×» остаётся


def test_branch_is_city_in_api_everywhere(c):
    login(c, 1)
    bad = re.compile(r"— (головной )?офис|— производство|\(командировка\)")
    for url in ("/api/panel/appeals?open=1", "/api/meetings", "/api/director/ideas", "/api/me", "/api/changes", "/api/staff/search?q=а"):
        r = c.get(url)
        assert r.status_code == 200 and not bad.search(r.text), url
    lg = c.get("/api/panel/league").json()   # «name» в лиге — название из справочника, на экран идёт «city»
    assert not any(bad.search(x.get("city") or "") for x in lg["items"]) and not any(bad.search(u.get("branch") or "") for u in lg["top"])
    rows = c.get("/api/panel/appeals?open=1").json()
    site = next(r for r in rows if r.get("site_city"))
    assert c.get(f"/api/appeals/{site['id']}").json()["branch"] == "объект · " + site["site_city"]
    from mf.ai import similar
    for cl in similar.clusters().get("clusters", []):
        assert not any(bad.search(b) for b in cl["branches"])


def test_map_labels_flip_instead_of_clipping():
    js = (ROOT / "web" / "a" / "mapview.js").read_text(encoding="utf-8")
    assert "const fitLabels = () =>" in js and "'flip-x'" in js and "ro.observe(lab)" in js   # подпись стала шире (шрифт) — пересчёт
    css = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
    assert ".marker.flip-x { flex-direction: row-reverse;" in css and re.search(r"\.map-country \{[^}]*font-size: 19px", css)
    assert "frame: MAP_DIRECTOR" in (ROOT / "web" / "a" / "panel.js").read_text(encoding="utf-8")
    assert "document.fonts.ready.then(() => fitLabels())" in js   # подписи пересчитываются, когда догрузился шрифт


def test_director_map_frame_and_objects_like_cities():
    """Карта директора (13.11): рамка 46…86° в. д. × 45…62° с. ш. (своя подложка), подписи стран в центре видимой части,
    объект — та же большая метка и карточка, что у города, «объект» — во второй строке; в легенде два пункта."""
    js = (ROOT / "web" / "a" / "mapview.js").read_text(encoding="utf-8")
    assert "const MAP_DIRECTOR = { lon0: 46, lon1: 86, lat0: 45, lat1: 62, aspect: 900 / 643, src: '/a/img/map-director.svg'" in js
    svg = (ROOT / "web" / "a" / "img" / "map-director.svg").read_text(encoding="utf-8")
    assert 'viewBox="0 0 900 643"' in svg
    assert "h('span', { class: 'm-site' }, 'объект'" in js and "icon('map-pin', { size: 30, fill: true, width: 1.5 })" in js
    assert "const sState = s.overdue ? ' m-late' : ' m-ok';" in js and "объект без открытых обращений" not in js
    css = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
    assert ".marker.site .mlabel {" not in css and ".marker.site .pin .ic" not in css   # объект оформлен как город


# ---------- объект на карте и в таблице «Филиалы» (13.11): очередь по городу объекта ----------

def test_queue_filter_by_site_and_rows_per_object(c):
    login(c, 1)
    rows = c.get("/api/panel/appeals?open=1&site=Атырау").json()
    assert rows and all(r["site_city"] == "Атырау" for r in rows) and "A-025" in [r["number"] for r in rows]
    by = c.get("/api/panel/summary?days=30").json()["by_branch"]
    sites = [b for b in by if b["kind"] == "field"]
    assert sites and all(b.get("site") for b in sites) and any(b["site"] == "Атырау" and b["total"] >= 1 for b in sites)   # строкой на каждый объект
    js = (ROOT / "web" / "a" / "panel.js").read_text(encoding="utf-8")
    assert "onSite: s => { S.filters = { site: s.city };" in js and "b.site + ' · объект'" in js and "if (k === 'site') return 'Объект: ' + v;" in js
    css = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
    assert ".map-layer { position: absolute; inset: 0; pointer-events: none; }" in css and ".map-layer .marker { pointer-events: auto; }" in css
