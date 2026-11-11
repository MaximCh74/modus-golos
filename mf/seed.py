"""Тестовые данные (ТЗ v1.1 §10, ТЗ v2 по кастдеву): 20 обращений датасета организаторов с теми же номерами, типами,
категориями, приоритетами, статусами и ответственными; «дальнейшие действия» датасета записаны событиями истории.
Города — реальные офисы заказчика по первому интервью (Омск, Самара, Тюмень, Астана, Павлодар) плюс «Объект» для
командированных; пользователи, награды и баллы — ДЕМОНСТРАЦИОННЫЕ, имена вымышленные.
A-021…A-028 — синтетические обращения по мотивам кастдева (номенклатура и 1С в разных городах, два предложения,
ждущие решения директора). Повторный seed: python3 -m mf.seed --force (сносит базу — журналы append-only)."""
from __future__ import annotations

import json
import secrets
import sys
from datetime import timedelta

from . import db

BRANCHES = [  # code, name, city, country, lat, lng, hq, kind (office | production | field)
    ("OMSK", "Омск — головной офис", "Омск", "Россия", 54.9885, 73.3242, 1, "office"),
    ("SAM", "Самара", "Самара", "Россия", 53.1959, 50.1002, 0, "office"),
    ("TMN", "Тюмень", "Тюмень", "Россия", 57.1530, 65.5343, 0, "office"),
    ("AST", "Астана — офис", "Астана", "Казахстан", 51.1694, 71.4491, 0, "office"),
    ("PVL", "Павлодар — производство", "Павлодар", "Казахстан", 52.2873, 76.9674, 0, "production"),
    ("FIELD", "Объект (командировка)", None, "Казахстан", None, None, 0, "field"),
]
DEPARTMENTS = ["Продажи", "Закупки", "Проектирование", "Бухгалтерия", "IT", "Сервис", "Администрация", "HR",
               "Руководство", "Проектный офис", "Отдел развития", "Производство"]   # id 1..12
