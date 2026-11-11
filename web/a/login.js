'use strict';
// Демо-вход «Войти как…» без паролей. В пилоте — Битрикс24 или корпоративная учётка.
(async function () {
  const root = document.getElementById('root');
  const next = qs('next') || '';
  const [users, me] = await Promise.all([API.get('/api/auth/users'), API.me()]);
  const order = ['employee', 'responsible', 'director', 'admin'];
  const names = { employee: 'Сотрудники', responsible: 'Ответственные', director: 'Директор', admin: 'Администратор' };
  const page = h('div', { class: 'wrap' },
    h('div', { class: 'hero dots' }, h('a', { href: '/', class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })), h('div', { class: 'lbl mt16' }, 'Обратная связь · демо'), h('div', { class: 'h1' }, 'Войти как…')),
    h('p', { class: 'muted small' }, 'Демо-вход без паролей. Все пользователи вымышленные.'),
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
  page.append(h('div', { class: 'dev' }, 'разработано ', h('b', {}, 'Cyber QALQAN Systems'), ' · демо-вход без паролей, в пилоте — Битрикс24 или корпоративная учётка'));
  root.replaceChildren(page);

  async function loginAs(u) {
    try {
      const me = await API.post('/api/auth/login-as', { user_id: u.id });
      location.href = next || (me.role === 'employee' ? '/app' : '/panel');
    } catch (e) { toast(e.message, 'bad'); }
  }
})();
