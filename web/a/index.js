'use strict';
// Стартовая страница демо: входы и QR-коды филиалов.
(async function () {
  const root = document.getElementById('root');
  const [branches, me] = await Promise.all([API.get('/api/public/branches'), API.me()]);
  root.replaceChildren(h('div', { class: 'wrap' },
    h('div', { class: 'hero dots' }, h('div', { class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })),
      h('div', { class: 'lbl mt16' }, 'Хакатон Pavlodar Hub · демо на синтетических данных'),
      h('div', { class: 'h1' }, 'Обратная связь и предложения сотрудников'),
      h('p', { class: 'muted' }, 'Сотрудник сообщает о проблеме или идее → обращение попадает к ответственному → автор видит статус и результат → повторяющиеся темы видны руководству.')),
    h('div', { class: 'grid2' },
      h('a', { href: '/app', class: 'btn btn-primary btn-big' }, 'Приложение сотрудника'),
      h('a', { href: '/panel', class: 'btn btn-outline btn-big' }, 'Панель руководителя')),
    h('p', { class: 'small' }, me ? ['Вы вошли как ', h('b', {}, me.name), ' (', me.role_label, '). ', h('a', { href: '/login' }, 'Сменить')] : h('a', { href: '/login' }, 'Войти как… (демо-вход без паролей)')),
    h('div', { class: 'lbl mt16' }, 'Главный вход'), h('div', { class: 'h1' }, 'QR-коды филиалов — без установки'),
    h('p', { class: 'hint' }, 'Сканируйте с телефона: откроется форма «Проблема / Идея» для этого филиала. Филиалы демонстрационные.'),
    h('div', { class: 'qr-grid' }, branches.map(b => h('a', { href: '/q/' + b.code, class: 'card' }, h('img', { src: b.qr_svg, alt: 'QR ' + b.name }), h('b', {}, b.name), h('div', { class: 'small muted' }, b.qr_url)))),
    h('p', { class: 'small' }, h('a', { href: '/rules' }, 'Как начисляются баллы'), ' — прозрачные правила вместо разовых премий.'),
    h('div', { class: 'dev' }, 'разработано ', h('b', {}, 'Cyber QALQAN Systems'), ' · стиль — по сайту заказчика, данные синтетические')));
})();