DEV_DEPARTMENT = 11
USERS = [  # id, name, role, branch, dept, manager, position
    (1, "Виктор Орлов", "director", "OMSK", 9, None, "Директор"),
    (2, "Олег Савельев", "responsible", "OMSK", 9, 1, "Руководитель направления"),
    (3, "Ерлан Жумабеков", "responsible", "PVL", 5, 2, "IT-специалист"),
    (4, "Айгерим Нурланова", "responsible", "AST", 1, 2, "Руководитель продаж"),
    (5, "Дмитрий Козлов", "responsible", "OMSK", 2, 2, "Руководитель закупок"),
    (6, "Сауле Абишева", "employee", "PVL", 4, 7, "Бухгалтер"),
    (7, "Марина Соколова", "responsible", "OMSK", 4, 2, "Руководитель бухгалтерии"),
    (8, "Тимур Ахметов", "responsible", "AST", 3, 2, "Руководитель проектирования"),
    (9, "Алексей Волков", "responsible", "TMN", 10, 2, "Руководитель проектов"),
    (10, "Наталья Петрова", "responsible", "OMSK", 8, 2, "HR, внутренние коммуникации и обучение"),
    (11, "Сергей Иванов", "responsible", "OMSK", 7, 2, "Административный руководитель"),
    (12, "Анна Громова", "responsible", "OMSK", 3, 8, "Ответственный за номенклатуру"),
    (13, "Руслан Бекенов", "responsible", "AST", 1, 4, "Ответственный за договоры"),
    (14, "Елена Фролова", "responsible", "OMSK", 9, 2, "Ответственный за процессы"),
    (15, "Игорь Лебедев", "admin", "OMSK", 5, 1, "Администратор системы"),
    (16, "Данияр Сейткали", "employee", "PVL", 2, 5, "Сотрудник закупок"),
    (17, "Ольга Миронова", "employee", "TMN", 2, 5, "Сотрудник закупок"),
    (18, "Асель Касымова", "employee", "AST", 3, 8, "Инженер-проектировщик"),
    (19, "Павел Кузнецов", "employee", "SAM", 4, 7, "Бухгалтер"),
    (20, "Жанна Токтарова", "employee", "AST", 1, 4, "Менеджер по продажам"),
    (21, "Максим Белов", "employee", "SAM", 1, 4, "Менеджер по продажам"),
    (22, "Айдана Ермекова", "employee", "AST", 10, 9, "Координатор проекта"),
    (23, "Кирилл Смирнов", "employee", "OMSK", 10, 9, "Руководитель проекта"),
    (24, "Динара Омарова", "employee", "PVL", 7, 11, "Сотрудник офиса"),
    # ТЗ v2: отдел развития (путь предложения к директору) и ответственный за 1С; производство в Павлодаре
    (25, "Гульнара Сейтжанова", "responsible", "OMSK", 11, 1, "Руководитель отдела развития"),
    (26, "Бауыржан Сапаров", "responsible", "OMSK", 5, 2, "Ответственный за 1С"),
    (27, "Серик Нурмагамбетов", "employee", "PVL", 12, 8, "Мастер участка"),
]
# 18 категорий датасета + «1С и автоматизация» по кастдеву; «Каталог и данные» → «Номенклатура и спецификации» (уточнена по кастдеву).
# id, название, ответственный (None — вакансия «Администратор документов», сценарий 2), SLA первого ответа, ч
CATEGORIES = [
    (1, "Межотдельное взаимодействие", 5, 48), (2, "Информационная прозрачность", 2, 72), (3, "Номенклатура и спецификации", 12, 24),
    (4, "Обучение", 10, 72), (5, "Документооборот", 7, 48), (6, "Регламенты", 14, 72), (7, "Интеграции и IT", 3, 24),
    (8, "Знания и наставничество", 7, 72), (9, "Договорная работа", 13, 24), (10, "Задачи и коммуникации", 4, 48),
    (11, "Оперативность", 2, 24), (12, "Коммуникации", 3, 72), (13, "Проектная деятельность", 9, 48),
    (14, "Планирование ресурсов", 8, 72), (15, "Постановка задач", 2, 48), (16, "Корпоративная среда", 11, 72),
    (17, "Хранение документов", None, 48), (18, "Прозрачность результатов", 5, 72),
    (19, "1С и автоматизация", 26, 24),
]
REWARDS = [  # демо-примеры, состав определяет компания; первой — привычная заказчику форма поощрения, теперь по понятным правилам
    ("Премия за внедрённую идею", "Денежная премия автору предложения, которое реализовано; размер — по решению директора", 200),
    ("Дополнительный выходной", "Один оплачиваемый день отдыха по согласованию с руководителем", 300),
    ("Сертификат на обучение", "Курс или конференция по профилю на выбор", 250),
    ("Мерч компании", "Набор фирменной атрибутики", 100),
    ("Скидка у партнёра", "Скидка в партнёрской сети", 150),
]


def st(frm: str, to: str, text: str | None = None) -> dict:
    return {"from": frm, "to": to, **({"text": text} if text else {})}


