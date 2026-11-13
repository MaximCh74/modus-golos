"""Лига по образцу владельца 13.11 («Лучшие голоса компании»), панель и приложение: заголовок «Лига», пояснение — в «?»; пьедестал филиалов
2–1–3 (центр выше), места 4+ списком, метрики под «Подробнее»; топ-3 сотрудников карточками с фото, места 4–10 по линейке, своя строка
подсвечена, вне топ-10 — «Вы — N место»; витрина наград ведёт в «Награды»; телефон — вкладки; ширины 360–1440 без горизонтальной прокрутки."""
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

from mf import director
from mf.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def test_league_api_me_place_and_help_text(c):
    assert c.post("/api/auth/login-as", json={"user_id": 1}).status_code == 200
    d = c.get("/api/panel/league").json()
    assert d["me"]["id"] == 1 and d["me"]["show"] is False   # директору без баллов строка «Вы — N место» не нужна
    top = d["top"]
    for u in top:
        p = director.my_place(u["id"])
        assert p["points"] == u["points"] and p["rank"] == 1 + sum(1 for x in top if x["points"] > u["points"])
    from mf import glossary
    hint = glossary.TERMS["league"]["hint"] if hasattr(glossary, "TERMS") else c.get("/api/public/glossary").json()["terms"]["league"]["hint"]
    assert "50 %" in hint and "30 %" in hint and "20 %" in hint   # длинное пояснение — в «?»
    for f in ("panel.js", "app.js"):
        js = (ROOT / "web" / "a" / f).read_text(encoding="utf-8")
        assert "'Лига', helpBtn('league')" in js and "awardCard(" in js and "По качеству работы" not in js and "Качество работы с обращениями, не их число" not in js


# ---------- в браузере ----------

@pytest.fixture(scope="module")
def base():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "MF_DATA_DIR": tempfile.mkdtemp(prefix="mf-ui19-"), "MF_STT": "off", "MF_STT_WARMUP": "0", "OPENAI_API_KEY": "", "MF_PUBLIC_URL": ""}
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


_STATES: dict = {}   # демо-вход ограничен по частоте — входим по разу на пользователя


def _open(browser, base, uid, width, path):
    phone = width < 500
    key = (base, uid)
    ctx = browser.new_context(viewport={"width": width, "height": 844 if phone else 900}, locale="ru-RU", is_mobile=phone, has_touch=phone,
                              service_workers="block", storage_state=_STATES.get(key))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if key not in _STATES:
        assert page.request.post(f"{base}/api/auth/login-as", data={"user_id": uid}).ok
        _STATES[key] = ctx.storage_state()
    page.goto(base + path)
    page.wait_for_selector(".pod-step")
    page.wait_for_timeout(300)
    return ctx, page, errors


