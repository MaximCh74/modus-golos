'use strict';
// /design — живой справочник токенов и компонентов «Модус Голос» (этап 7 §1): значения читаются из :root style.css, образцы — те же классы,
// что на экранах. Новых цветов, шрифтов и декора нет: бренд зафиксирован.
(function () {
  const root = document.getElementById('root');
  const cs = getComputedStyle(document.documentElement);
  const token = n => cs.getPropertyValue(n).trim();
  const groups = [
    ['Бренд', ['--navy', '--red', '--red-dark', '--ink', '--muted', '--muted-2', '--line', '--line-soft', '--bg-soft', '--tint', '--white']],
    ['Статусы — пять на экране (13.11)', ['--st-fg', '--st-new-bg', '--st-work-bg', '--st-clarify-bg', '--st-done-bg', '--st-rejected-bg', '--tag-neutral-bg', '--tag-neutral-fg']],
    ['Карточки-состояния и карта', ['--ok-bg', '--ok-line', '--warn-bg', '--warn-line', '--bad-bg', '--bad-line', '--tint-line', '--map-water', '--map-label']],
  ];
  const swatches = groups.map(([title, names]) => h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, title),
    h('div', { class: 'swatches' }, names.map(n => { const i = h('i'); i.style.background = 'var(' + n + ')'; return h('div', { class: 'swatch' }, i, h('div', {}, h('b', {}, n), h('br'), h('code', {}, token(n)))); }))));
  const scale = [['display', 'Заголовок страницы — display, 700'], ['h1', 'Заголовок раздела — h1, 700'], ['h2', 'Подзаголовок — h2, 700'], ['', 'Основной текст 16px, 500 — как этот абзац'], ['small', 'Мелкий текст 14px'], ['hint', 'Подсказка 13px, серым']];
  const type = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Типографика'), h('p', { class: 'hint' }, 'Montserrat, две насыщенности на экран: 500 и 700. Цифры моноширинные (tabular-nums): 1 234 567. 8px-сетка.'),
    scale.map(([cls, text]) => h('div', { class: cls }, text)), h('div', { class: 'row mt16' }, h('span', { class: 'dash' }), h('span', { class: 'hint' }, 'красная черта над заголовком — фирменный акцент')));
  const buttons = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Кнопки'), h('p', { class: 'hint' }, 'Главная (тёмно-синяя с красным акцентом в углу) — одно главное действие на экране. Контурная тёмно-синяя — вторичное. Нейтральная — служебное, в том числе отказ и удаление. Все: hover, focus (рамка), active, disabled; высота от 44px. Сплошных красных кнопок нет: красный только у меток карты, логотипа, черты у заголовков и точки просрочки.'),
    h('div', { class: 'ds-row' }, h('button', { class: 'btn btn-primary' }, 'Подать обращение'), h('button', { class: 'btn btn-outline' }, 'Войти'), h('button', { class: 'btn' }, 'Нейтральная'), h('button', { class: 'btn btn-ghost' }, 'Прозрачная'),
      h('button', { class: 'btn btn-sm' }, 'Маленькая'), h('button', { class: 'btn btn-sm' }, 'Отклонить'), h('button', { class: 'btn btn-primary', disabled: true }, 'Недоступна'), h('button', { class: 'btn btn-round', title: 'Команда голосом' }, icon('mic'))));
  // пункт 3 очереди 12.11: главная кнопка нового стиля — три варианта угла и доли красного (выбирает Марк), потом раскатка везде
  const VARIANTS = [['1', 'Мягкий', '135°, красный 20 %', '135deg', '20%'], ['2', 'Заметный', '120°, красный 28 %', '120deg', '28%'], ['3', 'Пологий', '155°, красный 24 %', '155deg', '24%']];
  const variants = h('div', { class: 'ds-section', id: 'ds-main-button' }, h('div', { class: 'h2' }, 'Главная кнопка — три варианта угла и доли красного (в работе вариант 2 «Заметный»)'),
    h('p', { class: 'hint' }, 'Тёмно-синяя основа, красный бренда мягко появляется в правом нижнем углу; текст и иконка белые и всегда на синей части; тонкий светлый блик по верхнему краю, мягкая тень. Три варианта отличаются углом градиента и долей красного. Состояния: обычное, наведение (красная зона плавно растёт за 200 мс), нажатие (темнее, тень меньше), фокус (видимая рамка), недоступна (плоский серый).'),
    h('div', { class: 'ds-variants' }, VARIANTS.map(([n, name, params, angle, red]) => {
      const box = h('div', { class: 'ds-variant', 'data-variant': n });
      box.style.setProperty('--btn-main-angle', angle); box.style.setProperty('--btn-main-red', red);
      const mk = (cls, label, ic) => h('button', { type: 'button', class: 'btn btn-main ' + cls }, ic ? iconText(ic, label) : label);
      box.append(h('div', { class: 'ds-name' }, 'Вариант ' + n + ' · ' + name), h('div', { class: 'ds-params' }, params),
        h('div', { class: 'ds-phone' }, mk('btn-big', 'Отправить', 'send')),
        h('div', { class: 'ds-states' }, mk('', 'Подать обращение', 'pencil'), mk('btn-sm', 'Выполнить'), h('small', {}, 'обычная · маленькая')),
        h('div', { class: 'ds-states' }, mk('is-hover', 'Наведение'), mk('is-active', 'Нажатие'), mk('is-focus', 'Фокус'), mk('is-disabled', 'Недоступна'), h('small', {}, 'состояния — статически, для сравнения')));
      return box;
    })));
  const cards = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Поверхности'), h('p', { class: 'hint' }, 'Скругления: карточки 16–20px, кнопки и поля 12px, чипы 999px. Тени две: обычная карточка (shadow-1) и всплывающая (shadow-2).'),
    h('div', { class: 'grid2' }, h('div', { class: 'card' }, h('b', {}, 'Карточка'), h('div', { class: 'small muted' }, 'рамка 1px, без тени')), h('div', { class: 'card card-elevated' }, h('b', {}, 'Всплывающая'), h('div', { class: 'small muted' }, 'тень shadow-2, без рамки')),
      h('div', { class: 'card card-info' }, h('b', {}, 'Информация')), h('div', { class: 'card card-ok' }, h('b', {}, 'Сделано')), h('div', { class: 'card card-warn' }, h('b', {}, 'Внимание')), h('div', { class: 'card card-bad' }, h('b', {}, 'Отклонено'))),
    h('div', { class: 'cc-tiles' }, h('div', { class: 'tile' }, icon('folder', { size: 22 }), h('span', {}, 'Открытых'), h('b', {}, '12')), h('div', { class: 'tile' }, icon('check-circle', { size: 22 }), h('span', {}, 'Решено за месяц'), h('b', {}, '9'))),
    h('div', { class: 'cc-theme mt8' }, icon('layers', { size: 18 }), h('span', {}, 'Главная тема: ', h('b', {}, 'Номенклатура и спецификации'))));
  const chips = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Чипы и статусы'),
    h('div', { class: 'chips' }, h('button', { class: 'chip on' }, 'Прямо сейчас мешает'), h('button', { class: 'chip' }, 'Мешает, но обхожусь'), h('button', { class: 'chip' }, 'Мелочь')),
    h('div', { class: 'small muted mt8' }, 'Статусы — пять, мягкая заливка, тёмный текст 500 (выбор владельца 13.11)'),
    h('div', { class: 'row mt8 ds-statuses' }, STATUS_GROUPS.map(g => h('span', { class: 'badge ' + g.cls }, g.label))),
    h('div', { class: 'small muted mt8' }, 'Не статусы — прозрачные: серо-синий текст 500, тонкая серая рамка; «Просрочено» — красная точка'),
    h('div', { class: 'row mt8 ds-tags' }, h('span', { class: 'badge tag-overdue' }, 'Просрочено'), h('span', { class: 'badge tag-unassigned' }, 'Без ответственного')));   // плашек и значков ИИ нет — пояснение в «?» (13.11)
  const tracker = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Таймлайн стадий (словами собственника)'),
    stageTracker({ code: 'elaboration', label: 'Проработка', index: 1, note: null, steps: [{ code: 'accepted', label: 'Принято', state: 'done' }, { code: 'elaboration', label: 'Проработка', state: 'cur' }, { code: 'decision', label: 'Принятие решения', state: 'future' }, { code: 'implementation', label: 'Реализация', state: 'future' }, { code: 'done', label: 'Готово', state: 'future' }] }));
  const inputs = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Поля ввода'),
    h('div', { class: 'grid2' }, field('Текст', h('input', { type: 'text', placeholder: 'Например: «запроси новости по Омску»' })), field('Выбор', pick({ value: 'cat', options: [{ value: 'cat', label: 'Категория' }, { value: 'other', label: 'Другая' }] })),
      field('Многострочное', h('textarea', { placeholder: 'Что происходит и что предлагаете' })), h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: true }), 'Флажок')));
  const map = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Карта и метки'), h('p', { class: 'hint' }, 'Метка — красная; подпись — белая «таблетка» с мягкой тенью; выбранный город — пульсирующее свечение; объекты — серые точки; подписи стран — разреженные заглавные светло-серым.'),
    h('div', { class: 'row' }, (() => { const m = h('button', { type: 'button', class: 'marker sel', style: null }, h('span', { class: 'pin' }, icon('map-pin', { size: 30, fill: true, width: 1.5 })), h('span', { class: 'mlabel' }, h('b', {}, 'Омск'), h('span', {}, 'головной офис'))); m.style.position = 'relative'; m.style.transform = 'none'; return m; })(),
      h('span', { class: 'sdot' }), h('span', { class: 'map-country', style: null }, 'Казахстан')));
  map.querySelector('.map-country').style.position = 'static'; map.querySelector('.map-country').style.transform = 'none';
  const motion = h('div', { class: 'ds-section' }, h('div', { class: 'h2' }, 'Движение и состояния'), h('p', { class: 'hint' }, '150–250 мс, ease-out; появление карточек — подъём и проявление; prefers-reduced-motion выключает анимации. Загрузка — скелетоны:'),
    h('div', { class: 'row' }, (() => { const k = h('div', { class: 'skeleton' }); k.style.width = '220px'; k.style.height = '56px'; return k; })(), (() => { const k = h('div', { class: 'skeleton' }); k.style.width = '120px'; k.style.height = '56px'; return k; })()));
  root.replaceChildren(siteHeader(null, {}), h('main', { class: 'home' }, h('span', { class: 'dash' }), h('h1', { class: 'display' }, 'Дизайн-система'), h('p', { class: 'lead' }, 'Токены и компоненты «Модус Голос». Бренд зафиксирован: тёмно-синий, красный, белый, два серых, Montserrat, логотип заказчика. Иконки — Lucide.'),
    swatches, type, variants, buttons, cards, chips, tracker, inputs, map, motion));
})();
