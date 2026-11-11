#!/usr/bin/env python3
"""Убрать совещание из демо-базы целиком (этап 5, решение Марка): пункты, поручения, события «обсуждено на совещании» у связанных
обращений и уведомления о нём. Журнал событий append-only — триггеры снимаются только на время операции (инструмент для
подготовки демо, не для рабочих данных). Запуск при ОСТАНОВЛЕННОМ сервере: python3 tools/demo_remove_meeting.py <id> ; потом tools/demo_snapshot.sh."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mf import config, db, demo  # noqa: E402


def main() -> None:
    mid = int(sys.argv[1])
    c = sqlite3.connect(str(config.DB_PATH))
    try:
        m = c.execute("SELECT id, title FROM meetings WHERE id=?", (mid,)).fetchone()
        if not m:
            raise SystemExit(f"совещания {mid} нет")
        for t in demo.TRIGGERS:
            c.execute(f"DROP TRIGGER IF EXISTS {t}")
        ev = 0
        for row in c.execute("SELECT id, payload FROM appeal_events WHERE kind='discussed_at_meeting'").fetchall():
            if (json.loads(row[1] or "{}")).get("meeting_id") == mid:
                c.execute("DELETE FROM appeal_events WHERE id=?", (row[0],)); ev += 1
        n_items = c.execute("DELETE FROM meeting_items WHERE meeting_id=?", (mid,)).rowcount
        n_notif = c.execute("DELETE FROM notifications WHERE text LIKE ? OR link LIKE ?", (f"%«{m[1]}»%", f"%/meetings/{mid}%")).rowcount
        c.execute("DELETE FROM meetings WHERE id=?", (mid,))
        c.executescript(db.SCHEMA)   # триггеры обратно
        c.commit()
        print(f"удалено совещание {mid} «{m[1]}»: пунктов {n_items}, событий {ev}, уведомлений {n_notif}. Теперь: tools/demo_snapshot.sh")
    finally:
        c.close()


if __name__ == "__main__":
    main()
