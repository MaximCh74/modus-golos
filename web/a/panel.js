'use strict';
// Веб-панель (desktop): очередь обращений с фильтрами и карточкой, сводка. Для ответственных, директора, администратора.
let ME = null, DICTS = null;
const root = document.getElementById('root');
const S = { filters: {}, rows: [], selected: null, view: 'queue', tab: 'attention' };
let reloadTimer = null;
// компактный режим (этап 9 §4): внутри портала Битрикс24 (iframe или адрес /bitrix/app) — без нашей шапки с логотипом, меньше отступов;
// ?compact=1 — для проверки без портала
const COMPACT = (window.self !== window.top) || location.pathname.startsWith('/bitrix/') || new URLSearchParams(location.search).get('compact') === '1';
if (COMPACT) document.documentElement.classList.add('compact');

async function boot() {
  ME = await API.me();
  if (!ME) { location.href = '/login?next=' + encodeURIComponent('/panel' + location.hash); return; }
  if (ME.role === 'employee') {
    root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-info' }, 'Панель доступна ответственным, директору и администратору. ', h('a', { href: '/app' }, 'Открыть приложение сотрудника'), ' · ', h('a', { href: '/login' }, 'войти как другой пользователь'))));
    return;
  }
  DICTS = await API.get('/api/dicts');
  renderTop();
  if (!document.getElementById('foot')) document.body.append(h('div', { id: 'foot', class: 'foot' }, 'демо · данные синтетические, имена вымышленные · разработано Cyber QALQAN Systems'));
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
    h('a', { href: '#/queue', class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' }), h('span', {}, 'Модус Голос', h('small', {}, 'Панель'))),
    h('div', { class: 'nav' }, nav.map(([href, label]) => h('a', { href, class: hash.startsWith(href) || (href === '#/queue' && hash.startsWith('#/appeal')) ? 'active' : '' }, label))),
    h('div', { class: 'spacer' }),
    h('a', { href: '#/notifications', class: 'btn btn-sm bell', title: 'Уведомления' }, icon('bell'), ME.unread ? h('span', { class: 'n' }, String(ME.unread)) : null),
    h('a', { href: '/app', class: 'btn btn-sm' }, 'Приложение'),
    h('a', { href: '/login', class: 'btn btn-sm', title: ME.name + ' · ' + ME.role_label }, h('span', {}, ME.name), h('span', { class: 'role-lbl' }, ' · ' + ME.role_label)));
}

async function route() {
  const hash = location.hash || '#/queue';
  const p = hash.slice(1).split('/').filter(Boolean);
  renderTop();
  try {
    if (p[0] === 'appeal') { S.view = 'queue'; S.selected = Number(p[1]); if (document.getElementById('queue-table')) { await loadCard(S.selected); return; } return await queue(); }
    if (p[0].startsWith('queue?')) { S.view = 'queue'; const qp = new URLSearchParams(p[0].slice(6)); S.filters = {}; for (const [k, v] of qp) S.filters[k] = v === '1' ? true : v; S.tab = tabFromFilters(); S.selected = null; return await queue(); }
    if (p[0] !== 'appeal' && p[0] !== 'queue') closeOverlay();
    if (p[0] === 'summary') { S.view = 'summary'; return await summary(); }
    if (p[0] === 'notifications') { S.view = 'notifications'; return await notifications(); }
    if (p[0] === 'meetings' && p[1] === 'new') { S.view = 'meetings'; return await meetingStart({ backHref: '#/meetings', cardPrefix: '#/meetings/' }); }
    if (p[0] === 'meetings' && p[1]) { S.view = 'meetings'; return await meetingCard(Number(p[1]), { backHref: '#/meetings', cardPrefix: '#/meetings/' }); }
    if (p[0] === 'meetings' || p[0].startsWith('meetings?')) { S.view = 'meetings'; return await meetingsList(); }
    if (p[0] === 'decisions') { S.view = 'decisions'; return await decisionsScreen({ backHref: '#/queue' }); }
    if (p[0] === 'admin') { S.view = 'admin'; return await adminScreen(); }
    if (p[0] === 'league') { S.view = 'league'; return await leaguePanel(); }
    S.view = 'queue'; if (S.selected && !location.hash.startsWith('#/appeal/')) S.selected = null; return await queue();
  } catch (e) { root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-bad' }, e.message))); }
}

function placeholder(title, text) {
  root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'h1' }, title), h('div', { class: 'card card-info' }, text, h('div', { class: 'hint mt8' }, 'Честная маркировка: раздел ещё не реализован.'))));
}

// ---------- очередь (этап 9: четыре колонки, вкладки, фильтры в боковой панели, карточка справа или поверх таблицы) ----------

const QUEUE_TABS = [['attention', 'Требуют внимания'], ['open', 'Все открытые'], ['mine', 'Мои'], ['closed', 'Закрытые']];
const EXTRA_COLS = [['type', 'Тип', 110], ['category', 'Категория', 170], ['branch', 'Филиал', 130], ['department', 'Подразделение', 140], ['news', 'Новость автору', 120], ['flags', 'Метки', 150], ['supports', 'Поддержка', 90]];
const CLOSED_STATUSES = ['done', 'closed', 'rejected'];
const OPEN_STATUSES = ['new', 'review', 'clarify', 'in_progress'];
const FILTER_LABELS = { branch_id: 'Филиал', department_id: 'Подразделение', category_id: 'Категория', status: 'Статус', responsible_id: 'Ответственный', days: 'Срок', sort: 'Сортировка', urgency: 'Мешают сейчас', cluster_id: 'Тема', overdue: 'Просроченные', unassigned: 'Без ответственного' };
S.tab = S.tab || 'attention';
let OVERLAY = null;   // выезжающая панель поверх таблицы: карточка (когда ширины не хватает) или фильтры

function colsKey() { return 'mf.queue.cols.' + (ME ? ME.id : 0); }
function loadCols() { try { return new Set(JSON.parse(localStorage.getItem(colsKey()) || '[]')); } catch (e) { return new Set(); } }
function saveCols(set) { try { localStorage.setItem(colsKey(), JSON.stringify([...set])); } catch (e) { /* приватный режим — не сохраняем */ } }
// карточка справа — только когда ширины хватает на таблицу и карточку; иначе (≤1440, во фрейме Битрикса, планшет) — поверх таблицы
function sideCard() { return !COMPACT && window.matchMedia('(min-width: 1441px)').matches; }

