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
    if (ev.type === 'appeal_created') { toast('Новое обращение ' + ev.number); if (MAPVIEW && ev.branch_id) MAPVIEW.flash(ev.branch_id); }
    if (ev.type === 'meeting_updated' && location.hash.startsWith('#/meetings/' + ev.id)) route();
    if (ev.type === 'idea_pending' && location.hash === '#/decisions') route();
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
  if (ME.role !== 'responsible') nav.push(['#/decisions', 'На решение']);
  nav.push(['#/league', 'Лига']);
  if (ME.role === 'admin' || ME.role === 'director') nav.push(['#/admin', 'Администрирование']);
  top.replaceChildren(
    h('a', { href: '#/queue', class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' }), h('span', {}, 'Панель', h('small', {}, 'обратная связь · демо'))),
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
    if (p[0].startsWith('queue?')) { S.view = 'queue'; const qp = new URLSearchParams(p[0].slice(6)); S.filters = {}; for (const [k, v] of qp) S.filters[k] = v === '1' ? true : v; return await queue(); }
    if (p[0] === 'summary') { S.view = 'summary'; return await summary(); }
    if (p[0] === 'notifications') { S.view = 'notifications'; return await notifications(); }
    if (p[0] === 'meetings' && p[1] === 'new') { S.view = 'meetings'; return await meetingStart({ backHref: '#/meetings', cardPrefix: '#/meetings/' }); }
    if (p[0] === 'meetings' && p[1]) { S.view = 'meetings'; return await meetingCard(Number(p[1]), { backHref: '#/meetings', cardPrefix: '#/meetings/' }); }
    if (p[0] === 'meetings' || p[0].startsWith('meetings?')) { S.view = 'meetings'; return await meetingsList(); }
    if (p[0] === 'decisions') { S.view = 'decisions'; return await decisionsScreen({ backHref: '#/queue' }); }
    if (p[0] === 'admin') { S.view = 'admin'; return await adminScreen(); }
    if (p[0] === 'league') { S.view = 'league'; return await leaguePanel(); }
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
    sel('sort', [{ value: 'priority', label: 'По приоритету' }], 'Сортировка', 'По дате'),
    h('div', {}, h('label', {}, 'Поиск'), q),
    h('div', { class: 'col' }, chk('overdue', 'Только просроченные'), chk('unassigned', 'Без ответственного'), chk('open', 'Только открытые')),
    h('div', { class: 'col' }, (() => { const c = h('input', { type: 'checkbox', checked: S.filters.urgency === 'now' }); c.addEventListener('change', () => { S.filters.urgency = c.checked ? 'now' : ''; loadQueue(); }); return h('label', { class: 'check' }, c, 'Мешает работать сейчас'); })()));
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
    h('thead', {}, h('tr', {}, ['№ · Коротко', 'Тип', 'Категория', 'Филиал', 'Подразделение', 'Статус', 'Ответственный', 'Возраст', 'Новость автору', 'Метки', '👍'].map(t => h('th', {}, t)))),
    h('tbody', {}, rows.map(r => h('tr', { class: (S.selected === r.id ? 'sel' : '') + (flashId === r.id ? ' flash' : ''), onclick: () => { location.hash = '#/appeal/' + r.id; } },
      h('td', {}, h('b', {}, r.number), h('div', { class: 'small muted' }, (r.brief_line || r.text).slice(0, 70) + ((r.brief_line || r.text).length > 70 ? '…' : ''))),
      h('td', {}, r.type_label, h('div', {}, tag('tag-prio-' + r.priority, r.priority_label)), r.author_urgency === 'now' ? h('div', {}, tag('tag-flag', 'мешает сейчас')) : null),
      h('td', {}, r.category || h('span', { class: 'muted' }, '—')),
      h('td', {}, r.branch || '—'), h('td', {}, r.department || '—'),
      h('td', {}, badge(r.status)),
      h('td', {}, r.responsible || h('span', { class: 'muted' }, '—')),
      h('td', { title: fmtDate(r.created_at) }, fmtHours(r.age_hours)),
      h('td', { class: 'small' }, r.news_days === null || r.news_days === undefined ? '—' : r.news_days < 1 ? 'сегодня' : Math.floor(r.news_days) + ' дн назад'),
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
  const rebriefBtn = a.can_manage ? h('button', { class: 'btn btn-sm', onclick: () => act(() => API.post('/api/panel/appeals/' + id + '/rebrief'), 'Пересказ обновлён') }, '↻ Пересказать заново') : null;
  const prioSel = a.can_manage ? h('select', { class: 'mi-sel' }, Object.entries(PRIO).map(([v, l]) => h('option', { value: v, selected: v === a.priority }, l))) : null;
  if (prioSel) prioSel.addEventListener('change', () => act(() => API.post('/api/panel/appeals/' + id + '/priority', { priority: prioSel.value }), 'Приоритет изменён'));
  const head = h('div', { class: 'card' },
    h('div', { class: 'row' }, h('span', { class: 'h1' }, a.number), badge(a.status), a.overdue ? tag('tag-overdue', 'Просрочено') : null, a.unassigned ? tag('tag-unassigned', 'Без ответственного') : null, a.is_anonymous ? tag('tag-anon', 'аноним') : null),
    tracker(a.status),
    h('div', { class: 'small muted' }, [a.type_label, a.category || 'категория не определена', a.branch, a.site_city ? 'объект: ' + a.site_city : null, a.department].filter(Boolean).join(' · ')),
    briefBlock(a, { actions: a.can_manage && a.brief ? h('div', { class: 'row mt8' }, a.brief.unclear && a.brief.question && ['new', 'review'].includes(a.status) ? h('button', { class: 'btn btn-sm btn-outline', onclick: () => act(() => API.post('/api/panel/appeals/' + id + '/clarify', { text: a.brief.question }), 'Уточнение запрошено') }, 'Запросить уточнение: вопрос ИИ') : null, rebriefBtn) : null }),
    fullText(a),
    h('div', { class: 'row small mt8' }, h('b', {}, 'Автор оценил: '), h('span', {}, [a.author_urgency_label, a.author_scope_label].filter(Boolean).join(' · ') || 'не отвечал'), h('span', { class: 'muted' }, '·'), h('b', {}, 'Приоритет: '), prioSel || h('span', {}, a.priority_label), a.priority_manual ? h('span', { class: 'hint' }, '(изменён ответственным)') : null),
    h('div', { class: 'row small mt8' }, h('span', { class: 'muted' }, 'Автор:'), userLink(a.author, 'sm')),
    h('div', { class: 'small muted' }, 'Ответственный: ' + (a.responsible || 'не назначен') + ' · SLA ' + (a.sla || 48) + ' ч · первый ответ: ' + (a.first_response_hours === null ? 'нет' : 'через ' + fmtHours(a.first_response_hours))),
    a.attachments.length ? h('div', { class: 'small mt8' }, 'Вложения: ', a.attachments.map(f => h('a', { href: '/api/attachments/' + f.id, target: '_blank' }, f.filename + ' '))) : null,
    h('div', { class: 'small muted mt8' }, '👍 У меня так же: ' + a.supports + (a.thanks ? ' · 🙏 спасибо: ' + a.thanks : '') + (a.news_days !== null && a.news_days !== undefined ? ' · последняя новость автору: ' + (a.news_days < 1 ? 'сегодня' : Math.floor(a.news_days) + ' дн назад') : '')));
  const result = a.resolution_text ? h('div', { class: 'card ' + (a.status === 'rejected' ? 'card-bad' : 'card-ok') }, h('b', {}, a.status === 'rejected' ? 'Отклонено — причина' : 'Что сделали'), h('p', { class: 'pre' }, a.resolution_text)) : null;
  const director = a.director_decision ? h('div', { class: 'card ' + (a.director_decision === 'pending' ? 'card-info' : a.director_decision === 'accepted' ? 'card-ok' : 'card-bad') },
    h('div', { class: 'row' }, h('b', {}, 'Решение директора: '), tag(a.director_decision === 'pending' ? 'st-review' : a.director_decision === 'accepted' ? 'st-done' : 'st-rejected', a.director_decision_label), h('span', { class: 'small muted' }, fmtDate(a.director_decided_at || a.director_requested_at))),
    h('div', { class: 'small mt8' }, h('b', {}, 'Что требуется: '), a.director_request_text), a.director_comment ? h('div', { class: 'small' }, h('b', {}, 'Комментарий: '), a.director_comment) : null) : null;
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
    const dirTa = h('textarea', { class: 'hidden', placeholder: 'Что требуется: ресурсы, бюджет, люди — коротко' });
    const dirBtn = h('button', { class: 'btn btn-sm btn-outline', onclick: () => { if (dirTa.classList.contains('hidden')) { dirTa.classList.remove('hidden'); dirTa.focus(); dirBtn.textContent = 'Вынести на решение'; return; } act(() => API.post('/api/panel/appeals/' + id + '/director', { text: dirTa.value }), 'Вынесено на решение директора'); } }, 'Нужно решение директора');
    const comTa = h('textarea', { placeholder: 'Комментарий (увидит автор)' });
    const comBtn = h('button', { class: 'btn btn-sm', onclick: () => act(() => API.post('/api/panel/appeals/' + id + '/comment', { text: comTa.value }), 'Комментарий добавлен') }, 'Комментировать');
    const progTa = h('textarea', { placeholder: 'Сообщить о ходе: что сделано, что дальше — автор увидит в истории и получит уведомление' });
    const progBtn = h('button', { class: 'btn btn-sm btn-primary', onclick: () => act(() => API.post('/api/panel/appeals/' + id + '/progress', { text: progTa.value }), 'Новость отправлена автору') }, 'Сообщить о ходе');
    actions = h('div', { class: 'card actions' },
      h('b', {}, 'Действия'),
      ['new', 'review', 'clarify', 'in_progress'].includes(a.status) ? h('div', { class: 'row' }, h('div', { class: 'spacer' }, assignSel), assignBtn) : null,
      (a.allowed_next || []).length ? h('div', {}, h('div', { class: 'hint' }, 'Статус'), statusBox, reasonTa, h('div', { class: 'mt8' }, confirmBtn)) : null,
      a.can_request_director ? h('div', {}, h('div', { class: 'hint' }, 'Предложение требует ресурсов или бюджета?'), dirTa, h('div', { class: 'mt8' }, dirBtn)) : null,
      ['new', 'review'].includes(a.status) ? h('div', {}, clarTa, h('div', { class: 'mt8' }, clarBtn)) : null,
      ['new', 'review', 'clarify', 'in_progress'].includes(a.status) ? h('div', {}, h('div', { class: 'hint' }, 'Новость автору без смены статуса'), progTa, h('div', { class: 'mt8' }, progBtn)) : null,
      ['new', 'review', 'clarify', 'in_progress'].includes(a.status) ? h('div', {}, comTa, h('div', { class: 'mt8' }, comBtn)) : null);
  }
  box.replaceChildren(...[head, result, director, actions, h('div', { class: 'card' }, h('div', { class: 'h2' }, 'История'), history(a.events))].filter(Boolean));
  const row = [...document.querySelectorAll('#queue-table tbody tr')].find(tr => tr.textContent.startsWith(a.number));
  if (row) row.classList.add('sel');
}

// ---------- совещания ----------

async function meetingsList() {
  const overdueOnly = (location.hash.split('?')[1] || '').includes('overdue=1');
  const list = await API.get('/api/meetings' + (overdueOnly ? '?overdue=1' : ''));
  const st = s => s === 'sent' ? 'st-done' : s === 'review' ? 'st-review' : s === 'failed' ? 'st-rejected' : 'st-new';
  const tbl = h('table', { class: 'tbl' },
    h('thead', {}, h('tr', {}, ['Дата', 'Совещание', 'Филиал', 'Ведущий', 'Итог', 'Статус', 'Поручения', 'Идеи'].map(t => h('th', {}, t)))),
    h('tbody', {}, list.map(m => h('tr', { onclick: () => { location.hash = '#/meetings/' + m.id; } },
      h('td', { class: 'small' }, fmtDate(m.created_at)), h('td', {}, h('b', {}, m.title), m.fallback ? h('div', {}, tag('tag-demo', m.demo ? 'демо-разбор без ИИ' : 'без ИИ')) : null),
      h('td', {}, m.branch || '—'), h('td', {}, m.creator || '—'), h('td', { class: 'small' }, m.summary_line || (m.error ? h('span', { class: 'muted' }, m.error) : '—')),
      h('td', {}, tag(st(m.status), m.status_label)),
      h('td', {}, 'выполнено ' + m.counts.tasks_done + ' / ' + m.counts.tasks + ' ', m.counts.tasks_overdue ? tag('tag-overdue', 'просрочено ' + m.counts.tasks_overdue) : null, ' ', m.counts.flags ? tag('tag-flag', 'флагов ' + m.counts.flags) : null),
      h('td', {}, 'принято ' + m.counts.ideas_accepted + ' · на решении ' + m.counts.ideas_pending + (m.counts.ideas_rejected ? ' · отклонено ' + m.counts.ideas_rejected : ''))))));
  const chk = h('input', { type: 'checkbox', checked: overdueOnly });
  chk.addEventListener('change', () => { location.hash = '#/meetings' + (chk.checked ? '?overdue=1' : ''); });
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, h('div', { class: 'row' }, h('div', { class: 'h1' }, 'Совещания'), h('label', { class: 'check small' }, chk, 'только с просроченными поручениями'), h('div', { class: 'spacer' }),
    h('a', { href: '#/meetings/new', class: 'btn btn-primary btn-sm' }, '+ Записать или загрузить планёрку')),
    h('p', { class: 'hint' }, 'Запись планёрки → расшифровка → разбор: итог, решения, поручения, идеи директору, связанные обращения. Ответственные видят свои совещания, директор и администратор — все.'),
    h('div', { class: 'card' }, list.length ? tbl : h('div', { class: 'muted' }, 'Совещаний пока нет'))));
}

// ---------- сводка ----------

let MAPVIEW = null;
async function summary() {
  const [d, ds, md] = await Promise.all([API.get('/api/panel/summary?days=30'), API.get('/api/panel/director-summary').catch(() => null), API.get('/api/panel/map').catch(() => null)]);
  const sumBlock = ds ? summaryBlockPanel(ds) : null;
  MAPVIEW = md ? mapView(md, { onBranch: b => { S.filters = { branch_id: b.id, open: true }; location.hash = '#/queue'; }, onSite: s => { S.filters = { q: s.city, open: true }; location.hash = '#/queue'; } }) : null;
  const mapCard = h('div', { class: 'card' }, h('div', { class: 'row' }, h('b', {}, 'Карта'), h('span', { class: 'hint' }, 'клик по городу — очередь филиала; новое обращение — маркер мигает')), MAPVIEW || h('div', { class: 'muted small' }, 'карта недоступна'));
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
  const branches = h('div', { class: 'card' }, h('b', {}, 'Филиалы'), h('div', { class: 'hint' }, 'Количество обращений филиал не ранжирует — лига по качеству во вкладке «Лига».'),
    h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Филиал', 'Всего', 'Открыто', 'Просрочено', 'Рассмотрено', 'Первый ответ', 'Реализовано', 'Главная тема'].map(t => h('th', {}, t)))),
      h('tbody', {}, d.by_branch.map(b => h('tr', { onclick: () => { S.filters = { branch_id: b.id }; location.hash = '#/queue'; } },
        h('td', {}, b.name), h('td', {}, b.total), h('td', {}, b.open), h('td', {}, b.overdue ? tag('tag-overdue', String(b.overdue)) : '0'),
        h('td', {}, pct(b.considered_share)), h('td', {}, fmtHours(b.avg_first_response_hours)), h('td', {}, b.done_total), h('td', { class: 'small' }, b.top_category || '—'))))));
  const clustersBox = h('div', { class: 'card' }, h('b', {}, 'Повторяющиеся темы'), h('div', { class: 'hint' }, 'Считаем…'));
  API.get('/api/panel/clusters').then(c => {
    const note = c.engine === 'embeddings' ? 'кластеры по смыслу (эмбеддинги ИИ), порог ' + c.threshold : 'по ключевым словам (без ИИ), порог ' + c.threshold;
    clustersBox.replaceChildren(h('b', {}, 'Повторяющиеся темы'), h('div', { class: 'hint' }, 'Группы из двух и более открытых обращений об одном и том же — ' + note + '. Открытых всего: ' + c.open_total + '.'),
      c.clusters.length ? h('div', { class: 'mt8' }, c.clusters.map(k => h('div', { class: 'cluster' },
        h('div', { class: 'row' }, h('b', {}, plural(k.size, 'обращение', 'обращения', 'обращений')), k.category ? tag('tag-type', k.category) : null, k.supports ? h('span', { class: 'small muted' }, '👍 ' + k.supports) : null, h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, k.branches.join(' · '))),
        h('div', { class: 'small' }, k.label),
        h('div', { class: 'small nums mt8' }, k.items.map(i => h('a', { href: '#/appeal/' + i.id }, i.number)))))) : h('div', { class: 'muted small mt8' }, 'Повторов не найдено'));
  }).catch(e => clustersBox.replaceChildren(h('b', {}, 'Повторяющиеся темы'), h('div', { class: 'card-bad small' }, e.message)));
  const cats = h('div', { class: 'card' }, h('b', {}, 'Открытые обращения по категориям'),
    h('div', { class: 'list mt8' }, d.top_categories.map(c => h('div', { class: 'item', onclick: () => { const id = (DICTS.categories.find(x => x.name === c.category) || {}).id; S.filters = { category_id: id, open: true }; location.hash = '#/queue'; } }, h('div', { class: 'row' }, c.category, h('div', { class: 'spacer' }), h('b', {}, String(c.open)))))));
  const check = ME.role !== 'responsible' ? h('button', { class: 'btn btn-sm', onclick: async () => { const r = await API.post('/api/panel/check-overdue'); toast(r.escalated.length ? 'Эскалировано: ' + r.escalated.join(', ') : 'Новых просрочек нет'); summary(); } }, 'Проверить просрочки сейчас') : null;
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, h('div', { class: 'row' }, h('div', { class: 'h1' }, 'Сводка'), h('div', { class: 'spacer' }), check), sumBlock, kpis, h('div', { class: 'split mt16' }, h('div', {}, mapCard, branches, clustersBox, cats), byType)));
}

