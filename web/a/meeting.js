'use strict';
// Режим совещания (ТЗ v1.1 §6.2): общий код для /app и /panel — старт/запись/обработка, экран разбора с правкой пунктов,
// «Мои поручения», «На решение» у директора. Использует глобальные ME, DICTS, root, h, API, toast из страницы.
// Упрощено по правилам этапа 9 (пункт 4 очереди 12.11): одна главная кнопка на экран, служебные плашки про режим разбора — подсказка «?»
// (значка ИИ нет, 13.11), нули не показываем, никаких нативных элементов (списки — pick, срок — datePick), без горизонтальной прокрутки.
const MEETING = { rec: null, stream: null, chunks: [], timer: null, startedAt: 0, poll: null };
const KIND_LABEL = { decision: 'Решения', task: 'Поручения', idea: 'Идеи и проблемы', linked: 'Связанные обращения' };
const TASK_ST = { draft: 'Черновик', assigned: 'Назначено', in_progress: 'В работе', done: 'Выполнено' };

function add(el, ...kids) { for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) el.append(k); return el; }
function back(href, label) { return h('a', { href, class: 'small ict' }, icon('arrow-left', { size: 14 }), label || 'Назад'); }
function fmtDue(d) { if (!d) return ''; const [y, m, dd] = d.split('-'); return dd + '.' + m + '.' + y; }
// «ИИ / без ИИ» — маленькая иконка с подсказкой, не цветной бейдж (правило 5)

// ---------- старт / запись / загрузка ----------

async function meetingStart(opts) {
  opts = opts || {};
  stopPoll();
  const list = await API.get('/api/meetings');
  const title = h('input', { type: 'text', placeholder: 'Название (необязательно)' });   // подсказка влезает целиком на 360 (13.11)
  const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  const recBtn = h('button', { class: 'btn btn-primary btn-big', disabled: !canRecord }, 'Начать запись');   // в кнопках с текстом значков нет (13.11)
  const file = h('input', { type: 'file', accept: 'audio/*,video/*,.m4a,.mp3,.wav,.ogg,.webm,.opus,.mp4,.mov,.mkv', class: 'visually-hidden', tabindex: '-1' });
  const uploadBtn = h('button', { class: 'btn btn-outline btn-big', onclick: () => file.click() }, 'Загрузить');   // что можно загрузить — в «?» у заголовка
  const ta = h('textarea', { placeholder: 'Текст расшифровки. Формат «Имя: реплика» помогает разбору.' });
  const textBtn = h('button', { class: 'btn btn-sm btn-primary', onclick: () => submitMeeting({ title: title.value, transcript: ta.value }, opts) }, 'Разобрать текст');
  const demoBtn = h('button', { class: 'btn btn-sm', onclick: () => { ta.value = DEMO_TRANSCRIPT; } }, 'Подставить демо-планёрку');
  file.addEventListener('change', () => { if (file.files && file.files[0]) submitMeeting({ title: title.value, audio: file.files[0] }, opts); });
  recBtn.addEventListener('click', () => startRecording(title.value, opts));
  root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/'), h('div', { class: 'row' }, h('div', { class: 'h1' }, 'Режим совещания', helpBtn('meeting'))),
    h('div', { class: 'card' }, field('Название', title),
      h('div', { class: 'grid2' }, recBtn, uploadBtn), file,
      h('div', { class: 'hint mt8' }, canRecord ? 'Участники уведомлены о записи. Аудио и видео удаляются сразу после расшифровки — хранится только текст.' : 'Запись с микрофона доступна по HTTPS или на localhost — загрузите файл или вставьте текст. Аудио удаляется после расшифровки.')),
    h('details', { class: 'card sect' }, h('summary', {}, 'Вставить текст расшифровки'), h('div', { class: 'mt8' }, ta), h('div', { class: 'row mt8' }, textBtn, demoBtn)),
    list.length ? h('div', { class: 'lbl mt16' }, 'Мои совещания') : null,
    list.length ? h('div', { class: 'card list' }, list.slice(0, 10).map(m => meetingRow(m, opts))) : null));
}

