'use strict';
// Приложение сотрудника (PWA): главная, новое обращение, карточка, «Что изменили», уведомления, баллы.
let ME = null, DICTS = null;
const root = document.getElementById('root');

async function boot() {
  ME = await API.me();
  if (!ME) { location.href = '/login?next=' + encodeURIComponent('/app' + location.hash); return; }
  DICTS = await API.get('/api/dicts');
  renderTop();
  window.addEventListener('hashchange', route);
  await route();
  API.sse(ev => {
    if (ev.type === 'notification') {
      toast(ev.text); ME.unread = (ME.unread || 0) + 1; renderTop();
      const hsh = location.hash || '#/';
      if (hsh.startsWith('#/appeal/') || hsh === '#/notifications' || hsh === '#/') route();
    }
    if (ev.type === 'points') { ME.points = (ME.points || 0) + ev.amount; renderTop(); }
    if (ev.type === 'meeting_updated' && location.hash === '#/meeting/' + ev.id) route();
    if (ev.type === 'idea_pending' && (location.hash === '#/decisions' || location.hash === '#/')) route();
  });
}

function renderTop() {
  let top = document.getElementById('top');
  if (!top) { top = h('div', { class: 'topbar', id: 'top' }); document.body.prepend(top); }
  top.replaceChildren(
    h('a', { href: '#/', class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' }), h('span', {}, 'Обратная связь', h('small', {}, 'демо'))),
    h('div', { class: 'spacer' }),
    h('span', { class: 'small muted' }, '⭐ ' + (ME.points || 0)),
    h('a', { href: '#/notifications', class: 'btn btn-sm bell', title: 'Уведомления' }, '🔔', ME.unread ? h('span', { class: 'n' }, String(ME.unread)) : null),
    h('a', { href: '/login', class: 'btn btn-sm', title: 'Сменить пользователя' }, ME.name.split(' ')[0]));
}

async function route() {
  const hash = location.hash || '#/';
  const [path, qstr] = hash.slice(1).split('?');
  const p = path.split('/').filter(Boolean);
  const params = new URLSearchParams(qstr || '');
  try {
    if (p.length === 0) return await home();
    if (p[0] === 'new') return await newAppeal(params.get('type') || 'problem');
    if (p[0] === 'appeal') return await appealCard(Number(p[1]));
    if (p[0] === 'changes') return await changes();
    if (p[0] === 'notifications') return await notifications();
    if (p[0] === 'points') return await points();
    if (p[0] === 'rewards') return placeholder('Награды', 'Витрина наград и заявки — этап 4.');
    if (p[0] === 'league') return placeholder('Лига филиалов', 'Лига филиалов и топ сотрудников — этап 4.');
    if (p[0] === 'tasks') return await tasksScreen({ backHref: '#/' });
    if (p[0] === 'meeting' && p[1]) return await meetingCard(Number(p[1]), { backHref: '#/meeting', cardPrefix: '#/meeting/' });
    if (p[0] === 'meeting') return await meetingStart({ backHref: '#/', cardPrefix: '#/meeting/' });
    if (p[0] === 'decisions') return await decisionsScreen({ backHref: '#/' });
    return placeholder('Нет такой страницы', '');
  } catch (e) {
    root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-bad' }, e.message), h('a', { href: '#/' }, '← На главную')));
  }
}

function placeholder(title, text) {
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small' }, '← Назад'), h('div', { class: 'h1' }, title),
    h('div', { class: 'card card-info' }, text || 'Раздел в работе.', h('div', { class: 'hint mt8' }, 'Честная маркировка: раздел ещё не реализован.'))));
}

function tabs(active) {
  const items = [['#/changes', 'Что изменили'], ['#/rewards', 'Награды'], ['#/league', 'Лига']];
  items.push(['#/tasks', 'Мои поручения']);
  if (ME.role !== 'employee') items.push(['#/meeting', 'Совещание']);
  if (ME.role === 'director' || ME.role === 'admin') items.push(['#/decisions', 'На решение']);
  return h('div', { class: 'tabs' }, items.map(([href, label]) => h('a', { href, class: href === active ? 'active' : '' }, label)));
}

function item(a) {
  return h('div', { class: 'item', onclick: () => { location.hash = '#/appeal/' + a.id; } },
    h('div', { class: 'row' }, h('b', {}, a.number), badge(a.status), h('span', { class: 'muted small' }, a.type_label + (a.category ? ' · ' + a.category : '')),
      a.is_anonymous ? tag('tag-anon', 'анонимно') : null, a.supports ? h('span', { class: 'small muted' }, '👍 ' + a.supports) : null,
      h('div', { class: 'spacer' }), h('span', { class: 'muted small' }, fmtAge(a.created_at))),
    h('div', { class: 'small' }, a.text));
}

