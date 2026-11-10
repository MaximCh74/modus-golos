'use strict';
// Стартовая страница демо: входы и QR-коды филиалов.
(async function () {
  const root = document.getElementById('root');
  const [branches, me] = await Promise.all([API.get('/api/public/branches'), API.me()]);
  root.replaceChildren(h('div', { class: 'wrap' },
    h('div', { class: 'hero' }, h('div', { class: 'brand' }, 'Обратная связь и предложения сотрудников', h('small', {}, 'ГК «Модус Трейд» · хакатон Pavlodar Hub · демо на синтетических данных')),
      h('p', { class: 'muted' }, 'Сотрудник сообщает о проблеме или идее → обращение попадает к ответственному → автор видит статус и результат → повторяющиеся темы видны руководству.')),
    h('div', { class: 'grid2' },
      h('a', { href: '/app', class: 'btn btn-primary btn-big' }, 'Приложение сотрудника'),
      h('a', { href: '/panel', class: 'btn btn-primary btn-big' }, 'Панель руководителя')),
    h('p', { class: 'small' }, me ? ['Вы вошли как ', h('b', {}, me.name), ' (', me.role_label, '). ', h('a', { href: '/login' }, 'Сменить')] : h('a', { href: '/login' }, 'Войти как… (демо-вход без паролей)')),
    h('div', { class: 'h2' }, 'QR-коды филиалов — главный вход без установки'),
    h('p', { class: 'hint' }, 'Сканируйте с телефона: откроется форма «Проблема / Идея» для этого филиала. Филиалы демонстрационные.'),
    h('div', { class: 'qr-grid' }, branches.map(b => h('a', { href: '/q/' + b.code, class: 'card' }, h('img', { src: b.qr_svg, alt: 'QR ' + b.name }), h('b', {}, b.name), h('div', { class: 'small muted' }, b.qr_url))))));
})();