function summaryBlockPanel(d) {
  const canSpeak = !!(window.speechSynthesis && speechSynthesis.getVoices().some(v => v.lang && v.lang.toLowerCase().startsWith('ru')));
  const speak = () => { const u = new SpeechSynthesisUtterance(d.sentences.map(s => s.text).join(' ')); u.lang = 'ru-RU'; const v = speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith('ru')); if (v) u.voice = v; speechSynthesis.cancel(); speechSynthesis.speak(u); };
  const refreshBtn = h('button', { class: 'btn btn-sm', onclick: async () => { refreshBtn.disabled = true; try { await API.get('/api/panel/director-summary?refresh=1'); summary(); } catch (e) { toast(e.message, 'bad'); refreshBtn.disabled = false; } } }, '↻ Обновить');
  const tplBtn = d.engine === 'openai' ? h('button', { class: 'btn btn-sm', title: 'Показать шаблон без ИИ для сравнения', onclick: async () => { const t = await API.get('/api/panel/director-summary?engine=template'); const box = document.querySelector('.summary-ai'); if (box) box.replaceWith(summaryBlockPanel(t)); } }, 'шаблон') : null;
  const l = d.lines || {};
  const link = href => href && href.startsWith('/panel') ? href.slice(6) : href;
  return h('div', { class: 'card summary-ai mt16' },
    h('div', { class: 'row' }, h('div', { class: 'lbl' }, 'Сводка для директора'), tag(d.engine === 'openai' ? 'tag-ai' : 'tag-demo', d.engine === 'openai' ? 'пересказ ИИ по фактам сервера' : 'шаблон без ИИ'), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(d.at)), canSpeak ? h('button', { class: 'btn btn-sm', onclick: speak }, '🔊 Озвучить') : null, tplBtn, refreshBtn),
    d.sentences.map(s => h('p', {}, s.href ? h('a', { href: link(s.href) }, s.text) : s.text)),
    h('div', { class: 'lines mt8' },
      l.urgent_open ? h('a', { href: '#/queue?open=1&urgency=now' }, tag('tag-flag', 'Мешают работать сейчас: ' + l.urgent_open)) : null,
      l.decisions_over_threshold ? h('a', { href: '#/decisions' }, tag('tag-flag', 'Ждут решения дольше ' + l.threshold_days + ' дн: ' + l.decisions_over_threshold)) : null,
      l.tasks_overdue ? h('a', { href: '#/meetings?overdue=1' }, tag('tag-overdue', 'Поручения просрочены: ' + l.tasks_overdue)) : null,
      l.no_news ? h('a', { href: '#/queue?status=in_progress' }, tag('tag-flag', 'Без новостей авторам дольше ' + l.news_days + ' дн: ' + l.no_news)) : null));
}