async function home() {
  const [mine, pts, decisions] = await Promise.all([API.get('/api/appeals/mine'), API.get('/api/me/points'),
    (ME.role === 'director' || ME.role === 'admin') ? decisionsBlock('/app#/decisions') : null]);
  ME.points = pts.balance; renderTop();
  root.replaceChildren(h('div', { class: 'wrap' }, decisions,
    h('div', { class: 'grid2' },
      h('a', { href: '#/new?type=problem', class: 'btn btn-primary btn-big' }, 'Сообщить о проблеме'),
      h('a', { href: '#/new?type=suggestion', class: 'btn btn-outline btn-big' }, 'Предложить улучшение')),
    h('div', { class: 'row mt8' }, h('a', { href: '#/new?type=praise', class: 'btn btn-sm' }, 'Сказать спасибо'), h('div', { class: 'spacer' }),
      h('a', { href: '#/points', class: 'small' }, 'Мои баллы: ', h('b', {}, String(pts.balance)))),
    tabs(null),
    h('div', { class: 'lbl mt16' }, 'Мои обращения'),
    h('div', { class: 'card list' }, mine.length ? mine.map(item) : h('div', { class: 'muted' }, 'Пока нет обращений — нажмите одну из кнопок выше.'))));
}

async function newAppeal(startType) {
  let type = startType;
  const types = [['problem', 'Проблема'], ['suggestion', 'Идея'], ['praise', 'Спасибо']];
  const switchEl = h('div', { class: 'type-switch three' });
  const btns = {};
  for (const [code, label] of types) {
    btns[code] = h('button', { type: 'button', class: 'btn' + (code === type ? ' on' : ''), onclick: () => { type = code; for (const k in btns) btns[k].classList.toggle('on', k === code); } }, label);
    switchEl.append(btns[code]);
  }
  const text = h('textarea', { name: 'text', required: true, placeholder: 'Что происходит и что предлагаете' });
  const sol = h('textarea', { name: 'proposed_solution', placeholder: 'Как это можно решить (необязательно)' });
  const cat = h('select', { name: 'category_id' }, h('option', { value: '' }, '— не знаю, пусть определит ответственный —'), DICTS.categories.map(c => h('option', { value: c.id }, c.name)));
  const prio = h('select', { name: 'priority' }, Object.entries(PRIO).map(([v, l]) => h('option', { value: v, selected: v === 'medium' }, l)));
  const anon = h('input', { type: 'checkbox' });
  const file = h('input', { type: 'file', accept: 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary btn-big' }, 'Отправить');
  const mic = h('button', { type: 'button', class: 'btn mic' }, '🎤');
  const draftBox = h('div', {});
  const simBox = h('div', {});
  let similarShown = false, anyway = false;
  const setType = code => { type = code; for (const k in btns) btns[k].classList.toggle('on', k === code); };
  const draftBtn = h('button', { type: 'button', class: 'btn btn-sm', onclick: () => draft() }, '✨ Черновик ИИ');
  async function draft() {
    if (text.value.trim().length < 5) { toast('Сначала опишите, что происходит', 'bad'); return; }
    draftBtn.disabled = true;
    try {
      const d = await API.post('/api/ai/draft', { text: text.value, type });
      if (d.type && ['problem', 'suggestion', 'praise'].includes(d.type)) setType(d.type);
      if (d.category_id) cat.value = String(d.category_id);
      if (d.priority) prio.value = d.priority;
      if (d.proposed_solution && !sol.value.trim()) sol.value = d.proposed_solution;
      const ai = d.engine === 'openai';
      draftBox.replaceChildren(h('div', { class: 'card card-info small' }, h('b', {}, ai ? 'Черновик ИИ' : 'Черновик без ИИ (словарь ключевых слов)'),
        d.summary ? h('div', { class: 'mt8' }, 'Суть: ' + d.summary) : null,
        h('div', { class: 'mt8' }, 'Категория: ' + (d.category || 'не определена — выберите сами') + (d.confidence ? ' (' + Math.round(d.confidence * 100) + ' %)' : '') + ' · приоритет: ' + (PRIO[d.priority] || '—') + ' · тип: ' + (TYPES[d.type] || '—')),
        d.clarifying_question ? h('div', { class: 'mt8' }, h('b', {}, 'Уточните сразу: '), d.clarifying_question) : null,
        h('div', { class: 'hint mt8' }, 'Поля подставлены — проверьте и поправьте перед отправкой.')));
    } catch (e) { toast(e.message, 'bad'); }
    draftBtn.disabled = false;
  }
  Voice.attach(mic, text, { onText: () => draft() });
  const form = h('form', { class: 'card' },
    switchEl,
    h('div', { class: 'row' }, h('div', { class: 'spacer' }, text), mic),
    h('div', { class: 'row mb8' }, draftBtn, h('span', { class: 'hint' }, 'голос → текст → ИИ подставит категорию, приоритет и решение')),
    draftBox,
    field('Предлагаемое решение', sol),
    h('div', { class: 'grid2' }, field('Категория', cat, 'Если не выбрать — категорию подставит ИИ (без ключа — словарь ключевых слов)'), field('Приоритет', prio)),
    field('Вложение (необязательно)', file),
    h('label', { class: 'check mb8' }, anon, 'Анонимно', h('span', { class: 'hint' }, '— анонимные обращения не дают баллов')),
    simBox,
    submit);
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    if (!anyway && !similarShown && type !== 'praise' && text.value.trim().length >= 8) {
      submit.disabled = true;
      try {
        const r = await API.post('/api/ai/similar', { text: text.value });
        if (r.items.length) {
          similarShown = true;
          simBox.replaceChildren(similarBlock(r, { canSupport: true, onAnyway: () => { anyway = true; simBox.replaceChildren(); form.requestSubmit(); },
            onSupported: i => { location.hash = '#/appeal/' + i.id; } }));
          submit.disabled = false;
          return;
        }
      } catch (e) { /* сервис похожих недоступен — отправляем как есть */ }
      submit.disabled = false;
    }
    const fd = new FormData();
    fd.set('type', type); fd.set('text', text.value); fd.set('proposed_solution', sol.value);
    fd.set('category_id', cat.value); fd.set('priority', prio.value); fd.set('is_anonymous', anon.checked ? '1' : '0');
    if (file.files && file.files[0]) fd.set('file', file.files[0]);
    submit.disabled = true;
    try { const r = await API.postForm('/api/appeals', fd); toast('Обращение ' + r.number + ' отправлено'); location.hash = '#/appeal/' + r.id; }
    catch (e) { toast(e.message, 'bad'); submit.disabled = false; }
  });
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small' }, '← Назад'), h('div', { class: 'h1' }, 'Новое обращение'), form));
}

