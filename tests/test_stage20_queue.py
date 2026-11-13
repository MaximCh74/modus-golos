"""Очередь — единый вид для всех ролей (ТЗ владельца 13.11): постоянные колонки «Обращение · Статус · Ответственный · Подразделение · Метки»,
кнопки «Вид» и выбора колонок нет; в ячейке — точка просрочки, номер · город · текст, без значков; метки из данных обращения прозрачными
чипами (две, остальное «+N»); вкладка «История» — все подряд с A-001, под номером дата; телефон — карточки, метки под текстом."""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mf import appeals, demo
from mf.main import app

ROOT = Path(__file__).resolve().parent.parent
HEADS = ["обращение", "статус", "ответственный", "подразделение", "метки"]


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def test_labels_rules():
    L = appeals.labels_for
    assert L({"priority": "high", "author_urgency": "now", "cluster_id": 3, "supports": 2, "is_anonymous": 1, "meeting_id": 1}) == \
        ["срочно", "мешает сейчас", "повтор", "со стенограммы", "поддержали 2", "анонимно"]
    assert L({"priority": "low"}) == ["не срочно"] and L({"priority": "medium"}) == [] and L({"priority": "low", "type": "praise"}) == []
    assert L({"priority": "medium", "source": "meeting"}) == ["со стенограммы"]


def test_history_tab_all_from_first_with_labels(c):
    assert c.post("/api/auth/login-as", json={"user_id": 1}).status_code == 200
    rows = c.get("/api/panel/appeals?history=1").json()
    nums = [r["number"] for r in rows]
    assert nums[0] == "A-001" and nums == sorted(nums) and len(rows) == len(set(nums))
    assert {r["status"] for r in rows} & {"done", "closed", "rejected"} and {r["status"] for r in rows} & {"new", "in_progress"}   # любые статусы
    assert all("labels" in r and isinstance(r["labels"], list) for r in rows)
    att = c.get("/api/panel/appeals?attention=1").json()
    assert att and all("labels" in r for r in att)


@pytest.mark.skipif(not demo.FIXTURE.is_file(), reason="нет снапшота")
def test_demo_snapshot_labels_on_most_rows_and_varied(c):
    """Демо-данные: метки — у большинства открытых строк и разные (приоритеты и оценки автора проставлены в снапшоте)."""
    demo.reset()
    assert c.post("/api/auth/login-as", json={"user_id": 1}).status_code == 200
    rows = c.get("/api/panel/appeals?open=1").json()
    with_labels = [r for r in rows if r["labels"]]
    kinds = {t.split(" ")[0] for r in rows for t in r["labels"]}
    assert len(with_labels) >= 0.7 * len(rows), (len(with_labels), len(rows))
    assert {"срочно", "не", "мешает", "повтор", "поддержали"} <= kinds, kinds


# ---------- в браузере ----------

@pytest.fixture(scope="module")
def base():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui20-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "mf.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/api/health", timeout=1).read()
                break
            except Exception:   # noqa: BLE001
                time.sleep(0.2)
        else:
            raise RuntimeError("сервер не поднялся")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:   # noqa: BLE001
            pytest.skip(f"нет Chromium для Playwright: {e}")
        yield b
        b.close()


_STATES: dict = {}


def _open(browser, base, uid, width, path):
    phone = width < 500
    key = (base, uid)
    ctx = browser.new_context(viewport={"width": width, "height": 812 if phone else 900}, locale="ru-RU", is_mobile=phone, has_touch=phone,
                              service_workers="block", storage_state=_STATES.get(key))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if key not in _STATES:
        assert page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid}).ok
        _STATES[key] = ctx.storage_state()
    page.goto(base + path)
    page.wait_for_selector("table.queue tbody tr, .qcard")
    page.wait_for_timeout(400)
    return ctx, page, errors


@pytest.mark.parametrize("uid", [1, 2, 15])   # директор, ответственный, администратор — один вид
def test_fixed_columns_no_view_button_no_icons(base, browser, uid):
    ctx, page, errors = _open(browser, base, uid, 1440, "/panel#/queue?open=1")
    try:
        assert [t.strip().lower() for t in page.locator("table.queue thead th").all_inner_texts()] == HEADS
        assert page.locator(".view-btn").count() == 0 and page.locator("text=Колонки").count() == 0 and page.locator("button", has_text="Фильтры").count() == 1
        assert page.locator("td.q-main svg").count() == 0 and page.locator("td.q-main .mini").count() == 0   # значков типа, △ и 👍 нет
        cells = page.evaluate("""[...document.querySelectorAll('table.queue tbody tr')].map(tr => ({ main: tr.querySelector('td.q-main').innerText,
          chips: [...tr.querySelectorAll('.q-labels .q-tag:not(.q-more)')].map(x => x.textContent), more: (tr.querySelector('.q-more') || {}).textContent || '' }))""")
        assert all(" · " in x["main"] for x in cells)   # номер · город · текст
        assert all(len(x["chips"]) <= 2 for x in cells) and any(x["more"].startswith("+") for x in cells)   # не больше двух, остальное «+N»
        api = page.evaluate("API.get('/api/panel/appeals?open=1')")
        for r, x in zip(api, cells):
            assert x["chips"] == r["labels"][:2] and (x["more"] == (f"+{len(r['labels']) - 2}" if len(r["labels"]) > 2 else ""))
        chip = page.locator(".q-tag").first
        assert page.evaluate("(el) => getComputedStyle(el).backgroundColor", chip.element_handle()) in ("rgba(0, 0, 0, 0)", "transparent")   # прозрачные
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") and not errors, errors
    finally:
        ctx.close()


def test_tabs_and_history_from_first_with_date(base, browser):
    ctx, page, errors = _open(browser, base, 1, 1440, "/panel#/queue")
    try:
        assert page.locator(".tabs.q a").all_inner_texts() == ["Требуют внимания", "Все открытые", "Мои", "Закрытые", "История"]
        page.click(".tabs.q a:has-text('История')"); page.wait_for_timeout(700)
        nums = page.evaluate("[...document.querySelectorAll('table.queue tbody tr .num')].map(n => n.textContent)")
        assert nums[0] == "A-001" and nums == sorted(nums)
        first = page.locator("table.queue tbody tr").first
        date = first.locator(".q-date").inner_text()
        assert len(date) == 10 and date.count(".") == 2   # под номером мелко дата создания
        assert first.locator(".q-date").bounding_box()["y"] > first.locator(".num").bounding_box()["y"]
        statuses = set(page.evaluate("[...document.querySelectorAll('table.queue tbody tr td:nth-child(2)')].map(t => t.innerText.trim())"))
        assert len(statuses) >= 4   # любые статусы
        page.click(".tabs.q a:has-text('Все открытые')"); page.wait_for_timeout(500)
        assert page.locator(".q-date").count() == 0
        assert not errors, errors
    finally:
        ctx.close()


def test_phone_cards_labels_under_text(base, browser):
    ctx, page, errors = _open(browser, base, 1, 375, "/panel#/queue?open=1")
    try:
        cards = page.evaluate("""[...document.querySelectorAll('.qcard')].filter(c => c.querySelector('.qcard-labels')).map(c => {
          const t = c.querySelector('.qcard-text').getBoundingClientRect(), l = c.querySelector('.qcard-labels').getBoundingClientRect(); return l.top >= t.bottom - 1; })""")
        assert cards and all(cards)
        assert page.locator(".qcard svg").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") and not errors, errors
    finally:
        ctx.close()
