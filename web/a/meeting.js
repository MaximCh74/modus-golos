'use strict';
// Режим совещания (ТЗ v1.1 §6.2): общий код для /app и /panel — старт/запись/обработка, экран разбора с правкой пунктов,
// «Мои поручения», «На решение» у директора. Использует глобальные ME, DICTS, root, h, API, toast из страницы.
const MEETING = { rec: null, stream: null, chunks: [], timer: null, startedAt: 0, poll: null };
const KIND_LABEL = { decision: 'Решения', task: 'Поручения', idea: 'Идеи и проблемы', linked: 'Связанные обращения' };
const TASK_ST = { draft: 'Черновик', assigned: 'Назначено', in_progress: 'В работе', done: 'Выполнено' };

function add(el, ...kids) { for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) el.append(k); return el; }
function back(href, label) { return h('a', { href, class: 'small' }, '← ' + (label || 'Назад')); }
function fmtDue(d) { if (!d) return ''; const [y, m, dd] = d.split('-'); return dd + '.' + m + '.' + y; }
function aiBadge(m) {
  if (!m) return null;
  if (m.fallback) return tag('tag-demo', m.demo ? 'Демо-разбор без ИИ' : 'Разбор без ИИ (эвристика)');
  return tag('tag-ai', 'Разбор ИИ · ' + (m.llm_engine || ''));
}

// ---------- старт / запись / загрузка ----------

async function meetingStart(opts) {
  opts = opts || {};
  stopPoll();
  const [list, ai] = await Promise.all([API.get('/api/meetings'), API.get('/api/ai/status')]);
  const title = h('input', { type: 'text', placeholder: 'Название встречи (необязательно), например «Планёрка продаж»' });
  const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  const recBtn = h('button', { class: 'btn btn-primary btn-big', disabled: !canRecord }, '● Начать запись');
  const file = h('input', { type: 'file', accept: 'audio/*,video/webm,video/mp4,.m4a,.mp3,.wav,.ogg,.webm,.opus', class: 'hidden' });
  const uploadBtn = h('button', { class: 'btn btn-big', onclick: () => file.click() }, 'Загрузить аудио');
  const ta = h('textarea', { placeholder: 'Вставьте текст расшифровки — для отладки без микрофона. Формат «Имя: реплика» помогает разбору.' });
  const textBtn = h('button', { class: 'btn btn-sm btn-primary', onclick: () => submitMeeting({ title: title.value, transcript: ta.value }, opts) }, 'Разобрать текст');
  const demoBtn = h('button', { class: 'btn btn-sm', onclick: () => { ta.value = DEMO_TRANSCRIPT; } }, 'Подставить демо-планёрку из ТЗ §10');
  file.addEventListener('change', () => { if (file.files && file.files[0]) submitMeeting({ title: title.value, audio: file.files[0] }, opts); });
  recBtn.addEventListener('click', () => startRecording(title.value, opts));
  const sttLine = ai.stt.local ? 'Расшифровка: faster-whisper ' + ai.stt.local_model + ' локально на GPU' + (ai.stt.openai ? ', запасной — OpenAI whisper-1' : '')
    : ai.stt.openai ? 'Расшифровка: OpenAI whisper-1' : 'Расшифровка аудио недоступна (нет локальной модели и ключа) — вставьте текст';
  const llmLine = ai.llm ? 'Разбор: ' + ai.llm_model + ' через OpenAI' : 'Разбор: без ключа OpenAI — заскриптованный демо-разбор (честно помечается на экране)';
  root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/'), h('div', { class: 'h1' }, 'Режим совещания'),
    h('div', { class: 'card' }, field('Название', title),
      h('div', { class: 'card card-warn small' }, h('b', {}, 'Участники уведомлены о записи. '), 'Запись расшифровывается автоматически, аудио удаляется сразу после расшифровки — хранится только текст.'),
      h('div', { class: 'grid2' }, recBtn, uploadBtn), file,
      canRecord ? null : h('div', { class: 'hint mt8' }, 'Запись с микрофона доступна только по HTTPS (адрес туннеля) или на localhost — загрузите файл или вставьте текст.'),
      h('div', { class: 'hint mt8' }, sttLine), h('div', { class: 'hint' }, llmLine)),
    h('details', { class: 'card' }, h('summary', {}, 'Вставить текст расшифровки (для отладки)'), h('div', { class: 'mt8' }, ta), h('div', { class: 'row mt8' }, textBtn, demoBtn)),
    h('div', { class: 'h2' }, 'Мои совещания'),
    h('div', { class: 'card list' }, list.length ? list.slice(0, 10).map(m => meetingRow(m, opts)) : h('div', { class: 'muted' }, 'Пока нет — запишите первую планёрку.'))));
}