async function appealCard(id) {
  const a = await API.get('/api/appeals/' + id);
  const supportBtn = a.can_support ? h('button', { class: 'btn btn-sm', onclick: async () => {
    supportBtn.disabled = true;
    try { await API.post('/api/appeals/' + id + '/support'); toast('«У меня так же» учтено'); route(); } catch (e) { toast(e.message, 'bad'); supportBtn.disabled = false; }
  } }, '👍 У меня так же') : null;
  const card = h('div', { class: 'card' },
    h('div', { class: 'row' }, h('span', { class: 'h1' }, a.number), badge(a.status), a.overdue ? tag('tag-overdue', 'Просрочено') : null,
      a.is_anonymous ? tag('tag-anon', 'анонимно') : null, tag('tag-type', a.type_label)),
    tracker(a.status),
    h('div', { class: 'small muted' }, [a.category, a.branch, a.department].filter(Boolean).join(' · ')),
    h('p', { class: 'pre' }, a.text),
    a.proposed_solution ? h('div', { class: 'small' }, h('b', {}, 'Предлагаемое решение: '), a.proposed_solution) : null,
    h('div', { class: 'small muted mt8' }, 'Отвечает: ' + (a.responsible ? a.responsible + (a.responsible_position ? ' (' + a.responsible_position + ')' : '') : 'не назначен — в очереди администратора')),
    a.attachments.length ? h('div', { class: 'small mt8' }, 'Вложения: ', a.attachments.map(f => h('a', { href: '/api/attachments/' + f.id, target: '_blank' }, f.filename + ' '))) : null,
    a.points ? h('div', { class: 'small mt8' }, '⭐ Начислено баллов: ' + a.points) : null,
    h('div', { class: 'row mt8' }, h('span', { class: 'small muted' }, '👍 У меня так же: ' + a.supports), supportBtn, a.supported_by_me ? h('span', { class: 'small muted' }, '(вы поддержали)') : null));
  const result = a.status === 'done' || (a.status === 'closed' && a.resolution_text)
    ? h('div', { class: 'card card-ok' }, h('b', {}, 'Что сделали'), h('p', { class: 'pre' }, a.resolution_text))
    : a.status === 'rejected' ? h('div', { class: 'card card-bad' }, h('b', {}, 'Отклонено — причина'), h('p', { class: 'pre' }, a.resolution_text)) : null;
  let answer = null;
  if (a.pending_question && a.is_mine) {
    const ta = h('textarea', { placeholder: 'Ваш ответ' });
    const btn = h('button', { class: 'btn btn-primary', onclick: async () => {
      btn.disabled = true;
      try { await API.post('/api/appeals/' + id + '/answer', { text: ta.value }); toast('Ответ отправлен'); route(); } catch (e) { toast(e.message, 'bad'); btn.disabled = false; }
    } }, 'Ответить');
    answer = h('div', { class: 'card card-warn' }, h('b', {}, 'Ответственный просит уточнить'), h('p', { class: 'pre' }, a.pending_question), ta, h('div', { class: 'mt8' }, btn));
  }
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small' }, '← Назад'), card, result, answer,
    a.can_manage ? h('div', { class: 'card card-info small' }, 'Вы можете вести это обращение: ', h('a', { href: '/panel#/appeal/' + id }, 'открыть в панели')) : null,
    h('div', { class: 'card' }, h('div', { class: 'h2' }, 'История'), history(a.events))));
}

