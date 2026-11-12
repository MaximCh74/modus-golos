'use strict';
// Раздел «Сотрудники» администратора (этап 8 §4, /panel#/admin): ручное добавление, импорт списком (CSV/Excel по шаблону),
// личные приглашения для тех, кого нет в Битриксе (ссылка /i/<token> и QR, одноразовые, срок — в настройках), карточки для печати
// (PDF, 4 на лист), отключение с сохранением истории. Состояние раздела живёт между перерисовками экрана администрирования.
const STAFF_UI = { showAdd: false, showImport: false, invite: null, importResult: null, q: '', showInactive: false };

function staffSection(d, reload) {
  const users = d.users || [], invites = d.invites || {};
  const fmtDay = (iso, year) => iso ? new Date(iso).toLocaleDateString('ru-RU', year ? { day: '2-digit', month: '2-digit', year: 'numeric' } : { day: '2-digit', month: '2-digit' }) : '';
  const brSel = v => h('select', {}, h('option', { value: '' }, '—'), d.branches.map(b => h('option', { value: b.id, selected: b.id === v }, b.city || b.name)));
  const depSel = v => h('select', {}, h('option', { value: '' }, '—'), d.departments.map(x => h('option', { value: x.id, selected: x.id === v }, x.name)));
  const roleSel = (v, all) => h('select', {}, (all ? [['employee', 'Сотрудник'], ['responsible', 'Ответственный'], ['director', 'Директор'], ['admin', 'Администратор']] : [['employee', 'Сотрудник'], ['responsible', 'Ответственный']]).map(([c, l]) => h('option', { value: c, selected: c === v }, l)));
  const mgrSel = v => h('select', {}, h('option', { value: '' }, '—'), users.filter(u => u.role !== 'employee' && u.active).map(u => h('option', { value: u.id, selected: u.id === v }, u.name)));
  const post = async (fn, ok) => { try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message, 'bad'); throw e; } };
  const statusLabel = i => i.status === 'active' ? 'до ' + fmtDay(i.expires_at) : i.status === 'used' ? 'вошёл ' + fmtDay(i.used_at) : i.status === 'expired' ? 'истекло' : i.status === 'revoked' ? 'отозвано' : i.status === 'deactivated' ? 'отключён' : i.status;
  const statusCls = i => i.status === 'active' ? 'st-done' : i.status === 'used' ? 'st-closed' : 'tag-overdue';
  const showInvite = async id => { STAFF_UI.invite = await post(() => API.get('/api/admin/invites/' + id)); reload(); };
  const issue = async u => { STAFF_UI.invite = await post(() => API.post('/api/admin/invites', { user_id: u.id }), 'Приглашение выдано: ' + u.name); reload(); };

  // ---- кнопки раздела
  const tools = h('div', { class: 'row staff-tools' },
    h('button', { class: 'btn btn-sm' + (STAFF_UI.showAdd ? ' on' : ''), onclick: () => { STAFF_UI.showAdd = !STAFF_UI.showAdd; reload(); } }, iconText('user-plus', 'Добавить сотрудника')),
    h('button', { class: 'btn btn-sm' + (STAFF_UI.showImport || STAFF_UI.importResult ? ' on' : ''), onclick: () => { STAFF_UI.showImport = !STAFF_UI.showImport; if (!STAFF_UI.showImport) STAFF_UI.importResult = null; reload(); } }, iconText('upload', 'Импорт из CSV или Excel')),
    h('a', { href: '/api/admin/users/template.csv', class: 'btn btn-sm', download: 'сотрудники_шаблон.csv', title: 'Шаблон списка для Excel: Имя; Город; Отдел; Роль; Телефон; Должность; Почта' }, iconText('download', 'Шаблон CSV')),
    h('a', { href: '/api/admin/invites/cards.pdf?all=1', class: 'btn btn-sm', target: '_blank', rel: 'noopener', title: 'Все действующие приглашения — карточки для печати, 4 на лист A4' }, iconText('printer', 'Карточки: все действующие')));

  // ---- добавить вручную
  let addCard = null;
  if (STAFF_UI.showAdd) {
    const name = h('input', { type: 'text', placeholder: 'Имя Фамилия', autocomplete: 'off' }); const br = brSel(null); const dep = depSel(null); const role = roleSel('employee');
    const pos = h('input', { type: 'text', placeholder: 'например, Оператор участка' }); const phone = h('input', { type: 'text', placeholder: '+7 701 000 00 00', inputmode: 'tel' }); const email = h('input', { type: 'text', placeholder: 'необязательно' });
    const inv = h('input', { type: 'checkbox', checked: true });
    const btn = h('button', { class: 'btn btn-primary', onclick: async () => {
      btn.disabled = true;
      try {
        const r = await API.post('/api/admin/users', { name: name.value, role: role.value, position: pos.value, branch_id: br.value ? Number(br.value) : null, department_id: dep.value ? Number(dep.value) : null, manager_id: null, active: true, email: email.value, phone: phone.value, invite: inv.checked });
        toast('Сотрудник добавлен: ' + r.name + (r.invite ? ' — приглашение выдано' : ''));
        STAFF_UI.invite = r.invite || null; STAFF_UI.showAdd = false; reload();
      } catch (e) { toast(e.message, 'bad'); btn.disabled = false; }
    } }, iconText('plus', 'Добавить'));
    addCard = h('div', { class: 'card card-info' }, h('b', {}, 'Новый сотрудник'),
      h('div', { class: 'hint' }, 'Для тех, кого нет в Битрикс24: рабочие, производство, командированные. Телефон необязателен, но по нему профиль склеится с учёткой портала, если человек появится и там.'),
      h('div', { class: 'grid3 mt8' }, field('Имя и фамилия', name), field('Город / филиал', br), field('Отдел', dep), field('Роль', role), field('Должность', pos), field('Телефон', phone), field('Почта', email)),
      h('div', { class: 'row mt8' }, btn, h('label', { class: 'check small' }, inv, 'сразу выдать личное приглашение — ссылку и QR'), h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-ghost', onclick: () => { STAFF_UI.showAdd = false; reload(); } }, 'Отмена')));
  }

  // ---- импорт списком
  let importCard = null;
  if (STAFF_UI.showImport || STAFF_UI.importResult) {
    const file = h('input', { type: 'file', accept: '.csv,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const inv = h('input', { type: 'checkbox', checked: true });
    const btn = h('button', { class: 'btn btn-primary btn-sm', onclick: async () => {
      if (!file.files.length) return toast('Выберите файл CSV или Excel по шаблону', 'bad');
      btn.disabled = true;
      const fd = new FormData(); fd.set('file', file.files[0]); fd.set('invite', inv.checked ? '1' : '0');
      try { STAFF_UI.importResult = await API.postForm('/api/admin/users/import', fd); STAFF_UI.showImport = true; reload(); } catch (e) { toast(e.message, 'bad'); btn.disabled = false; }
    } }, iconText('upload', 'Импортировать'));
    const r = STAFF_UI.importResult;
    const result = r ? h('div', { class: 'mt8' },
      h('div', { class: 'row' }, tag(r.created ? 'st-done' : 'tag-type', 'добавлено ' + r.created), tag('tag-type', 'обновлено ' + r.updated), tag(r.errors.length ? 'tag-overdue' : 'tag-type', 'ошибок ' + r.errors.length),
        r.cards_url ? h('a', { href: r.cards_url, class: 'btn btn-sm btn-primary', target: '_blank', rel: 'noopener' }, iconText('printer', 'Карточки для добавленных (' + r.invites.length + ')')) : null,
        h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-ghost', onclick: () => { STAFF_UI.importResult = null; STAFF_UI.showImport = false; reload(); } }, 'Закрыть')),
      r.errors.length ? h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Строка', 'Что в файле', 'Почему не загружена'].map(t => h('th', {}, t)))),
        h('tbody', {}, r.errors.map(e => h('tr', { class: 'noclick' }, h('td', { class: 'small' }, String(e.row)), h('td', { class: 'small' }, e.text), h('td', { class: 'small' }, e.error))))) : null,
      r.users.length ? h('div', { class: 'small muted mt8' }, 'Загружены: ' + r.users.map(u => u.name + (u.action === 'updated' ? ' (уже был — дополнен)' : '')).join(', ')) : null) : null;
    importCard = h('div', { class: 'card card-info' }, h('b', {}, 'Импорт списком'),
      h('div', { class: 'hint' }, 'Файл по шаблону: Имя; Город; Отдел; Роль; Телефон; Должность; Почта (CSV или Excel). Ошибочная строка попадает в отчёт, остальные заводятся; повторы по телефону или почте не плодят дублей.'),
      h('div', { class: 'row mt8' }, file, h('label', { class: 'check small' }, inv, 'новым — сразу приглашения'), btn), result);
  }

  // ---- карточка приглашения: QR, ссылка, PDF, выдать заново
  let inviteCard = null;
  if (STAFF_UI.invite) {
    const i = STAFF_UI.invite, u = i.user || {};
    const link = h('input', { type: 'text', value: i.url || '', readonly: true, class: 'inv-link' });
    inviteCard = h('div', { class: 'card card-ok invite-card' },
      h('div', { class: 'row' }, h('b', {}, 'Личное приглашение: ' + (u.name || '')), h('span', { class: 'small muted' }, [u.city, u.department, u.position].filter(Boolean).join(' · ')), tag(statusCls(i), statusLabel(i)),
        h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-ghost', title: 'Закрыть', onclick: () => { STAFF_UI.invite = null; reload(); } }, icon('x'))),
      h('div', { class: 'inv-body mt8' },
        h('img', { src: i.qr_svg, alt: 'QR приглашения', class: 'inv-qr' }),
        h('div', { class: 'inv-text' },
          h('div', { class: 'small' }, 'Сотрудник открывает QR камерой телефона (или ссылку), нажимает «Войти» — и телефон запомнил его. Паролей нет. Ссылка одноразовая, действует до ' + fmtDay(i.expires_at, true) + '.'),
          h('div', { class: 'row mt8' }, link, h('button', { class: 'btn btn-sm', onclick: async () => { try { await navigator.clipboard.writeText(i.url); toast('Ссылка скопирована'); } catch (e) { link.select(); toast('Скопируйте ссылку из поля'); } } }, iconText('copy', 'Копировать'))),
          h('div', { class: 'row mt8' }, h('a', { href: i.card_url, class: 'btn btn-sm btn-primary', target: '_blank', rel: 'noopener' }, iconText('printer', 'Карточка для печати (PDF)')),
            h('button', { class: 'btn btn-sm', onclick: () => issue(u) }, iconText('refresh', 'Выдать заново')),
            h('span', { class: 'hint' }, '«Выдать заново» — прежняя ссылка сразу перестаёт работать, прежний телефон выходит из системы.')))));
  }

  // ---- таблица
  const counter = h('span', { class: 'small muted' });
  const q = h('input', { type: 'search', placeholder: 'Имя, город, отдел, телефон', value: STAFF_UI.q });
  q.addEventListener('input', () => { STAFF_UI.q = q.value; renderRows(); });
  const showInactive = h('input', { type: 'checkbox', checked: STAFF_UI.showInactive });
  showInactive.addEventListener('change', () => { STAFF_UI.showInactive = showInactive.checked; renderRows(); });
  const tbody = h('tbody', {});
  const bOf = id => d.branches.find(b => b.id === id) || {}; const dOf = id => (d.departments.find(x => x.id === id) || {}).name || '';

  function userRow(u) {
    const inv = invites[u.id];
    const name = h('input', { type: 'text', value: u.name || '' }); const pos = h('input', { type: 'text', value: u.position || '', placeholder: 'Должность' }); const role = roleSel(u.role, true);
    const br = brSel(u.branch_id); const dep = depSel(u.department_id); const mgr = mgrSel(u.manager_id);
    const phone = h('input', { type: 'text', value: u.phone || '', placeholder: '+7…', class: 'w120', inputmode: 'tel' }); const email = h('input', { type: 'text', value: u.email || '', placeholder: 'почта', class: 'w120' }); const bx = h('input', { type: 'number', value: u.bitrix_id || '', placeholder: 'ID', class: 'w70' });
    const save = h('button', { class: 'btn btn-sm', title: 'Сохранить изменения', onclick: () => post(() => API.post('/api/admin/users', { id: u.id, name: name.value, role: role.value, position: pos.value, branch_id: br.value ? Number(br.value) : null, department_id: dep.value ? Number(dep.value) : null, manager_id: mgr.value ? Number(mgr.value) : null, active: !!u.active, email: email.value, bitrix_id: bx.value ? Number(bx.value) : null, phone: phone.value }), 'Сохранено: ' + name.value).then(reload, () => {}) }, icon('check'));
    const toggle = u.active
      ? h('button', { class: 'btn btn-sm btn-danger', title: 'Отключить: сотрудник больше не входит, обращения и история остаются', onclick: () => { if (confirm('Отключить ' + u.name + '? Вход закроется, обращения, баллы и история останутся.')) post(() => API.post('/api/admin/users/' + u.id + '/active', { active: false }), 'Отключён: ' + u.name).then(reload, () => {}); } }, icon('user-x'))
      : h('button', { class: 'btn btn-sm btn-ok', title: 'Включить обратно', onclick: () => post(() => API.post('/api/admin/users/' + u.id + '/active', { active: true }), 'Включён: ' + u.name).then(reload, () => {}) }, icon('user-plus'));
    let invCell;
    if (!u.active) invCell = h('span', { class: 'muted small' }, 'отключён');
    else {
      const parts = [];
      if (u.bitrix_id) parts.push(h('span', { class: 'small muted', title: 'Сопоставлен с учётной записью портала' }, 'Битрикс24'));
      if (inv) {
        parts.push(tag(statusCls(inv), statusLabel(inv)));
        if (inv.status === 'active') parts.push(h('button', { class: 'btn btn-sm', title: 'Показать QR и ссылку', onclick: () => showInvite(inv.id) }, icon('qr')),
          h('a', { href: '/api/admin/invites/cards.pdf?ids=' + inv.id, class: 'btn btn-sm', target: '_blank', rel: 'noopener', title: 'Карточка для печати (PDF)' }, icon('printer')));
      }
      parts.push(h('button', { class: 'btn btn-sm', title: inv ? 'Выдать заново: прежняя ссылка перестанет работать, прежний телефон выйдет' : 'Выдать личное приглашение — ссылку и QR', onclick: () => issue(u) }, inv ? icon('refresh') : iconText('qr', 'Пригласить')));
      invCell = h('div', { class: 'row inv-cell' }, parts);
    }
    return h('tr', { class: 'noclick' + (u.active ? '' : ' muted') }, h('td', {}, name), h('td', {}, pos), h('td', {}, role), h('td', {}, br), h('td', {}, dep), h('td', {}, mgr), h('td', {}, phone), h('td', {}, email), h('td', {}, bx), h('td', {}, invCell), h('td', {}, h('div', { class: 'row inv-cell' }, save, toggle)));
  }
  function renderRows() {
    const needle = STAFF_UI.q.trim().toLowerCase();
    const rows = users.filter(u => (STAFF_UI.showInactive || u.active) && (!needle || [u.name, u.position, bOf(u.branch_id).city, bOf(u.branch_id).name, dOf(u.department_id), u.phone, u.email].filter(Boolean).join(' ').toLowerCase().includes(needle)));
    tbody.replaceChildren(...rows.map(userRow));
    counter.textContent = rows.length + ' из ' + users.length + ' · активных ' + users.filter(u => u.active).length + ' · с приглашением ' + users.filter(u => invites[u.id] && invites[u.id].status === 'active').length;
  }
  renderRows();
  const table = h('div', { class: 'tblwrap mt8' }, h('table', { class: 'tbl compact staff-tbl' }, h('thead', {}, h('tr', {}, ['Имя', 'Должность', 'Роль', 'Город', 'Отдел', 'Руководитель', 'Телефон', 'Почта', 'ID Б24', 'Приглашение', ''].map(t => h('th', {}, t)))), tbody));
  return h('div', { class: 'card staff' },
    h('div', { class: 'row' }, h('b', {}, 'Сотрудники'), counter, h('div', { class: 'spacer' }), tools),
    h('div', { class: 'hint' }, 'Подать обращение по QR может любой без аккаунта. Аккаунт нужен для «Моих обращений», баллов и наград: сотрудники из Битрикс24 приходят синхронизацией, остальных (рабочие, производство, командированные) добавьте здесь — вручную или списком — и выдайте личное приглашение: ссылку или QR, одноразовую, на ' + (d.invite_days || 14) + ' дн (срок — в настройках). Отключённый сотрудник не входит, его обращения и история остаются.'),
    addCard, importCard, inviteCard,
    h('div', { class: 'row mt8' }, h('div', { class: 'staff-search' }, q), h('label', { class: 'check small' }, showInactive, 'показывать отключённых')),
    table);
}
