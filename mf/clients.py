"""Обратная связь от клиентов — минимум (решение владельца 13.11): благодарность, вопрос или замечание без входа — форма /c (QR на акте
сдачи объекта или на шкафу оборудования, CONCEPT.md «Интеграции и roadmap», п. 4); в панели «От клиентов» — простой список для директора
и администратора, новые сверху. Без статусов, баллов, лиги, счётчиков и уведомлений. Контакт (имя, телефон или почта) — необязательный и
сохраняется только с отметкой согласия на обработку персональных данных."""
from __future__ import annotations

from . import db

KINDS = {"thanks": "благодарность", "question": "вопрос", "remark": "замечание"}
MAX_TEXT, MAX_PLACE, MAX_NAME, MAX_CONTACT = 4000, 120, 80, 120


def clean(v: str | None, limit: int) -> str:
    return " ".join((v or "").split())[:limit]


def create(kind: str, text: str, place: str = "", name: str = "", contact: str = "", consent: bool = False) -> dict:
    """Проверка и запись сообщения. Ошибки — ValueError с текстом для человека (API отдаёт 422)."""
    if kind not in KINDS:
        raise ValueError("Выберите: благодарность, вопрос или замечание")
    text = (text or "").strip()[:MAX_TEXT]
    if len(text) < 3:
        raise ValueError("Напишите несколько слов")
    place, name, contact = clean(place, MAX_PLACE), clean(name, MAX_NAME), clean(contact, MAX_CONTACT)
    if (name or contact) and not consent:
        raise ValueError("Отметьте согласие на обработку имени и контакта — или оставьте эти поля пустыми")
    now = db.now_iso()
    mid = db.ex("INSERT INTO client_messages(kind, text, place, name, contact, consent_at, created_at) VALUES(?,?,?,?,?,?,?)",
                (kind, text, place or None, name or None, contact or None, now if (name or contact) else None, now))
    return get(mid)


def get(mid: int) -> dict | None:
    r = db.one("SELECT * FROM client_messages WHERE id=?", (mid,))
    return decorate(r) if r else None


def decorate(r: dict) -> dict:
    return {"id": r["id"], "kind": r["kind"], "kind_label": KINDS.get(r["kind"], r["kind"]), "text": r["text"], "place": r["place"],
            "name": r["name"], "contact": r["contact"], "created_at": r["created_at"],
            "photo_url": f"/api/panel/client-messages/{r['id']}/photo" if r["photo"] else None}


def listing() -> list[dict]:
    """Все сообщения, новые сверху."""
    return [decorate(r) for r in db.q("SELECT * FROM client_messages ORDER BY created_at DESC, id DESC")]
