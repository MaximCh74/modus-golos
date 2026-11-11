'use strict';
// /design — живой справочник токенов и компонентов «Модус Голос» (этап 7 §1): значения читаются из :root style.css, образцы — те же классы,
// что на экранах. Новых цветов, шрифтов и декора нет: бренд зафиксирован.
(function () {
  const root = document.getElementById('root');
  const cs = getComputedStyle(document.documentElement);
  const token = n => cs.getPropertyValue(n).trim();
  const groups = [
    ['Бренд', ['--navy', '--red', '--red-dark', '--ink', '--muted', '--muted-2', '--line', '--line-soft', '--bg-soft', '--tint', '--white']],
    ['Статусы (приглушённые)', ['--st-new-bg', '--st-new-fg', '--st-review-bg', '--st-review-fg', '--st-clarify-bg', '--st-clarify-fg', '--st-work-bg', '--st-work-fg', '--ok-tag-bg', '--ok-tag-fg', '--st-closed-bg', '--st-closed-fg', '--st-rejected-bg', '--st-rejected-fg', '--warn-tag-bg', '--warn-tag-fg']],
    ['Карточки-состояния и карта', ['--ok-bg', '--ok-line', '--warn-bg', '--warn-line', '--bad-bg', '--bad-line', '--tint-line', '--map-water', '--map-label']],
  ];
  const swatches = groups.map(([title, names]) => h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, title),
    h('div', { class: 'swatches' }, names.map(n => { const i = h('i'); i.style.background = 'var(' + n + ')'; return h('div', { class: 'swatch' }, i, h('div', {}, h('b', {}, n), h('br'), h('code', {}, token(n)))); }))));
  const scale = [['display', 'Заголовок страницы — display, 700'], ['h1', 'Заголовок раздела — h1, 700'], ['h2', 'Подзаголовок — h2, 700'], ['', 'Основной текст 16px, 500 — как этот абзац'], ['small', 'Мелкий текст 14px'], ['hint', 'Подсказка 13px, серым']];
  const type = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Типографика'), h('p', { class: 'hint' }, 'Montserrat, две насыщенности на экран: 500 и 700. Цифры моноширинные (tabular-nums): 1 234 567. 8px-сетка.'),
    scale.map(([cls, text]) => h('div', { class: cls }, text)), h('div', { class: 'row mt16' }, h('span', { class: 'dash' }), h('span', { class: 'hint' }, 'красная черта над заголовком — фирменный акцент')));
  const buttons = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Кнопки'), h('p', { class: 'hint' }, 'Красная — одно главное действие на экране. Контурная — вторичное. Нейтральная — служебное. Все: hover, focus (рамка), active, disabled; высота от 44px.'),
    h('div', { class: 'ds-row' }, h('button', { class: 'btn btn-primary' }, iconText('pencil', 'Подать обращение')), h('button', { class: 'btn btn-outline' }, iconText('user', 'Войти')), h('button', { class: 'btn' }, 'Нейтральная'), h('button', { class: 'btn btn-ghost' }, 'Прозрачная'),
      h('button', { class: 'btn btn-sm' }, 'Маленькая'), h('button', { class: 'btn btn-ok btn-sm' }, 'Принять'), h('button', { class: 'btn btn-danger btn-sm' }, 'Отклонить'), h('button', { class: 'btn btn-primary', disabled: true }, 'Недоступна'), h('button', { class: 'btn btn-round', title: 'Команда голосом' }, icon('mic'))));
  const cards = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Поверхности'), h('p', { class: 'hint' }, 'Скругления: карточки 16–20px, кнопки и поля 12px, чипы 999px. Тени две: обычная карточка (shadow-1) и всплывающая (shadow-2).'),
    h('div', { class: 'grid2' }, h('div', { class: 'card' }, h('b', {}, 'Карточка'), h('div', { class: 'small muted' }, 'рамка 1px, без тени')), h('div', { class: 'card card-elevated' }, h('b', {}, 'Всплывающая'), h('div', { class: 'small muted' }, 'тень shadow-2, без рамки')),
      h('div', { class: 'card card-info' }, h('b', {}, 'Информация')), h('div', { class: 'card card-ok' }, h('b', {}, 'Сделано')), h('div', { class: 'card card-warn' }, h('b', {}, 'Внимание')), h('div', { class: 'card card-bad' }, h('b', {}, 'Отклонено'))),
    h('div', { class: 'cc-tiles' }, h('div', { class: 'tile' }, icon('folder', { size: 22 }), h('span', {}, 'Открытых'), h('b', {}, '12')), h('div', { class: 'tile' }, icon('check-circle', { size: 22 }), h('span', {}, 'Решено за месяц'), h('b', {}, '9'))),
    h('div', { class: 'cc-theme mt8' }, icon('layers', { size: 18 }), h('span', {}, 'Главная тема: ', h('b', {}, 'Номенклатура и спецификации'))));
  const chips = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Чипы и статусы'),
    h('div', { class: 'chips' }, h('button', { class: 'chip on' }, 'Прямо сейчас мешает'), h('button', { class: 'chip' }, 'Мешает, но обхожусь'), h('button', { class: 'chip' }, 'Мелочь')),
    h('div', { class: 'row mt8' }, Object.entries(STATUS).map(([k, v]) => h('span', { class: 'badge ' + v[1] }, v[0])), h('span', { class: 'badge tag-overdue' }, 'Просрочено'), h('span', { class: 'badge tag-unassigned' }, 'Без ответственного'), h('span', { class: 'badge tag-ai' }, 'пересказ ИИ'), h('span', { class: 'badge tag-demo' }, 'без ИИ')));
  const tracker = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Таймлайн стадий (словами собственника)'),
    stageTracker({ code: 'elaboration', label: 'Проработка', index: 1, note: null, steps: [{ code: 'accepted', label: 'Принято', state: 'done' }, { code: 'elaboration', label: 'Проработка', state: 'cur' }, { code: 'decision', label: 'Принятие решения', state: 'future' }, { code: 'implementation', label: 'Реализация', state: 'future' }, { code: 'done', label: 'Готово', state: 'future' }] }));
  const inputs = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Поля ввода'),
    h('div', { class: 'grid2' }, field('Текст', h('input', { type: 'text', placeholder: 'Например: «запроси новости по Омску»' })), field('Выбор', h('select', {}, h('option', {}, 'Категория'), h('option', {}, 'Другая'))),
      field('Многострочное', h('textarea', { placeholder: 'Что происходит и что предлагаете' })), h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: true }), 'Флажок')));
  const map = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Карта и метки'), h('p', { class: 'hint' }, 'Метка — красная; подпись — белая «таблетка» с мягкой тенью; выбранный город — пульсирующее свечение; объекты — серые точки; подписи стран — разреженные заглавные светло-серым.'),
    h('div', { class: 'row' }, (() => { const m = h('button', { type: 'button', class: 'marker sel', style: null }, h('span', { class: 'pin' }, icon('map-pin', { size: 30, fill: true, width: 1.5 })), h('span', { class: 'mlabel' }, h('b', {}, 'Омск'), h('span', {}, 'головной офис'))); m.style.position = 'relative'; m.style.transform = 'none'; return m; })(),
      h('span', { class: 'sdot' }), h('span', { class: 'map-country', style: null }, 'Казахстан')));
  map.querySelector('.map-country').style.position = 'static'; map.querySelector('.map-country').style.transform = 'none';
  const motion = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Движение и состояния'), h('p', { class: 'hint' }, '150–250 мс, ease-out; появление карточек — подъём и проявление; prefers-reduced-motion выключает анимации. Загрузка — скелетоны:'),
    h('div', { class: 'row' }, (() => { const k = h('div', { class: 'skeleton' }); k.style.width = '220px'; k.style.height = '56px'; return k; })(), (() => { const k = h('div', { class: 'skeleton' }); k.style.width = '120px'; k.style.height = '56px'; return k; })()));
  root.replaceChildren(siteHeader(null, {}), h('main', { class: 'home' }, h('span', { class: 'dash' }), h('h1', { class: 'display' }, 'Дизайн-система'), h('p', { class: 'lead' }, 'Токены и компоненты «Модус Голос». Бренд зафиксирован: тёмно-синий, красный, белый, два серых, Montserrat, логотип заказчика. Иконки — Lucide.'),
    swatches, type, buttons, cards, chips, tracker, inputs, map, motion));
})();