def _fits(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.parametrize("path", ["/panel#/league", "/app#/league"])
def test_podium_order_2_1_3_center_highest(base, browser, path):
    ctx, page, errors = _open(browser, base, 1, 1440, path)
    try:
        api = page.evaluate("API.get('/api/panel/league')")
        best = [b for b in api["items"] if b["enough"]][:3]
        steps = page.evaluate("""[...document.querySelectorAll('.pod-step')].map(s => ({ rank: s.dataset.rank, city: s.querySelector('.pod-city').textContent,
          n: s.querySelector('.laurel-n').textContent, score: s.querySelector('.pod-score').textContent, h: s.getBoundingClientRect().height, x: s.getBoundingClientRect().x }))""")
        assert [s["rank"] for s in steps] == ["2", "1", "3"] and [s["n"] for s in steps] == ["2", "1", "3"]
        assert [s["city"] for s in steps] == [best[1]["city"], best[0]["city"], best[2]["city"]]
        assert [s["score"] for s in steps] == [str(best[1]["score"]), str(best[0]["score"]), str(best[2]["score"])]
        assert steps[1]["h"] > steps[0]["h"] > steps[2]["h"] and steps[0]["x"] < steps[1]["x"] < steps[2]["x"]   # центр выше, второй слева
        assert page.locator(".laurel svg path").count() >= 6 * 2 * 3   # венок: ветви и листья линией
        rest = page.evaluate("[...document.querySelectorAll('.lg-rest-row .lg-place')].map(e => e.textContent)")
        assert rest == [str(i) for i in range(4, 4 + len(rest))]
        assert page.locator("table.league").count() == 0   # метрики — только под «Подробнее»
        page.click(".lg-more"); page.wait_for_selector("table.league tbody tr")
        assert page.locator(".lg-more").inner_text() == "Свернуть"
        assert page.evaluate("getComputedStyle(document.querySelector('.pod-score')).fontWeight") == "600"   # цифры — 600
        assert "Качество работы" not in page.locator("#root").inner_text() and "реализовано 50" not in page.locator("#root").inner_text()
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


def test_podium_with_fewer_than_three_branches(base, browser):
    ctx, page, errors = _open(browser, base, 1, 1440, "/panel#/league")
    try:
        r = page.evaluate("""(() => { const it = (rank, city, enough) => ({ id: rank, rank, city, name: city, score: 90 - rank * 10, enough, total: enough ? 5 : 1,
            done_share: .5, considered_share: .5, speed: .5, open: 1, overdue: 0 });
          const el = leagueBranches([it(1, 'Тюмень', true), it(2, 'Омск', true), it(3, 'Самара', false)]);
          return { steps: [...el.querySelectorAll('.pod-step')].map(s => s.dataset.rank), rest: [...el.querySelectorAll('.lg-rest-city')].map(s => s.textContent) }; })()""")
        assert r["steps"] == ["2", "1"] and r["rest"][0].startswith("Самара")   # пьедестал — из тех, что есть; без данных — в список
        assert not errors, errors
    finally:
        ctx.close()


def test_own_row_highlighted_or_place_line(base, browser):
    """У сотрудника своя строка подсвечена; не в топ-10 — внизу «Вы — N место, ★ баллы»."""
    for uid in (19, 24, 17):
        ctx, page, errors = _open(browser, base, uid, 1440, "/app#/league")
        try:
            d = page.evaluate("API.get('/api/panel/league')")
            me = d["me"]
            name = page.evaluate("ME.name")
            hi = page.locator(".lg-top .me")
            assert hi.count() == 1, uid
            if any(u["id"] == uid for u in d["top"]):
                assert name in hi.inner_text() and page.locator(".lg-me").count() == 0
                assert page.evaluate("getComputedStyle(document.querySelector('.lg-top .me')).backgroundColor") != "rgba(0, 0, 0, 0)"
            else:
                txt = page.locator(".lg-me").inner_text().replace("\n", " ")
                assert f"Вы — {me['rank']} место" in txt and str(me["points"]) in txt
            assert not errors, errors
        finally:
            ctx.close()


@pytest.mark.parametrize("width", [360, 375, 390, 768, 1024, 1280, 1440])
def test_league_widths_no_scroll_tabs_and_award(base, browser, width):
    ctx, page, errors = _open(browser, base, 19, width, "/app#/league")
    try:
        steps = page.evaluate("[...document.querySelectorAll('.pod-step')].map(s => s.getBoundingClientRect()).map(r => [r.left, r.right])")
        assert len(steps) == 3 and steps[0][0] >= 0 and steps[-1][1] <= width   # пьедестал ужимается в ширину экрана
        phone = width <= 760
        assert page.locator(".lg-seg").is_visible() == phone
        if phone:   # вкладки «Филиалы / Сотрудники», витрина под ними
            assert not page.locator(".lg-col-top").is_visible()
            page.click(".lg-seg .seg-btn[data-tab=top]")
            assert page.locator(".emp-card").first.is_visible() and not page.locator(".lg-col-branches").is_visible()
        else:
            l, r = page.locator(".lg-col-branches").bounding_box(), page.locator(".lg-col-top").bounding_box()
            assert (r["x"] >= l["x"] + l["width"] - 1) if width >= 1280 else (r["y"] >= l["y"] + l["height"] - 1)
        award = page.locator(".award-card")
        box, split = award.bounding_box(), page.locator(".lg-split").bounding_box()
        assert box["y"] >= split["y"] + split["height"] - 1 and abs(box["width"] - split["width"]) <= 2   # витрина — ниже, на всю ширину
        assert "Витрина наград" in award.inner_text() and "состав наград утверждает компания" in award.inner_text()
        names = page.evaluate("[...document.querySelectorAll('.emp-card .lg-who b')].map(b => b.scrollWidth <= b.clientWidth + 1)")
        assert all(names)   # имена топ-3 не обрезаются
        assert _fits(page) and not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("uid,path,target", [(19, "/app#/league", "/app#/rewards"), (1, "/panel#/league", "/app#/rewards")])
def test_award_card_opens_rewards(base, browser, uid, path, target):
    ctx, page, errors = _open(browser, base, uid, 1440, path)
    try:
        page.click(".award-card")
        page.wait_for_url("**" + target)
        page.wait_for_selector("text=Награды")
        assert not errors, errors
    finally:
        ctx.close()
