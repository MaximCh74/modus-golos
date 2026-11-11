'use strict';
// Стартовая страница (этап 6 §3): интерактивная карта вместо стены QR. Шапка — логотип, одна строка, кнопка «Войти»;
// нажатие на город — карточка с типом, открытыми и решёнными за месяц, главной темой, QR города и кнопкой «Подать обращение».
// На телефоне карта сверху, ниже — города кнопками. Данные — /api/public/map (без входа), тот же компонент карты, что у директора.
(async function () {
  const root = document.getElementById('root');
  const [map, me, cfg] = await Promise.all([API.get('/api/public/map'), API.me(), API.get('/api/public/config').catch(() => ({}))]);
  const card = h('div', { class: 'card city-card' });
  const buttons = h('div', { class: 'city-buttons' });
  let mapEl = null;

  function show(b) {
    if (mapEl) mapEl.select(b.id);
    for (const x of buttons.children) x.classList.toggle('on', String(x.dataset.id) === String(b.id));
    const theme = b.top_category ? b.top_category : 'открытых обращений нет';
    card.replaceChildren(
      h('div', { class: 'row' }, h('div', { class: 'h1' }, b.city || b.name), tag('tag-type', b.kind_label || 'объект')),
      b.kind === 'field' ? h('p', { class: 'small muted' }, 'Для командированных на объектах по всему Казахстану: в форме можно указать город или объект.')
        : h('div', { class: 'row small' }, h('span', {}, 'Открытых: ', h('b', {}, String(b.open))), h('span', { class: 'muted' }, '·'), h('span', {}, 'Решено за месяц: ', h('b', {}, String(b.done_month))),
            h('span', { class: 'muted' }, '·'), h('span', {}, 'Главная тема: ', h('b', {}, theme))),
      h('div', { class: 'qr-box mt8' }, h('img', { src: b.qr_svg, alt: 'QR ' + (b.city || b.name) }), h('div', {}, h('div', { class: 'small muted' }, 'Отсканируйте с телефона — откроется форма «Проблема / Идея» для ' + (b.kind === 'field' ? 'объекта' : 'этого города') + '.'),
        h('div', { class: 'small muted mt8' }, b.qr_url))),
      h('a', { href: b.form_url, class: 'btn btn-primary btn-big mt8' }, 'Подать обращение'));
  }
  mapEl = mapView(map, { onBranch: show, onSite: () => { if (map.field) show(map.field); } });
  for (const b of map.branches) { const bt = h('button', { type: 'button', class: 'btn btn-sm', onclick: () => show(b) }, b.city + (b.kind === 'production' ? ' · производство' : '')); bt.dataset.id = b.id; buttons.append(bt); }
  if (map.field) { const bt = h('button', { type: 'button', class: 'btn btn-sm', onclick: () => show(map.field) }, 'Я на объекте'); bt.dataset.id = map.field.id; buttons.append(bt); }
  card.replaceChildren(h('div', { class: 'h2' }, 'Выберите город'), h('p', { class: 'small muted' }, 'Нажмите на метку города на карте или на кнопку — появится QR и кнопка «Подать обращение». Командированным на объектах — кнопка «Я на объекте».'));

  const loginBtns = me
    ? h('div', { class: 'row' }, h('span', { class: 'small muted' }, me.name), h('a', { href: me.role === 'employee' ? '/app' : '/panel', class: 'btn btn-sm btn-primary' }, me.role === 'employee' ? 'Приложение' : 'Панель'))
    : h('div', { class: 'row' }, cfg.bitrix ? h('a', { href: cfg.bitrix_login, class: 'btn btn-sm btn-primary' }, iconText('log-in', 'Войти через Битрикс24')) : null,
        h('a', { href: '/login', class: 'btn btn-sm' + (cfg.bitrix ? '' : ' btn-primary') }, iconText('log-in', cfg.bitrix ? 'Демо-вход' : 'Войти')));
  root.replaceChildren(
    h('div', { class: 'topbar home-top' }, h('a', { href: '/', class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })),
      h('div', { class: 'home-line' }, 'Есть идея или проблема? Выберите город или отсканируйте QR'), h('div', { class: 'spacer' }), loginBtns),
    h('div', { class: 'wrap wrap-wide' },
      h('div', { class: 'home-grid' }, h('div', {}, mapEl, buttons), card),
      h('p', { class: 'small muted' }, h('a', { href: '/rules' }, 'Как начисляются баллы'), ' — прозрачные правила вместо разовых премий. Филиалы и данные демонстрационные.'),
      h('div', { class: 'dev' }, 'разработано ', h('b', {}, 'Cyber QALQAN Systems'), ' · хакатон Pavlodar Hub · стиль — по сайту заказчика, данные синтетические')));
})();