function meetingRow(m, opts) {
  const c = m.counts || {};
  const bits = [c.tasks ? 'поручения ' + (c.tasks_done || 0) + '/' + c.tasks : null, c.ideas_accepted ? 'идей принято ' + c.ideas_accepted : null, c.ideas_pending ? 'на решении ' + c.ideas_pending : null, c.tasks_overdue ? 'просрочено ' + c.tasks_overdue : null].filter(Boolean);
  return h('div', { class: 'item', onclick: () => { location.hash = (opts.cardPrefix || '#/meeting/') + m.id; } },
    h('div', { class: 'row' }, h('b', {}, m.title), tag('st-' + (m.status === 'sent' ? 'done' : m.status === 'review' ? 'review' : m.status === 'failed' ? 'rejected' : 'new'), m.status_label),
      h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, fmtDate(m.created_at))),
    m.summary_line ? h('div', { class: 'small muted' }, m.summary_line) : null,
    bits.length ? h('div', { class: 'small' }, c.tasks_overdue ? h('span', { class: 'dot-overdue' }) : null, bits.join(' · ')) : null);
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
    h('div', { class: 'card rec' }, h('div', { class: 'row' }, h('span', { class: 'rec-dot' }), h('span', {}, 'Идёт запись')), timer,
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
        h('p', { class: 'hint' }, m.stage === 'stt' ? 'Минута записи — несколько секунд.' : 'Выделяем итог, решения, поручения, идеи и связанные обращения.'))));
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
  const meta = [m.creator, brCity(m.branch), fmtDate(m.created_at), m.duration_sec ? Math.round(m.duration_sec / 60) + ' мин' : null].filter(Boolean).join(' · ');
  const head = h('div', { class: 'card' },
    h('div', { class: 'row' }, h('span', { class: 'h1 num' }, m.title), tag('st-' + (m.status === 'sent' ? 'done' : m.status === 'failed' ? 'rejected' : 'review'), m.status_label), helpBtn('meeting_analysis')),
    h('div', { class: 'small muted' }, meta),
    m.error ? h('div', { class: 'card card-warn small mt8' }, m.error) : null);
  if (m.status === 'failed') {
    root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/meeting', 'К совещаниям'), head,
      h('div', { class: 'card card-bad' }, h('b', {}, 'Не удалось обработать'), h('p', {}, m.error || 'Ошибка'), h('a', { href: opts.backHref || '#/meeting', class: 'btn btn-outline' }, 'Попробовать ещё раз'))));
    return;
  }
  const summary = h('div', { class: 'card' }, h('div', { class: 'lbl' }, 'Итог'), h('p', { class: 'pre' }, m.summary || '—'),
    m.open_questions.length ? h('div', { class: 'small mt8' }, h('b', {}, 'Осталось открытым: '), m.open_questions.join('; ')) : null);
  const HELP = { decision: 'meeting_decision', task: 'task', idea: 'idea', linked: 'linked' };
  const sections = ['decision', 'task', 'idea', 'linked'].map(kind => {
    const items = groups[kind] || [];
    if (!items.length && !m.can_edit) return null;   // пустые разделы не показываем (правило 4)
    return h('div', { class: 'card' }, h('div', { class: 'row' }, h('div', { class: 'h2' }, KIND_LABEL[kind], helpBtn(HELP[kind])),
      items.length ? h('span', { class: 'small muted' }, items.filter(i => !i.removed).length) : null),
      items.length ? items.map(i => itemRow(m, i, kind, staff, save, () => meetingCard(id, opts))) : h('div', { class: 'muted small' }, 'Пока пусто'),
      m.can_edit ? addItemRow(id, kind, staff, () => meetingCard(id, opts)) : null);
  }).filter(Boolean);
  let footer = null;
  if (m.can_edit) {
    const sendBtn = h('button', { class: 'btn btn-primary btn-big', onclick: async () => {
      sendBtn.disabled = true;
      try { const r = await API.post('/api/meetings/' + id + '/send'); toast('Отправлено: поручений ' + r.sent.tasks + ', идей ' + r.sent.ideas + ', обращений ' + r.sent.linked); meetingCard(id, opts); }
      catch (e) { toast(e.message, 'bad'); sendBtn.disabled = false; }
    } }, iconText('send', 'Отправить'));
    const live = m.items.filter(i => !i.removed);
    const flagged = live.filter(i => i.kind === 'task' && i.flags.length).length;
    footer = h('div', { class: 'card card-info' }, h('div', { class: 'small mb8' }, 'Проверьте пункты: текст, исполнителя и срок; лишнее уберите. ', flagged ? h('span', {}, 'С флагами: ' + flagged + ' — можно отправить и так.', helpBtn('flags')) : null), sendBtn);
  } else if (m.status === 'sent') {
    footer = h('div', { class: 'card card-ok small' }, h('b', {}, 'Отправлено ' + fmtDate(m.sent_at) + '. '), 'Поручения у исполнителей, идеи у директора в «На решение», авторы связанных обращений уведомлены.');
  }
  const transcript = h('details', { class: 'card sect' }, h('summary', {}, 'Расшифровка' + (m.language ? ' · ' + m.language : '')), h('p', { class: 'pre small' }, m.transcript || '—'));
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
      const candIds = new Set(cands.map(c => c.id));
      const options = cands.map(c => ({ value: c.id, label: c.name, hint: 'похоже на «' + (i.assignee_name || '') + '» · ' + Math.round(c.score * 100) + ' %' }))
        .concat(staff.filter(u => !candIds.has(u.id)).map(u => ({ value: u.id, label: u.name, hint: u.position || '' })));
      const sel = pick({ placeholder: 'исполнитель не выбран', value: i.assignee_id || '', options });
      sel.classList.add('mi-pick');
      sel.addEventListener('change', async () => { await save(i, { assignee_id: sel.value ? Number(sel.value) : null }, 'Исполнитель сохранён'); refresh(); });
      const due = datePick({ value: i.due_date || '', placeholder: 'срок не назван' });
      due.classList.add('mi-pick');
      due.addEventListener('change', async () => { await save(i, { due_date: due.value || null }, 'Срок сохранён'); refresh(); });
      add(meta, h('div', { class: 'mi-fields' }, field('Кто', sel), field('Срок' + (i.due_text ? ' («' + i.due_text + '»)' : ''), due)));
    } else {
      add(meta, h('span', {}, h('b', {}, 'Кто: '), i.assignee || h('span', { class: 'muted' }, 'не назначен')), h('span', {}, h('b', {}, 'Срок: '), i.due_date ? fmtDue(i.due_date) : h('span', { class: 'muted' }, 'нет')),
        i.task_status && i.task_status !== 'draft' ? tag(i.task_status === 'done' ? 'st-done' : 'st-work', TASK_ST[i.task_status]) : null, i.overdue ? h('span', { class: 'small' }, h('span', { class: 'dot-overdue' }), 'просрочено') : null);
    }
    for (const f of i.flag_labels) meta.append(tag('tag-flag', f));
  }
  if (kind === 'idea') {
    if (edit) {
      const sel = pick({ placeholder: 'категория не определена', value: i.category_id || '', options: DICTS.categories.map(c => ({ value: c.id, label: c.name, hint: c.responsible || 'вакансия' })) });
      sel.classList.add('mi-pick');
      sel.addEventListener('change', async () => { await save(i, { category_id: sel.value ? Number(sel.value) : null }, 'Категория сохранена'); refresh(); });
      add(meta, h('div', { class: 'mi-fields' }, field('Категория', sel)));
    } else add(meta, h('span', {}, h('b', {}, 'Категория: '), i.category || h('span', { class: 'muted' }, 'не определена')));
    if (i.voiced_by) meta.append(h('span', { class: 'muted' }, 'озвучил(а): ' + i.voiced_by));
    meta.append(tag(i.director_decision ? (i.director_decision === 'accepted' ? 'st-done' : i.director_decision === 'rejected' ? 'st-rejected' : 'st-review') : 'tag-type', i.director_decision ? 'Директор: ' + i.director_decision_label : 'директору на решение'));
    if (i.created_appeal_number) meta.append(h('a', { href: '#/appeal/' + i.created_appeal_id, class: 'ict' }, icon('arrow-right', { size: 14 }), i.created_appeal_number));
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
  if (edit) {   // «Убрать / Вернуть» — тихая кнопка справа, главная кнопка экрана одна — «Отправить»
    const rm = h('button', { class: 'btn btn-sm btn-ghost mi-rm', title: i.removed ? 'Вернуть пункт' : 'Убрать пункт', onclick: async () => { await save(i, { removed: !i.removed }, i.removed ? 'Возвращено' : 'Убрано'); refresh(); } }, i.removed ? iconText('refresh', 'Вернуть') : iconText('x', 'Убрать'));
    meta.append(h('div', { class: 'spacer' }), rm);
  }
  return row;
}

