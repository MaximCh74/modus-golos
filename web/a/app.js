'use strict';
// Приложение сотрудника (PWA): главная, новое обращение, карточка, «Что изменили», уведомления, баллы.
let ME = null, DICTS = null;
const root = document.getElementById('root');

async function boot() {
  ME = await API.me();
  if (!ME) { location.href = '/login?next=' + encodeURIComponent('/app' + location.hash); return; }
  DICTS = await API.get('/api/dicts');
  renderTop();
  if (!document.getElementById('foot')) document.body.append(h('div', { id: 'foot', class: 'foot' }, 'демо · данные синтетические, имена вымышленные · разработано Cyber QALQAN Systems'));
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
    h('a', { href: '#/', class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' }), h('span', {}, 'Модус Голос', h('small', {}, 'Каждый голос услышан'))),
    h('div', { class: 'spacer' }),
    h('span', { class: 'small muted', title: 'Мои баллы' }, iconText('star', String(ME.points || 0))),
    h('a', { href: '#/notifications', class: 'btn btn-sm bell', title: 'Уведомления' }, icon('bell'), ME.unread ? h('span', { class: 'n' }, String(ME.unread)) : null),
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
    if (p[0] === 'rewards') return await rewardsScreen();
    if (p[0] === 'league') return await leagueScreen();
    if (p[0] === 'u') return await profileScreen(Number(p[1]));
    if (p[0] === 'tasks') return await tasksScreen({ backHref: '#/' });
    if (p[0] === 'meeting' && p[1]) return await meetingCard(Number(p[1]), { backHref: '#/meeting', cardPrefix: '#/meeting/' });
    if (p[0] === 'meeting') return await meetingStart({ backHref: '#/', cardPrefix: '#/meeting/' });
    if (p[0] === 'decisions') return await decisionsScreen({ backHref: '#/' });
    return placeholder('Нет такой страницы', '');
  } catch (e) {
    root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-bad' }, e.message), h('a', { href: '#/', class: 'ict' }, icon('arrow-left', { size: 14 }), 'На главную')));
  }
}

function placeholder(title, text) {
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small ict' }, icon('arrow-left', { size: 14 }), 'Назад'), h('div', { class: 'h1' }, title),
    h('div', { class: 'card card-info' }, text || 'Раздел в работе.', h('div', { class: 'hint mt8' }, 'Честная маркировка: раздел ещё не реализован.'))));
}

function tabs(active) {
  const items = [['#/changes', 'Что изменили'], ['#/rewards', 'Награды'], ['#/league', 'Лига']];
  items.push(['#/tasks', 'Мои поручения'], ['#/u/' + ME.id, 'Мой профиль']);
  if (ME.role !== 'employee') items.push(['#/meeting', 'Совещание']);
  if (ME.role === 'director' || ME.role === 'admin') items.push(['#/decisions', 'На решение']);
  return h('div', { class: 'tabs' }, items.map(([href, label]) => h('a', { href, class: href === active ? 'active' : '' }, label)));
}

function item(a) {
  return h('div', { class: 'item', onclick: () => { location.hash = '#/appeal/' + a.id; } },
    h('div', { class: 'row' }, h('b', {}, a.number), badge(a.status), h('span', { class: 'muted small' }, a.type_label + (a.category ? ' · ' + a.category : '')),
      a.is_anonymous ? tag('tag-anon', 'анонимно') : null, a.supports ? h('span', { class: 'small muted' }, iconText('thumbs-up', String(a.supports))) : null,
      h('div', { class: 'spacer' }), h('span', { class: 'muted small' }, fmtAge(a.created_at))),
    h('div', { class: 'small' }, a.text));
}