function meetingRow(m, opts) {
  const c = m.counts || {};
  return h('div', { class: 'item', onclick: () => { location.hash = (opts.cardPrefix || '#/meeting/') + m.id; } },
    h('div', { class: 'row' }, h('b', {}, m.title), tag('st-' + (m.status === 'sent' ? 'done' : m.status === 'review' ? 'review' : m.status === 'failed' ? 'rejected' : 'new'), m.status_label),
      m.fallback ? tag('tag-demo', 'без ИИ') : null, h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(m.created_at))),
    m.summary_line ? h('div', { class: 'small muted' }, m.summary_line) : null,
    h('div', { class: 'small' }, 'Поручения ' + (c.tasks_done || 0) + '/' + (c.tasks || 0) + ' · идеи приняты ' + (c.ideas_accepted || 0) + ', на решении ' + (c.ideas_pending || 0)));
}

async function startRecording(title, opts) {
  try {
    MEETING.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) { toast('Нет доступа к микрофону: ' + e.message, 'bad'); return; }
  const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', ''].find(m => !m || MediaRecorder.isTypeSupported(m));
  MEETING.rec = new MediaRecorder(MEETING.stream, mime ? { mimeType: mime } : undefined);
  MEETING.chunks = [];
  MEETING.rec.ondataavailable = e => { if (e.data && e.data.size) MEETING.chunks.push(e.data); };
  MEETING.rec.onstop = () => {
    const blob = new Blob(MEETING.chunks, { type: MEETING.rec.mimeType || 'audio/webm' });
    MEETING.stream.getTracks().forEach(t => t.stop());
    const sec = Math.round((Date.now() - MEETING.startedAt) / 1000);
    const ext = (MEETING.rec.mimeType || '').includes('mp4') ? 'm4a' : (MEETING.rec.mimeType || '').includes('ogg') ? 'ogg' : 'webm';
    submitMeeting({ title, audio: new File([blob], 'meeting.' + ext, { type: blob.type }), duration_sec: sec }, opts);
  };
  MEETING.rec.start(1000);
  MEETING.startedAt = Date.now();
  const timer = h('div', { class: 'timer' }, '00:00');
  MEETING.timer = setInterval(() => { const s = Math.round((Date.now() - MEETING.startedAt) / 1000); timer.textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); }, 500);
  const stop = h('button', { class: 'btn btn-primary btn-big', onclick: () => { clearInterval(MEETING.timer); stop.disabled = true; stop.textContent = 'Отправляем…'; MEETING.rec.stop(); } }, 'Завершить');
  root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'h1' }, title || 'Запись совещания'),
    h('div', { class: 'card rec' }, h('div', { class: 'row' }, h('span', { class: 'rec-dot' }), h('span', {}, 'Идёт запись'), h('span', { class: 'small muted' }, MEETING.rec.mimeType)), timer,
      h('p', { class: 'hint' }, 'Говорите как обычно: имена, сроки и номера обращений («A-007») разбор подхватит.'), stop)));
}

async function submitMeeting(data, opts) {
  const fd = new FormData();
  fd.set('title', data.title || '');
  if (data.audio) fd.set('audio', data.audio, data.audio.name || 'meeting.webm');
  if (data.transcript) fd.set('transcript', data.transcript);
  if (data.duration_sec) fd.set('duration_sec', String(data.duration_sec));
  root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card' }, h('div', { class: 'row' }, h('span', { class: 'spin' }), 'Отправляем запись…'))));
  try {
    const r = await API.postForm('/api/meetings', fd);
    location.hash = (opts.cardPrefix || '#/meeting/') + r.id;
  } catch (e) { toast(e.message, 'bad'); meetingStart(opts); }
}