function addItemRow(id, kind, staff, refresh) {
  const det = h('details', { class: 'small mt8 sect' });
  const text = h('textarea', { rows: 2, placeholder: { decision: 'Решение', task: 'Что сделать', idea: 'Идея или проблема для директора', linked: 'Что сообщить автору обращения' }[kind] });
  const extra = [];
  const body = { kind };
  if (kind === 'task') {
    const sel = pick({ placeholder: 'исполнитель', options: staff.map(u => ({ value: u.id, label: u.name, hint: u.position || '' })) });
    const due = datePick({ placeholder: 'срок' });
    extra.push(field('Кто', sel), field('Срок', due));
    body.get = () => ({ assignee_id: sel.value ? Number(sel.value) : null, due_date: due.value || null });
  }
  if (kind === 'idea') {
    const sel = pick({ placeholder: 'категория', options: DICTS.categories.map(c => ({ value: c.id, label: c.name })) });
    extra.push(field('Категория', sel)); body.get = () => ({ category_id: sel.value ? Number(sel.value) : null });
  }
  if (kind === 'linked') {
    const num = h('input', { type: 'text', placeholder: 'Номер, например A-007' });
    extra.push(field('Обращение', num));
    body.get = () => ({ linked_number: num.value });
  }
  const btn = h('button', { class: 'btn btn-sm btn-outline', onclick: async () => {
    const payload = { kind, text: text.value, ...(body.get ? body.get() : {}) };
    if (payload.linked_number) {
      const row = (S_APPEALS_CACHE[payload.linked_number.toUpperCase()]);
      if (!row) { toast('Обращение ' + payload.linked_number + ' не найдено в открытых', 'bad'); return; }
      payload.linked_appeal_id = row; delete payload.linked_number;
    }
    try { await API.post('/api/meetings/' + id + '/items', payload); toast('Добавлено'); refresh(); } catch (e) { toast(e.message, 'bad'); }
  } }, iconText('plus', 'Добавить'));
  det.append(h('summary', {}, 'Добавить пункт'), h('div', { class: 'mt8' }, text), extra.length ? h('div', { class: 'mi-fields mt8' }, extra) : null, h('div', { class: 'row mt8' }, btn));
  if (kind === 'linked') ensureAppealsCache();
  return det;
}
let S_APPEALS_CACHE = {};
async function ensureAppealsCache() {
  if (Object.keys(S_APPEALS_CACHE).length) return;
  try { for (const a of await API.get('/api/panel/appeals?open=1')) S_APPEALS_CACHE[a.number] = a.id; } catch (e) { /* сотруднику недоступно */ }
}

