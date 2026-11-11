'use strict';
// «Что изменили» без входа (этап 7, шаг 1): реализованные обращения — что было и что сделали. Без авторов: имена видны только после входа.
(async function () {
  const root = document.getElementById('root');
  const [rows, me, cfg] = await Promise.all([API.get('/api/public/changes'), API.me(), API.get('/api/public/config').catch(() => ({}))]);
  root.replaceChildren(siteHeader(me, cfg, { next: '/app#/changes' }), h('main', { class: 'home' }, h('span', { class: 'dash' }), h('h1', { class: 'display' }, 'Что изменили'),
    h('p', { class: 'lead' }, 'Уже сделано по идеям и проблемам сотрудников. ' + (me ? '' : 'После входа видно, кто предложил, и можно сказать «спасибо».')),
    h('div', { class: 'mt16' }, rows.length ? rows.map(r => h('div', { class: 'card' },
      h('div', { class: 'row' }, h('b', {}, r.number), tag('tag-type', r.type_label), h('span', { class: 'small muted' }, [r.category, r.branch].filter(Boolean).join(' · ')), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(r.closed_at))),
      h('p', { class: 'muted' }, r.text),
      h('div', { class: 'card card-ok small ict' }, icon('check-circle', { size: 16 }), r.resolution_text),
      r.thanks ? h('div', { class: 'small muted' }, iconText('heart', plural(r.thanks, 'спасибо от коллеги', 'спасибо от коллег', 'спасибо от коллег'))) : null)) : h('div', { class: 'card muted' }, 'Пока ничего не реализовано — первые результаты появятся здесь.')),
    h('p', { class: 'small muted mt16' }, h('a', { href: '/' }, 'На главную'), ' · ', h('a', { href: me ? '/app#/changes' : '/login?next=' + encodeURIComponent('/app#/changes') }, me ? 'Открыть в приложении' : 'Войти, чтобы сказать «спасибо»'))));
})();