async function home() {
  const [mine, pts, decisions, summary] = await Promise.all([API.get('/api/appeals/mine'), API.get('/api/me/points'),
    (ME.role === 'director' || ME.role === 'admin') ? decisionsBlock('/app#/decisions') : null,
    (ME.role === 'director' || ME.role === 'admin') ? API.get('/api/panel/director-summary').catch(() => null) : null]);
  ME.points = pts.balance; renderTop();
  const command = (ME.role === 'director' || ME.role === 'admin') ? commandPanel({ decisionsHref: '#/decisions' }) : null;
  root.replaceChildren(h('div', { class: 'wrap' }, summary ? summaryBlock(summary, () => route()) : null, command, decisions,
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
  const prio = h('select', { name: 'priority' }, h('option', { value: '' }, '— по ответу выше и мнению ИИ —'), Object.entries(PRIO).map(([v, l]) => h('option', { value: v }, l)));
  const anon = h('input', { type: 'checkbox' });
  const file = h('input', { type: 'file', accept: 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary btn-big' }, 'Отправить');
  const mic = h('button', { type: 'button', class: 'btn mic', title: 'Голосовой ввод' });
  let inputMode = 'text';
  const urg = chips(URGENCY); const sc = chips(SCOPE);
  const chipLabel = h('span', { class: 'muted small' });
  const chipRow = h('div', { class: 'row mb8' });
  const renderChips = () => { chipRow.replaceChildren(chipLabel, type === 'problem' ? urg : sc); chipLabel.textContent = type === 'problem' ? 'Насколько мешает работать?' : 'Кого затронет?'; };
  const draftBox = h('div', {});
  const simBox = h('div', {});
  let similarShown = false, anyway = false;
  const setType = code => { type = code; for (const k in btns) btns[k].classList.toggle('on', k === code); renderChips(); };
  const draftBtn = h('button', { type: 'button', class: 'btn btn-sm', onclick: () => draft() }, iconText('sparkles', 'Черновик ИИ'));
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
  Voice.attach(mic, text, { onText: () => { inputMode = 'voice'; draft(); } });
  renderChips();
  for (const [code] of types) btns[code].addEventListener('click', renderChips);
  const form = h('form', { class: 'card' },
    switchEl,
    h('div', { class: 'row' }, h('div', { class: 'spacer' }, text), mic),
    chipRow,
    h('div', { class: 'row mb8' }, draftBtn, h('span', { class: 'hint' }, 'голос или текст: ИИ подставит категорию, приоритет и решение')),
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
    fd.set('author_urgency', urg.value() || ''); fd.set('author_scope', sc.value() || ''); fd.set('input_mode', inputMode);
    if (file.files && file.files[0]) fd.set('file', file.files[0]);
    submit.disabled = true;
    try { const r = await API.postForm('/api/appeals', fd); toast('Обращение ' + r.number + ' отправлено'); location.hash = '#/appeal/' + r.id; }
    catch (e) { toast(e.message, 'bad'); submit.disabled = false; }
  });
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small ict' }, icon('arrow-left', { size: 14 }), 'Назад'), h('div', { class: 'h1' }, 'Новое обращение'), form));
}

async function appealCard(id) {
  const a = await API.get('/api/appeals/' + id);
  const supportBtn = a.can_support ? h('button', { class: 'btn btn-sm', onclick: async () => {
    supportBtn.disabled = true;
    try { await API.post('/api/appeals/' + id + '/support'); toast('«У меня так же» учтено'); route(); } catch (e) { toast(e.message, 'bad'); supportBtn.disabled = false; }
  } }, iconText('thumbs-up', 'У меня так же')) : null;
  const thankBtn = a.can_thank ? h('button', { class: 'btn btn-sm', onclick: async () => { thankBtn.disabled = true; try { await API.post('/api/appeals/' + id + '/thank'); toast('Спасибо передано автору'); route(); } catch (e) { toast(e.message, 'bad'); thankBtn.disabled = false; } } }, iconText('heart', 'Спасибо')) : null;
  const card = h('div', { class: 'card' },
    h('div', { class: 'row' }, h('span', { class: 'h1' }, a.number), tag(a.stage.code === 'rejected' ? 'st-rejected' : a.stage.code === 'done' ? 'st-done' : 'st-review', a.stage.label), a.overdue ? tag('tag-overdue', 'Просрочено') : null,
      a.is_anonymous ? tag('tag-anon', 'анонимно') : null, tag('tag-type', a.type_label)),
    stageTracker(a.stage),
    h('div', { class: 'small muted' }, [a.category, a.branch, a.site_city ? 'объект: ' + a.site_city : null, a.department].filter(Boolean).join(' · ')),
    a.is_mine ? null : h('div', { class: 'row small mt8' }, userLink(a.author, 'sm')),
    a.brief && !a.is_mine ? briefBlock(a) : null,
    a.brief && !a.is_mine ? fullText(a) : h('p', { class: 'pre' }, a.text),
    a.brief && !a.is_mine ? null : (a.proposed_solution ? h('div', { class: 'small' }, h('b', {}, 'Предлагаемое решение: '), a.proposed_solution) : null),
    (a.author_urgency_label || a.author_scope_label) ? h('div', { class: 'small mt8' }, h('b', {}, 'Автор: '), [a.author_urgency_label, a.author_scope_label].filter(Boolean).join(' · '), ' · ', h('b', {}, 'Приоритет: '), a.priority_label) : h('div', { class: 'small mt8' }, h('b', {}, 'Приоритет: '), a.priority_label),
    h('div', { class: 'small muted mt8' }, 'Отвечает: ' + (a.responsible ? a.responsible + (a.responsible_position ? ' (' + a.responsible_position + ')' : '') : 'не назначен — в очереди администратора')),
    a.attachments.length ? h('div', { class: 'small mt8' }, 'Вложения: ', a.attachments.map(f => h('a', { href: '/api/attachments/' + f.id, target: '_blank' }, f.filename + ' '))) : null,
    a.points ? h('div', { class: 'small mt8' }, iconText('star', 'Начислено баллов: ' + a.points)) : null,
    h('div', { class: 'row mt8' }, h('span', { class: 'small muted' }, iconText('thumbs-up', 'У меня так же: ' + a.supports)), supportBtn, a.supported_by_me ? h('span', { class: 'small muted' }, '(вы поддержали)') : null,
      a.thanks ? h('span', { class: 'small muted' }, iconText('heart', String(a.thanks))) : null, thankBtn, a.thanked_by_me ? h('span', { class: 'small muted' }, '(вы поблагодарили)') : null));
  const director = a.director_decision ? h('div', { class: 'card ' + (a.director_decision === 'pending' ? 'card-info' : a.director_decision === 'accepted' ? 'card-ok' : 'card-bad') }, h('b', {}, 'Решение директора: ' + a.director_decision_label), h('div', { class: 'small mt8' }, 'Что требуется: ' + a.director_request_text), a.director_comment ? h('div', { class: 'small' }, 'Комментарий: ' + a.director_comment) : null) : null;
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
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small ict' }, icon('arrow-left', { size: 14 }), 'Назад'), card, director, result, answer,
    a.can_manage ? h('div', { class: 'card card-info small' }, 'Вы можете вести это обращение: ', h('a', { href: '/panel#/appeal/' + id }, 'открыть в панели')) : null,
    h('div', { class: 'card' }, h('div', { class: 'h2' }, 'История'), history(a.events))));
}

async function changes() {
  const rows = await API.get('/api/changes');
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small ict' }, icon('arrow-left', { size: 14 }), 'Назад'), h('div', { class: 'h1' }, 'Что изменили'), tabs('#/changes'),
    h('p', { class: 'hint' }, 'Реализованные обращения: проблема и что сделали.'),
    rows.length ? rows.map(r => {
      const tb = (!r.is_mine && !r.thanked_by_me && r.author) ? h('button', { class: 'btn btn-sm', onclick: async ev => { ev.stopPropagation(); tb.disabled = true; try { await API.post('/api/appeals/' + r.id + '/thank'); toast('Спасибо передано ' + r.author.name); changes(); } catch (e) { toast(e.message, 'bad'); tb.disabled = false; } } }, iconText('heart', 'Спасибо')) : null;
      return h('div', { class: 'card', onclick: () => { location.hash = '#/appeal/' + r.id; } },
        h('div', { class: 'row' }, h('b', {}, r.number), tag('tag-type', r.type_label), h('span', { class: 'small muted' }, [r.category, r.branch].filter(Boolean).join(' · ')), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(r.closed_at))),
        h('div', { class: 'row small mt8' }, userLink(r.author, 'sm')),
        h('p', { class: 'small muted' }, r.brief_line || r.text),
        h('div', { class: 'card card-ok small ict' }, icon('arrow-right', { size: 14 }), r.resolution_text),
        h('div', { class: 'row small' }, h('span', { class: 'muted' }, iconText('heart', r.thanks + (r.thanked_by_me ? ' (и вы)' : ''))), tb));
    }) : h('div', { class: 'card muted' }, 'Пока ничего не реализовано')));
}