// ---------- мои поручения: одна главная кнопка у поручения — «Выполнено», «В работу» — в меню ----------

async function tasksScreen(opts) {
  opts = opts || {};
  const tasks = await API.get('/api/tasks/mine');
  const act = async (t, status) => { try { await API.post('/api/tasks/' + t.id + '/status', { status }); toast('Статус: ' + TASK_ST[status]); tasksScreen(opts); } catch (e) { toast(e.message, 'bad'); } };
  const open = tasks.filter(t => t.task_status !== 'done'), done = tasks.filter(t => t.task_status === 'done');
  const row = t => h('div', { class: 'item' + (t.task_status === 'done' ? ' muted' : '') },
    h('div', { class: 'row' }, t.task_status !== 'done' && t.task_status !== 'assigned' ? tag('st-work', TASK_ST[t.task_status]) : null, t.overdue ? h('span', { class: 'small' }, h('span', { class: 'dot-overdue' }), 'просрочено') : null,
      h('span', { class: 'small muted' }, 'из «' + t.meeting_title + '»' + (t.meeting_creator ? ' · ' + t.meeting_creator : '')), h('div', { class: 'spacer' }),
      h('span', { class: 'small' }, t.due_date ? 'до ' + fmtDue(t.due_date) : h('span', { class: 'muted' }, 'срок не назван'))),
    h('div', { class: 'mt8' }, t.text),
    t.task_status !== 'done' ? h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm btn-primary', onclick: () => act(t, 'done') }, 'Выполнено'),
      t.task_status !== 'in_progress' ? menuButton([['Взять в работу', () => act(t, 'in_progress')]]) : null) : h('div', { class: 'small muted mt8' }, 'выполнено' + (t.done_at ? ' ' + fmtDate(t.done_at) : '')));
  root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/'), h('div', { class: 'h1' }, 'Мои поручения', helpBtn('my_tasks')),
    h('p', { class: 'hint' }, 'Поручения с совещаний, где вас назначили исполнителем.'),
    h('div', { class: 'card list' }, open.length ? open.map(row) : h('div', { class: 'muted' }, 'Невыполненных поручений нет')),
    done.length ? h('details', { class: 'card sect' }, h('summary', {}, 'Выполненные · ' + done.length), h('div', { class: 'list mt8' }, done.map(row))) : null));
}