// ---------- обработка и разбор ----------

function stopPoll() { if (MEETING.poll) { clearTimeout(MEETING.poll); MEETING.poll = null; } }

async function meetingCard(id, opts) {
  opts = opts || {};
  stopPoll();
  let m;
  try { m = await API.get('/api/meetings/' + id); } catch (e) { root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/meeting'), h('div', { class: 'card card-bad' }, e.message))); return; }
  if (m.status === 'processing') {
    root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/meeting', 'К совещаниям'), h('div', { class: 'h1' }, m.title),
      h('div', { class: 'card' }, h('div', { class: 'row' }, h('span', { class: 'spin' }), h('b', {}, m.stage_label || 'Обрабатываем…')),
        h('div', { class: 'steps mt8' }, h('div', { class: 'step ' + (m.stage === 'stt' ? 'cur' : 'done') }, '1. Расшифровываем'), h('div', { class: 'step ' + (m.stage === 'analysis' ? 'cur' : '') }, '2. Разбираем')),
        h('p', { class: 'hint' }, m.stage === 'stt' ? 'Локальная модель на GPU: минута записи — несколько секунд.' : 'Выделяем итог, решения, поручения, идеи и связанные обращения.'))));
    MEETING.poll = setTimeout(() => meetingCard(id, opts), 1500);
    return;
  }
  const staff = (DICTS.users || []).filter(u => u.active);
  const save = async (item, patch, okMsg) => {
    try { const r = await API.post('/api/meetings/' + id + '/items/' + item.id, patch); if (okMsg) toast(okMsg); return r; }
    catch (e) { toast(e.message, 'bad'); throw e; }
  };
  const groups = {};
  for (const i of m.items) (groups[i.kind] = groups[i.kind] || []).push(i);
  const head = h('div', { class: 'card' },
    h('div', { class: 'row' }, h('span', { class: 'h1' }, m.title), tag('st-' + (m.status === 'sent' ? 'done' : m.status === 'failed' ? 'rejected' : 'review'), m.status_label), aiBadge(m)),
    h('div', { class: 'small muted' }, [m.creator, m.branch, fmtDate(m.created_at), m.duration_sec ? Math.round(m.duration_sec / 60) + ' мин' : null, m.stt_engine ? 'STT: ' + m.stt_engine : null].filter(Boolean).join(' · ')),
    m.error ? h('div', { class: 'card card-warn small mt8' }, m.error) : null,
    m.fallback ? h('div', { class: 'card card-warn small mt8' }, h('b', {}, 'Демо-разбор без ИИ. '), m.demo ? 'Ключ OpenAI не задан — показан заскриптованный разбор демо-планёрки из ТЗ §10. С ключом этот же экран строит настоящий разбор.' : 'Ключ OpenAI не задан — грубая эвристика: проверьте пункты вручную.') : null);
  if (m.status === 'failed') {
    root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/meeting', 'К совещаниям'), head,
      h('div', { class: 'card card-bad' }, h('b', {}, 'Не удалось обработать'), h('p', {}, m.error || 'Ошибка'), h('a', { href: opts.backHref || '#/meeting', class: 'btn' }, 'Попробовать ещё раз или вставить текст'))));
    return;
  }
  const summary = h('div', { class: 'card' }, h('div', { class: 'h2' }, 'Итог'), h('p', { class: 'pre' }, m.summary || '—'),
    m.open_questions.length ? h('div', { class: 'small mt8' }, h('b', {}, 'Осталось открытым: '), m.open_questions.join('; ')) : null);
  const sections = ['decision', 'task', 'idea', 'linked'].map(kind => {
    const items = groups[kind] || [];
    return h('div', { class: 'card' }, h('div', { class: 'row' }, h('div', { class: 'h2' }, KIND_LABEL[kind]),
      kind === 'idea' ? h('span', { class: 'hint' }, 'уйдут директору в «На решение»') : kind === 'linked' ? h('span', { class: 'hint' }, 'автор и поддержавшие получат уведомление') : null),
      items.length ? items.map(i => itemRow(m, i, kind, staff, save, () => meetingCard(id, opts))) : h('div', { class: 'muted small' }, 'Нет'),
      m.can_edit ? addItemRow(id, kind, staff, () => meetingCard(id, opts)) : null);
  });
  let footer = null;
  if (m.can_edit) {
    const sendBtn = h('button', { class: 'btn btn-primary btn-big', onclick: async () => {
      sendBtn.disabled = true;
      try { const r = await API.post('/api/meetings/' + id + '/send'); toast('Отправлено: поручений ' + r.sent.tasks + ', идей ' + r.sent.ideas + ', обращений ' + r.sent.linked); meetingCard(id, opts); }
      catch (e) { toast(e.message, 'bad'); sendBtn.disabled = false; }
    } }, 'Отправить');
    const live = m.items.filter(i => !i.removed);
    const flagged = live.filter(i => i.kind === 'task' && i.flags.length).length;
    footer = h('div', { class: 'card card-info' }, h('div', { class: 'small mb8' }, 'Проверьте пункты: исправьте текст, выберите исполнителя и срок, уберите лишнее. ' + (flagged ? 'Поручений с флагами: ' + flagged + ' — их можно отправить и так, флаг останется виден.' : '')), sendBtn);
  } else if (m.status === 'sent') {
    footer = h('div', { class: 'card card-ok small' }, h('b', {}, 'Отправлено ' + fmtDate(m.sent_at) + '. '), 'Поручения у исполнителей, идеи у директора в «На решение», авторы связанных обращений уведомлены.');
  }
  const transcript = h('details', { class: 'card' }, h('summary', {}, 'Расшифровка' + (m.language ? ' (' + m.language + ')' : '')), h('p', { class: 'pre small' }, m.transcript || '—'));
  root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/meeting', 'К совещаниям'), head, summary, sections, footer, transcript));
}