async function notifications() {
  const data = await API.get('/api/notifications');
  const list = h('div', { class: 'card list' }, data.items.length ? data.items.map(n => h('div', { class: 'item' + (n.read_at ? '' : ' unread'), onclick: () => { if (n.link) location.href = n.link; } },
    h('div', { class: 'row' }, n.read_at ? null : h('span', { class: 'badge st-new' }, 'новое'), h('span', { class: 'small muted' }, fmtDate(n.created_at))), h('div', {}, n.text))) : h('div', { class: 'muted' }, 'Уведомлений нет'));
  const btn = h('button', { class: 'btn btn-sm', onclick: async () => { await API.post('/api/notifications/read', {}); ME.unread = 0; renderTop(); route(); } }, 'Отметить прочитанными');
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small ict' }, icon('arrow-left', { size: 14 }), 'Назад'), h('div', { class: 'row' }, h('div', { class: 'h1' }, 'Уведомления'), h('div', { class: 'spacer' }), data.unread ? btn : null), list));
  if (data.unread) { await API.post('/api/notifications/read', {}); ME.unread = 0; renderTop(); }
}

async function points() {
  const d = await API.get('/api/me/points');
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small ict' }, icon('arrow-left', { size: 14 }), 'Назад'), h('div', { class: 'h1' }, 'Мои баллы'),
    h('div', { class: 'card' }, h('div', { class: 'big' }, String(d.balance)), h('div', { class: 'hint' }, 'Принято к рассмотрению +' + d.rules.accepted + ' · реализовано +' + d.rules.done + ' · «У меня так же» +' + d.rules.support + ' (до +' + d.rules.support_cap + ' на обращение). За отправку, отклонённые, отзывы и анонимные — нет. ', h('a', { href: '/rules', target: '_blank' }, 'Как начисляются баллы'))),
    h('div', { class: 'card list' }, d.ledger.length ? d.ledger.map(l => h('div', { class: 'item', onclick: () => { if (l.appeal_id) location.hash = '#/appeal/' + l.appeal_id; } },
      h('div', { class: 'row' }, h('b', {}, '+' + l.amount), h('span', {}, l.number || ''), h('span', { class: 'small muted' }, l.reason_label), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(l.created_at))))) : h('div', { class: 'muted' }, 'Начислений пока нет'))));
}

