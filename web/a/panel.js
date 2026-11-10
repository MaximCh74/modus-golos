'use strict';
// Веб-панель (desktop): очередь обращений с фильтрами и карточкой, сводка. Для ответственных, директора, администратора.
let ME = null, DICTS = null;
const root = document.getElementById('root');
const S = { filters: {}, rows: [], selected: null, view: 'queue' };
let reloadTimer = null;

async function boot() {
  ME = await API.me();
  if (!ME) { location.href = '/login?next=' + encodeURIComponent('/panel' + location.hash); return; }
  if (ME.role === 'employee') {
    root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-info' }, 'Панель доступна ответственным, директору и администратору. ', h('a', { href: '/app' }, 'Открыть приложение сотрудника'), ' · ', h('a', { href: '/login' }, 'войти как другой пользователь'))));
    return;
  }
  DICTS = await API.get('/api/dicts');
  renderTop();
  window.addEventListener('hashchange', route);
  await route();
  API.sse(ev => {
    if (ev.type === 'notification') { toast(ev.text); ME.unread = (ME.unread || 0) + 1; renderTop(); }
    if (ev.type === 'appeal_created') toast('Новое обращение ' + ev.number);
    if (['appeal_created', 'appeal_updated', 'escalated', 'notification'].includes(ev.type)) {
      clearTimeout(reloadTimer);
      reloadTimer = setTimeout(() => { if (S.view === 'queue') loadQueue(ev.type === 'appeal_created' ? ev.id : null); if (S.selected) loadCard(S.selected); }, 400);
    }
  });
}

function renderTop() {
  let top = document.getElementById('top');
  if (!top) { top = h('div', { class: 'topbar', id: 'top' }); document.body.prepend(top); }
  const hash = location.hash || '#/queue';
  const nav = [['#/queue', 'Очередь']];
  if (ME.role !== 'responsible') nav.push(['#/summary', 'Сводка']);
  nav.push(['#/meetings', 'Совещания']);
  if (ME.role === 'admin') nav.push(['#/admin', 'Администрирование']);
  top.replaceChildren(
    h('a', { href: '#/queue', class: 'brand' }, 'Панель', h('small', {}, 'ГК «Модус Трейд» · обратная связь · демо')),
    h('div', { class: 'nav' }, nav.map(([href, label]) => h('a', { href, class: hash.startsWith(href) || (href === '#/queue' && hash.startsWith('#/appeal')) ? 'active' : '' }, label))),
    h('div', { class: 'spacer' }),
    h('a', { href: '#/notifications', class: 'btn btn-sm bell' }, '🔔', ME.unread ? h('span', { class: 'n' }, String(ME.unread)) : null),
    h('a', { href: '/app', class: 'btn btn-sm' }, 'Приложение'),
    h('a', { href: '/login', class: 'btn btn-sm', title: ME.role_label }, ME.name + ' · ' + ME.role_label));
}

async function route() {
  const hash = location.hash || '#/queue';
  const p = hash.slice(1).split('/').filter(Boolean);
  renderTop();
  try {
    if (p[0] === 'appeal') { S.view = 'queue'; S.selected = Number(p[1]); return await queue(); }
    if (p[0] === 'summary') { S.view = 'summary'; return await summary(); }
    if (p[0] === 'notifications') { S.view = 'notifications'; return await notifications(); }
    if (p[0] === 'meetings') { S.view = 'meetings'; return placeholder('Совещания', 'Список совещаний: итог, поручения, идеи и решения директора — этап 2.'); }
    if (p[0] === 'admin') { S.view = 'admin'; return placeholder('Администрирование', 'Категории ↔ ответственные ↔ SLA, пользователи, филиалы и QR, награды, баллы — этап 4. Сейчас всё задаётся в mf/seed.py.'); }
    S.view = 'queue'; return await queue();
  } catch (e) { root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-bad' }, e.message))); }
}

function placeholder(title, text) {
  root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'h1' }, title), h('div', { class: 'card card-info' }, text, h('div', { class: 'hint mt8' }, 'Честная маркировка: раздел ещё не реализован.'))));
}