function closeOverlay() { if (OVERLAY) { OVERLAY.remove(); OVERLAY = null; } document.documentElement.classList.remove('has-drawer'); }
function openDrawer(content, opts) {
  closeOverlay(); closeMenus();
  opts = opts || {};
  const back = h('div', { class: 'drawer-back', onclick: () => { const cb = OVERLAY && OVERLAY.onClose; closeOverlay(); if (cb) cb(); } });
  const box = h('div', { class: 'drawer' + (opts.narrow ? ' narrow' : ''), role: 'dialog', 'aria-label': opts.label || '' }, content);
  OVERLAY = h('div', { class: 'drawer-wrap' }, back, box);
  OVERLAY.onClose = opts.onClose || null;
  document.body.append(OVERLAY);
  document.documentElement.classList.add('has-drawer');
  return box;
}
function closeMenus() { document.querySelectorAll('.menu-wrap.open').forEach(m => m.classList.remove('open')); }
document.addEventListener('click', ev => { if (!ev.target.closest('.menu-wrap')) closeMenus(); });
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') { closeMenus(); if (OVERLAY) { const cb = OVERLAY.onClose; closeOverlay(); if (cb) cb(); } } });
// меню «…»: остальные действия экрана (правило 3 — одна главная кнопка на экран)
function menuButton(items, opts) {
  opts = opts || {};
  const wrap = h('div', { class: 'menu-wrap' });
  const btn = h('button', { type: 'button', class: 'btn btn-sm' + (opts.ghost === false ? '' : ' btn-ghost'), title: opts.title || 'Ещё действия', 'aria-label': opts.title || 'Ещё действия',
    onclick: ev => { ev.stopPropagation(); const open = wrap.classList.contains('open'); closeMenus(); if (!open) wrap.classList.add('open'); } }, icon('more'));
  wrap.append(btn, h('div', { class: 'menu' }, items.filter(Boolean).map(([label, fn]) => h('button', { type: 'button', onclick: ev => { ev.stopPropagation(); closeMenus(); fn(); } }, label))));
  return wrap;
}
function shortName(name) { const p = String(name || '').split(' '); return name && name.length > 18 && p.length > 1 ? p[0] + ' ' + p[1][0] + '.' : name; }

function tabFromFilters() {
  const f = S.filters;
  if (f.closed || (f.status && CLOSED_STATUSES.includes(f.status))) return 'closed';
  if (f.mine) return 'mine';
  if (f.attention) return 'attention';
  if (Object.keys(f).some(k => f[k] && k !== 'q' && k !== 'open')) return 'open';   // ссылки из сводки и кластеров — среди открытых
  return f.open ? 'open' : 'attention';
}

async function queue() {
  const q = h('input', { type: 'search', class: 'search', placeholder: 'Номер или текст', value: S.filters.q || '', 'aria-label': 'Поиск' });
  q.addEventListener('input', () => { S.filters.q = q.value; clearTimeout(reloadTimer); reloadTimer = setTimeout(loadQueue, 300); });
  const tabs = h('div', { class: 'tabs q' }, QUEUE_TABS.map(([code, label]) => h('a', { href: '#', class: S.tab === code ? 'active' : '', onclick: ev => { ev.preventDefault(); S.tab = code; delete S.filters.closed; delete S.filters.mine; delete S.filters.attention; delete S.filters.open; if (code !== 'closed' && S.filters.status && CLOSED_STATUSES.includes(S.filters.status)) delete S.filters.status; queue(); } }, label)));
  const active = FILTER_KEYS.filter(k => S.filters[k]);
  const filtersBtn = h('button', { class: 'btn btn-sm' + (active.length ? ' on' : ''), onclick: () => filtersDrawer() }, iconText('filter', 'Фильтры' + (active.length ? ' · ' + active.length : '')));
  const viewBtn = h('button', { class: 'btn btn-sm', onclick: () => viewMenu(viewBtn) }, iconText('sliders', 'Вид'));
  const toolbar = h('div', { class: 'toolbar' }, q, tabs, h('div', { class: 'spacer' }), filtersBtn, viewBtn);
  const chips = h('div', { class: 'chips chips-active' }, active.map(k => h('button', { type: 'button', class: 'chip', title: 'Убрать фильтр', onclick: () => { delete S.filters[k]; queue(); } }, filterLabel(k), ' ', icon('x', { size: 12 }))),
    active.length > 1 ? h('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: () => { for (const k of active) delete S.filters[k]; queue(); } }, 'Сбросить всё') : null);
  const counts = h('div', { id: 'queue-counts', class: 'small muted mb8' });
  const table = h('div', { id: 'queue-table' });
  const side = sideCard();
  const card = side ? h('div', { id: 'card', class: 'sticky' }, h('div', { class: 'card muted' }, 'Выберите обращение в очереди')) : null;
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, toolbar, active.length ? chips : null, counts, h('div', { class: 'split' + (side ? '' : ' one') }, table, card)));
  await loadQueue();
  if (S.selected) await loadCard(S.selected);
  else if (!side) closeOverlay();
}
const FILTER_KEYS = ['branch_id', 'department_id', 'category_id', 'status', 'responsible_id', 'days', 'sort', 'urgency', 'cluster_id', 'overdue', 'unassigned'];
function filterLabel(k) {
  const v = S.filters[k];
  const name = (list, id) => (list.find(x => String(x.id) === String(id)) || {}).name;
  if (k === 'branch_id') return (DICTS.branches.find(b => String(b.id) === String(v)) || {}).name || 'Филиал';
  if (k === 'department_id') return name(DICTS.departments, v) || 'Подразделение';
  if (k === 'category_id') return name(DICTS.categories, v) || 'Категория';
  if (k === 'responsible_id') return name(DICTS.users || [], v) || 'Ответственный';
  if (k === 'status') return STATUS[v] ? STATUS[v][0] : v;
  if (k === 'days') return v + ' дн';
  if (k === 'sort') return 'По приоритету';
  if (k === 'cluster_id') return 'Тема';
  return FILTER_LABELS[k] || k;
}