function itemRow(m, i, kind, staff, save, refresh) {
  const edit = m.can_edit;
  const row = h('div', { class: 'mi' + (i.removed ? ' removed' : '') });
  const text = edit ? h('textarea', { class: 'mi-text', rows: 2 }, i.text) : h('div', { class: 'pre' }, i.text);
  if (edit) { text.value = i.text; text.addEventListener('change', () => save(i, { text: text.value }, 'Сохранено')); }
  const meta = h('div', { class: 'row small mt8' });
  if (kind === 'task') {
    if (edit) {
      const cands = i.candidates || [];
      const sel = h('select', { class: 'mi-sel' }, h('option', { value: '' }, '— исполнитель не выбран —'),
        cands.length ? h('optgroup', { label: 'Похоже на «' + (i.assignee_name || '') + '»' }, cands.map(c => h('option', { value: c.id, selected: c.id === i.assignee_id }, c.name + ' · ' + Math.round(c.score * 100) + ' %'))) : null,
        h('optgroup', { label: 'Все сотрудники' }, staff.map(u => h('option', { value: u.id, selected: u.id === i.assignee_id }, u.name + (u.position ? ' · ' + u.position : '')))));
      sel.addEventListener('change', async () => { await save(i, { assignee_id: sel.value ? Number(sel.value) : null }, 'Исполнитель сохранён'); refresh(); });
      const due = h('input', { type: 'date', value: i.due_date || '' });
      due.addEventListener('change', async () => { await save(i, { due_date: due.value || null }, 'Срок сохранён'); refresh(); });
      add(meta, h('span', { class: 'muted' }, 'Кто:'), sel, h('span', { class: 'muted' }, 'Срок:'), due, i.due_text ? h('span', { class: 'muted' }, '(«' + i.due_text + '»)') : null);
    } else {
      add(meta, h('span', {}, h('b', {}, 'Кто: '), i.assignee || h('span', { class: 'muted' }, 'не назначен')), h('span', {}, h('b', {}, 'Срок: '), i.due_date ? fmtDue(i.due_date) : h('span', { class: 'muted' }, 'нет')),
        i.task_status && i.task_status !== 'draft' ? tag(i.task_status === 'done' ? 'st-done' : 'st-work', TASK_ST[i.task_status]) : null);
    }
    for (const f of i.flag_labels) meta.append(tag('tag-flag', f));
  }
  if (kind === 'idea') {
    if (edit) {
      const sel = h('select', { class: 'mi-sel' }, h('option', { value: '' }, '— категория не определена —'), DICTS.categories.map(c => h('option', { value: c.id, selected: c.id === i.category_id }, c.name + (c.responsible ? ' → ' + c.responsible : ' → вакансия'))));
      sel.addEventListener('change', async () => { await save(i, { category_id: sel.value ? Number(sel.value) : null }, 'Категория сохранена'); refresh(); });
      add(meta, h('span', { class: 'muted' }, 'Категория:'), sel);
    } else add(meta, h('span', {}, h('b', {}, 'Категория: '), i.category || h('span', { class: 'muted' }, 'не определена')));
    if (i.voiced_by) meta.append(h('span', { class: 'muted' }, 'озвучил(а): ' + i.voiced_by));
    meta.append(tag('tag-director', i.director_decision ? 'Директор: ' + i.director_decision_label : 'уйдёт директору на решение'));
    if (i.created_appeal_number) meta.append(h('a', { href: '#/appeal/' + i.created_appeal_id }, '→ ' + i.created_appeal_number));
    if (i.director_comment) meta.append(h('span', { class: 'small' }, 'Причина: ' + i.director_comment));
    for (const f of i.flag_labels) meta.append(tag('tag-flag', f));
  }
  if (kind === 'linked') {
    add(row, h('div', { class: 'small' }, h('b', {}, 'Обсуждали ' + (i.linked_appeal_number || i.linked_number || '?')), i.linked_appeal_text ? h('span', { class: 'muted' }, ' — ' + i.linked_appeal_text) : null,
      i.linked_appeal_id ? h('a', { href: '#/appeal/' + i.linked_appeal_id, class: 'small' }, ' открыть') : null),
      h('div', { class: 'small muted mt8' }, 'Сообщить автору' + (i.linked_appeal_id ? ' и поддержавшим' : '') + ':'));
    for (const f of i.flag_labels) meta.append(tag('tag-flag', f));
  }
  row.append(text, meta);
  if (edit) {
    const rm = h('button', { class: 'btn btn-sm', onclick: async () => { await save(i, { removed: !i.removed }, i.removed ? 'Возвращено' : 'Убрано'); refresh(); } }, i.removed ? 'Вернуть' : 'Убрать');
    row.append(h('div', { class: 'row mt8' }, h('div', { class: 'spacer' }), rm));
  }
  return row;
}

