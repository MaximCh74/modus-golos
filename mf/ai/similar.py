"""Похожие обращения и кластеры «Повторяющиеся темы» (ТЗ v1.1 §7).
С ключом — эмбеддинги OpenAI (text-embedding-3-small), кэш векторов в таблице appeal_embeddings, косинусная близость.
Без ключа — честный запасной режим «по ключевым словам»: совпадение основ слов (Жаккар) + общая категория по словарю.
Порог настраивается (settings.similar_threshold), кластер — два и более обращения."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re

from .. import db
from . import fallback

log = logging.getLogger("mf.ai.similar")
EMBED_MODEL = os.environ.get("MF_EMBED_MODEL", "text-embedding-3-small")
DEFAULTS = {"embeddings": 0.45, "keywords": 0.22}          # «похоже на ваше» при отправке
CLUSTER_DEFAULTS = {"embeddings": 0.50, "keywords": 0.22}  # «одна и та же тема» для кластеров — строже, иначе всё сцепляется
STOP = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только её мне было вот от меня ещё нет о из
ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они
тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого
какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть
после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть
том нельзя такой им более всегда конечно всю между это при нужна нужно хотелось предлагаю предлагает можно ли бы также очень""".split())


def available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def threshold(engine: str, kind: str = "similar") -> float:
    cfg = db.setting("similar_threshold" if kind == "similar" else "cluster_threshold", {}) or {}
    return float(cfg.get(engine, (DEFAULTS if kind == "similar" else CLUSTER_DEFAULTS)[engine]))


# ---------- ключевые слова (запасной режим) ----------

def _stems(text: str) -> set[str]:
    words = re.findall(r"[а-яёa-zәіңғүұқөһ0-9]+", (text or "").lower().replace("ё", "е"))
    return {w[:5] for w in words if len(w) >= 4 and w not in STOP}


def keyword_score(a: str, b: str, cats: list[dict]) -> float:
    sa, sb = _stems(a), _stems(b)
    if not sa or not sb:
        return 0.0
    jac = len(sa & sb) / len(sa | sb)
    ca = fallback.classify(a, cats)["category_id"]
    cb = fallback.classify(b, cats)["category_id"]
    bonus = 0.2 if ca and ca == cb else 0.0
    return round(min(1.0, jac + bonus), 3)


# ---------- эмбеддинги ----------

def embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI
    from . import budget
    budget.spend("embeddings")   # потолок суток → исключение → вызывающий код честно переходит на ключевые слова
    r = OpenAI(timeout=30).embeddings.create(model=EMBED_MODEL, input=[t[:4000] for t in texts])
    return [d.embedding for d in r.data]


def _hash(text: str) -> str:
    return hashlib.sha1((EMBED_MODEL + "|" + text).encode("utf-8")).hexdigest()


def vectors_for(rows: list[dict]) -> dict[int, list[float]]:
    """Векторы обращений из кэша; недостающие считаются одним запросом и сохраняются."""
    out, missing = {}, []
    for r in rows:
        h = _hash(r["text"])
        c = db.one("SELECT vec FROM appeal_embeddings WHERE appeal_id=? AND hash=?", (r["id"], h))
        if c:
            out[r["id"]] = json.loads(c["vec"])
        else:
            missing.append((r, h))
    if missing:
        vecs = embed([r["text"] for r, _ in missing])
        for (r, h), v in zip(missing, vecs):
            db.ex("INSERT INTO appeal_embeddings(appeal_id, model, hash, vec) VALUES(?,?,?,?) ON CONFLICT(appeal_id) DO UPDATE SET model=excluded.model, hash=excluded.hash, vec=excluded.vec",
                  (r["id"], EMBED_MODEL, h, json.dumps(v)))
            out[r["id"]] = v
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


# ---------- публичные функции ----------

def _open_rows(exclude_id: int | None = None) -> list[dict]:
    rows = db.q("""SELECT a.id, a.number, a.text, a.status, a.category_id, c.name AS category, b.name AS branch, a.branch_id,
                   (SELECT COUNT(*) FROM supports s WHERE s.appeal_id=a.id) AS supports
                   FROM appeals a LEFT JOIN categories c ON c.id=a.category_id LEFT JOIN branches b ON b.id=a.branch_id
                   WHERE a.status IN ('new','review','clarify','in_progress') AND a.type != 'praise' ORDER BY a.id""")
    return [r for r in rows if r["id"] != exclude_id]