// ---------- этап 4: сводка директора, профиль, награды, лига ----------

function summaryBlock(d, refresh) {
  const speakBtn = h('button', { class: 'btn btn-sm', title: 'Озвучить сводку' }, iconText('volume', 'Озвучить'));
  speakBtn.addEventListener('click', () => speakSummary(speakBtn, d.sentences));
  const refreshBtn = h('button', { class: 'btn btn-sm', onclick: async () => { refreshBtn.disabled = true; try { await API.get('/api/panel/director-summary?refresh=1'); refresh(); } catch (e) { toast(e.message, 'bad'); refreshBtn.disabled = false; } } }, iconText('refresh', 'Обновить'));
  const l = d.lines || {};
  return h('div', { class: 'card summary-ai' },
    h('div', { class: 'row' }, h('div', { class: 'lbl' }, 'Сводка'), aiMark(d.engine === 'openai', 'пересказ ИИ по фактам', 'шаблон без ИИ'), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(d.at)), speakBtn, refreshBtn),
    d.sentences.map(s => h('p', {}, s.href ? h('a', { href: s.href }, s.text) : s.text)),
    attentionLine([[l.urgent_open, '/panel#/queue?open=1&urgency=now', 'мешают работать'], [l.decisions_over_threshold, '#/decisions', 'ждут решения'],
      [l.tasks_overdue, '/panel#/meetings?overdue=1', 'поручения просрочены'], [l.no_news, '/panel#/queue?status=in_progress', 'без новостей']]));
}