# number, type, category, author, priority, status, created hours ago, text, proposed_solution, responsible override,
# history: (hours after creation, actor, kind, payload)
APPEALS = [
    ("A-001", "problem", 1, 16, "medium", "new", 72,
     "В заявках на приобретение оборудования иногда не хватает назначения изделия и требуемых параметров. Предлагаю добавить обязательные поля, чтобы сократить число уточнений.",
     "Добавить в шаблон заявки обязательные поля «назначение изделия» и «требуемые параметры».", None, []),
    ("A-002", "suggestion", 2, 16, "medium", "review", 480,
     "При общении с поставщиками полезно видеть общую стадию проекта без доступа к коммерческим деталям. Можно ли показывать краткий статус и ориентировочные контрольные даты?",
     None, None, [(5, 2, "status_changed", st("new", "review", "Определим перечень доступных статусов и источник их обновления"))]),
    ("A-003", "problem", 3, 18, "high", "in_progress", 432,
     "В рабочих материалах иногда встречаются разные обозначения одного изделия. Это увеличивает время проверки спецификации. Нужен понятный способ находить актуальную карточку позиции.",
     None, None, [(3, 12, "status_changed", st("new", "review")),
                  (30, 12, "status_changed", st("review", "in_progress", "Готовим правило проверки и корректировки номенклатуры"))]),
    ("A-004", "suggestion", 4, 17, "low", "done", 600,
     "Было бы полезно проводить короткие занятия по новым товарным линейкам с разбором типовых запросов. Предлагаю составить календарь таких встреч.",
     "Календарь коротких занятий по линейкам, раз в две недели.", None,
     [(6, 10, "status_changed", st("new", "review")),
      (48, 10, "status_changed", st("review", "in_progress", "Составляем календарь встреч")),
      (360, 10, "status_changed", st("in_progress", "done", "Запланирован пробный обучающий семинар по новым товарным линейкам; календарь коротких занятий опубликован"))]),
    ("A-005", "problem", 5, 6, "medium", "clarify", 360,
     "При обработке документов между подразделениями возникают дополнительные вопросы о том, на каком этапе находится пакет. Хотелось бы видеть ответственного и текущий статус.",
     None, None, [(2, 7, "status_changed", st("new", "review")),
                  (26, 7, "clarification_requested", {"text": "Уточните, пожалуйста, о каких видах документов идёт речь и какие этапы согласования для вас ключевые", "from": "review"})]),
    ("A-006", "suggestion", 6, 19, "medium", "review", 300,
     "Предлагаю собрать короткую пошаговую памятку для операций, в которых последовательно участвуют несколько подразделений, и определить порядок актуализации памятки.",
     None, None, [(12, 14, "status_changed", st("new", "review", "Назначим владельца процесса и согласуем черновик памятки"))]),
    ("A-007", "problem", 7, 19, "high", "new", 48,
     "Иногда повторный ввод одних и тех же сведений в разных рабочих системах занимает много времени. Нужна оценка, какие операции можно синхронизировать безопасно.",
     None, None, []),
    ("A-008", "suggestion", 8, 6, "low", "done", 576,
     "При передаче сложной задачи новому сотруднику полезен короткий разбор типовых ошибок и контактов, к которым можно обратиться за помощью. Предлагаю сделать такую памятку.",
     None, None, [(4, 7, "status_changed", st("new", "review")),
                  (72, 7, "status_changed", st("review", "in_progress", "Собираем типовые ошибки и контакты")),
                  (288, 7, "status_changed", st("in_progress", "done", "Создана учебная инструкция для передачи сложных задач: типовые ошибки и контакты для консультаций"))]),
    ("A-009", "problem", 9, 20, "high", "in_progress", 288,
     "Не всегда понятно, кто готовит очередную версию приложения к договору и кто должен проверить её перед отправкой. Это приводит к повторным согласованиям.",
     None, None, [(1, 13, "status_changed", st("new", "review")),
                  (20, 13, "status_changed", st("review", "in_progress", "Разграничиваем этапы подготовки, проверки и утверждения приложений"))]),
    ("A-010", "suggestion", 10, 21, "medium", "review", 240,
     "Предлагаю не закрывать рабочую задачу до подтверждения заказчиком результата внутри компании, чтобы связанные вопросы оставались в общей истории обсуждения.",
     None, None, [(20, 4, "status_changed", st("new", "review", "Проверим, подходит ли правило для разных типов задач"))]),
    ("A-011", "problem", 11, 20, "high", "new", 36,
     "При срочной подготовке клиентского предложения сложно прогнозировать сроки ответа от смежных подразделений. Хотелось бы видеть ожидаемый срок и уведомление при задержке.",
     None, None, []),
    ("A-012", "suggestion", 12, 21, "low", "review", 216,
     "Рабочие обсуждения распределены по нескольким каналам, из-за чего теряется контекст. Предлагаю выбрать единое место для итоговых решений по задаче.",
     "Фиксировать итоговые решения по задаче в одном месте.", None,
     [(30, 3, "status_changed", st("new", "review", "Сравним варианты и предложим правила фиксации итогов"))]),
    ("A-013", "problem", 13, 22, "medium", "clarify", 192,
     "Когда изменяется состав оборудования в проекте, не всегда ясно, какие строки спецификации были пересмотрены. Нужна более заметная история изменений.",
     None, None, [(5, 9, "status_changed", st("new", "review")),
                  (40, 9, "clarification_requested", {"text": "Уточните формат исходных файлов спецификации и как сейчас сравниваете версии", "from": "review"})]),
    ("A-014", "suggestion", 14, 22, "medium", "review", 168,
     "Предлагаю показывать загруженность проектной группы на ближайшие недели в укрупнённом виде. Так будет проще согласовывать сроки запуска новых задач.",
     None, None, [(8, 8, "status_changed", st("new", "review", "Согласуем показатели загрузки и права просмотра"))]),
    ("A-015", "problem", 15, 23, "medium", "in_progress", 336,
     "Некоторые поручения поступают без ожидаемого результата и даты завершения. Предлагаю договориться о минимальном наборе данных при постановке задачи.",
     "Минимальный набор при постановке задачи: цель, срок, приоритет, ответственный.", None,
     [(3, 2, "status_changed", st("new", "review")),
      (50, 2, "status_changed", st("review", "in_progress", "Готовим шаблон постановки задачи: цель, срок, приоритет, ответственный"))]),
    ("A-016", "suggestion", 4, 23, "low", "new", 6,
     "Для новых сотрудников полезны практические демонстрации оборудования, а не только презентации. Предлагаю пилотное занятие с учебными образцами.",
     None, None, []),
    ("A-017", "suggestion", 16, 24, "low", "rejected", 264,
     "Предлагаю организовать отдельную небольшую зону для коротких перерывов рядом с рабочими помещениями.",
     None, None, [(70, 11, "status_changed", st("new", "rejected", "Сейчас нет подходящего помещения; вернёмся к вопросу при перепланировке офиса"))]),
    ("A-018", "praise", 16, 24, "low", "closed", 120,
     "Хочу отметить пользу внутренних учебных встреч: после них стало легче обращаться к коллегам за консультацией. Было бы хорошо сохранить этот формат.",
     None, 10, [(2, 10, "status_changed", st("new", "closed", "Передано организаторам учебных встреч"))]),
    ("A-019", "problem", 17, 22, "medium", "review", 96,
     "В общих папках трудно быстро определить актуальную редакцию инструкции. Можно ли закрепить единые правила именования и архивирования старых версий?",
     None, None, [(10, 15, "status_changed", st("new", "review", "Ответственный за хранение документов не назначен — обращение у администратора до назначения"))]),
    ("A-020", "suggestion", 18, 16, "low", "new", 24,
     "Предлагаю публиковать краткий обзор завершённых внутренних улучшений, чтобы сотрудники видели результат направленных предложений.",
     None, None, []),
]
# ТЗ v2: синтетические обращения по мотивам кастдева — номенклатура и 1С в разных городах (кластер «Номенклатура в 1С»),
# командированный на объекте (филиал FIELD + город объекта), два предложения, ждущие решения директора дольше порога.
# number, type, category, author, priority, status, hours ago, text, solution, responsible override, history, extra
CUSTDEV_APPEALS = [
    ("A-021", "problem", 3, 23, "high", "review", 200,
     "В спецификациях проектов номенклатура из 1С часто устаревшая: позиции уже сняты с производства, а в справочнике ещё активны. Приходится перепроверять каждую строку вручную.",
     None, None, [(6, 12, "status_changed", st("new", "review", "Смотрим, как помечать снятые позиции в справочнике"))], {}),
    ("A-022", "problem", 3, 27, "medium", "new", 150,
     "На производстве карточки позиций в 1С без габаритов и веса, при комплектации заказов пересчитываем по каталогам поставщиков.",
     None, None, [], {}),
    ("A-023", "problem", 3, 20, "high", "new", 120,
     "В коммерческие предложения попадают позиции с разными названиями одного и того же товара из 1С, клиент путается, потом переделываем.",
     None, None, [], {}),
    ("A-024", "problem", 3, 17, "medium", "review", 96,
     "Одна и та же номенклатура заведена в 1С дважды с разными артикулами, остатки по складу не сходятся при сверке.",
     None, None, [(8, 12, "status_changed", st("new", "review", "Проверяем дубли по артикулам"))], {}),
    ("A-025", "problem", 3, 16, "high", "new", 60,
     "На объекте в Атырау спецификация из 1С не совпадает с тем, что приехало: часть позиций переименована в справочнике уже после отгрузки.",
     None, None, [], {"branch": "FIELD", "site_city": "Атырау", "source": "qr"}),
    ("A-026", "problem", 19, 19, "medium", "new", 40,
     "Выгрузка актов из 1С в Битрикс24 падает, когда в номенклатуре есть позиции без единиц измерения — каждый раз правим вручную.",
     None, None, [], {}),
    ("A-027", "suggestion", 3, 22, "medium", "review", 320,
     "Предлагаю единый регламент заведения позиций в 1С: обязательные поля, ответственный за справочник, проверка дублей раз в месяц.",
     "Регламент заведения позиций и ежемесячная проверка дублей.", 25,
     [(5, 25, "status_changed", st("new", "review", "Предложение требует ресурсов — выносим директору"))],
     {"director_request": "Нужны две недели работы специалиста по 1С и доступ к справочнику", "director_requested_hours_ago": 12 * 24}),
    ("A-028", "suggestion", 19, 23, "medium", "review", 260,
     "Предлагаю связать 1С с каталогом проектирования, чтобы спецификации проверялись на актуальность позиций автоматически.",
     None, 25,
     [(4, 25, "status_changed", st("new", "review", "Нужен бюджет на доработку 1С — выносим директору"))],
     {"director_request": "Бюджет на доработку конфигурации 1С, ориентировочно 2–3 недели подрядчика", "director_requested_hours_ago": 9 * 24}),
]
SUPPORTS = {"A-003": [22], "A-007": [17, 20], "A-012": [20, 22, 23], "A-021": [18, 27], "A-023": [21], "A-027": [12, 18]}
SETTINGS = {
    "points": {"accepted": 10, "done": 50, "support": 2, "support_cap": 20},
    "league_weights": {"done": 0.5, "considered": 0.3, "speed": 0.2},
    "director_wait_days": 7,         # «ждёт решения дольше порога» — подсветка в «На решение» и счётчик у директора
    "dev_department_head_id": 25,    # предложения по умолчанию уходят руководителю отдела развития
}