async function leaguePanel() {
  const d = await API.get('/api/panel/league');
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, h('div', { class: 'h1' }, 'Лига филиалов'),
    h('div', { class: 'hint' }, 'Качество работы с обращениями, не их число: реализовано ' + Math.round(d.weights.done * 100) + ' % · рассмотрено ' + Math.round(d.weights.considered * 100) + ' % · скорость первого ответа ' + Math.round(d.weights.speed * 100) + ' % (веса — в настройках).'),
    h('div', { class: 'split mt16' },
      h('div', { class: 'card' }, h('table', { class: 'tbl league' }, h('thead', {}, h('tr', {}, ['#', 'Филиал', 'Балл', 'Реализовано', 'Рассмотрено', 'Скорость', 'Открыто', 'Просрочено'].map(t => h('th', {}, t)))),
        h('tbody', {}, d.items.map(b => h('tr', { onclick: () => { S.filters = { branch_id: b.id }; location.hash = '#/queue'; } }, h('td', {}, String(b.rank)), h('td', {}, h('b', {}, b.name), h('div', { class: 'small muted' }, b.total + ' обращений' + (b.enough ? '' : ' — мало данных'))), h('td', { class: 'score' }, h('b', {}, String(b.score))), h('td', {}, Math.round(b.done_share * 100) + ' %'), h('td', {}, Math.round(b.considered_share * 100) + ' %'), h('td', {}, Math.round(b.speed * 100) + ' %'), h('td', {}, String(b.open)), h('td', {}, b.overdue ? tag('tag-overdue', String(b.overdue)) : '0')))))),
      h('div', { class: 'card' }, h('b', {}, 'Топ сотрудников'), h('div', { class: 'list mt8' }, d.top.map((u, i) => h('div', { class: 'item', onclick: () => { location.href = '/app#/u/' + u.id; } }, h('div', { class: 'row' }, h('b', {}, (i + 1) + '.'), avatarEl(u), h('div', {}, h('b', {}, u.name), h('div', { class: 'small muted' }, [u.position, u.branch].filter(Boolean).join(' · '))), h('div', { class: 'spacer' }), h('span', { class: 'small' }, '⭐ ' + u.points + ' · внедрено ' + u.implemented + ' · 🙏 ' + u.thanks)))))))));
}