function filtersDrawer() {
  const staff = (DICTS.users || []).filter(u => u.role !== 'employee' && u.active);
  const draft = { ...S.filters };
  const sel = (name, options, label, placeholder) => { const s = h('select', {}, h('option', { value: '' }, placeholder || 'Все'), options.map(o => h('option', { value: o.value, selected: String(draft[name] || '') === String(o.value) }, o.label))); s.addEventListener('change', () => { draft[name] = s.value; }); return field(label, s); };
  const chk = (name, label) => { const c = h('input', { type: 'checkbox', checked: !!draft[name] }); c.addEventListener('change', () => { draft[name] = c.checked; }); return h('label', { class: 'check' }, c, label); };
  const urg = h('input', { type: 'checkbox', checked: draft.urgency === 'now' }); urg.addEventListener('change', () => { draft.urgency = urg.checked ? 'now' : ''; });
  const apply = h('button', { class: 'btn btn-primary', onclick: () => { for (const k of FILTER_KEYS) { if (draft[k]) S.filters[k] = draft[k]; else delete S.filters[k]; } closeOverlay(); queue(); } }, 'Применить');
  const reset = h('button', { class: 'btn', onclick: () => { for (const k of FILTER_KEYS) delete S.filters[k]; closeOverlay(); queue(); } }, 'Сбросить всё');
  const content = h('div', {},
    h('div', { class: 'row' }, h('div', { class: 'h2' }, 'Фильтры'), h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-ghost', title: 'Закрыть', onclick: closeOverlay }, icon('x'))),
    sel('branch_id', DICTS.branches.map(b => ({ value: b.id, label: b.name })), 'Филиал'),
    sel('department_id', DICTS.departments.map(d => ({ value: d.id, label: d.name })), 'Подразделение'),
    sel('category_id', DICTS.categories.map(c => ({ value: c.id, label: c.name })), 'Категория'),
    sel('status', Object.entries(STATUS).map(([v, l]) => ({ value: v, label: l[0] })), 'Статус'),
    sel('responsible_id', staff.map(u => ({ value: u.id, label: u.name })), 'Ответственный'),
    sel('days', [{ value: 7, label: '7 дней' }, { value: 14, label: '14 дней' }, { value: 30, label: '30 дней' }], 'Срок', 'Всё время'),
    sel('sort', [{ value: 'priority', label: 'По приоритету' }], 'Сортировка', 'По дате'),
    h('div', { class: 'col mt8' }, chk('overdue', 'Только просроченные'), chk('unassigned', 'Без ответственного'), h('label', { class: 'check' }, urg, 'Мешают работать сейчас')),
    h('div', { class: 'row mt16' }, apply, reset));
  openDrawer(content, { narrow: true, label: 'Фильтры' });
}

function viewMenu(anchor) {
  const cols = loadCols();
  const list = h('div', { class: 'card card-elevated view-menu' }, h('div', { class: 'row' }, h('b', {}, 'Колонки'), h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-ghost', onclick: () => list.remove() }, icon('x'))),
    h('div', { class: 'hint' }, 'По умолчанию четыре: обращение, статус, ответственный, возраст. Остальное — в карточке. Выбор запоминается.'),
    h('div', { class: 'col mt8' }, EXTRA_COLS.map(([code, label]) => { const c = h('input', { type: 'checkbox', checked: cols.has(code) }); c.addEventListener('change', () => { if (c.checked) cols.add(code); else cols.delete(code); saveCols(cols); loadQueue(); }); return h('label', { class: 'check' }, c, label); })));
  const old = document.querySelector('.view-menu'); if (old) { old.remove(); return; }
  anchor.parentElement.append(list);
}

function queueParams() {
  const qp = new URLSearchParams();
  for (const [k, v] of Object.entries(S.filters)) if (v && !['open', 'closed', 'mine', 'attention'].includes(k)) qp.set(k, v === true ? '1' : v);
  if (S.tab === 'attention') qp.set('attention', '1');
  if (S.tab === 'open') qp.set('open', '1');
  if (S.tab === 'mine') { qp.set('open', '1'); qp.set('responsible_id', ME.id); }
  if (S.tab === 'closed') qp.set('closed', '1');
  return qp;
}

function extraCell(r, code) {
  if (code === 'type') return h('td', {}, r.type_label);
  if (code === 'category') return h('td', { title: r.category || '' }, r.category || h('span', { class: 'muted' }, '—'));
  if (code === 'branch') return h('td', {}, r.branch || '—');
  if (code === 'department') return h('td', {}, r.department || '—');
  if (code === 'news') return h('td', {}, r.news_days === null || r.news_days === undefined ? '—' : r.news_days < 1 ? 'сегодня' : Math.floor(r.news_days) + ' дн назад');
  if (code === 'flags') return h('td', {}, r.overdue ? tag('tag-overdue', 'Просрочено') : null, ' ', r.unassigned ? tag('tag-unassigned', 'Без ответственного') : null, ' ', r.author_urgency === 'now' ? tag('tag-flag', 'мешает сейчас') : null);
  return h('td', {}, r.supports ? String(r.supports) : '');
}

function queueRow(r, cols) {
  const tIcon = r.type === 'problem' ? 'alert-circle' : r.type === 'suggestion' ? 'lightbulb' : 'heart';
  const text = r.brief_line || r.text || '';
  const first = h('td', { class: 'q-main', title: r.number + ' · ' + r.type_label + ' · ' + text },
    icon(tIcon, { size: 14, cls: 'tic', title: r.type_label }), h('span', { class: 'num' }, r.number),
    r.priority === 'high' ? h('span', { class: 'mini', title: 'Высокий приоритет' }, icon('alert', { size: 11 })) : null,
    r.supports ? h('span', { class: 'mini', title: '«У меня так же»: ' + r.supports }, icon('thumbs-up', { size: 11 }), String(r.supports)) : null,
    h('span', { class: 'brief' }, ' · ' + text));
  const tds = [first, h('td', {}, badge(r.status)),
    h('td', { class: 'q-resp', title: r.responsible || 'не назначен' }, r.responsible ? h('span', { class: 'ulink' }, avatarEl({ name: r.responsible }, 'sm'), ' ', shortName(r.responsible)) : h('span', { class: 'muted' }, '—')),
    h('td', { class: 'q-age', title: fmtDate(r.created_at) + (r.overdue ? ' · просрочено' : '') }, r.overdue ? h('span', { class: 'dot-overdue', title: 'Просрочено' }) : null, fmtHours(r.age_hours))];
  for (const c of EXTRA_COLS) if (cols.has(c[0])) tds.push(extraCell(r, c[0]));
  return h('tr', { class: S.selected === r.id ? 'sel' : '', onclick: () => { location.hash = '#/appeal/' + r.id; } }, ...tds);
}

async function loadQueue(flashId) {
  const rows = await API.get('/api/panel/appeals?' + queueParams().toString());
  S.rows = rows;
  const table = document.getElementById('queue-table');
  if (!table) return;
  const cols = loadCols();
  const overdue = rows.filter(r => r.overdue).length, unassigned = rows.filter(r => r.unassigned).length;
  const counts = document.getElementById('queue-counts');
  if (counts) counts.textContent = plural(rows.length, 'обращение', 'обращения', 'обращений') + (overdue ? ' · просрочено ' + overdue : '') + (unassigned ? ' · без ответственного ' + unassigned : '');
  const heads = ['Обращение', 'Статус', 'Ответственный', 'Возраст'].concat(EXTRA_COLS.filter(c => cols.has(c[0])).map(c => c[1]));
  const widths = [null, 176, 190, 92].concat(EXTRA_COLS.filter(c => cols.has(c[0])).map(c => c[2]));
  const tbl = h('table', { class: 'tbl queue' },
    h('colgroup', {}, widths.map(w => { const c = document.createElement('col'); if (w) c.style.width = w + 'px'; return c; })),
    h('thead', {}, h('tr', {}, heads.map(t => h('th', {}, t)))),
    h('tbody', {}, rows.map(r => { const tr = queueRow(r, cols); if (flashId === r.id) tr.classList.add('flash'); return tr; })));
  const empty = { attention: 'Ничего не требует внимания — посмотрите «Все открытые».', open: 'Открытых обращений нет.', mine: 'На вас сейчас ничего не назначено.', closed: 'Закрытых обращений нет.' };
  table.replaceChildren(h('div', { class: 'card' }, rows.length ? tbl : h('div', { class: 'muted' }, empty[S.tab] || 'Ничего не найдено')));
}

// ---------- карточка (этап 9: одна главная кнопка по статусу, остальное в «…», подробности и история свёрнуты) ----------

async function loadCard(id) {
  let a;
  try { a = await API.get('/api/appeals/' + id); } catch (e) { toast(e.message, 'bad'); return; }
  const el = cardContent(a, id);
  const box = document.getElementById('card');
  if (sideCard() && box) box.replaceChildren(el);
  else if (OVERLAY && OVERLAY.cardId === id) { OVERLAY.querySelector('.drawer').replaceChildren(el); }
  else { openDrawer(el, { label: a.number, onClose: () => { S.selected = null; if (location.hash.startsWith('#/appeal/')) location.hash = '#/queue'; } }); OVERLAY.cardId = id; }
  for (const tr of document.querySelectorAll('#queue-table tbody tr')) tr.classList.toggle('sel', tr.textContent.includes(a.number));
}

function cardContent(a, id) {
  const act = async (fn, okMsg) => { try { await fn(); if (okMsg) toast(okMsg); await loadCard(id); await loadQueue(); } catch (e) { toast(e.message, 'bad'); } };
  const post = (path, body) => API.post('/api/panel/appeals/' + id + path, body);
  const staff = (DICTS.users || []).filter(u => u.role !== 'employee' && u.active);
  const formBox = h('div', { class: 'act-form' });
  const show = el => { formBox.replaceChildren(el); const f = el.querySelector('textarea, select'); if (f) f.focus(); };
  const form = (title, fieldEl, onSubmit, btnLabel) => h('div', { class: 'card card-info act' },
    h('div', { class: 'row' }, h('b', {}, title), h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-ghost', title: 'Закрыть', onclick: () => formBox.replaceChildren() }, icon('x'))),
    h('div', { class: 'mt8' }, fieldEl), h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm btn-primary', onclick: onSubmit }, btnLabel)));
  const textForm = (title, placeholder, path, ok, btnLabel, extra) => { const ta = h('textarea', { placeholder }); return form(title, ta, () => act(() => post(path, { ...(extra || {}), text: ta.value }), ok), btnLabel); };
  const assignForm = () => { const sel = h('select', {}, h('option', { value: '' }, '— выбрать ответственного —'), staff.map(u => h('option', { value: u.id, selected: u.id === a.responsible_id }, u.name + ' · ' + (u.position || u.role)))); return form('Ответственный', sel, () => sel.value ? act(() => post('/assign', { responsible_id: Number(sel.value) }), 'Назначено') : toast('Выберите ответственного', 'bad'), 'Назначить'); };
  const priorityForm = () => { const sel = h('select', {}, Object.entries(PRIO).map(([v, l]) => h('option', { value: v, selected: v === a.priority }, l))); return form('Приоритет', sel, () => act(() => post('/priority', { priority: sel.value }), 'Приоритет изменён'), 'Сохранить'); };
  const progressForm = () => textForm('Сообщить о ходе', 'Что сделано и что дальше — автор увидит в истории и получит уведомление', '/progress', 'Новость отправлена автору', 'Отправить автору');
  const clarifyForm = () => textForm('Вопрос автору', 'Что уточнить', '/clarify', 'Уточнение запрошено', 'Запросить уточнение');
  const directorForm = () => textForm('Нужно решение директора', 'Что требуется: ресурсы, бюджет, люди — коротко', '/director', 'Вынесено на решение директора', 'Вынести на решение');
  const commentForm = () => textForm('Комментарий автору', 'Комментарий (увидит автор)', '/comment', 'Комментарий добавлен', 'Добавить');
  const statusChange = (code, label) => {
    if (code !== 'rejected' && code !== 'done') return act(() => post('/status', { status: code }), 'Статус: ' + label);
    show(textForm(code === 'rejected' ? 'Отклонить' : 'Реализовано', code === 'rejected' ? 'Мотивировка отказа — автор её увидит (обязательно)' : 'Что сделано — увидит автор и лента «Что изменили» (обязательно)', '/status', 'Статус изменён', 'Подтвердить', { status: code }));
  };
  const decisionForm = () => h('div', { class: 'card card-info act' },
    h('div', { class: 'row' }, h('b', {}, 'Решение по обращению'), h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-ghost', title: 'Закрыть', onclick: () => formBox.replaceChildren() }, icon('x'))),
    h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm btn-primary', onclick: () => statusChange('in_progress', 'В работе') }, 'В работу'),
      h('button', { class: 'btn btn-sm btn-danger', onclick: () => statusChange('rejected', 'Отклонено') }, 'Отклонить'),
      a.can_request_director ? h('button', { class: 'btn btn-sm', onclick: () => show(directorForm()) }, 'К директору') : null,
      h('button', { class: 'btn btn-sm', onclick: () => show(clarifyForm()) }, 'Уточнить у автора')));
  const btnP = (label, fn) => h('button', { class: 'btn btn-primary', onclick: fn }, label);
  const btnS = (label, fn) => h('button', { class: 'btn btn-outline', onclick: fn }, label);
  let primary = null, secondary = null;
  const next = (a.allowed_next || []).map(n => n.code);
  if (a.can_manage) {
    if (a.status === 'new') primary = a.unassigned ? btnP('Назначить', () => show(assignForm())) : btnP('Взять в работу', () => statusChange('review', 'На рассмотрении'));
    else if (a.status === 'review') { primary = btnP('Принять решение', () => show(decisionForm())); secondary = btnS('Сообщить о ходе', () => show(progressForm())); }
    else if (a.status === 'clarify') primary = btnP('Напомнить автору', () => act(() => post('/clarify', { text: 'Напоминание: ' + (a.pending_question || 'ждём вашего ответа') }), 'Напоминание отправлено автору'));
    else if (a.status === 'in_progress') { primary = btnP('Сообщить о ходе', () => show(progressForm())); secondary = btnS('Готово', () => statusChange('done', 'Реализовано')); }
    else if (a.status === 'done' && next.includes('closed')) primary = btnP('Закрыть', () => statusChange('closed', 'Закрыто'));
  }
  const items = [];
  if (a.can_manage) {
    if (a.brief && a.brief.unclear && a.brief.question && ['new', 'review'].includes(a.status)) items.push(['Уточнить у автора: вопрос ИИ', () => act(() => post('/clarify', { text: a.brief.question }), 'Уточнение запрошено')]);
    if (OPEN_STATUSES.includes(a.status)) items.push([a.responsible ? 'Переназначить' : 'Назначить ответственного', () => show(assignForm())]);
    for (const n of a.allowed_next || []) items.push(['Статус: ' + n.label, () => statusChange(n.code, n.label)]);
    if (OPEN_STATUSES.includes(a.status)) items.push(['Приоритет', () => show(priorityForm())]);
    if (['new', 'review'].includes(a.status)) items.push(['Запросить уточнение', () => show(clarifyForm())]);
    if (a.can_request_director) items.push(['Нужно решение директора', () => show(directorForm())]);
    if (['new', 'clarify'].includes(a.status)) items.push(['Сообщить о ходе', () => show(progressForm())]);
    if (OPEN_STATUSES.includes(a.status)) items.push(['Комментарий автору', () => show(commentForm())]);
    if (a.brief) items.push(['Пересказать заново', () => act(() => post('/rebrief'), 'Пересказ обновлён')]);
  }
  const closeBtn = sideCard() ? null : h('button', { class: 'btn btn-sm btn-ghost', title: 'Закрыть (Esc)', 'aria-label': 'Закрыть', onclick: () => { const cb = OVERLAY && OVERLAY.onClose; closeOverlay(); if (cb) cb(); } }, icon('x'));
  const kv = (k, v) => v === null || v === undefined || v === '' ? null : h('div', { class: 'kv-row' }, h('span', { class: 'k' }, k), h('span', { class: 'v' }, v));
  const head = h('div', { class: 'card' },
    h('div', { class: 'row' }, h('span', { class: 'h1 num' }, a.number), badge(a.status), a.overdue ? h('span', { class: 'mini', title: 'Просрочен первый ответ' }, h('span', { class: 'dot-overdue' }), 'просрочено') : null,
      a.is_anonymous ? tag('tag-anon', 'аноним') : null, h('div', { class: 'spacer' }), items.length ? menuButton(items) : null, closeBtn),
    tracker(a.status, true),
    h('div', { class: 'small muted' }, [a.type_label, a.category || 'категория не определена', a.branch, a.site_city ? 'объект: ' + a.site_city : null].filter(Boolean).join(' · ')),
    a.brief ? briefBlock(a, {}) : h('div', { class: 'mt8' }, h('p', { class: 'pre' }, a.text), a.proposed_solution ? h('div', { class: 'small' }, h('b', {}, 'Предлагаемое решение: '), a.proposed_solution) : null),
    primary || secondary ? h('div', { class: 'row mt8' }, primary, secondary) : null,
    formBox);
  const result = a.resolution_text ? h('div', { class: 'card ' + (a.status === 'rejected' ? 'card-bad' : 'card-ok') }, h('b', {}, a.status === 'rejected' ? 'Отклонено — причина' : 'Что сделали'), h('p', { class: 'pre' }, a.resolution_text)) : null;
  const director = a.director_decision ? h('div', { class: 'card ' + (a.director_decision === 'pending' ? 'card-info' : a.director_decision === 'accepted' ? 'card-ok' : 'card-bad') },
    h('div', { class: 'row' }, h('b', {}, 'Решение директора: '), tag(a.director_decision === 'pending' ? 'st-review' : a.director_decision === 'accepted' ? 'st-done' : 'st-rejected', a.director_decision_label), h('span', { class: 'small muted' }, fmtDate(a.director_decided_at || a.director_requested_at))),
    h('div', { class: 'small mt8' }, h('b', {}, 'Что требуется: '), a.director_request_text), a.director_comment ? h('div', { class: 'small' }, h('b', {}, 'Комментарий: '), a.director_comment) : null) : null;
  const details = h('details', { class: 'card sect' }, h('summary', {}, 'Подробности'),
    h('div', { class: 'kv mt8' },
      kv('Автор', userLink(a.author, 'sm')), kv('Филиал', [a.branch, a.site_city ? 'объект: ' + a.site_city : null].filter(Boolean).join(' · ') || '—'), kv('Подразделение', a.department || '—'), kv('Категория', a.category || 'не определена'),
      kv('Оценка автора', [a.author_urgency_label, a.author_scope_label].filter(Boolean).join(' · ') || 'не отвечал'), kv('Приоритет', a.priority_label + (a.priority_manual ? ' (изменён ответственным)' : '')),
      a.supports ? kv('«У меня так же»', String(a.supports)) : null, a.thanks ? kv('«Спасибо»', String(a.thanks)) : null,
      a.news_days !== null && a.news_days !== undefined ? kv('Последняя новость автору', a.news_days < 1 ? 'сегодня' : Math.floor(a.news_days) + ' дн назад') : null,
      kv('Ответственный', a.responsible || 'не назначен'), kv('Первый ответ', (a.first_response_hours === null ? 'нет' : 'через ' + fmtHours(a.first_response_hours)) + ' · SLA ' + (a.sla || 48) + ' ч'),
      kv('Подано', fmtDate(a.created_at) + (a.input_mode === 'voice' ? ' · голосом' : '')),
      a.attachments.length ? kv('Вложения', h('span', {}, a.attachments.map(f => h('a', { href: '/api/attachments/' + f.id, target: '_blank' }, f.filename + ' ')))) : null));
  const full = a.brief ? h('details', { class: 'card sect' }, h('summary', {}, 'Показать полностью' + (a.input_mode === 'voice' ? ' (расшифровка голоса)' : '')), h('p', { class: 'pre' }, a.text), a.proposed_solution ? h('div', { class: 'small' }, h('b', {}, 'Предлагаемое решение: '), a.proposed_solution) : null) : null;
  const hist = h('details', { class: 'card sect' }, h('summary', {}, 'История · ' + (a.events || []).length), history(a.events));
  return h('div', { class: 'appeal-card' }, ...[head, result, director, details, full, hist].filter(Boolean));
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
    h('a', { href: '#/meetings/new', class: 'btn btn-primary btn-sm' }, iconText('plus', 'Записать или загрузить планёрку'))),
    h('p', { class: 'hint' }, 'Запись планёрки, расшифровка, разбор: итог, решения, поручения, идеи директору, связанные обращения. Ответственные видят свои совещания, директор и администратор — все.'),
    h('div', { class: 'card' }, list.length ? tbl : h('div', { class: 'muted' }, 'Совещаний пока нет'))));
}

// ---------- главная директора (этап 9 §5: четыре плитки, «Требуют внимания» одной строкой, сводка до трёх строк, команда в одну строку) ----------

let MAPVIEW = null;
async function summary() {
  const [d, ds, md] = await Promise.all([API.get('/api/panel/summary?days=30'), API.get('/api/panel/director-summary').catch(() => null), API.get('/api/panel/map').catch(() => null)]);
  const l = (ds && ds.lines) || {};
  const sumBlock = ds ? summaryBlockPanel(ds) : null;
  MAPVIEW = md ? mapView(md, { staff: true, legend: true, onBranch: b => { S.filters = { branch_id: b.id }; S.tab = 'open'; location.hash = '#/queue'; }, onSite: s => { S.filters = { q: s.city }; S.tab = 'open'; location.hash = '#/queue'; } }) : null;
  const mapCard = h('div', { class: 'card' }, h('div', { class: 'row' }, h('b', {}, 'Карта'), h('span', { class: 'hint' }, 'клик по городу — очередь филиала')), MAPVIEW || h('div', { class: 'muted small' }, 'карта недоступна'));
  const pct = x => x === null || x === undefined ? '—' : Math.round(x * 100) + ' %';
  const attention = h('div', { class: 'card attention' }, attentionLine([[d.overdue, '#/queue?overdue=1', 'просрочено'], [d.unassigned, '#/queue?unassigned=1', 'без ответственного'], [l.decisions_over_threshold, '#/decisions', 'ждут решения'],
    [l.no_news, '#/queue?status=in_progress', 'без новостей'], [l.urgent_open, '#/queue?open=1&urgency=now', 'мешают работать'], [l.tasks_overdue, '#/meetings?overdue=1', 'поручения просрочены']]));
  const kpis = h('div', { class: 'kpis' },
    h('div', { class: 'kpi' }, h('b', {}, String(d.open)), h('span', {}, 'открытых обращений')),
    h('div', { class: 'kpi' }, h('b', {}, pct(d.considered_share)), h('span', {}, 'доля рассмотренных')),
    h('div', { class: 'kpi' }, h('b', {}, fmtHours(d.avg_first_response_hours)), h('span', {}, 'среднее время первого ответа')),
    h('div', { class: 'kpi' }, h('b', {}, String(d.done_period)), h('span', {}, 'реализовано за 30 дней')));
  const byType = h('div', { class: 'card' }, h('b', {}, 'По типам'), h('div', { class: 'row mt8' }, Object.entries(d.by_type).filter(([, n]) => n).map(([t, n]) => h('span', { class: 'badge tag-type' }, TYPES[t] + ': ' + n))),
    h('b', { class: 'mt16' }, 'По статусам'), h('div', { class: 'row mt8' }, Object.entries(d.by_status).filter(([, n]) => n).map(([s, n]) => h('span', { class: 'badge ' + STATUS[s][1] }, STATUS[s][0] + ': ' + n))));
  const branches = h('div', { class: 'card' }, h('b', {}, 'Филиалы'), h('div', { class: 'hint' }, 'Количество обращений филиал не ранжирует — лига по качеству во вкладке «Лига».'),
    h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Филиал', 'Всего', 'Открыто', 'Просрочено', 'Рассмотрено', 'Первый ответ', 'Реализовано', 'Главная тема'].map(t => h('th', {}, t)))),
      h('tbody', {}, d.by_branch.map(b => h('tr', { onclick: () => { S.filters = { branch_id: b.id }; S.tab = 'open'; location.hash = '#/queue'; } },
        h('td', {}, b.name), h('td', {}, b.total), h('td', {}, b.open), h('td', {}, b.overdue ? h('span', {}, h('span', { class: 'dot-overdue' }), String(b.overdue)) : ''),
        h('td', {}, pct(b.considered_share)), h('td', {}, fmtHours(b.avg_first_response_hours)), h('td', {}, b.done_total), h('td', { class: 'small' }, b.top_category || '—'))))));
  const clustersBox = h('div', { class: 'card' }, h('b', {}, 'Повторяющиеся темы'), h('div', { class: 'hint' }, 'Считаем…'));
  API.get('/api/panel/clusters').then(c => {
    clustersBox.replaceChildren(h('div', { class: 'row' }, h('b', {}, 'Повторяющиеся темы'), aiMark(c.engine === 'embeddings', 'кластеры по смыслу (эмбеддинги ИИ), порог ' + c.threshold, 'по ключевым словам (без ИИ), порог ' + c.threshold)),
      h('div', { class: 'hint' }, 'Группы из двух и более открытых обращений об одном и том же. Открытых всего: ' + c.open_total + '.'),
      c.clusters.length ? h('div', { class: 'mt8' }, c.clusters.map(k => h('div', { class: 'cluster' },
        h('div', { class: 'row' }, h('b', {}, plural(k.size, 'обращение', 'обращения', 'обращений')), k.category ? tag('tag-type', k.category) : null, k.supports ? h('span', { class: 'small muted' }, iconText('thumbs-up', String(k.supports))) : null, h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, k.branches.join(' · '))),
        h('div', { class: 'small' }, k.label),
        h('div', { class: 'small nums mt8' }, k.items.map(i => h('a', { href: '#/appeal/' + i.id }, i.number)))))) : h('div', { class: 'muted small mt8' }, 'Повторов не найдено'));
  }).catch(e => clustersBox.replaceChildren(h('b', {}, 'Повторяющиеся темы'), h('div', { class: 'card-bad small' }, e.message)));
  const cats = h('div', { class: 'card' }, h('b', {}, 'Открытые обращения по категориям'),
    h('div', { class: 'list mt8' }, d.top_categories.filter(c => c.open).map(c => h('div', { class: 'item', onclick: () => { const id = (DICTS.categories.find(x => x.name === c.category) || {}).id; S.filters = { category_id: id }; S.tab = 'open'; location.hash = '#/queue'; } }, h('div', { class: 'row' }, c.category, h('div', { class: 'spacer' }), h('b', {}, String(c.open)))))));
  const more = ME.role !== 'responsible' ? menuButton([
    ['Проверить просрочки сейчас', async () => { const r = await API.post('/api/panel/check-overdue'); toast(r.escalated.length ? 'Эскалировано: ' + r.escalated.join(', ') : 'Новых просрочек нет'); summary(); }],
    ds && ds.engine === 'openai' ? ['Показать сводку шаблоном без ИИ', async () => { const t = await API.get('/api/panel/director-summary?engine=template'); const box = document.querySelector('.summary-ai'); if (box) box.replaceWith(summaryBlockPanel(t)); }] : null]) : null;
  const command = (ME.role === 'director' || ME.role === 'admin') ? commandPanel({ decisionsHref: '#/decisions', compact: true }) : null;
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, h('div', { class: 'row' }, h('div', { class: 'h1' }, 'Сводка'), h('div', { class: 'spacer' }), more), sumBlock, attention, command, kpis, h('div', { class: 'split mt16' }, h('div', {}, mapCard, branches, clustersBox, cats), byType)));
}

