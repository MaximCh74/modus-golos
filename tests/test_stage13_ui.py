"""Пункт 4 очереди 12.11 — остальные экраны этапа 9 (статус обращения, совещание, профиль, лига, награды) по тем же правилам:
без горизонтальной прокрутки на телефоне, одна главная кнопка, нули не показываем, никаких нативных элементов (списки — pick,
срок поручения — datePick без календаря браузера), служебные плашки про режим разбора — значок с подсказкой."""
import os
import pathlib
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPT = open(ROOT / "tests" / "test_stage2.py", encoding="utf-8").read().split('TRANSCRIPT = """')[1].split('"""')[0]


def test_no_native_browser_elements_in_frontend():
    """Правило владельца: никаких нативных элементов — select, календарь, prompt/confirm; выбор файла только через скрытый input + кнопку."""
    bad = []
    for f in (ROOT / "web" / "a").glob("*.js"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//")[0]
            if re.search(r"h\('select'|type: 'date'|\bprompt\(|\bconfirm\(|\balert\(", code):
                bad.append(f"{f.name}:{n}: {line.strip()[:90]}")
    assert not bad, bad
    for f in (ROOT / "web").glob("*.html"):
        assert "<select" not in f.read_text(encoding="utf-8") and 'type="date"' not in f.read_text(encoding="utf-8"), f.name
    js = "\n".join(f.read_text(encoding="utf-8") for f in (ROOT / "web" / "a").glob("*.js"))
    assert "tag-demo" not in js.replace("'tag-demo'", "") or "aiBadge" in js   # плашки «демо-разбор без ИИ» заменены значком


playwright = pytest.importorskip("playwright.sync_api")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    data = tempfile.mkdtemp(prefix="mf-ui13-")
    env = {**os.environ, "MF_DATA_DIR": data, "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "mf.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1).read()
                break
            except Exception:   # noqa: BLE001
                time.sleep(0.2)
        else:
            raise RuntimeError("сервер не поднялся")
        yield base, data
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:   # noqa: BLE001
            pytest.skip(f"нет Chromium для Playwright: {e}")
        yield b
        b.close()


def _phone(browser, base, uid):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, locale="ru-RU", is_mobile=True, has_touch=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if uid:
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid})
    return ctx, page, errors


def _fits(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_meeting_review_pick_and_datepick(server, browser):
    base, data = server
    ctx, page, errors = _phone(browser, base, 2)
    try:
        mid = page.request.post(f"{base}/api/meetings", form={"title": "Планёрка", "transcript": TRANSCRIPT}).json()["id"]
        for _ in range(100):
            if page.request.get(f"{base}/api/meetings/{mid}").json()["status"] == "review":
                break
            page.wait_for_timeout(200)
        page.goto(f"{base}/app#/meeting"); page.wait_for_selector("text=Режим совещания")
        assert _fits(page) and page.locator(".btn-primary:visible").count() == 1   # одна главная кнопка — «Начать запись»
        assert page.locator(".tag-demo").count() == 0 and page.locator(".ai-ic").count() >= 1   # режим разбора — значок, не плашка
        page.goto(f"{base}/app#/meeting/{mid}"); page.wait_for_selector("button:has-text('Отправить')")
        assert _fits(page) and page.locator("select, input[type=date]").count() == 0
        assert page.locator(".btn-primary:visible").count() == 1   # «Отправить» — единственная главная
        assert page.locator(".mi .datepick").count() == 2 and page.locator(".mi .pickwrap").count() >= 3
        # срок поручения Айгерим («нет срока») — «другая дата» вручную, без календаря браузера
        second = page.locator(".mi .datepick").nth(1)
        second.locator(".pick").click(); second.locator(".pick-menu button:has-text('Другая дата')").click()
        inp = second.locator(".date-other")
        inp.fill("20.11"); inp.press("Enter"); page.wait_for_timeout(800)
        tasks = [i for i in page.request.get(f"{base}/api/meetings/{mid}").json()["items"] if i["kind"] == "task"]
        assert tasks[1]["due_date"].endswith("-11-20") and "no_due" not in tasks[1]["flags"]
        first = page.locator(".mi .datepick").nth(0)
        first.locator(".pick").click(); first.locator(".pick-menu button:has-text('через неделю')").click(); page.wait_for_timeout(800)
        tasks = [i for i in page.request.get(f"{base}/api/meetings/{mid}").json()["items"] if i["kind"] == "task"]
        assert tasks[0]["due_date"] and tasks[0]["due_date"] != tasks[1]["due_date"]
        assert not errors, errors
    finally:
        ctx.close()


def test_tasks_decisions_profile_league_rewards_on_phone(server, browser):
    base, data = server
    ctx, page, errors = _phone(browser, base, 1)
    try:
        page.goto(f"{base}/app#/decisions"); page.wait_for_selector("text=На решение"); page.wait_for_timeout(300)
        assert _fits(page) and page.locator("select").count() == 0
        assert page.locator("button:has-text('Принять')").count() >= 2 and page.locator(".btn-danger").count() == 0   # отказ — нейтральный
        page.goto(f"{base}/app#/u/6"); page.wait_for_selector(".profile-head"); page.wait_for_timeout(300)
        assert _fits(page) and "0" not in [b.inner_text() for b in page.locator(".stat b").all()]   # нули не показываем
        page.goto(f"{base}/app#/league"); page.wait_for_selector(".lg-row"); page.wait_for_timeout(300)
        assert _fits(page) and page.locator("table").count() == 0 and page.locator(".lg-row").count() >= 5
        assert "открыто 0" not in page.locator("#root").inner_text()
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": 17})   # у Ольги 130 баллов — «Мерч компании» доступен
        page.goto(f"{base}/app#/rewards"); page.wait_for_selector("text=Награды"); page.wait_for_timeout(300)
        assert _fits(page) and page.locator(".btn-primary").count() == 0 and page.locator("button:has-text('Получить')").count() >= 1
        assert "ещё 0" not in page.locator("#root").inner_text()
        page.request.post(f"{base}/api/auth/login-as", data={"user_id": 3})
        page.goto(f"{base}/app#/tasks"); page.wait_for_selector("text=Мои поручения"); page.wait_for_timeout(300)
        assert _fits(page)
        assert not errors, errors
    finally:
        ctx.close()


def test_track_page_one_main_button(server, browser):
    base, data = server
    c = sqlite3.connect(data + "/mf.db")
    tok_q = c.execute("SELECT tracking_token FROM appeals WHERE status='clarify' LIMIT 1").fetchone()[0]
    tok_w = c.execute("SELECT tracking_token FROM appeals WHERE status='in_progress' LIMIT 1").fetchone()[0]
    ctx, page, errors = _phone(browser, base, None)
    try:
        page.goto(f"{base}/t/{tok_q}"); page.wait_for_selector("text=Статус обращения"); page.wait_for_timeout(300)
        assert _fits(page) and page.locator(".btn-primary").count() == 1 and "Ответить" in page.locator(".btn-primary").inner_text()
        assert page.locator("details.sect summary").first.inner_text().startswith("История")
        page.goto(f"{base}/t/{tok_w}"); page.wait_for_selector("text=Статус обращения"); page.wait_for_timeout(300)
        assert _fits(page) and page.locator(".btn-primary").count() == 0
        assert not errors, errors
    finally:
        ctx.close()
