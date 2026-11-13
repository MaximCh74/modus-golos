#!/usr/bin/env python3
"""Пять статусов в «Моих обращениях» для слайда (список владельца 13.11, п. 4): мастеру участка Серику Нурмагамбетову (Павлодар,
производство) — три синтетических обращения в духе компании (сборка шкафов систем безопасности, спецификации): отклонено с объяснением,
уточнение, в работе. Вместе с его A-022 (новое) и A-034 (решено) — по одному на каждый статус экрана. Новых городов на карте нет
(объекты Караганда, Актобе, Усть-Каменогорск владелец снял: «не смотрятся»).

Пишет в живую демо-базу (var/mf.db) так же, как начальное заполнение (mf/seed.py — не меняется): даты относительно «сейчас», история
событий, +10 баллов автору за «принято на рассмотрение». «Коротко» — живым ИИ (без ключа — словарь). Повторный запуск ничего не делает.
После — прогрев сводки и tools/demo_snapshot.sh. Запуск: python3 tools/demo_five_statuses.py"""
from __future__ import annotations

import json
import secrets
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mf import ai, appeals, db  # noqa: E402
from mf.seed import st  # noqa: E402

SERIK = 27
# type, category, priority, status, created hours ago, text, proposed_solution, history, urgency
ITEMS = [
    ("suggestion", 14, "medium", "rejected", 150,
     "На участке сборки шкафов охранно-пожарной сигнализации кабель ждём со склада по 4–5 дней. Предлагаю разрешить мастеру закупать "
     "кабель в Павлодаре у местного поставщика, чтобы сборка не стояла.",
     "Разрешить закупку кабеля на месте в пределах лимита по согласованию с руководителем проекта.",
     [(30, 8, "status_changed", st("new", "rejected", "Марка кабеля для пожарной сигнализации задана проектом и сертификатом — менять её "
                                   "без проектировщика нельзя. Вместо этого поставки кабеля на участок в Павлодаре теперь идут в течение суток"))],
     None),
    ("problem", 13, "medium", "clarify", 20,
     "При сборке шкафа СКУД контроллер не видит часть считывателей: схема подключения в проекте расходится с маркировкой на плате. "
     "Нужна консультация проектировщика.",
     None,
     [(2, 9, "status_changed", st("new", "review")),
      (3, 9, "clarification_requested", {"text": "Уточните, пожалуйста, модель контроллера и номер схемы из проекта — сверим с проектировщиками",
                                         "from": "review"})],
     "workaround"),
    ("suggestion", 6, "medium", "in_progress", 70,
     "Предлагаю при отгрузке шкафов с участка вести фотоотчёт прямо в приложении: к каждой позиции спецификации — фото и серийный номер. "
     "Сейчас при сдаче объекта всё это ищем по чатам.",
     "Шаблон фотоотчёта по позициям спецификации, заполняется с телефона на участке.",
     [(5, 14, "status_changed", st("new", "review", "Обсудим с руководителями проектов")),
      (30, 14, "status_changed", st("review", "in_progress", "Готовим шаблон фотоотчёта; пилот — на участке в Павлодаре"))],
     None),
]


def main() -> None:
    have = db.q("SELECT a.number FROM appeals a JOIN appeal_authors aa ON aa.appeal_id=a.id WHERE aa.user_id=? AND a.status IN ('rejected','clarify','in_progress')", (SERIK,))
    if have:
        print("уже есть:", ", ".join(r["number"] for r in have), "— ничего не делаю")
        return
    c = db.conn()
    now = db.now()
    serik = db.one("SELECT id, branch_id, department_id FROM users WHERE id=?", (SERIK,))
    cats = {r["id"]: r for r in db.q("SELECT id, name, responsible_user_id FROM categories")}
    users = {r["id"]: r for r in db.q("SELECT id, name FROM users")}
    cat_list = [{"id": r["id"], "name": r["name"]} for r in cats.values()]

    def event(aid, actor, kind, payload, at):
        c.execute("INSERT INTO appeal_events(appeal_id, actor_id, kind, payload, created_at) VALUES(?,?,?,?,?)",
                  (aid, actor, kind, json.dumps(payload, ensure_ascii=False), db.iso(at)))

    def points(uid, aid, reason, amount, at, number):
        c.execute("INSERT INTO points_ledger(user_id, appeal_id, reason, amount, created_at) VALUES(?,?,?,?,?)", (uid, aid, reason, amount, db.iso(at)))
        event(aid, None, "points_awarded", {"user_id": uid, "amount": amount, "reason": reason}, at)
        c.execute("INSERT INTO notifications(user_id, text, link, created_at, read_at) VALUES(?,?,?,?,?)",
                  (uid, f"+{amount} баллов за {number}", "/app#/points", db.iso(at), db.iso(at)))

    out = []
    author = SERIK
    for typ, cat, prio, status, hours, text, solution, history, urgency in ITEMS:
        created = now - timedelta(hours=hours)
        number = appeals.next_number()
        cls = ai.classify_appeal(text + ("\n" + solution if solution else ""), cat_list, typ, urgency, None)   # «Коротко» — как при отправке
        responsible = cats[cat]["responsible_user_id"]
        staff = [h for h, actor, kind, _ in history if actor and kind in ("status_changed", "comment", "clarification_requested")]
        first_resp = created + timedelta(hours=min(staff)) if staff else None
        closed_at = next((created + timedelta(hours=h) for h, _, k, p in history if k == "status_changed" and p["to"] in ("done", "closed", "rejected")), None)
        resolution = next((p.get("text") for _, _, k, p in history if k == "status_changed" and p["to"] in ("done", "rejected")), None)
        last = created + timedelta(hours=max([h for h, *_ in history], default=0))
        aid = db.ex("""INSERT INTO appeals(number, type, category_id, branch_id, department_id, text, proposed_solution, priority, status,
                       responsible_id, is_anonymous, source, tracking_token, resolution_text, created_at, updated_at, first_response_at, closed_at,
                       author_urgency, brief, brief_engine, brief_at, input_mode)
                       VALUES(?,?,?,?,?,?,?,?,?,?,0,'app',?,?,?,?,?,?,?,?,?,?,'text')""",
                    (number, typ, cat, serik["branch_id"], serik["department_id"], text, solution, prio, status, responsible,
                     secrets.token_urlsafe(24), resolution, db.iso(created), db.iso(last),
                     db.iso(first_resp) if first_resp else None, db.iso(closed_at) if closed_at else None, urgency,
                     json.dumps(cls["brief"], ensure_ascii=False) if cls.get("brief") else None, cls.get("engine") if cls.get("brief") else None,
                     db.iso(created) if cls.get("brief") else None))
        c.execute("INSERT INTO appeal_authors(appeal_id, user_id) VALUES(?,?)", (aid, author))
        event(aid, author, "created", {"source": "app", "type": typ, "anonymous": False}, created)
        event(aid, None, "ai_classified", {"engine": cls.get("engine"), "category_id": cat, "category": cats[cat]["name"],
                                           "confidence": cls.get("confidence"), "priority": prio, "summary": cls.get("summary")}, created)
        event(aid, None, "assigned", {"responsible_id": responsible, "responsible": users[responsible]["name"], "auto": True}, created)
        for h, actor, kind, payload in history:
            at = created + timedelta(hours=h)
            event(aid, actor, kind, payload, at)
            if kind == "status_changed" and payload["to"] == "review":
                points(author, aid, "accepted", 10, at, number)
        c.commit()
        out.append(f"{number} · {status} · «Коротко»: {cls.get('engine')}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