function summaryBlockPanel(d) {
  const speakBtn = h('button', { class: 'btn btn-sm', title: 'Озвучить сводку' }, iconText('volume', 'Озвучить'));
  speakBtn.addEventListener('click', () => speakSummary(speakBtn, d.sentences));
  const refreshBtn = h('button', { class: 'btn btn-sm', onclick: async () => { refreshBtn.disabled = true; try { await API.get('/api/panel/director-summary?refresh=1'); summary(); } catch (e) { toast(e.message, 'bad'); refreshBtn.disabled = false; } } }, iconText('refresh', 'Обновить'));
  // до трёх строк: приветствие склеивается с первым предложением, остальное — за «ещё»
  const s = d.sentences.slice();
  const lines = [];
  if (s.length > 1 && !s[0].href && s[0].text.length < 60) { lines.push({ text: s[0].text + ' ' + s[1].text, href: s[1].href }); s.splice(0, 2); }
  lines.push(...s);
  const line = x => h('p', {}, x.href ? h('a', { href: x.href.startsWith('/panel') ? x.href.slice(6) : x.href }, x.text) : x.text);
  const rest = lines.slice(3);
  const restBox = h('div', { class: 'hidden' }, rest.map(line));
  const moreBtn = rest.length ? h('button', { class: 'btn btn-sm btn-ghost', onclick: () => { restBox.classList.toggle('hidden'); moreBtn.replaceChildren(restBox.classList.contains('hidden') ? iconText('chevron-down', 'ещё ' + rest.length) : 'свернуть'); } }, iconText('chevron-down', 'ещё ' + rest.length)) : null;
  return h('div', { class: 'card summary-ai mt16' },
    h('div', { class: 'row' }, h('div', { class: 'lbl' }, 'Сводка для директора'), aiMark(d.engine === 'openai', 'пересказ ИИ по фактам сервера', 'шаблон без ИИ'), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(d.at)), speakBtn, refreshBtn),
    lines.slice(0, 3).map(line), restBox, moreBtn);
}