// ---------- очередь ----------

function sel(name, options, label, placeholder) {
  const s = h('select', { name }, h('option', { value: '' }, placeholder || 'Все'), options.map(o => h('option', { value: o.value, selected: String(S.filters[name] || '') === String(o.value) }, o.label)));
  s.addEventListener('change', () => { S.filters[name] = s.value; loadQueue(); });
  return h('div', {}, h('label', {}, label), s);
}
function chk(name, label) {
  const c = h('input', { type: 'checkbox', checked: !!S.filters[name] });
  c.addEventListener('change', () => { S.filters[name] = c.checked; loadQueue(); });
  return h('label', { class: 'check' }, c, label);
}

async function queue() {
  const staff = (DICTS.users || []).filter(u => u.role !== 'employee' && u.active);
  const q = h('input', { type: 'search', placeholder: 'Номер или текст', value: S.filters.q || '' });
  q.addEventListener('input', () => { S.filters.q = q.value; clearTimeout(reloadTimer); reloadTimer = setTimeout(loadQueue, 300); });
  const filters = h('div', { class: 'filters' },
    sel('branch_id', DICTS.branches.map(b => ({ value: b.id, label: b.name })), 'Филиал'),
    sel('department_id', DICTS.departments.map(d => ({ value: d.id, label: d.name })), 'Подразделение'),
    sel('category_id', DICTS.categories.map(c => ({ value: c.id, label: c.name })), 'Категория'),
    sel('status', Object.entries(STATUS).map(([v, l]) => ({ value: v, label: l[0] })), 'Статус'),
    sel('responsible_id', staff.map(u => ({ value: u.id, label: u.name })), 'Ответственный'),
    sel('days', [{ value: 7, label: '7 дней' }, { value: 14, label: '14 дней' }, { value: 30, label: '30 дней' }], 'Срок', 'Всё время'),
    h('div', {}, h('label', {}, 'Поиск'), q),
    h('div', { class: 'col' }, chk('overdue', 'Только просроченные'), chk('unassigned', 'Без ответственного'), chk('open', 'Только открытые')));
  const table = h('div', { id: 'queue-table' });
  const card = h('div', { id: 'card', class: 'sticky' }, h('div', { class: 'card muted' }, 'Выберите обращение в очереди'));
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, filters, h('div', { class: 'split' }, table, card)));
  await loadQueue();
  if (S.selected) await loadCard(S.selected);
}

async function loadQueue(flashId) {
  const qp = new URLSearchParams();
  for (const [k, v] of Object.entries(S.filters)) if (v) qp.set(k, v === true ? '1' : v);
  const rows = await API.get('/api/panel/appeals?' + qp.toString());
  S.rows = rows;
  const table = document.getElementById('queue-table');
  if (!table) return;
  const counts = h('div', { class: 'small muted mb8' }, rows.length + ' обращений · просрочено ' + rows.filter(r => r.overdue).length + ' · без ответственного ' + rows.filter(r => r.unassigned).length);
  const tbl = h('table', { class: 'tbl' },
    h('thead', {}, h('tr', {}, ['№', 'Тип', 'Категория', 'Филиал', 'Подразделение', 'Статус', 'Ответственный', 'Возраст', 'Метки', '👍'].map(t => h('th', {}, t)))),
    h('tbody', {}, rows.map(r => h('tr', { class: (S.selected === r.id ? 'sel' : '') + (flashId === r.id ? ' flash' : ''), onclick: () => { location.hash = '#/appeal/' + r.id; } },
      h('td', {}, h('b', {}, r.number), h('div', { class: 'small muted' }, r.text.slice(0, 60) + (r.text.length > 60 ? '…' : ''))),
      h('td', {}, r.type_label, h('div', {}, tag('tag-prio-' + r.priority, r.priority_label))),
      h('td', {}, r.category || h('span', { class: 'muted' }, '—')),
      h('td', {}, r.branch || '—'), h('td', {}, r.department || '—'),
      h('td', {}, badge(r.status)),
      h('td', {}, r.responsible || h('span', { class: 'muted' }, '—')),
      h('td', { title: fmtDate(r.created_at) }, fmtHours(r.age_hours)),
      h('td', {}, r.overdue ? tag('tag-overdue', 'Просрочено') : null, ' ', r.unassigned ? tag('tag-unassigned', 'Без ответственного') : null, ' ', r.is_anonymous ? tag('tag-anon', 'аноним') : null),
      h('td', {}, r.supports || '')))));
  table.replaceChildren(counts, h('div', { class: 'card' }, rows.length ? tbl : h('div', { class: 'muted' }, 'Ничего не найдено')));
}