function addItemRow(id, kind, staff, refresh) {
  const det = h('details', { class: 'small mt8' });
  const text = h('textarea', { rows: 2, placeholder: { decision: 'Решение', task: 'Что сделать', idea: 'Идея или проблема для директора', linked: 'Что сообщить автору обращения' }[kind] });
  const extra = [];
  const body = { kind };
  if (kind === 'task') {
    const sel = h('select', {}, h('option', { value: '' }, '— исполнитель —'), staff.map(u => h('option', { value: u.id }, u.name)));
    const due = h('input', { type: 'date' });
    extra.push(sel, due);
    body.get = () => ({ assignee_id: sel.value ? Number(sel.value) : null, due_date: due.value || null });
  }
  if (kind === 'idea') {
    const sel = h('select', {}, h('option', { value: '' }, '— категория —'), DICTS.categories.map(c => h('option', { value: c.id }, c.name)));
    extra.push(sel); body.get = () => ({ category_id: sel.value ? Number(sel.value) : null });
  }
  if (kind === 'linked') {
    const num = h('input', { type: 'text', placeholder: 'Номер, например A-007' });
    extra.push(num);
    body.get = () => ({ linked_number: num.value });
  }
  const btn = h('button', { class: 'btn btn-sm', onclick: async () => {
    const payload = { kind, text: text.value, ...(body.get ? body.get() : {}) };
    if (payload.linked_number) {
      const row = (S_APPEALS_CACHE[payload.linked_number.toUpperCase()]);
      if (!row) { toast('Обращение ' + payload.linked_number + ' не найдено в открытых', 'bad'); return; }
      payload.linked_appeal_id = row; delete payload.linked_number;
    }
    try { await API.post('/api/meetings/' + id + '/items', payload); toast('Добавлено'); refresh(); } catch (e) { toast(e.message, 'bad'); }
  } }, 'Добавить');
  det.append(h('summary', {}, '+ добавить пункт'), h('div', { class: 'mt8' }, text), h('div', { class: 'row mt8' }, extra, btn));
  if (kind === 'linked') ensureAppealsCache();
  return det;
}
let S_APPEALS_CACHE = {};
async function ensureAppealsCache() {
  if (Object.keys(S_APPEALS_CACHE).length) return;
  try { for (const a of await API.get('/api/panel/appeals?open=1')) S_APPEALS_CACHE[a.number] = a.id; } catch (e) { /* сотруднику недоступно */ }
}