// ---------- «На решение» у директора: «Принять» — главная, «Отклонить» — нейтральная с причиной ----------

async function decisionsScreen(opts) {
  opts = opts || {};
  const d = await API.get('/api/director/ideas');
  root.replaceChildren(h('div', { class: 'wrap' }, back(opts.backHref || '#/'), h('div', { class: 'row' }, h('div', { class: 'h1' }, 'На решение', helpBtn('decision')), h('div', { class: 'spacer' }),
      d.over_threshold ? h('span', { class: 'small' }, 'ждут дольше ' + d.threshold_days + ' дн: ' + d.over_threshold, helpBtn('director_wait')) : null),
    h('p', { class: 'hint' }, 'Идеи с совещаний и предложения из обращений, которым нужны ресурсы. «Принять» для идеи создаёт обращение ответственному по категории; отклонение — с причиной.'),
    d.pending.length ? d.pending.map(i => i.source === 'appeal' ? appealDecisionCard(i, () => decisionsScreen(opts)) : ideaCard(i, () => decisionsScreen(opts))) : h('div', { class: 'card muted' }, 'Нет идей, ожидающих решения'),
    d.decided.length ? h('details', { class: 'card sect' }, h('summary', {}, 'Решено · ' + d.decided.length), h('div', { class: 'list mt8' }, d.decided.map(i => h('div', { class: 'item' }, h('div', { class: 'row' }, tag(i.director_decision === 'accepted' ? 'st-done' : 'st-rejected', i.director_decision_label),
      h('span', { class: 'small muted' }, (i.meeting_title ? '«' + i.meeting_title + '» · ' : (i.number ? i.number + ' · ' : '')) + fmtDate(i.decided_at) + (i.decided_by_name ? ' · ' + i.decided_by_name : '')), i.created_appeal_number ? h('a', { href: '#/appeal/' + i.created_appeal_id, class: 'small ict' }, icon('arrow-right', { size: 14 }), i.created_appeal_number) : null),
      h('div', { class: 'small' }, i.text), i.director_comment ? h('div', { class: 'small muted' }, 'Причина: ' + i.director_comment) : null)))) : null));
}

function waitTag(i) {
  if (i.wait_days === null || i.wait_days === undefined) return null;
  const d = Math.floor(i.wait_days);
  return h('span', { class: 'small ' + (i.over_threshold ? 'boss-late' : 'muted') }, 'ждёт ' + (d < 1 ? 'меньше дня' : d + ' дн'));
}

function appealDecisionCard(i, refresh) {
  const reason = h('textarea', { class: 'hidden', rows: 2, placeholder: 'Причина отклонения — её увидят автор и ответственный (обязательно)' });
  const comment = h('input', { type: 'text', placeholder: 'Комментарий при принятии (необязательно): что выделено, какой срок' });
  const act = async (decision, text) => { try { await API.post('/api/director/appeals/' + i.appeal_id + '/decide', { decision, comment: text }); toast(decision === 'accepted' ? 'Принято — ответственный и автор уведомлены' : 'Отклонено'); refresh(); } catch (e) { toast(e.message, 'bad'); } };
  const accept = h('button', { class: 'btn btn-sm btn-primary', onclick: () => act('accepted', comment.value) }, 'Принять');
  const rejectBtn = h('button', { class: 'btn btn-sm', onclick: () => { if (reason.classList.contains('hidden')) { reason.classList.remove('hidden'); reason.focus(); rejectBtn.textContent = 'Подтвердить отклонение'; return; } act('rejected', reason.value); } }, 'Отклонить');
  return h('div', { class: 'card ' + (i.over_threshold ? 'card-warn' : '') },
    h('div', { class: 'row' }, h('a', { href: '#/appeal/' + i.appeal_id }, h('b', {}, i.number)), h('span', { class: 'small muted' }, [i.category, brCity(i.branch), i.responsible ? 'ведёт ' + i.responsible : null].filter(Boolean).join(' · ')), h('div', { class: 'spacer' }), waitTag(i)),
    h('p', {}, i.text),
    h('div', { class: 'small' }, h('b', {}, 'Что требуется: '), i.request), i.supports ? h('div', { class: 'small muted' }, iconText('thumbs-up', 'У меня так же: ' + i.supports)) : null,
    comment, reason, h('div', { class: 'row mt8' }, accept, rejectBtn));
}