async function loadCard(id) {
  const box = document.getElementById('card');
  if (!box) return;
  let a;
  try { a = await API.get('/api/appeals/' + id); } catch (e) { box.replaceChildren(h('div', { class: 'card card-bad' }, e.message)); return; }
  for (const tr of document.querySelectorAll('#queue-table tbody tr')) tr.classList.remove('sel');
  const staff = (DICTS.users || []).filter(u => u.role !== 'employee' && u.active);
  const act = async (fn, okMsg) => { try { await fn(); if (okMsg) toast(okMsg); await loadCard(id); await loadQueue(); } catch (e) { toast(e.message, 'bad'); } };
  const head = h('div', { class: 'card' },
    h('div', { class: 'row' }, h('span', { class: 'h1' }, a.number), badge(a.status), a.overdue ? tag('tag-overdue', 'Просрочено') : null, a.unassigned ? tag('tag-unassigned', 'Без ответственного') : null, a.is_anonymous ? tag('tag-anon', 'аноним') : null),
    tracker(a.status),
    h('div', { class: 'small muted' }, [a.type_label, a.priority_label + ' приоритет', a.category || 'категория не определена', a.branch, a.department].filter(Boolean).join(' · ')),
    h('p', { class: 'pre' }, a.text),
    a.proposed_solution ? h('div', { class: 'small' }, h('b', {}, 'Предлагаемое решение: '), a.proposed_solution) : null,
    h('div', { class: 'small muted mt8' }, 'Автор: ' + (a.author ? a.author.name + (a.author.position ? ' (' + a.author.position + ')' : '') : 'анонимно')),
    h('div', { class: 'small muted' }, 'Ответственный: ' + (a.responsible || 'не назначен') + ' · SLA ' + (a.sla || 48) + ' ч · первый ответ: ' + (a.first_response_hours === null ? 'нет' : 'через ' + fmtHours(a.first_response_hours))),
    a.attachments.length ? h('div', { class: 'small mt8' }, 'Вложения: ', a.attachments.map(f => h('a', { href: '/api/attachments/' + f.id, target: '_blank' }, f.filename + ' '))) : null,
    h('div', { class: 'small muted mt8' }, '👍 У меня так же: ' + a.supports));
  const result = a.resolution_text ? h('div', { class: 'card ' + (a.status === 'rejected' ? 'card-bad' : 'card-ok') }, h('b', {}, a.status === 'rejected' ? 'Отклонено — причина' : 'Что сделали'), h('p', { class: 'pre' }, a.resolution_text)) : null;
  let actions = null;
  if (a.can_manage) {
    const assignSel = h('select', {}, h('option', { value: '' }, '— выбрать ответственного —'), staff.map(u => h('option', { value: u.id, selected: u.id === a.responsible_id }, u.name + ' · ' + (u.position || u.role))));
    const assignBtn = h('button', { class: 'btn btn-sm', onclick: () => { if (!assignSel.value) return toast('Выберите ответственного', 'bad'); act(() => API.post('/api/panel/appeals/' + id + '/assign', { responsible_id: Number(assignSel.value) }), 'Назначено'); } }, 'Назначить');
    const statusBox = h('div', { class: 'inline' });
    const reasonTa = h('textarea', { class: 'hidden', placeholder: 'Текст для автора' });
    let pendingStatus = null;
    const confirmBtn = h('button', { class: 'btn btn-sm btn-primary hidden' }, 'Подтвердить');
    confirmBtn.addEventListener('click', () => act(() => API.post('/api/panel/appeals/' + id + '/status', { status: pendingStatus, text: reasonTa.value }), 'Статус изменён'));
    for (const n of a.allowed_next || []) {
      const needText = n.code === 'rejected' || n.code === 'done';
      statusBox.append(h('button', { class: 'btn btn-sm ' + (n.code === 'rejected' ? 'btn-danger' : n.code === 'done' ? 'btn-ok' : ''), onclick: () => {
        if (!needText) return act(() => API.post('/api/panel/appeals/' + id + '/status', { status: n.code }), 'Статус: ' + n.label);
        pendingStatus = n.code; reasonTa.classList.remove('hidden'); confirmBtn.classList.remove('hidden');
        reasonTa.placeholder = n.code === 'rejected' ? 'Мотивировка отказа — автор её увидит (обязательно)' : 'Что сделано — увидит автор и лента «Что изменили» (обязательно)';
        reasonTa.focus();
      } }, '→ ' + n.label));
    }
    const clarTa = h('textarea', { placeholder: 'Вопрос автору' });
    const clarBtn = h('button', { class: 'btn btn-sm', onclick: () => act(() => API.post('/api/panel/appeals/' + id + '/clarify', { text: clarTa.value }), 'Уточнение запрошено') }, 'Запросить уточнение');
    const comTa = h('textarea', { placeholder: 'Комментарий (увидит автор)' });
    const comBtn = h('button', { class: 'btn btn-sm', onclick: () => act(() => API.post('/api/panel/appeals/' + id + '/comment', { text: comTa.value }), 'Комментарий добавлен') }, 'Комментировать');
    actions = h('div', { class: 'card actions' },
      h('b', {}, 'Действия'),
      ['new', 'review', 'clarify', 'in_progress'].includes(a.status) ? h('div', { class: 'row' }, h('div', { class: 'spacer' }, assignSel), assignBtn) : null,
      (a.allowed_next || []).length ? h('div', {}, h('div', { class: 'hint' }, 'Статус'), statusBox, reasonTa, h('div', { class: 'mt8' }, confirmBtn)) : null,
      ['new', 'review'].includes(a.status) ? h('div', {}, clarTa, h('div', { class: 'mt8' }, clarBtn)) : null,
      ['new', 'review', 'clarify', 'in_progress'].includes(a.status) ? h('div', {}, comTa, h('div', { class: 'mt8' }, comBtn)) : null);
  }
  box.replaceChildren(head, result, actions, h('div', { class: 'card' }, h('div', { class: 'h2' }, 'История'), history(a.events)));
  const row = [...document.querySelectorAll('#queue-table tbody tr')].find(tr => tr.textContent.startsWith(a.number));
  if (row) row.classList.add('sel');
}