def ensure() -> None:
    if not db.one("SELECT 1 FROM users LIMIT 1"):
        run()


def run(force: bool = False) -> None:
    if force:
        db.reset()
    c = db.conn()
    now = db.now()
    branch_ids = {}
    for code, name, city, country, lat, lng, hq, kind in BRANCHES:
        branch_ids[code] = db.ex("INSERT INTO branches(code, name, city, country, lat, lng, is_hq, kind) VALUES(?,?,?,?,?,?,?,?)",
                                 (code, name, city, country, lat, lng, hq, kind))
    for i, name in enumerate(DEPARTMENTS, 1):
        db.ex("INSERT INTO departments(id, name) VALUES(?,?)", (i, name))
    for uid, name, role, br, dept, mgr, pos in USERS:
        db.ex("INSERT INTO users(id, name, role, branch_id, department_id, manager_id, position, active) VALUES(?,?,?,?,?,?,?,1)",
              (uid, name, role, branch_ids[br], dept, mgr, pos))
    cats = {}
    for cid, name, resp, sla in CATEGORIES:
        db.ex("INSERT INTO categories(id, name, responsible_user_id, sla_first_response_hours) VALUES(?,?,?,?)", (cid, name, resp, sla))
        cats[cid] = resp
    users = {u[0]: u for u in USERS}

    def event(aid, actor, kind, payload, at):
        c.execute("INSERT INTO appeal_events(appeal_id, actor_id, kind, payload, created_at) VALUES(?,?,?,?,?)",
                  (aid, actor, kind, json.dumps(payload, ensure_ascii=False), db.iso(at)))

    def points(uid, aid, reason, amount, at, number):
        c.execute("INSERT INTO points_ledger(user_id, appeal_id, reason, amount, created_at) VALUES(?,?,?,?,?)",
                  (uid, aid, reason, amount, db.iso(at)))
        event(aid, None, "points_awarded", {"user_id": uid, "amount": amount, "reason": reason}, at)
        c.execute("INSERT INTO notifications(user_id, text, link, created_at, read_at) VALUES(?,?,?,?,?)",
                  (uid, f"+{amount} баллов за {number}", "/app#/points", db.iso(at), db.iso(at)))

    ids = {}
    for number, typ, cat, author, prio, status, hours, text, solution, resp_override, history, *rest in APPEALS + CUSTDEV_APPEALS:
        extra = rest[0] if rest else {}
        created = now - timedelta(hours=hours)
        author_u = users[author]
        responsible = resp_override if resp_override else cats[cat]
        staff_offsets = [h for h, actor, kind, _ in history if actor and kind in ("status_changed", "comment", "clarification_requested")]
        first_resp = created + timedelta(hours=min(staff_offsets)) if staff_offsets else None
        closed_at = None
        for h, _, kind, payload in history:
            if kind == "status_changed" and payload["to"] in ("done", "closed", "rejected"):
                closed_at = created + timedelta(hours=h)
        resolution = next((p.get("text") for _, _, k, p in history if k == "status_changed" and p["to"] in ("done", "rejected")), None)
        source = extra.get("source", "app")
        aid = db.ex("""INSERT INTO appeals(number, type, category_id, branch_id, department_id, text, proposed_solution, priority, status,
                       responsible_id, is_anonymous, source, tracking_token, resolution_text, created_at, updated_at, first_response_at, closed_at, site_city)
                       VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?)""",
                    (number, typ, cat, branch_ids[extra.get("branch", author_u[3])], author_u[4], text, solution, prio, status, responsible, source,
                     secrets.token_urlsafe(24), resolution, db.iso(created), db.iso(created), db.iso(first_resp) if first_resp else None,
                     db.iso(closed_at) if closed_at else None, extra.get("site_city")))
        ids[number] = aid
        c.execute("INSERT INTO appeal_authors(appeal_id, user_id) VALUES(?,?)", (aid, author))
        event(aid, author, "created", {"source": source, "type": typ, "anonymous": False, **({"synthetic": "custdev"} if extra else {})}, created)
        if extra.get("director_request"):
            req_at = now - timedelta(hours=extra["director_requested_hours_ago"])
            c.execute("UPDATE appeals SET director_request_text=?, director_requested_at=?, director_requested_by=?, director_decision='pending' WHERE id=?",
                      (extra["director_request"], db.iso(req_at), responsible, aid))
            event(aid, responsible, "director_requested", {"text": extra["director_request"]}, req_at)
        if responsible:
            event(aid, None, "assigned", {"responsible_id": responsible, "responsible": users[responsible][1], "auto": True}, created)
        else:
            event(aid, None, "assigned", {"responsible_id": None, "auto": True, "reason": "no_responsible"}, created)
        for h, actor, kind, payload in history:
            at = created + timedelta(hours=h)
            event(aid, actor, kind, payload, at)
            if kind == "status_changed" and typ != "praise":
                if payload["to"] == "review":
                    points(author, aid, "accepted", 10, at, number)
                if payload["to"] == "done":
                    points(author, aid, "done", 50, at, number)
    for number, supporters in SUPPORTS.items():
        aid = ids[number]
        row = db.one("SELECT created_at, type FROM appeals WHERE id=?", (aid,))
        author = db.one("SELECT user_id FROM appeal_authors WHERE appeal_id=?", (aid,))["user_id"]
        created = db.parse(row["created_at"])
        for i, uid in enumerate(supporters, 1):
            at = created + timedelta(hours=10 + 7 * i)
            c.execute("INSERT INTO supports(appeal_id, user_id, created_at) VALUES(?,?,?)", (aid, uid, db.iso(at)))
            event(aid, None, "supported", {"count": i}, at)
            points(author, aid, "support", 2, at, number)
    for title, descr, cost in REWARDS:
        db.ex("INSERT INTO rewards(title, description, cost_points, active) VALUES(?,?,?,1)", (title, descr, cost))
    for k, v in SETTINGS.items():
        db.set_setting(k, v)
    db.ex("INSERT INTO meta(key, value) VALUES('seeded_at', ?)", (db.now_iso(),))
    c.commit()


if __name__ == "__main__":
    run(force="--force" in sys.argv)
    print("seed ok:", db.one("SELECT COUNT(*) AS n FROM appeals")["n"], "обращений")
