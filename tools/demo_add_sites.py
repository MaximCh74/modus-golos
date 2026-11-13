#!/usr/bin/env python3
"""Демо-объекты командированных (замечание владельца 13.11, п. 1): три объекта далеко друг от друга — Караганда, Актобе, Усть-Каменогорск,
по 1–2 синтетических обращения в духе компании (монтаж и пусконаладка систем безопасности, спецификации, оборудование на объекте).
Состояния: Караганда — без просрочек (зелёная: одно отклонено с объяснением, одно решено), Актобе — с просрочкой (красная: нет первого
ответа дольше срока), Усть-Каменогорск — открытые без просрочек (зелёная: уточнение и в работе). Атырау не трогаем.

Автор трёх обращений — мастер участка Серик Нурмагамбетов (ездит по объектам): у него в «Моих обращениях» все пять статусов на экране
(Новое — A-022, В работе, Уточнение, Решено — A-034, Отклонено) — для слайда. Два обращения — анонимно по QR на объекте.

Пишет в живую демо-базу (var/mf.db) так же, как начальное заполнение (mf/seed.py — не меняется): даты относительно «сейчас», история
событий, баллы автору за «принято в работу». «Коротко» — живым ИИ (как при отправке из приложения; без ключа — словарь). Просрочка
Актобе эскалируется сразу (check_overdue), чтобы снапшот был устойчивым. Повторный запуск ничего не делает. После — прогрев сводки
и tools/demo_snapshot.sh. Запуск: python3 tools/demo_add_sites.py"""
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
# site_city, type, category, author (None — анонимно по QR), priority, status, created hours ago, text, proposed_solution, history, urgency
SITES = [
    ("Караганда", "suggestion", 14, SERIK, "medium", "rejected", 150,
     "На объекте в Караганде кабель для охранно-пожарной сигнализации ждём со склада Павлодара по 4–5 дней. Предлагаю разрешить мастеру "
     "закупать кабель на месте у местного поставщика, чтобы монтаж не стоял.",
     "Разрешить закупку кабеля на месте в пределах лимита по согласованию с руководителем проекта.",
     [(4, 8, "status_changed", st("new", "review", "Посмотрим с проектировщиками, какие марки кабеля допустимы")),
      (30, 8, "status_changed", st("review", "rejected", "Марка кабеля для пожарной сигнализации задана проектом и сертификатом — менять её "
                                   "без проектировщика нельзя. Вместо этого отгрузки на объекты в Караганде теперь идут со склада Павлодара в течение суток"))],
     None),
    ("Караганда", "problem", 3, None, "high", "done", 110,
     "При пусконаладке видеонаблюдения на объекте в Караганде не хватило двух блоков питания для камер — в спецификации их не было. "
     "Монтажники ждали доставку, сдача системы сдвинулась на два дня.",
     None,
     [(2, 12, "status_changed", st("new", "review")),
      (6, 12, "status_changed", st("review", "in_progress", "Заказали блоки питания, проверяем шаблон спецификации")),
      (40, 12, "status_changed", st("in_progress", "done", "Блоки питания доставлены на объект; в шаблон спецификации видеонаблюдения "
                                    "добавлена строка расчёта питания камер"))],
     "workaround"),
    ("Актобе", "problem", 3, None, "high", "new", 52,
     "На объект в Актобе привезли извещатели другой модели, чем указано в спецификации проекта. Монтаж охранной сигнализации остановлен: "
     "нужна замена или согласованный аналог.",
     None, [], "now"),
    ("Усть-Каменогорск", "problem", 13, SERIK, "medium", "clarify", 20,
     "На объекте в Усть-Каменогорске при пусконаладке СКУД контроллер не видит часть считывателей на втором этаже. Нужна консультация "
     "проектировщика по схеме подключения.",
     None,
     [(2, 9, "status_changed", st("new", "review")),
      (3, 9, "clarification_requested", {"text": "Уточните, пожалуйста, модель контроллера и сколько считывателей не определяется — сверим "
                                                 "со схемой проекта", "from": "review"})],
     "workaround"),
    ("Усть-Каменогорск", "suggestion", 6, SERIK, "medium", "in_progress", 70,
     "Предлагаю при сдаче объекта вести фотоотчёт по смонтированному оборудованию прямо в приложении: к каждой позиции спецификации — "
     "фото и серийный номер. Сейчас всё это ищем по чатам, когда заказчик принимает систему.",
     "Шаблон фотоотчёта по позициям спецификации, заполняется на объекте с телефона.",
     [(5, 14, "status_changed", st("new", "review", "Обсудим с руководителями проектов")),
      (30, 14, "status_changed", st("review", "in_progress", "Готовим шаблон фотоотчёта; пилот — на объекте в Усть-Каменогорске"))],
     None),
]


def main() -> None:
    cities = sorted({s[0] for s in SITES})
    have = db.q(f"SELECT number, site_city FROM appeals WHERE site_city IN ({','.join('?' * len(cities))})", tuple(cities))
    if have:
        print("уже есть:", ", ".join(f"{r['number']} · {r['site_city']}" for r in have), "— ничего не делаю")
        return
    c = db.conn()
    now = db.now()
    field = db.one("SELECT id FROM branches WHERE kind='field' ORDER BY id LIMIT 1")["id"]
    cats = {r["id"]: r for r in db.q("SELECT id, name, responsible_user_id FROM categories")}
    users = {r["id"]: r for r in db.q("SELECT id, name, department_id FROM users")}
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
    for city, typ, cat, author, prio, status, hours, text, solution, history, urgency in SITES:
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
                       site_city, author_urgency, brief, brief_engine, brief_at, input_mode)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,'qr',?,?,?,?,?,?,?,?,?,?,?,'text')""",
                    (number, typ, cat, field, users[author]["department_id"] if author else None, text, solution, prio, status, responsible,
                     0 if author else 1, secrets.token_urlsafe(24), resolution, db.iso(created), db.iso(last),
                     db.iso(first_resp) if first_resp else None, db.iso(closed_at) if closed_at else None, city, urgency,
                     json.dumps(cls["brief"], ensure_ascii=False) if cls.get("brief") else None, cls.get("engine") if cls.get("brief") else None,
                     db.iso(created) if cls.get("brief") else None))
        if author:
            c.execute("INSERT INTO appeal_authors(appeal_id, user_id) VALUES(?,?)", (aid, author))
        event(aid, author, "created", {"source": "qr", "type": typ, "anonymous": not author}, created)
        event(aid, None, "ai_classified", {"engine": cls.get("engine"), "category_id": cat, "category": cats[cat]["name"],
                                           "confidence": cls.get("confidence"), "priority": prio, "summary": cls.get("summary")}, created)
        event(aid, None, "assigned", {"responsible_id": responsible, "responsible": users[responsible]["name"], "auto": True}, created)
        for h, actor, kind, payload in history:
            at = created + timedelta(hours=h)
            event(aid, actor, kind, payload, at)
            if kind == "status_changed" and author and payload["to"] == "review":
                points(author, aid, "accepted", 10, at, number)
            if kind == "status_changed" and author and payload["to"] == "done":
                points(author, aid, "done", 50, at, number)
        c.commit()
        out.append(f"{number} · {city} · {status} · «Коротко»: {cls.get('engine')}")
    esc = appeals.check_overdue()   # Актобе: просрочка сразу с эскалацией — снапшот устойчив, сервер не допишет её после
    c.commit()
    print("\n".join(out))
    print("эскалировано:", ", ".join(esc) or "—")


if __name__ == "__main__":
    main()