// ---------- мои поручения ----------

async function tasksScreen(opts) {
  opts = opts || {};
  const tasks = await API.get('/api/tasks/mine');
  const act = async (t, status) => { try { await API.post('/api/tasks/' + t.id + '/status', { status }); toast('Статус: ' + TASK_ST[status]); tasksScreen(opts); } catch (e) { toast(e.message, 'bad'); } };
  root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/'), h('div', { class: 'h1' }, 'Мои поручения'),
    h('p', { class: 'hint' }, 'Поручения с совещаний, где вас назначили исполнителем.'),
    h('div', { class: 'card list' }, tasks.length ? tasks.map(t => h('div', { class: 'item' },
      h('div', { class: 'row' }, tag(t.task_status === 'done' ? 'st-done' : t.task_status === 'in_progress' ? 'st-work' : 'st-new', t.task_status_label),
        t.overdue ? tag('tag-overdue', 'Просрочено') : null, h('span', { class: 'small muted' }, 'из «' + t.meeting_title + '» · ' + (t.meeting_creator || '')), h('div', { class: 'spacer' }),
        h('span', { class: 'small' }, t.due_date ? 'до ' + fmtDue(t.due_date) : h('span', { class: 'muted' }, 'срок не назван'))),
      h('div', { class: 'mt8' }, t.text), t.quote ? h('div', { class: 'small muted' }, '«' + t.quote + '»') : null,
      t.task_status !== 'done' ? h('div', { class: 'row mt8' }, t.task_status !== 'in_progress' ? h('button', { class: 'btn btn-sm', onclick: () => act(t, 'in_progress') }, 'В работу') : null,
        h('button', { class: 'btn btn-sm btn-ok', onclick: () => act(t, 'done') }, 'Выполнено')) : null)) : h('div', { class: 'muted' }, 'Поручений нет'))));
}

// ---------- «На решение» у директора ----------

async function decisionsScreen(opts) {
  opts = opts || {};
  const d = await API.get('/api/director/ideas');
  root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/'), h('div', { class: 'h1' }, 'На решение'),
    h('p', { class: 'hint' }, 'Идеи и проблемы с совещаний. «Принять» создаёт обращение и отправляет его ответственному по категории; отклонение — только с причиной.'),
    d.pending.length ? d.pending.map(i => ideaCard(i, () => decisionsScreen(opts))) : h('div', { class: 'card muted' }, 'Нет идей, ожидающих решения'),
    d.decided.length ? h('div', { class: 'h2' }, 'Решено') : null,
    d.decided.length ? h('div', { class: 'card list' }, d.decided.map(i => h('div', { class: 'item' }, h('div', { class: 'row' }, tag(i.director_decision === 'accepted' ? 'st-done' : 'st-rejected', i.director_decision_label),
      h('span', { class: 'small muted' }, '«' + i.meeting_title + '» · ' + fmtDate(i.decided_at) + (i.decided_by_name ? ' · ' + i.decided_by_name : '')), i.created_appeal_number ? h('a', { href: '#/appeal/' + i.created_appeal_id, class: 'small' }, '→ ' + i.created_appeal_number) : null),
      h('div', { class: 'small' }, i.text), i.director_comment ? h('div', { class: 'small muted' }, 'Причина: ' + i.director_comment) : null))) : null));
}