async function leaguePanel() {
  const d = await API.get('/api/panel/league');
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, h('div', { class: 'h1' }, 'Лига филиалов'),
    h('div', { class: 'hint' }, 'Качество работы с обращениями, не их число: реализовано ' + Math.round(d.weights.done * 100) + ' % · рассмотрено ' + Math.round(d.weights.considered * 100) + ' % · скорость первого ответа ' + Math.round(d.weights.speed * 100) + ' % (веса — в настройках).'),
    h('div', { class: 'split mt16' },
      h('div', { class: 'card' }, h('table', { class: 'tbl league' }, h('thead', {}, h('tr', {}, ['#', 'Филиал', 'Балл', 'Реализовано', 'Рассмотрено', 'Скорость', 'Открыто', 'Просрочено'].map(t => h('th', {}, t)))),
        h('tbody', {}, d.items.map(b => h('tr', { onclick: () => { S.filters = { branch_id: b.id }; location.hash = '#/queue'; } }, h('td', {}, String(b.rank)), h('td', {}, h('b', {}, b.name), h('div', { class: 'small muted' }, b.total + ' обращений' + (b.enough ? '' : ' — мало данных'))), h('td', { class: 'score' }, h('b', {}, String(b.score))), h('td', {}, Math.round(b.done_share * 100) + ' %'), h('td', {}, Math.round(b.considered_share * 100) + ' %'), h('td', {}, Math.round(b.speed * 100) + ' %'), h('td', {}, String(b.open)), h('td', {}, b.overdue ? tag('tag-overdue', String(b.overdue)) : '0')))))),
      h('div', { class: 'card' }, h('b', {}, 'Топ сотрудников'), h('div', { class: 'list mt8' }, d.top.map((u, i) => h('div', { class: 'item', onclick: () => { location.href = '/app#/u/' + u.id; } }, h('div', { class: 'row' }, h('b', {}, (i + 1) + '.'), avatarEl(u), h('div', {}, h('b', {}, u.name), h('div', { class: 'small muted' }, [u.position, u.branch].filter(Boolean).join(' · '))), h('div', { class: 'spacer' }), h('span', { class: 'small row' }, iconText('star', String(u.points)), 'внедрено ' + u.implemented, iconText('heart', String(u.thanks)))))))))));
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
    num('similar_threshold.embeddings', 'Порог похожих (ИИ)', (st.similar_threshold || {}).embeddings), num('cluster_threshold.embeddings', 'Порог кластеров (ИИ)', (st.cluster_threshold || {}).embeddings),
    num('invite_days', 'Срок личного приглашения, дн', st.invite_days)];
  const saveBtn = h('button', { class: 'btn btn-sm btn-primary', onclick: async () => {
    const out = {};
    for (const box of inputs) { const i = box.querySelector('input'); if (i.value === '') continue; const v = Number(i.value); const [k, sub] = i.dataset.key.split('.'); if (sub) { out[k] = out[k] || { ...(st[k] || {}) }; out[k][sub] = v; } else out[k] = v; }
    try { await API.post('/api/admin/settings', { settings: out }); toast('Настройки сохранены'); adminScreen(); } catch (e) { toast(e.message, 'bad'); }
  } }, 'Сохранить настройки');
  const staff = d.users.filter(u => u.role !== 'employee' && u.active);
  const userSel = (val) => h('select', {}, h('option', { value: '' }, '— вакансия —'), staff.map(u => h('option', { value: u.id, selected: u.id === val }, u.name + ' · ' + (u.position || u.role))));
  const catRows = d.categories.map(c => { const rs = userSel(c.responsible_user_id); const ss = userSel(c.suggestion_responsible_user_id); const sla = h('input', { type: 'number', value: c.sla, class: 'w70' });
    const save = h('button', { class: 'btn btn-sm', onclick: async () => { try { await API.post('/api/admin/categories/' + c.id, { responsible_user_id: rs.value ? Number(rs.value) : null, suggestion_responsible_user_id: ss.value ? Number(ss.value) : null, sla: Number(sla.value) }); toast('Сохранено: ' + c.name); } catch (e) { toast(e.message, 'bad'); } }, title: 'Сохранить' }, icon('check'));
    return h('tr', {}, h('td', {}, h('b', {}, c.name), h('div', { class: 'small muted' }, c.appeals + ' обращений')), h('td', {}, rs), h('td', {}, ss), h('td', {}, sla), h('td', {}, save)); });
  const claimRows = claims.map(c => { const dec = (decision) => async () => { const comment = decision === 'rejected' ? prompt('Причина отказа') : ''; if (decision === 'rejected' && !comment) return; try { await API.post('/api/admin/reward-claims/' + c.id + '/decide', { decision, comment }); toast('Решено'); adminScreen(); } catch (e) { toast(e.message, 'bad'); } };
    return h('tr', {}, h('td', {}, c.user_name), h('td', {}, c.title + ' · ' + c.cost_points), h('td', {}, tag(c.status === 'approved' ? 'st-done' : c.status === 'rejected' ? 'st-rejected' : 'st-review', c.status)), h('td', { class: 'small' }, fmtDate(c.created_at)), h('td', {}, c.status === 'requested' ? h('div', { class: 'row' }, h('button', { class: 'btn btn-sm btn-ok', onclick: dec('approved') }, 'Одобрить'), h('button', { class: 'btn btn-sm btn-danger', onclick: dec('rejected') }, 'Отклонить')) : (c.comment || ''))); });
  const avatars = d.users.filter(u => u.avatar);
  // награды: добавить / изменить / отключить
  const rewardRow = (r) => { const title = h('input', { type: 'text', value: r.title || '', placeholder: 'Название' }); const descr = h('input', { type: 'text', value: r.description || '', placeholder: 'Описание' }); const cost = h('input', { type: 'number', value: r.cost_points || 100, class: 'w70' }); const act = h('input', { type: 'checkbox', checked: r.active !== 0 && r.active !== false });
    const save = h('button', { class: 'btn btn-sm' + (r.id ? '' : ' btn-primary'), onclick: async () => { try { await API.post('/api/admin/rewards', { id: r.id || null, title: title.value, description: descr.value, cost_points: Number(cost.value), active: act.checked }); toast(r.id ? 'Награда сохранена' : 'Награда добавлена'); adminScreen(); } catch (e) { toast(e.message, 'bad'); } }, title: r.id ? 'Сохранить' : 'Добавить' }, r.id ? icon('check') : iconText('plus', 'Добавить'));
    return h('tr', { class: r.active === 0 ? 'muted' : '' }, h('td', {}, title), h('td', {}, descr), h('td', {}, cost), h('td', {}, h('label', { class: 'check' }, act, 'активна')), h('td', {}, save)); };
  const rewardsCard = h('div', { class: 'card' }, h('b', {}, 'Витрина наград'), h('div', { class: 'hint' }, 'Состав определяет компания: добавьте, измените стоимость или отключите.'),
    h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Название', 'Описание', 'Баллы', '', ''].map(t => h('th', {}, t)))), h('tbody', {}, d.rewards.map(rewardRow), rewardRow({}))));
  // сотрудники (этап 8 §4): раздел вынесен в web/a/staff.js — добавление, импорт, приглашения, карточки, отключение
  const bx = d.bitrix || {};
  const bitrixCard = h('div', { class: 'card' }, h('b', {}, 'Битрикс24'),
    bx.configured ? h('div', { class: 'small mt8' }, h('div', {}, 'Портал: ', h('b', {}, bx.portal)), h('div', {}, 'Приложение установлено (токены портала): ', h('b', {}, bx.tokens ? 'да' + (bx.installed_at ? ' · ' + fmtDate(bx.installed_at) : '') : 'нет — откройте «Модус Голос» в меню портала или нажмите «Установить»')),
      h('div', {}, 'Сопоставлено сотрудников: ', h('b', {}, String(bx.mapped_users || 0))), h('div', {}, 'Поручения в задачи Битрикса: ', h('b', {}, bx.tasks ? 'включено' : 'выключено (BITRIX_TASKS=1)')),
      bx.sync ? h('div', {}, 'Последняя синхронизация: ', h('b', {}, fmtDate(bx.sync.at)), ' — в портале ' + bx.sync.portal_users + ', новых ' + bx.sync.created + ', обновлено ' + bx.sync.updated + ', деактивировано ' + bx.sync.deactivated + (bx.sync.conflicts && bx.sync.conflicts.length ? ', спорных ' + bx.sync.conflicts.length : '')) : h('div', { class: 'muted' }, 'Синхронизация ещё не выполнялась'),
      bx.sync && bx.sync.conflicts && bx.sync.conflicts.length ? h('div', { class: 'card card-warn small mt8' }, h('b', {}, 'Спорные склейки — проверьте в «Сотрудниках»: '), bx.sync.conflicts.map(x => (x.bitrix_name || 'ID ' + x.bitrix_id) + ' (Битрикс) склеен с ' + x.name + (x.reason === 'several' ? ' — совпали ' + (x.candidates || []).map(k => k.name + ': ' + k.by).join(', ') : x.reason === 'name' ? ' — склеено по ' + (((x.candidates || [])[0] || {}).by || 'почте или телефону') + ', имена не похожи' : '')).join('; ')) : null,
      h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm btn-primary', disabled: !bx.tokens, onclick: async ev => { ev.target.disabled = true; try { const r = await API.post('/api/admin/bitrix/sync'); toast('Синхронизация: в портале ' + r.portal_users + ', новых ' + r.created + ', обновлено ' + r.updated + ', деактивировано ' + r.deactivated); adminScreen(); } catch (e) { toast(e.message, 'bad'); ev.target.disabled = false; } } }, iconText('refresh', 'Синхронизировать сотрудников')), h('span', { class: 'hint' }, 'сотрудники и отделы из портала; автоматически — раз в сутки')))
      : h('div', { class: 'small mt8' }, bx.webhook ? 'Только входящий вебхук: уведомления дублируются в чат, входа через Битрикс24 нет.' : 'Не подключён: нет настроек в .env. Инструкция — docs/BITRIX24.md. Без настроек ничего не имитируется.'));
  root.replaceChildren(h('div', { class: 'wrap wrap-wide' }, h('div', { class: 'h1' }, 'Администрирование'),
    staffSection(d, adminScreen),
    h('div', { class: 'split' },
      h('div', {},
        h('div', { class: 'card' }, h('b', {}, 'Категории, ответственные, SLA'), h('div', { class: 'hint' }, 'Проблемы идут ответственному; предложения — ответственному за предложения, иначе в отдел развития.'),
          h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Категория', 'Ответственный', 'За предложения', 'SLA, ч', ''].map(t => h('th', {}, t)))), h('tbody', {}, catRows))),
        rewardsCard,
        h('div', { class: 'card' }, h('b', {}, 'Заявки на награды'), claims.length ? h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Кто', 'Награда', 'Статус', 'Когда', ''].map(t => h('th', {}, t)))), h('tbody', {}, claimRows)) : h('div', { class: 'muted small mt8' }, 'Заявок нет'))),
      h('div', {},
        h('div', { class: 'card' }, h('b', {}, 'Настройки'), h('div', { class: 'grid2 mt8' }, inputs), h('div', { class: 'mt8' }, saveBtn), h('div', { class: 'hint mt8' }, 'Пороги похожести и кластеров — для режима ИИ; без ключа действуют пороги по ключевым словам.')),
        bitrixCard,
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