async function adminScreen() {
  const d = await API.get('/api/admin/settings');
  const claims = await API.get('/api/admin/reward-claims');
  const st = d.settings;
  const num = (key, label, val) => { const i = h('input', { type: 'number', value: val === null || val === undefined ? '' : val }); i.dataset.key = key; return h('div', {}, h('label', { class: 'small muted' }, label), i); };
  const pts = st.points || {};
  const inputs = [num('director_wait_days', 'Порог «ждёт решения», дн', st.director_wait_days), num('news_days', 'Порог «без новостей автору», дн', st.news_days),
    num('points.accepted', 'Баллы: принято', pts.accepted), num('points.done', 'Баллы: реализовано', pts.done), num('points.support', 'Баллы: «у меня так же»', pts.support), num('points.support_cap', 'Потолок за поддержку', pts.support_cap),
    num('league_weights.done', 'Лига: вес «реализовано»', (st.league_weights || {}).done), num('league_weights.considered', 'Лига: вес «рассмотрено»', (st.league_weights || {}).considered), num('league_weights.speed', 'Лига: вес «скорость»', (st.league_weights || {}).speed),
    num('similar_threshold.embeddings', 'Порог похожих (ИИ)', (st.similar_threshold || {}).embeddings), num('cluster_threshold.embeddings', 'Порог кластеров (ИИ)', (st.cluster_threshold || {}).embeddings)];
  const saveBtn = h('button', { class: 'btn btn-sm btn-primary', onclick: async () => {
    const out = {};
    for (const box of inputs) { const i = box.querySelector('input'); if (i.value === '') continue; const v = Number(i.value); const [k, sub] = i.dataset.key.split('.'); if (sub) { out[k] = out[k] || { ...(st[k] || {}) }; out[k][sub] = v; } else out[k] = v; }
    try { await API.post('/api/admin/settings', { settings: out }); toast('Настройки сохранены'); adminScreen(); } catch (e) { toast(e.message, 'bad'); }
  } }, 'Сохранить настройки');
  const staff = d.users.filter(u => u.role !== 'employee' && u.active);
  const userSel = (val) => h('select', {}, h('option', { value: '' }, '— вакансия —'), staff.map(u => h('option', { value: u.id, selected: u.id === val }, u.name + ' · ' + (u.position || u.role))));
  const catRows = d.categories.map(c => { const rs = userSel(c.responsible_user_id); const ss = userSel(c.suggestion_responsible_user_id); const sla = h('input', { type: 'number', value: c.sla, class: 'w70' });
    const save = h('button', { class: 'btn btn-sm', onclick: async () => { try { await API.post('/api/admin/categories/' + c.id, { responsible_user_id: rs.value ? Number(rs.value) : null, suggestion_responsible_user_id: ss.value ? Number(ss.value) : null, sla: Number(sla.value) }); toast('Сохранено: ' + c.name); } catch (e) { toast(e.message, 'bad'); } } }, '✓');
    return h('tr', {}, h('td', {}, h('b', {}, c.name), h('div', { class: 'small muted' }, c.appeals + ' обращений')), h('td', {}, rs), h('td', {}, ss), h('td', {}, sla), h('td', {}, save)); });
  const claimRows = claims.map(c => { const dec = (decision) => async () => { const comment = decision === 'rejected' ? prompt('Причина отказа') : ''; if (decision === 'rejected' && !comment) return; try { await API.post('/api/admin/reward-claims/' + c.id + '/decide', { decision, comment }); toast('Решено'); adminScreen(); } catch (e) { toast(e.message, 'bad'); } };
    return h('tr', {}, h('td', {}, c.user_name), h('td', {}, c.title + ' · ' + c.cost_points), h('td', {}, tag(c.status === 'approved' ? 'st-done' : c.status === 'rejected' ? 'st-rejected' : 'st-review', c.status)), h('td', { class: 'small' }, fmtDate(c.created_at)), h('td', {}, c.status === 'requested' ? h('div', { class: 'row' }, h('button', { class: 'btn btn-sm btn-ok', onclick: dec('approved') }, 'Одобрить'), h('button', { class: 'btn btn-sm btn-danger', onclick: dec('rejected') }, 'Отклонить')) : (c.comment || ''))); });
  const avatars = d.users.filter(u => u.avatar);
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, h('div', { class: 'h1' }, 'Администрирование'),
    h('div', { class: 'split' },
      h('div', {},
        h('div', { class: 'card' }, h('b', {}, 'Категории ↔ ответственные ↔ SLA'), h('div', { class: 'hint' }, 'Проблемы идут ответственному; предложения — ответственному за предложения, иначе в отдел развития.'),
          h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Категория', 'Ответственный', 'За предложения', 'SLA, ч', ''].map(t => h('th', {}, t)))), h('tbody', {}, catRows))),
        h('div', { class: 'card' }, h('b', {}, 'Заявки на награды'), claims.length ? h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Кто', 'Награда', 'Статус', 'Когда', ''].map(t => h('th', {}, t)))), h('tbody', {}, claimRows)) : h('div', { class: 'muted small mt8' }, 'Заявок нет'))),
      h('div', {},
        h('div', { class: 'card' }, h('b', {}, 'Настройки'), h('div', { class: 'grid2 mt8' }, inputs), h('div', { class: 'mt8' }, saveBtn), h('div', { class: 'hint mt8' }, 'Пороги похожести и кластеров — для режима ИИ; без ключа действуют пороги по ключевым словам.')),
        h('div', { class: 'card' }, h('b', {}, 'Филиалы и QR'), h('div', { class: 'list mt8' }, d.branches.map(b => h('div', { class: 'item', onclick: () => window.open('/q/' + b.code, '_blank') }, h('div', { class: 'row' }, h('b', {}, b.name), tag('tag-type', b.kind), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, '/q/' + b.code))))), h('div', { class: 'hint mt8' }, 'QR-коды для печати — на стартовой странице; адрес — постоянный (туннель).')),
        h('div', { class: 'card' }, h('b', {}, 'Аватарки'), avatars.length ? h('div', { class: 'list mt8' }, avatars.map(u => h('div', { class: 'item' }, h('div', { class: 'row' }, avatarEl({ name: u.name, avatar: '/api/avatars/' + u.avatar }), h('span', {}, u.name), h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-danger', onclick: async () => { await API.post('/api/admin/users/' + u.id + '/avatar/remove'); toast('Убрана'); adminScreen(); } }, 'Убрать'))))) : h('div', { class: 'muted small mt8' }, 'Пользовательских аватарок нет'))))));
}

async function notifications() {
  const data = await API.get('/api/notifications');
  root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'h1' }, 'Уведомления'),
    h('div', { class: 'card list' }, data.items.length ? data.items.map(n => h('div', { class: 'item', onclick: () => { if (n.link) location.href = n.link; } },
      h('div', { class: 'row' }, n.read_at ? null : h('span', { class: 'badge st-new' }, 'новое'), h('span', { class: 'small muted' }, fmtDate(n.created_at))), h('div', {}, n.text))) : h('div', { class: 'muted' }, 'Уведомлений нет'))));
  if (data.unread) { await API.post('/api/notifications/read', {}); ME.unread = 0; renderTop(); }
}

boot();