function ideaCard(i, refresh) {
  const sel = h('select', {}, h('option', { value: '' }, '— категория (нужна для маршрутизации) —'), DICTS.categories.map(c => h('option', { value: c.id, selected: c.id === i.category_id }, c.name + (c.responsible ? ' → ' + c.responsible : ' → вакансия'))));
  const reason = h('textarea', { class: 'hidden', placeholder: 'Причина отклонения — её увидит ведущий совещания (обязательно)' });
  const accept = h('button', { class: 'btn btn-sm btn-ok', onclick: async () => {
    accept.disabled = true;
    try { const r = await API.post('/api/director/ideas/' + i.id + '/accept', { category_id: sel.value ? Number(sel.value) : null }); toast('Принято → обращение ' + r.appeal.number + ' у ' + (r.appeal.responsible || 'администратора')); refresh(); }
    catch (e) { toast(e.message, 'bad'); accept.disabled = false; }
  } }, 'Принять');
  const rejectBtn = h('button', { class: 'btn btn-sm btn-danger', onclick: async () => {
    if (reason.classList.contains('hidden')) { reason.classList.remove('hidden'); reason.focus(); rejectBtn.textContent = 'Подтвердить отклонение'; return; }
    try { await API.post('/api/director/ideas/' + i.id + '/reject', { reason: reason.value }); toast('Отклонено'); refresh(); } catch (e) { toast(e.message, 'bad'); }
  } }, 'Отклонить с причиной');
  return h('div', { class: 'card card-info' },
    h('div', { class: 'row' }, tag('tag-type', i.type === 'problem' ? 'Проблема' : 'Идея'), h('span', { class: 'small muted' }, 'с совещания «' + i.meeting_title + '» · ' + (i.meeting_creator || '') + (i.voiced_by ? ' · озвучил(а) ' + i.voiced_by : ''))),
    h('p', {}, i.text),
    h('div', { class: 'row small' }, h('span', { class: 'muted' }, 'Категория → ответственный:'), sel),
    reason, h('div', { class: 'row mt8' }, accept, rejectBtn));
}

async function decisionsBlock(href) {
  try {
    const d = await API.get('/api/director/ideas');
    if (!d.pending.length) return null;
    return h('div', { class: 'card card-info' }, h('div', { class: 'row' }, h('b', {}, 'На решение: ' + d.pending.length), h('div', { class: 'spacer' }), h('a', { href, class: 'btn btn-sm btn-primary' }, 'Открыть')),
      h('div', { class: 'list' }, d.pending.slice(0, 3).map(i => h('div', { class: 'item small', onclick: () => { location.hash = href.slice(href.indexOf('#')); } }, i.text))));
  } catch (e) { return null; }
}

const DEMO_TRANSCRIPT = `Олег: Коллеги, коротко. Бухгалтерия снова пишет про повторный ввод — одни и те же данные вбивают в две системы.
Ерлан: Могу собрать список таких операций и оценить, что можно синхронизировать.
Олег: Давай, Ерлан, до пятницы собери и покажи.
Айгерим: И ещё: итоговые решения по задачам у нас разбросаны по чатам, потом не найти.
Олег: Решили: итоги фиксируем в одном месте — в системе. Айгерим, подготовь короткое правило для своего отдела.
Айгерим: И идея: сделать шаблон коммерческого предложения с обязательными полями, чтобы не переделывать по три раза.
Олег: Хорошая идея, отправим директору. Всё, спасибо.`;