async function changes() {
  const rows = await API.get('/api/changes');
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small' }, '← Назад'), h('div', { class: 'h1' }, 'Что изменили'), tabs('#/changes'),
    h('p', { class: 'hint' }, 'Реализованные обращения: проблема → что сделали.'),
    rows.length ? rows.map(r => h('div', { class: 'card', onclick: () => { location.hash = '#/appeal/' + r.id; } },
      h('div', { class: 'row' }, h('b', {}, r.number), tag('tag-type', r.type_label), h('span', { class: 'small muted' }, [r.category, r.branch].filter(Boolean).join(' · ')), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(r.closed_at))),
      h('p', { class: 'small muted' }, r.text),
      h('div', { class: 'card card-ok small' }, h('b', {}, '→ '), r.resolution_text))) : h('div', { class: 'card muted' }, 'Пока ничего не реализовано')));
}

async function notifications() {
  const data = await API.get('/api/notifications');
  const list = h('div', { class: 'card list' }, data.items.length ? data.items.map(n => h('div', { class: 'item' + (n.read_at ? '' : ' unread'), onclick: () => { if (n.link) location.href = n.link; } },
    h('div', { class: 'row' }, n.read_at ? null : h('span', { class: 'badge st-new' }, 'новое'), h('span', { class: 'small muted' }, fmtDate(n.created_at))), h('div', {}, n.text))) : h('div', { class: 'muted' }, 'Уведомлений нет'));
  const btn = h('button', { class: 'btn btn-sm', onclick: async () => { await API.post('/api/notifications/read', {}); ME.unread = 0; renderTop(); route(); } }, 'Отметить прочитанными');
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small' }, '← Назад'), h('div', { class: 'row' }, h('div', { class: 'h1' }, 'Уведомления'), h('div', { class: 'spacer' }), data.unread ? btn : null), list));
  if (data.unread) { await API.post('/api/notifications/read', {}); ME.unread = 0; renderTop(); }
}

async function points() {
  const d = await API.get('/api/me/points');
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small' }, '← Назад'), h('div', { class: 'h1' }, 'Мои баллы'),
    h('div', { class: 'card' }, h('div', { class: 'big' }, String(d.balance)), h('div', { class: 'hint' }, 'Принято к рассмотрению +' + d.rules.accepted + ' · реализовано +' + d.rules.done + ' · «У меня так же» +' + d.rules.support + ' (до +' + d.rules.support_cap + ' на обращение). За отправку, отклонённые, отзывы и анонимные — нет.')),
    h('div', { class: 'card list' }, d.ledger.length ? d.ledger.map(l => h('div', { class: 'item', onclick: () => { if (l.appeal_id) location.hash = '#/appeal/' + l.appeal_id; } },
      h('div', { class: 'row' }, h('b', {}, '+' + l.amount), h('span', {}, l.number || ''), h('span', { class: 'small muted' }, l.reason_label), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(l.created_at))))) : h('div', { class: 'muted' }, 'Начислений пока нет'))));
}

boot();
