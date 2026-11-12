'use strict';
// Демо-вход «Войти как…» без паролей. В пилоте — Битрикс24 или корпоративная учётка.
(async function () {
  const root = document.getElementById('root');
  const next = qs('next') || '';
  const [me, cfg] = await Promise.all([API.me(), API.get('/api/public/config').catch(() => ({}))]);
  const demo = cfg.demo_login !== false;   // MF_DEMO_LOGIN=0 (пилот) — без «Войти как…»: только Битрикс24 или личное приглашение
  const users = demo ? await API.get('/api/auth/users').catch(() => []) : [];
  const order = ['employee', 'responsible', 'director', 'admin'];
  const names = { employee: 'Сотрудники', responsible: 'Ответственные', director: 'Директор', admin: 'Администратор' };
  const page = h('div', { class: 'wrap' },
    h('div', { class: 'hero dots' }, h('a', { href: '/', class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })), h('div', { class: 'lbl mt16' }, 'Модус Голос · каждый голос услышан'), h('div', { class: 'h1' }, 'Войти как…')),
    cfg.bitrix && window.self === window.top ? h('div', { class: 'card card-info' }, h('div', { class: 'row' }, h('div', {}, h('b', {}, 'Сотрудникам компании'), h('div', { class: 'small muted' }, 'Вход учётной записью портала ' + (cfg.bitrix_portal || 'Битрикс24') + '; внутри портала пункт «Модус Голос» открывается без входа.')),
      h('div', { class: 'spacer' }), h('a', { href: cfg.bitrix_login + (next ? '?next=' + encodeURIComponent(next) : ''), class: 'btn btn-primary' }, iconText('log-in', 'Войти через Битрикс24')))) : null,
    (window.self !== window.top) ? h('div', { class: 'card card-warn' }, h('b', {}, 'Сессия внутри портала не найдена. '), 'Откройте «Модус Голос» из левого меню Битрикс24 ещё раз — вход произойдёт автоматически, без пароля.') : null,
    demo ? h('p', { class: 'muted small' }, cfg.bitrix ? 'Запасной демо-вход без паролей. Все пользователи вымышленные.' : 'Демо-вход без паролей. Все пользователи вымышленные.')
      : h('div', { class: 'card card-info' }, 'Вход — через Битрикс24 или по личному приглашению от администратора (ссылка или QR-карточка).'),
    me ? h('div', { class: 'card card-info row' }, 'Сейчас вы — ', h('b', {}, me.name), h('div', { class: 'spacer' }),
      h('a', { href: me.role === 'employee' ? '/app' : '/panel', class: 'btn btn-sm' }, 'Продолжить'),
      h('button', { class: 'btn btn-sm', onclick: async () => { await API.post('/api/auth/logout'); location.reload(); } }, 'Выйти')) : null);
  for (const role of order) {
    const list = users.filter(u => u.role === role);
    if (!list.length) continue;
    page.append(h('div', { class: 'h2' }, names[role]), h('div', { class: 'user-grid' }, list.map(u =>
      h('div', { class: 'user-card', onclick: () => loginAs(u) },
        h('b', {}, u.name), h('div', { class: 'small' }, u.position || ''), h('div', { class: 'small muted' }, [u.branch, u.department].filter(Boolean).join(' · '))))));
  }
  page.append(h('div', { class: 'dev' }, 'разработано ', h('b', {}, 'Cyber QALQAN Systems'), demo ? ' · демо-вход без паролей, в пилоте — Битрикс24 или корпоративная учётка' : ''));
  root.replaceChildren(page);

  async function loginAs(u) {
    try {
      const me = await API.post('/api/auth/login-as', { user_id: u.id });
      location.href = next || (me.role === 'employee' ? '/app' : '/panel');
    } catch (e) { toast(e.message, 'bad'); }
  }
})();