// ---------- сводка ----------

async function summary() {
  const d = await API.get('/api/panel/summary?days=30');
  const pct = x => x === null || x === undefined ? '—' : Math.round(x * 100) + ' %';
  const kpis = h('div', { class: 'kpis' },
    h('div', { class: 'kpi' }, h('b', {}, String(d.open)), h('span', {}, 'открытых обращений')),
    h('div', { class: 'kpi' }, h('b', {}, pct(d.considered_share)), h('span', {}, 'доля рассмотренных')),
    h('div', { class: 'kpi' }, h('b', {}, fmtHours(d.avg_first_response_hours)), h('span', {}, 'среднее время первого ответа')),
    h('div', { class: 'kpi' }, h('b', {}, String(d.done_period)), h('span', {}, 'реализовано за 30 дней')),
    h('div', { class: 'kpi' }, h('b', {}, String(d.overdue)), h('span', {}, 'просрочено')),
    h('div', { class: 'kpi' }, h('b', {}, String(d.unassigned)), h('span', {}, 'без ответственного')));
  const byType = h('div', { class: 'card' }, h('b', {}, 'По типам'), h('div', { class: 'row mt8' }, Object.entries(d.by_type).map(([t, n]) => h('span', { class: 'badge tag-type' }, TYPES[t] + ': ' + n))),
    h('b', { class: 'mt16' }, 'По статусам'), h('div', { class: 'row mt8' }, Object.entries(d.by_status).map(([s, n]) => h('span', { class: 'badge ' + STATUS[s][1] }, STATUS[s][0] + ': ' + n))));
  const branches = h('div', { class: 'card' }, h('b', {}, 'Филиалы'), h('div', { class: 'hint' }, 'Карта филиалов и лига — этап 4; количество обращений филиал не ранжирует.'),
    h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Филиал', 'Всего', 'Открыто', 'Просрочено', 'Рассмотрено', 'Первый ответ', 'Реализовано', 'Главная тема'].map(t => h('th', {}, t)))),
      h('tbody', {}, d.by_branch.map(b => h('tr', { onclick: () => { S.filters = { branch_id: b.id }; location.hash = '#/queue'; } },
        h('td', {}, b.name), h('td', {}, b.total), h('td', {}, b.open), h('td', {}, b.overdue ? tag('tag-overdue', String(b.overdue)) : '0'),
        h('td', {}, pct(b.considered_share)), h('td', {}, fmtHours(b.avg_first_response_hours)), h('td', {}, b.done_total), h('td', { class: 'small' }, b.top_category || '—'))))));
  const cats = h('div', { class: 'card' }, h('b', {}, 'Открытые обращения по категориям'), h('div', { class: 'hint' }, 'Кластеры «Повторяющиеся темы» (ИИ) — этап 3.'),
    h('div', { class: 'list mt8' }, d.top_categories.map(c => h('div', { class: 'item', onclick: () => { const id = (DICTS.categories.find(x => x.name === c.category) || {}).id; S.filters = { category_id: id, open: true }; location.hash = '#/queue'; } }, h('div', { class: 'row' }, c.category, h('div', { class: 'spacer' }), h('b', {}, String(c.open)))))));
  const check = ME.role !== 'responsible' ? h('button', { class: 'btn btn-sm', onclick: async () => { const r = await API.post('/api/panel/check-overdue'); toast(r.escalated.length ? 'Эскалировано: ' + r.escalated.join(', ') : 'Новых просрочек нет'); summary(); } }, 'Проверить просрочки сейчас') : null;
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, h('div', { class: 'row' }, h('div', { class: 'h1' }, 'Сводка'), h('div', { class: 'spacer' }), check), kpis, h('div', { class: 'split mt16' }, h('div', {}, branches, cats), byType)));
}

async function notifications() {
  const data = await API.get('/api/notifications');
  root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'h1' }, 'Уведомления'),
    h('div', { class: 'card list' }, data.items.length ? data.items.map(n => h('div', { class: 'item', onclick: () => { if (n.link) location.href = n.link; } },
      h('div', { class: 'row' }, n.read_at ? null : h('span', { class: 'badge st-new' }, 'новое'), h('span', { class: 'small muted' }, fmtDate(n.created_at))), h('div', {}, n.text))) : h('div', { class: 'muted' }, 'Уведомлений нет'))));
  if (data.unread) { await API.post('/api/notifications/read', {}); ME.unread = 0; renderTop(); }
}

boot();