def similar(text: str, exclude_id: int | None = None, limit: int = 3) -> dict:
    """→ {engine, threshold, items: [{id, number, text, score, category, status, supports}]}. Пусто — если ничего не похоже."""
    text = (text or "").strip()
    rows = _open_rows(exclude_id)
    if len(text) < 8 or not rows:
        return {"engine": "embeddings" if available() else "keywords", "items": [], "threshold": None}
    cats = db.q("SELECT id, name FROM categories")
    engine = "keywords"
    scored = []
    if available():
        try:
            vecs = vectors_for(rows)
            q = embed([text])[0]
            scored = [(cosine(q, vecs[r["id"]]), r) for r in rows]
            engine = "embeddings"
        except Exception as e:   # noqa: BLE001 — сеть/лимит: честно падаем на ключевые слова
            log.warning("эмбеддинги недоступны (%s) — ключевые слова", e)
            scored = []
    if not scored:
        scored = [(keyword_score(text, r["text"], cats), r) for r in rows]
    th = threshold(engine)
    scored.sort(key=lambda x: -x[0])
    items = [{"id": r["id"], "number": r["number"], "text": r["text"] if len(r["text"]) <= 160 else r["text"][:159].rstrip() + "…",
              "score": round(s, 3), "category": r["category"], "status": r["status"], "supports": r["supports"]}
             for s, r in scored[:limit] if s >= th]
    return {"engine": engine, "threshold": th, "items": items}


def clusters(min_size: int = 2) -> dict:
    """Кластеры открытых обращений: жадное объединение пар с близостью ≥ порога. Пишет appeals.cluster_id."""
    rows = _open_rows()
    cats = db.q("SELECT id, name FROM categories")
    engine = "keywords"
    sim: dict[tuple[int, int], float] = {}
    if available() and rows:
        try:
            vecs = vectors_for(rows)
            for i, a in enumerate(rows):
                for b in rows[i + 1:]:
                    sim[(a["id"], b["id"])] = cosine(vecs[a["id"]], vecs[b["id"]])
            engine = "embeddings"
        except Exception as e:   # noqa: BLE001
            log.warning("эмбеддинги недоступны (%s) — ключевые слова", e)
            sim = {}
    if not sim and rows:
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                sim[(a["id"], b["id"])] = keyword_score(a["text"], b["text"], cats)
    th = threshold(engine, "cluster")
    # полная связь: группы сливаются, только если КАЖДАЯ пара между ними не ниже порога — без цепочек «похож на похожего»
    def s_of(a: int, b: int) -> float:
        return sim.get((a, b), sim.get((b, a), 0.0))

    groups_l: list[list[dict]] = [[r] for r in rows]
    for (a, b), s in sorted(sim.items(), key=lambda kv: -kv[1]):
        if s < th:
            break
        ga = next(g for g in groups_l if any(m["id"] == a for m in g))
        gb = next(g for g in groups_l if any(m["id"] == b for m in g))
        if ga is gb:
            continue
        if all(s_of(x["id"], y["id"]) >= th for x in ga for y in gb):
            ga.extend(gb)
            groups_l.remove(gb)
    groups = {i: g for i, g in enumerate(groups_l)}
    out = []
    db.ex("UPDATE appeals SET cluster_id=NULL WHERE cluster_id IS NOT NULL")
    for n, (root, members) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
        if len(members) < min_size:
            continue
        members.sort(key=lambda r: (-r["supports"], r["id"]))
        label = min((m["text"] for m in members), key=len)
        branches = sorted({m["branch"] for m in members if m["branch"]})
        catnames = {}
        for m in members:
            if m["category"]:
                catnames[m["category"]] = catnames.get(m["category"], 0) + 1
        for m in members:
            db.ex("UPDATE appeals SET cluster_id=? WHERE id=?", (n, m["id"]))
        out.append({"id": n, "size": len(members), "label": label if len(label) <= 120 else label[:119].rstrip() + "…",
                    "category": max(catnames.items(), key=lambda kv: kv[1])[0] if catnames else None, "branches": branches,
                    "supports": sum(m["supports"] for m in members),
                    "items": [{"id": m["id"], "number": m["number"], "text": m["text"][:120], "branch": m["branch"], "status": m["status"]} for m in members]})
    return {"engine": engine, "threshold": th, "open_total": len(rows), "clusters": out}