function ideaCard(i, refresh) {
  const sel = pick({ placeholder: 'категория — нужна для маршрутизации', value: i.category_id || '', options: DICTS.categories.map(c => ({ value: c.id, label: c.name, hint: c.responsible || 'вакансия' })) });
  const reason = h('textarea', { class: 'hidden', rows: 2, placeholder: 'Причина отклонения — её увидит ведущий совещания (обязательно)' });
  const accept = h('button', { class: 'btn btn-sm btn-primary', onclick: async () => {
    accept.disabled = true;
    try { const r = await API.post('/api/director/ideas/' + i.id + '/accept', { category_id: sel.value ? Number(sel.value) : null }); toast('Принято: обращение ' + r.appeal.number + ' у ' + (r.appeal.responsible || 'администратора')); refresh(); }
    catch (e) { toast(e.message, 'bad'); accept.disabled = false; }
  } }, iconText('check', 'Принять'));
  const rejectBtn = h('button', { class: 'btn btn-sm', onclick: async () => {
    if (reason.classList.contains('hidden')) { reason.classList.remove('hidden'); reason.focus(); rejectBtn.textContent = 'Подтвердить отклонение'; return; }
    try { await API.post('/api/director/ideas/' + i.id + '/reject', { reason: reason.value }); toast('Отклонено'); refresh(); } catch (e) { toast(e.message, 'bad'); }
  } }, 'Отклонить');
  return h('div', { class: 'card ' + (i.over_threshold ? 'card-warn' : '') },
    h('div', { class: 'row' }, h('b', {}, i.type === 'problem' ? 'Проблема с совещания' : 'Идея с совещания'), h('span', { class: 'small muted' }, '«' + i.meeting_title + '»' + (i.meeting_creator ? ' · ' + i.meeting_creator : '') + (i.voiced_by ? ' · озвучил(а) ' + i.voiced_by : '')), h('div', { class: 'spacer' }), waitTag(i)),
    h('p', {}, i.text),
    field('Категория и ответственный', sel),
    reason, h('div', { class: 'row mt8' }, accept, rejectBtn));
}

async function decisionsBlock(href) {
  try {
    const [d, t] = await Promise.all([API.get('/api/director/ideas'), API.get('/api/tasks/overdue').catch(() => null)]);
    if (!d.pending.length && !(t && t.overdue)) return null;
    return h('div', { class: 'card ' + (d.over_threshold ? 'card-warn' : 'card-info') }, h('div', { class: 'row' }, h('b', {}, 'На решение: ' + d.pending.length),
        d.over_threshold ? h('span', { class: 'small boss-late' }, 'ждут дольше ' + d.threshold_days + ' дн: ' + d.over_threshold) : null, h('div', { class: 'spacer' }), h('a', { href, class: 'btn btn-sm btn-outline' }, 'Открыть')),
      h('div', { class: 'list' }, d.pending.slice(0, 3).map(i => h('div', { class: 'item small', onclick: () => { location.hash = href.slice(href.indexOf('#')); } }, (i.source === 'appeal' ? i.number + ' · ' : '') + i.text))),
      t && t.overdue ? h('div', { class: 'row mt8 small' }, h('span', { class: 'dot-overdue' }), h('span', {}, 'Поручения с совещаний: просрочено ' + t.overdue), h('a', { href: '/panel#/meetings?overdue=1', class: 'small' }, 'открыть')) : null);
  } catch (e) { return null; }
}

const DEMO_TRANSCRIPT = `Олег: Коллеги, коротко. Бухгалтерия снова пишет про повторный ввод — одни и те же данные вбивают в две системы.
Ерлан: Могу собрать список таких операций и оценить, что можно синхронизировать.
Олег: Давай, Ерлан, до пятницы собери и покажи.
Айгерим: И ещё: итоговые решения по задачам у нас разбросаны по чатам, потом не найти.
Олег: Решили: итоги фиксируем в одном месте — в системе. Айгерим, подготовь короткое правило для своего отдела.
Айгерим: И идея: сделать шаблон коммерческого предложения с обязательными полями, чтобы не переделывать по три раза.
Олег: Хорошая идея, отправим директору. Всё, спасибо.`;
