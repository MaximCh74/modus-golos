#!/usr/bin/env python3
"""Демо «Обратная связь от клиентов» (решение владельца 13.11, минимум): четыре синтетических сообщения клиентов разных типов — две
благодарности, вопрос и замечание (объект в Атырау после пусконаладки), два с контактом и согласием. Контакты вымышленные (номер
+7 700 000 00 00 и адрес example.com — зарезервированы для примеров), реальных людей и контактов нет.

Пишет в живую демо-базу (var/mf.db), даты — относительно «сейчас». Повторный запуск ничего не делает. После — прогрев сводки и
tools/demo_snapshot.sh. Запуск: python3 tools/demo_clients.py"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mf import db  # noqa: E402

# kind, часов назад, город или объект, текст, имя, контакт
ITEMS = [
    ("thanks", 3, "Павлодар",
     "Спасибо монтажной бригаде за щит управления на нашем складе: сделали за два дня, убрали за собой и толково объяснили, как его "
     "обслуживать.", "Ерлан, завхоз склада", "+7 700 000 00 00"),
    ("remark", 21, "Атырау, объект ТЭЦ-2",
     "После пусконаладки шкаф управления насосами заметно гудит и греется, а на дверце нет схемы подключения. Просим прислать инженера "
     "и положить схему в шкаф.", None, None),
    ("question", 50, "Омск",
     "Подскажите, когда приедет инженер на плановое обслуживание вентиляции? По договору — в ноябре, а звонка пока не было.",
     "Ольга, управляющая бизнес-центром", "olga@example.com"),
    ("thanks", 96, "Астана",
     "Благодарим отдел продаж за быстрый ответ по спецификации: счёт и сроки поставки пришли в тот же день.", None, None),
]


def main() -> None:
    db.conn()   # схема и миграции — при первом открытии
    if db.one("SELECT COUNT(*) AS n FROM client_messages")["n"]:
        print("сообщения клиентов уже есть — ничего не делаю")
        return
    now = db.now()
    for kind, hours, place, text, name, contact in sorted(ITEMS, key=lambda x: -x[1]):
        at = db.iso(now - timedelta(hours=hours))
        db.ex("INSERT INTO client_messages(kind, text, place, name, contact, consent_at, created_at) VALUES(?,?,?,?,?,?,?)",
              (kind, text, place, name, contact, at if (name or contact) else None, at))
    print("добавлено сообщений клиентов:", len(ITEMS))


if __name__ == "__main__":
    main()
