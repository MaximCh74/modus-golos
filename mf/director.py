"""Главная директора (этап 4): факты за 7 дней → сводка (ИИ только пересказывает, числа проверяются; без ключа — шаблон),
лига филиалов по качеству работы с обращениями, топ сотрудников, данные карты (реальные города + слой «Объекты»)."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import timedelta

from . import appeals, db, geo, meetings
from .ai import llm, similar

log = logging.getLogger("mf.director")
CACHE_TTL = 3600
# координаты городов объектов для слоя «Объекты» (командированные указывают город текстом, без геолокации)
# координаты городов объектов — справочник mf/geo.py (все областные центры KZ и RU, промышленные города, точки администратора)


def _city_key(s: str) -> str:
    return re.split(r"[,;(]", (s or "").strip().lower())[0].strip()


# ---------- факты ----------

def facts(days: int = 7) -> dict:
    since = db.iso(db.now() - timedelta(days=days))
    new = db.one("SELECT COUNT(*) AS n FROM appeals WHERE created_at >= ?", (since,))["n"]
    done = db.one("SELECT COUNT(*) AS n FROM appeals WHERE closed_at >= ? AND status IN ('done','closed') AND type != 'praise'", (since,))["n"]
    open_rows = db.q("SELECT author_urgency FROM appeals WHERE status IN ('new','review','clarify','in_progress')")
    urgent_open = sum(1 for r in open_rows if r["author_urgency"] == "now")
    dq = meetings.director_ideas({"role": "director", "id": 0})
    pending = dq["pending"]
    waits = [p.get("wait_days") or 0 for p in pending]
    tasks = meetings.overdue_summary({"role": "director", "id": 0})
    cl = None
    try:
        c = similar.clusters()
        if c["clusters"]:
            top = c["clusters"][0]
            cl = {"label": top["label"], "category": top["category"], "size": top["size"], "cities": top["branches"], "id": top["id"], "engine": c["engine"]}
    except Exception as e:   # noqa: BLE001
        log.warning("кластеры для сводки: %s", e)
    return {"period_days": days, "new": new, "done": done, "open": len(open_rows), "urgent_open": urgent_open,
            "decisions_pending": len(pending), "decisions_over_threshold": dq["over_threshold"], "decision_threshold_days": dq["threshold_days"],
            "decision_max_days": int(max(waits)) if waits else 0, "tasks_overdue": tasks["overdue"], "tasks_open": tasks["open"],
            "no_news": appeals.no_news_count(), "news_days": appeals.news_days_setting(), "cluster": cl}


def greeting(user: dict) -> str:
    hour = (db.now() + timedelta(hours=int(db.setting("tz_offset_hours", 5) or 5))).hour   # Казахстан/Омск: UTC+5…+6
    word = "Доброе утро" if 5 <= hour < 12 else "Добрый день" if hour < 18 else "Добрый вечер"
    from . import auth
    return f"{word}, {auth.display_name(user)}."


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    m10, m100 = n % 10, n % 100
    return f"{n} " + (forms[0] if m10 == 1 and m100 != 11 else forms[1] if 2 <= m10 <= 4 and not 10 <= m100 <= 20 else forms[2])


def template(f: dict, user: dict) -> list[dict]:
    """Шаблонная сводка: каждое предложение ведёт в свой раздел. Используется без ключа и если ИИ исказил числа."""
    out = [{"text": greeting(user), "href": None}]
    out.append({"text": f"За {_plural(f['period_days'], ('день', 'дня', 'дней'))} пришло {_plural(f['new'], ('обращение', 'обращения', 'обращений'))}, решено {f['done']}; открыто {f['open']}" +
                        (f", из них мешают работать прямо сейчас {f['urgent_open']}" if f["urgent_open"] else "") + ".",
                "href": "/panel#/queue?open=1" + ("&urgency=now" if f["urgent_open"] else "")})
    if f["decisions_pending"]:
        s = f"Вашего решения ждут {_plural(f['decisions_pending'], ('предложение', 'предложения', 'предложений'))}"
        if f["decisions_max_days"] if "decisions_max_days" in f else f["decision_max_days"]:
            s += f", самое давнее — {_plural(f['decision_max_days'], ('день', 'дня', 'дней'))}"
        out.append({"text": s + ".", "href": "/panel#/decisions"})
    if f["cluster"]:
        c = f["cluster"]
        out.append({"text": f"Главная повторяющаяся тема — {c['category'] or 'без категории'}: {_plural(c['size'], ('обращение', 'обращения', 'обращений'))} из {_plural(len(c['cities']), ('города', 'городов', 'городов'))}.",
                    "href": f"/panel#/queue?cluster_id={c['id']}"})
    if f["tasks_overdue"]:
        out.append({"text": f"Просрочено {_plural(f['tasks_overdue'], ('поручение', 'поручения', 'поручений'))} с совещаний.", "href": "/panel#/meetings?overdue=1"})
    if f["no_news"]:
        out.append({"text": f"Без новостей авторам дольше {f['news_days']} дней: {f['no_news']}.", "href": "/panel#/queue?status=in_progress"})
    return out


def _word(n: int, forms: tuple[str, str, str]) -> str:
    return _plural(n, forms).split(" ", 1)[1]


def _lower_first(t: str) -> str:
    return t[:1].lower() + t[1:] if len(t) > 1 and t[1:2].islower() else t   # «1С …» и аббревиатуры не трогаем


def items(f: dict) -> list[dict]:
    """Сводка списком из фактов сервера (замечание владельца 13.11): строки — сегменты [текст, жирный], числа жирным; у строки — ссылка."""
    out = [{"key": "new", "parts": [["Поступило: ", False], [str(f["new"]), True]], "href": "/panel#/queue?open=1"},
           {"key": "done", "parts": [["Решено: ", False], [str(f["done"]), True]], "href": "/changes"}]
    # «мешают работать» — вложенной строкой под «Открыто» (образец владельца 13.11); красная точка + тёмная цифра, красного текста нет
    op = {"key": "open", "parts": [["Открыто: ", False], [str(f["open"]), True]], "href": "/panel#/queue?open=1" + ("&urgency=now" if f["urgent_open"] else "")}
    if f["urgent_open"]:
        op["sub"] = [["из них мешают работать: ", False], [str(f["urgent_open"]), True, "dot"]]
    out.append(op)
    if f["decisions_pending"]:
        dp = [["Ждут вашего решения: ", False], [str(f["decisions_pending"]), True]]
        if f["decision_max_days"]:
            dp += [[", самое давнее — ", False], [str(f["decision_max_days"]), True], [" " + _word(f["decision_max_days"], ("день", "дня", "дней")), False]]
        out.append({"key": "decisions", "parts": dp, "href": "/panel#/decisions"})
    if f["cluster"]:
        c = f["cluster"]; n = len(c["cities"])
        out.append({"key": "theme", "parts": [["Главная тема: ", False], [_lower_first(c["category"] or "без категории") + " — ", False], [str(c["size"]), True],
                              [" " + _word(c["size"], ("обращение", "обращения", "обращений")) + " из ", False], [str(n), True],
                              [" " + _word(n, ("города", "городов", "городов")), False]], "href": f"/panel#/queue?cluster_id={c['id']}"})
    for it in out:   # text — строка целиком (озвучка, команда «прочитай сводку»): «Открыто: 24, из них мешают работать: 7»
        it["text"] = "".join(p[0] for p in it["parts"]) + (", " + "".join(p[0] for p in it["sub"]) if it.get("sub") else "")
    return out


def _sentences(greet: str, f: dict, its: list[dict]) -> list[dict]:
    """Тот же текст предложениями — для озвучки, команды «прочитай сводку» и старых клиентов."""
    return ([{"text": greet, "href": None}, {"text": f"За {_plural(f['period_days'], ('день', 'дня', 'дней'))}:", "href": None}]
            + [{"text": it["text"] + ".", "href": it["href"]} for it in its])


def ai_phrase(f: dict) -> str | None:
    """ИИ — только фраза к приветствию, без чисел; без ключа или при сбое — без фразы."""
    if not llm.available():
        return None
    try:
        phrase = llm.director_greeting({k: v for k, v in f.items() if k != "cluster"} | {"cluster_category": f["cluster"] and f["cluster"]["category"]})
    except llm.LLMError as e:
        log.warning("приветствие сводки: %s", e)
        return None
    return None if llm.has_forbidden(phrase) else phrase


SUMMARY_FMT = 3   # формат списка сводки: при изменении (13.11 — красная точка у «мешают работать») старый кэш пересчитывается


def build(f: dict, user: dict, phrase: str | None, v: str) -> dict:
    greet = greeting(user) + (" " + phrase if phrase else "")
    its = items(f)
    return {"greeting": greet, "period": f"За {_plural(f['period_days'], ('день', 'дня', 'дней'))}:", "items": its,
            "sentences": _sentences(greet, f, its), "engine": "openai" if phrase else "template", "facts": f, "at": db.now_iso(), "version": v, "fmt": SUMMARY_FMT,
            "lines": _lines(f)}


def _numbers(text: str) -> set[int]:
    return {int(x) for x in re.findall(r"\d+", text)}


def _allowed_numbers(f: dict) -> set[int]:
    allowed = {f["period_days"], f["new"], f["done"], f["open"], f["urgent_open"], f["decisions_pending"], f["decisions_over_threshold"],
               f["decision_threshold_days"], f["decision_max_days"], f["tasks_overdue"], f["tasks_open"], f["no_news"], f["news_days"]}
    if f["cluster"]:
        allowed |= {f["cluster"]["size"], len(f["cluster"]["cities"])}
    allowed |= {1}   # «1С» в названии категории
    return allowed


def _link_for(sentence: str, f: dict) -> str | None:
    t = sentence.lower()
    if "решени" in t:
        return "/panel#/decisions"
    if "поручен" in t or "просроч" in t:
        return "/panel#/meetings?overdue=1"
    if "тема" in t or (f["cluster"] and (f["cluster"]["category"] or "").lower()[:10] in t):
        return f"/panel#/queue?cluster_id={f['cluster']['id']}" if f["cluster"] else "/panel#/queue"
    if "новост" in t:
        return "/panel#/queue?status=in_progress"
    if "мешают" in t:
        return "/panel#/queue?open=1&urgency=now"
    if "обращен" in t:
        return "/panel#/queue?open=1"
    return None


def ai_sentences(f: dict, user: dict) -> list[dict] | None:
    """LLM пересказывает факты; каждое число в ответе должно быть среди фактов, иначе — шаблон."""
    if not llm.available():
        return None
    payload = {**f, "greeting": greeting(user), "cluster": f["cluster"] and {k: v for k, v in f["cluster"].items() if k != "id"}}
    allowed = _allowed_numbers(f)
    for attempt in range(2):   # числа не из фактов или запрещённый синоним → повторная генерация, затем шаблон
        try:
            sentences = llm.director_summary(payload)
        except llm.LLMError as e:
            log.warning("сводка: %s", e)
            return None
        bad = next((s for s in sentences if not llm.numbers_in_answer(s) <= allowed or llm.negates_nonzero(s, f)), None)
        if bad:
            log.warning("сводка (попытка %d): лишние числа в «%s»", attempt + 1, bad)
            continue
        word = next((w for s in sentences if (w := llm.has_forbidden(s))), None)
        if word:
            log.warning("сводка (попытка %d): запрещённый термин «%s»", attempt + 1, word)
            payload = {**payload, "note": f"В прошлом ответе было слово «{word}» — так нельзя, используй термины из глоссария."}
            continue
        return [{"text": s, "href": _link_for(s, f)} for s in sentences]
    return None


def version() -> str:
    """Версия данных: меняется с любым событием — сводка пересчитывается при новых событиях или раз в час."""
    e = db.one("SELECT COUNT(*) AS n, MAX(id) AS m FROM appeal_events")
    i = db.one("SELECT COUNT(*) AS n, MAX(id) AS m FROM meeting_items")
    return hashlib.sha1(f"{e['n']}-{e['m']}-{i['n']}-{i['m']}".encode()).hexdigest()[:12]


def summary(user: dict, refresh: bool = False, force_template: bool = False) -> dict:
    key = f"director_summary:{user['id']}"
    cached = db.setting(key)
    v = version()
    if force_template:
        return build(facts(), user, None, v)
    age = (db.now() - db.parse(cached["at"])).total_seconds() if cached and cached.get("at") else None
    if cached and not refresh and cached.get("version") == v and age < CACHE_TTL and cached.get("fmt") == SUMMARY_FMT:   # старый формат кэша — пересчитать
        return cached
    if cached and refresh and age is not None and age < 60 and cached.get("fmt") == SUMMARY_FMT:   # F-07: «обновить» не чаще раза в минуту — каждое обновление это вызов ИИ
        return cached
    f = facts()
    out = build(f, user, ai_phrase(f), v)
    db.set_setting(key, out)
    return out


def _lines(f: dict) -> dict:
    return {"urgent_open": f["urgent_open"], "decisions_over_threshold": f["decisions_over_threshold"], "decisions_pending": f["decisions_pending"],
            "tasks_overdue": f["tasks_overdue"], "no_news": f["no_news"], "news_days": f["news_days"], "threshold_days": f["decision_threshold_days"]}


# ---------- лига и топ ----------

def league() -> dict:
    """Филиалы по качеству работы с обращениями: доля реализованного, доля рассмотренных, скорость первого ответа — веса в settings.league_weights.
    Количество обращений филиал не ранжирует (ТЗ v1.1 §1). «Объект» — вне лиги."""
    w = {**{"done": 0.5, "considered": 0.3, "speed": 0.2}, **(db.setting("league_weights", {}) or {})}
    rows = [appeals.decorate(r) for r in db.q(appeals.BASE_SELECT)]
    branches = db.q("SELECT * FROM branches WHERE kind != 'field' ORDER BY is_hq DESC, name")
    sla_default = appeals.DEFAULT_SLA
    out = []
    for b in branches:
        items = [r for r in rows if r["branch_id"] == b["id"]]
        total = len(items)
        considered = [r for r in items if r["first_response_at"]]
        done = [r for r in items if r["status"] in ("done", "closed") and r["type"] != "praise"]
        speeds = []
        for r in considered:
            h = r["first_response_hours"]
            sla = r["sla"] or sla_default
            if h is not None:
                speeds.append(max(0.0, 1 - h / (2 * sla)))   # 1 — мгновенно, 0 — вдвое дольше SLA
        done_share = len(done) / total if total else 0.0
        considered_share = len(considered) / total if total else 0.0
        speed = sum(speeds) / len(speeds) if speeds else 0.0
        score = w["done"] * done_share + w["considered"] * considered_share + w["speed"] * speed
        out.append({"id": b["id"], "code": b["code"], "name": b["name"], "city": b["city"], "total": total, "open": sum(1 for r in items if r["status"] in appeals.OPEN),
                    "done": len(done), "done_share": round(done_share, 2), "considered_share": round(considered_share, 2), "speed": round(speed, 2),
                    "overdue": sum(1 for r in items if r["overdue"]), "score": round(score * 100), "enough": total >= 3})
    out.sort(key=lambda x: (-x["enough"], -x["score"]))
    for i, x in enumerate(out, 1):
        x["rank"] = i
    return {"weights": w, "items": out}


def top_employees(limit: int = 10) -> list[dict]:
    rows = db.q("""SELECT u.id, u.name, u.position, u.avatar, """ + appeals.BRANCH_LABEL + """ AS branch, b.city AS city, COALESCE(SUM(l.amount), 0) AS points
                   FROM users u LEFT JOIN branches b ON b.id=u.branch_id LEFT JOIN points_ledger l ON l.user_id=u.id
                   WHERE u.active=1 GROUP BY u.id HAVING points > 0 ORDER BY points DESC, u.name LIMIT ?""", (limit,))
    for r in rows:
        r["avatar"] = appeals.avatar_url(r["id"], r["avatar"])
        r["implemented"] = db.one("""SELECT COUNT(*) AS n FROM appeals a JOIN appeal_authors aa ON aa.appeal_id=a.id
                                     WHERE aa.user_id=? AND a.status IN ('done','closed') AND a.type != 'praise' AND a.is_anonymous=0""", (r["id"],))["n"]
        r["thanks"] = db.one("SELECT COUNT(*) AS n FROM thanks t JOIN appeal_authors aa ON aa.appeal_id=t.appeal_id WHERE aa.user_id=?", (r["id"],))["n"]
    return rows


# ---------- карта ----------

def map_data() -> dict:
    rows = [appeals.decorate(r) for r in db.q(appeals.BASE_SELECT)]
    branches = db.q("SELECT * FROM branches ORDER BY is_hq DESC, name")
    out_b = []
    for b in branches:
        if b["kind"] == "field":
            continue
        items = [r for r in rows if r["branch_id"] == b["id"]]
        open_items = [r for r in items if r["status"] in appeals.OPEN]
        cats: dict[str, int] = {}
        for r in open_items:
            if r["category"]:
                cats[r["category"]] = cats.get(r["category"], 0) + 1
        clusters: dict[int, int] = {}
        for r in open_items:
            if r.get("cluster_id"):
                clusters[r["cluster_id"]] = clusters.get(r["cluster_id"], 0) + 1
        out_b.append({"id": b["id"], "code": b["code"], "name": b["name"], "city": b["city"], "kind": b["kind"], "lat": b["lat"], "lng": b["lng"],
                      "is_hq": b["is_hq"], "timezone": b["timezone"] or geo.timezone_for(b["city"]),   # часы по городам (ТЗ 13.11)
                      "total": len(items), "open": len(open_items), "overdue": sum(1 for r in open_items if r["overdue"]),
                      "urgent": sum(1 for r in open_items if r.get("author_urgency") == "now"),
                      "unassigned": sum(1 for r in open_items if r["unassigned"]),
                      "top_category": max(cats.items(), key=lambda kv: kv[1])[0] if cats else None,
                      "clusters": sorted(clusters.items(), key=lambda kv: -kv[1])[:3],
                      "last_at": max((r["created_at"] for r in items), default=None)})
    sites: dict[str, dict] = {}
    for r in rows:
        if not r.get("site_city"):
            continue
        g = geo.lookup(r["site_city"])
        key = geo.norm(g["name"] if g else r["site_city"])
        s = sites.setdefault(key, {"city": g["name"] if g else r["site_city"].split(",")[0].strip(), "total": 0, "open": 0, "overdue": 0, "numbers": [],
                                   "timezone": geo.timezone_for(g["name"] if g else r["site_city"])})
        s["total"] += 1
        is_open = r["status"] in appeals.OPEN
        s["open"] += 1 if is_open else 0
        s["overdue"] += 1 if is_open and r["overdue"] else 0
        s["numbers"].append(r["number"])
        if g:
            s["lat"], s["lng"] = g["lat"], g["lng"]
    return {"branches": out_b, "sites": list(sites.values()), "unplaced": [x for x in sites.values() if "lat" not in x]}   # «без метки» — админ ставит точку


def public_map_data(base_url: str) -> dict:
    """Карта на стартовой без входа (этап 6 §3): города с типом, открытых и решённых за месяц, главной темой и QR; объекты — только
    город и число открытых. Служебное (просрочки, «мешают сейчас», без ответственного, номера) наружу не отдаём."""
    full = map_data()
    since = db.iso(db.now() - timedelta(days=30))
    done = {r["branch_id"]: r["n"] for r in db.q("SELECT branch_id, COUNT(*) AS n FROM appeals WHERE status IN ('done','closed') AND type != 'praise' AND closed_at >= ? GROUP BY branch_id", (since,))}
    kind_label = {"office": "офис", "production": "производство", "field": "объект"}
    branches = []
    for b in full["branches"]:
        branches.append({"id": b["id"], "code": b["code"], "name": b["name"], "city": b["city"], "kind": b["kind"],
                         "kind_label": "головной офис" if b["code"] == "OMSK" else kind_label.get(b["kind"], b["kind"]), "lat": b["lat"], "lng": b["lng"],
                         "open": b["open"], "done_month": done.get(b["id"], 0), "top_category": b["top_category"],
                         "qr_url": f"{base_url}/q/{b['code']}", "qr_svg": f"/api/public/qr/{b['code']}.svg", "form_url": f"/q/{b['code']}"})
    sites = [{"city": s["city"], "lat": s.get("lat"), "lng": s.get("lng"), "open": s["open"]} for s in full["sites"]]
    field = db.one("SELECT id, code, name FROM branches WHERE kind='field'")
    if field:
        field = {**field, "qr_url": f"{base_url}/q/{field['code']}", "qr_svg": f"/api/public/qr/{field['code']}.svg", "form_url": f"/q/{field['code']}"}
    return {"branches": branches, "sites": sites, "field": field}


# ---------- озвучка сводки ----------

def tts_cached(text: str) -> tuple[bytes, str]:
    """mp3 озвучки текста (OpenAI TTS); кэш по хэшу текста в папке данных — повторные нажатия и reset не тратят вызовы.
    Используется для сводки и для голосового ответа на команду директора (этап 6 §2)."""
    from pathlib import Path
    from . import config
    key = hashlib.sha1((llm.TTS_MODEL + "|" + llm.TTS_VOICE + "|" + llm.TTS_INSTRUCTIONS + "|" + f"{llm.TTS_SPEED:.2f}" + "|" + text).encode("utf-8")).hexdigest()[:16]
    cache = Path(config.DATA_DIR) / "tts"
    cache.mkdir(exist_ok=True)
    f = cache / f"{key}.mp3"
    if f.is_file():
        return f.read_bytes(), "cache"
    audio = llm.speak(text)
    f.write_bytes(audio)
    return audio, "openai"


def summary_audio(user: dict) -> tuple[bytes, str]:
    d = summary(user)
    return tts_cached(" ".join(s["text"] for s in d["sentences"]))