async function profileScreen(uid) {
  const u = await API.get('/api/users/' + uid + '/profile');
  const mine = uid === ME.id;
  const file = h('input', { type: 'file', accept: 'image/*', class: 'hidden' });
  file.addEventListener('change', async () => { if (!file.files[0]) return; const fd = new FormData(); fd.set('file', file.files[0]); try { await API.postForm('/api/me/avatar', fd); toast('Аватарка обновлена'); profileScreen(uid); } catch (e) { toast(e.message, 'bad'); } });
  const removeBtn = (ME.role === 'admin' || ME.role === 'director') && u.avatar && !mine ? h('button', { class: 'btn btn-sm btn-danger', onclick: async () => { await API.post('/api/admin/users/' + uid + '/avatar/remove'); toast('Аватарка убрана'); profileScreen(uid); } }, 'Убрать аватарку') : null;
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small ict' }, icon('arrow-left', { size: 14 }), 'Назад'),
    h('div', { class: 'card' }, h('div', { class: 'profile-head' }, avatarEl(u, 'lg'), h('div', {}, h('div', { class: 'h1' }, u.name), h('div', { class: 'small muted' }, [u.position, u.city || u.branch, u.department].filter(Boolean).join(' · ')),
      mine ? h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm', onclick: () => file.click() }, u.avatar ? 'Сменить аватарку' : 'Загрузить аватарку'), file, h('span', { class: 'hint' }, 'квадратная обрезка, до 3 МБ')) : removeBtn)),
      h('div', { class: 'stats mt16' }, h('div', { class: 'stat' }, h('b', {}, String(u.points)), h('span', { class: 'small muted' }, 'баллов')), h('div', { class: 'stat' }, h('b', {}, String(u.implemented.length)), h('span', { class: 'small muted' }, 'внедрено')),
        h('div', { class: 'stat' }, h('b', {}, String(u.thanks)), h('span', { class: 'small muted' }, '«спасибо»')), h('div', { class: 'stat' }, h('b', {}, String(u.supported)), h('span', { class: 'small muted' }, 'поддержал коллег'))),
      h('div', { class: 'hint mt8' }, 'Витрина вклада — не соцсеть: без ленты и сообщений. В пилоте аватарка и данные берутся из Битрикс24.')),
    h('div', { class: 'lbl mt16' }, 'Внедрённые идеи'),
    h('div', { class: 'card list' }, u.implemented.length ? u.implemented.map(i => h('div', { class: 'item', onclick: () => { location.hash = '#/appeal/' + i.id; } }, h('div', { class: 'row' }, h('b', {}, i.number), h('span', { class: 'small muted' }, fmtDate(i.closed_at))), h('div', { class: 'small' }, i.text), h('div', { class: 'small card-ok ict' }, icon('arrow-right', { size: 14 }), i.resolution_text || ''))) : h('div', { class: 'muted' }, 'Пока нет — внедрённые идеи попадают сюда из «Что изменили»'))));
}

async function rewardsScreen() {
  const d = await API.get('/api/rewards');
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small ict' }, icon('arrow-left', { size: 14 }), 'Назад'), h('div', { class: 'h1' }, 'Награды'), tabs('#/rewards'),
    h('div', { class: 'card row' }, h('span', {}, 'У вас '), h('b', { class: 'big' }, String(d.balance)), h('span', {}, ' баллов'), h('div', { class: 'spacer' }), h('a', { href: '/rules', target: '_blank', class: 'small' }, 'как начисляются')),
    h('div', { class: 'hint' }, 'Состав наград демонстрационный, определяет компания. Заявку подтверждает администратор или директор, баллы списываются при одобрении.'),
    d.items.map(r => { const can = d.balance >= r.cost_points; const btn = h('button', { class: 'btn btn-sm ' + (can ? 'btn-primary' : ''), disabled: !can, onclick: async () => { btn.disabled = true; try { await API.post('/api/rewards/' + r.id + '/claim'); toast('Заявка отправлена'); rewardsScreen(); } catch (e) { toast(e.message, 'bad'); btn.disabled = false; } } }, can ? 'Получить' : 'Не хватает ' + (r.cost_points - d.balance));
      return h('div', { class: 'card' }, h('div', { class: 'row' }, h('b', {}, r.title), tag('tag-type', r.cost_points + ' баллов'), h('div', { class: 'spacer' }), btn), h('div', { class: 'small muted' }, r.description)); }),
    d.claims.length ? h('div', { class: 'lbl mt16' }, 'Мои заявки') : null,
    d.claims.length ? h('div', { class: 'card list' }, d.claims.map(c => h('div', { class: 'item' }, h('div', { class: 'row' }, tag(c.status === 'approved' ? 'st-done' : c.status === 'rejected' ? 'st-rejected' : 'st-review', c.status === 'approved' ? 'Одобрено' : c.status === 'rejected' ? 'Отклонено' : 'На рассмотрении'), h('b', {}, c.title), h('span', { class: 'small muted' }, fmtDate(c.created_at))), c.comment ? h('div', { class: 'small muted' }, c.comment) : null))) : null));
}

async function leagueScreen() {
  const d = await API.get('/api/panel/league');
  root.replaceChildren(h('div', { class: 'wrap' }, h('a', { href: '#/', class: 'small ict' }, icon('arrow-left', { size: 14 }), 'Назад'), h('div', { class: 'h1' }, 'Лига филиалов'), tabs('#/league'),
    h('div', { class: 'hint' }, 'По качеству работы с обращениями, а не по их числу: реализовано ' + Math.round(d.weights.done * 100) + ' % · рассмотрено ' + Math.round(d.weights.considered * 100) + ' % · скорость первого ответа ' + Math.round(d.weights.speed * 100) + ' %.'),
    h('div', { class: 'card' }, h('table', { class: 'tbl league' }, h('thead', {}, h('tr', {}, ['#', 'Филиал', 'Балл', 'Реализовано', 'Рассмотрено', 'Скорость', 'Открыто'].map(t => h('th', {}, t)))),
      h('tbody', {}, d.items.map(b => h('tr', {}, h('td', {}, String(b.rank)), h('td', {}, h('b', {}, b.city || b.name), h('div', { class: 'small muted' }, b.total + ' обращений' + (b.enough ? '' : ' — мало данных'))), h('td', { class: 'score' }, h('b', {}, String(b.score))), h('td', {}, Math.round(b.done_share * 100) + ' %'), h('td', {}, Math.round(b.considered_share * 100) + ' %'), h('td', {}, Math.round(b.speed * 100) + ' %'), h('td', {}, String(b.open))))))),
    h('div', { class: 'lbl mt16' }, 'Топ сотрудников'),
    h('div', { class: 'card list' }, d.top.map((u, i) => h('div', { class: 'item', onclick: () => { location.hash = '#/u/' + u.id; } }, h('div', { class: 'row' }, h('b', {}, (i + 1) + '.'), avatarEl(u), h('div', {}, h('b', {}, u.name), h('div', { class: 'small muted' }, [u.position, u.branch].filter(Boolean).join(' · '))), h('div', { class: 'spacer' }), h('span', { class: 'small row' }, iconText('star', String(u.points)), 'внедрено ' + u.implemented, iconText('heart', String(u.thanks)))))))));
}

boot();
