'use strict';
// Общие элементы интерфейса: словари, конструктор элементов, трекер статуса, история, тост.
const STATUS = {
  new: ['Новое', 'st-new'], review: ['На рассмотрении', 'st-review'], clarify: ['Ожидает уточнения', 'st-clarify'],
  in_progress: ['В работе', 'st-work'], done: ['Реализовано', 'st-done'], closed: ['Закрыто', 'st-closed'], rejected: ['Отклонено', 'st-rejected'],
};
const TYPES = { problem: 'Проблема', suggestion: 'Предложение', praise: 'Положительный отзыв' };
const PRIO = { low: 'Низкий', medium: 'Средний', high: 'Высокий' };
const REASON = { accepted: 'принято к рассмотрению', done: 'реализовано', support: '«У меня так же»' };

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function fmtDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}
function fmtAge(iso) {
  if (!iso) return '';
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return 'только что';
  if (m < 60) return m + ' мин';
  const hrs = Math.round(m / 60);
  if (hrs < 48) return hrs + ' ч';
  return Math.round(hrs / 24) + ' дн';
}
function fmtHours(x) {
  if (x === null || x === undefined) return '—';
  if (x < 1) return Math.round(x * 60) + ' мин';
  if (x < 48) return x.toFixed(x < 10 ? 1 : 0) + ' ч';
  return (x / 24).toFixed(1) + ' дн';
}

function badge(status) { const s = STATUS[status] || [status, '']; return h('span', { class: 'badge ' + s[1] }, s[0]); }
// Пометка «ИИ / без ИИ» (этап 9, правило 5): маленькая иконка с подсказкой при наведении, не цветной бейдж
function aiMark(isAi, aiLabel, plainLabel) { return h('span', { class: 'ai-ic', title: isAi ? (aiLabel || 'ИИ') : (plainLabel || 'без ИИ'), 'aria-label': isAi ? (aiLabel || 'ИИ') : (plainLabel || 'без ИИ') }, icon(isAi ? 'sparkles' : 'file-text', { size: 14 })); }
function tag(cls, text) { return h('span', { class: 'badge ' + cls }, text); }

function tracker(status, narrow) {
  const steps = [['new', 'Новое'], ['review', 'Рассмотрение'], ['in_progress', 'В работе'], ['done', 'Реализовано'], ['closed', 'Закрыто']];
  let cur = status === 'clarify' ? 'review' : status;
  let idx = steps.findIndex(s => s[0] === cur);
  if (status === 'rejected') idx = 4;
  const el = h('div', { class: 'tracker ' + (status === 'rejected' ? 'rejected' : status === 'clarify' ? 'clarify' : '') + (narrow ? ' narrow' : '') });
  steps.forEach((s, i) => {
    let label = s[1];
    if (status === 'rejected' && i === 4) label = 'Отклонено';
    if (status === 'clarify' && i === 1) label = 'Уточнение';
    el.append(h('div', { class: 'step ' + (i < idx ? 'done' : i === idx ? 'cur' : '') }, h('div', { class: 'bar' }), label));
  });
  return el;
}

function eventText(e) {
  const p = e.payload || {};
  switch (e.kind) {
    case 'created': return 'Обращение создано' + (p.source === 'qr' ? ' через QR-форму' : p.source === 'meeting' ? ' из совещания' : p.source === 'voice' ? ' голосом' : '') + (p.anonymous ? ' (анонимно)' : '');
    case 'assigned': return p.responsible_id ? 'Ответственный: ' + p.responsible + (p.auto ? ' (автоматически по категории)' : '') : 'Ответственный не назначен — передано администратору';
    case 'status_changed': return 'Статус: ' + (STATUS[p.to] ? STATUS[p.to][0] : p.to) + (p.text ? ' — ' + p.text : '');
    case 'comment': return 'Комментарий: ' + p.text;
    case 'clarification_requested': return 'Запрошено уточнение: ' + p.text;
    case 'clarification_answered': return 'Ответ автора: ' + p.text;
    case 'escalated': return 'Просрочено: нет первого ответа, срок ' + p.sla_hours + ' ч прошёл — уведомлён руководитель';
    case 'discussed_at_meeting': return 'Обсуждено на совещании' + (p.meeting_title ? ' «' + p.meeting_title + '»' : '') + (p.text ? ': ' + p.text : '');
    case 'director_requested': return 'Вынесено на решение директора' + (p.text ? ': ' + p.text : '');
    case 'director_decided': return 'Директор ' + (p.decision === 'accepted' ? 'принял' : 'отклонил') + ' предложение' + (p.text ? ': ' + p.text : '');
    case 'progress': return 'Как идут дела: ' + p.text;
    case 'director_requested_news': return 'Директор запросил новости: ' + p.text;
    case 'thanked': return '«Спасибо» от коллеги — уже ' + p.count;
    case 'praise_addressed': return 'Спасибо адресовано: ' + (p.user || ('отделу «' + p.department + '»'));
    case 'priority_changed': return 'Приоритет изменён с «' + (PRIO[p.from] || p.from) + '» на «' + (PRIO[p.to] || p.to) + '»' + (p.reason === 'supports' ? ' (по числу «У меня так же»)' : ' (ответственный)');
    case 'rebriefed': return 'Пересказ «Коротко» обновлён' + (p.clarifications ? ' с учётом уточнений' : '');
    case 'ai_classified': return p.category ? 'Категория определена ' + (p.engine === 'openai' ? 'ИИ' : 'по ключевым словам (без ИИ)') + ': ' + p.category + (p.confidence ? ' (' + Math.round(p.confidence * 100) + ' %)' : '')
      : 'Категория не определена ' + (p.engine === 'openai' ? 'ИИ' : 'по ключевым словам') + ' — передано администратору';
    case 'supported': return '«У меня так же» — уже ' + p.count;
    case 'points_awarded': return '+' + p.amount + ' баллов автору (' + (REASON[p.reason] || p.reason) + ')';
    default: return e.kind;
  }
}
function history(events) {
  if (!events || !events.length) return h('div', { class: 'muted small' }, 'Пока пусто');
  return h('div', { class: 'hist' }, events.slice().reverse().map(e =>
    h('div', { class: 'ev' }, h('div', { class: 'muted small' }, fmtDate(e.created_at), e.actor ? h('div', {}, e.actor) : null), h('div', {}, eventText(e)))));
}

// «Требуют внимания» одной строкой (этап 9): [[число, ссылка, подпись], …] — нули не показываем
function attentionLine(items) {
  const parts = items.filter(x => x[0]);
  const el = h('div', { class: 'attention' }, h('b', {}, 'Требуют внимания', helpBtn('attention'), ': '));
  if (!parts.length) { el.append(h('span', { class: 'muted' }, 'ничего — всё в порядке')); return el; }
  parts.forEach((x, i) => { if (i) el.append(h('span', { class: 'muted' }, ' · ')); el.append(h('a', { href: x[1] }, x[2] + ' ' + x[0])); });
  return el;
}

let _toastTimer = null;
function toast(msg, kind) {
  let t = document.getElementById('toast');
  if (!t) { t = h('div', { id: 'toast', class: 'toast' }); document.body.append(t); }
  t.textContent = msg;
  t.className = 'toast show' + (kind === 'bad' ? ' bad' : '');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { t.className = 'toast'; }, 3500);
}
function plural(n, one, few, many) { const m10 = n % 10, m100 = n % 100; return n + ' ' + (m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? few : many); }
function qs(name) { return new URLSearchParams(location.search).get(name); }
// подпись + поле; для стилизованных компонентов (pick, personPicker, filePicker) — div, а не label: иначе клик по пункту списка
// срабатывал бы ещё раз как клик по кнопке списка
function field(label, input, hint) { const native = !!(input && /^(INPUT|TEXTAREA|SELECT)$/.test(input.tagName)); return h(native ? 'label' : 'div', { class: 'field' }, h('span', {}, label), input, hint ? h('div', { class: 'hint' }, hint) : null); }

// Голосовой ввод (этап 3): кнопка-микрофон → MediaRecorder → /api/stt (или /api/public/stt без входа) → текст в поле.
const Voice = {
  pick() { return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', ''].find(m => !m || (window.MediaRecorder && MediaRecorder.isTypeSupported(m))); },
  supported() { return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder); },
  attach(btn, textarea, opts) {
    opts = opts || {};
    let rec = null, chunks = [], stream = null, timer = null, t0 = 0;
    const idle = () => { btn.replaceChildren(icon('mic', { size: 20 })); btn.classList.remove('recording'); btn.disabled = false; btn.title = 'Голосовой ввод: нажмите и говорите, нажмите ещё раз — стоп'; };
    if (!this.supported()) { btn.disabled = true; btn.title = 'Голосовой ввод доступен по HTTPS (адрес туннеля) или на localhost'; return; }
    idle();
    btn.addEventListener('click', async () => {
      if (rec && rec.state === 'recording') { clearInterval(timer); rec.stop(); btn.disabled = true; btn.replaceChildren('…'); return; }
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { toast('Нет доступа к микрофону: ' + e.message, 'bad'); return; }
      const mime = this.pick();
      rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks = [];
      rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
        const ext = (rec.mimeType || '').includes('mp4') ? 'm4a' : (rec.mimeType || '').includes('ogg') ? 'ogg' : 'webm';
        const fd = new FormData();
        fd.set('audio', new File([blob], 'voice.' + ext, { type: blob.type }));
        try {
          const r = await API.postForm(opts.public ? '/api/public/stt' : '/api/stt', fd);
          if (r.text) { textarea.value = (textarea.value ? textarea.value.trim() + ' ' : '') + r.text; textarea.dispatchEvent(new Event('input')); if (opts.onText) opts.onText(r.text, r); }
          else toast('Речь не распознана — попробуйте ещё раз', 'bad');
        } catch (e) { toast(e.message, 'bad'); }
        idle();
      };
      rec.start(1000);
      t0 = Date.now();
      btn.classList.add('recording');
      let hinted = false;
      timer = setInterval(() => {
        const s = Math.round((Date.now() - t0) / 1000);
        btn.replaceChildren(icon('square', { size: 14, fill: true }), ' ' + s);
        if (s >= 150 && !hinted) { hinted = true; toast('Осталось 30 секунд записи'); }
        if (s >= 180 && rec.state === 'recording') { clearInterval(timer); rec.stop(); btn.disabled = true; btn.replaceChildren('…'); toast('Запись остановлена: лимит 3 минуты'); }
      }, 500);
      btn.replaceChildren(icon('square', { size: 14, fill: true }), ' 0');
      btn.title = 'Идёт запись — нажмите, чтобы остановить';
    });
  },
};

// Блок «Похоже, об этом уже сообщали» (этап 3): перед отправкой — похожие открытые обращения.
function similarBlock(r, opts) {
  opts = opts || {};
  const note = r.engine === 'embeddings' ? 'сходство по смыслу (ИИ)' : 'по ключевым словам (без ИИ)';
  const items = r.items.map(i => h('div', { class: 'item' },
    h('div', { class: 'row' }, h('b', {}, i.number), i.category ? h('span', { class: 'small muted' }, i.category) : null, h('span', { class: 'small muted' }, Math.round(i.score * 100) + ' %'),
      h('div', { class: 'spacer' }),
      opts.canSupport ? h('button', { class: 'btn btn-sm', onclick: async ev => { ev.preventDefault(); try { await API.post('/api/appeals/' + i.id + '/support'); toast('«У меня так же» учтено — автору ' + i.number + ' начислены баллы'); if (opts.onSupported) opts.onSupported(i); } catch (e) { toast(e.message, 'bad'); } } }, iconText('thumbs-up', 'У меня так же')) : null),
    h('div', { class: 'small' }, i.text)));
  return h('div', { class: 'card card-warn' }, h('b', {}, 'Похоже, об этом уже сообщали'), h('div', { class: 'hint' }, note + '. Если это то же самое — отметьте «У меня так же» вместо нового обращения' + (opts.canSupport ? '' : ' (нужен вход)') + '.'),
    h('div', { class: 'list mt8' }, items),
    h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-outline', onclick: ev => { ev.preventDefault(); if (opts.onAnyway) opts.onAnyway(); } }, 'Всё равно отправить')));
}


// Аватарка: своя картинка или инициалы на фирменном фоне; анонимным — нейтральная иконка.
function avatarEl(u, size) {
  const cls = 'avatar' + (size === 'sm' ? ' avatar-sm' : size === 'lg' ? ' avatar-lg' : '');
  if (!u) return h('span', { class: cls + ' avatar-anon', title: 'Анонимно' }, icon('user', { size: size === 'lg' ? 36 : 14 }));
  if (u.avatar) return h('img', { class: cls, src: u.avatar, alt: u.name || '' });
  const parts = String(u.name || '?').split(' ');
  const ini = (parts[0][0] || '') + (parts[1] ? parts[1][0] : '');
  return h('span', { class: cls, title: u.name || '' }, ini.toUpperCase());
}
function userLink(u, size) {
  if (!u) return h('span', { class: 'row' }, avatarEl(null, size), h('span', { class: 'muted' }, 'Анонимно'));
  return h('a', { href: '/app#/u/' + u.id, class: 'row ulink' }, avatarEl(u, size), h('span', {}, u.name));
}

// Трекер для автора — стадиями собственника: Принято → Проработка → Принятие решения → Реализация → Готово (или Не принято).
function stageTracker(stage) {
  const el = h('div', { class: 'tracker ' + (stage.code === 'rejected' ? 'rejected' : stage.note === 'нужно ваше уточнение' ? 'clarify' : '') });
  stage.steps.forEach(s => el.append(h('div', { class: 'step ' + (s.state === 'skip' ? 'done skip' : s.state === 'future' ? '' : s.state), title: s.state === 'skip' ? 'пройдено автоматически' : '' }, h('div', { class: 'bar' }), s.label)));
  return h('div', {}, el, stage.note ? h('div', { class: 'small muted' }, stage.note) : null);
}

// «Коротко» — пересказ для ответственного (ТЗ этапа 4 §3): суть / что предлагает / чего ждёт.
function briefBlock(a, opts) {
  opts = opts || {};
  const b = a.brief;
  if (!b) return null;
  const ai = a.brief_engine === 'openai';
  const head = [a.author ? a.author.name : 'Анонимно', a.branch, a.input_mode === 'voice' ? 'голосом' : 'текстом'].filter(Boolean).join(' · ');
  return h('div', { class: 'card ' + (b.unclear ? 'card-warn' : 'card-info') + ' brief' },
    h('div', { class: 'row' }, h('b', {}, 'Коротко'), helpBtn('brief'), h('span', { class: 'small muted' }, head), h('div', { class: 'spacer' }), aiMark(ai, 'пересказ ИИ', b.note || 'без ИИ')),
    h('div', { class: 'mt8' }, h('b', {}, 'Суть: '), b.gist || '—'),
    b.proposes ? h('div', {}, h('b', {}, 'Что предлагает: '), b.proposes) : null,
    b.expects ? h('div', {}, h('b', {}, 'Чего ждёт: '), b.expects) : null,
    b.unclear && b.question ? h('div', { class: 'small mt8' }, h('b', {}, 'Уточняющий вопрос ИИ: '), b.question) : null,
    opts.actions || null);
}
function fullText(a) {
  const sol = a.proposed_solution ? h('div', { class: 'small' }, h('b', {}, 'Предлагаемое решение: '), a.proposed_solution) : null;
  if (!a.brief) return h('div', {}, h('p', { class: 'pre' }, a.text), sol);
  return h('details', { class: 'mt8' }, h('summary', { class: 'small' }, 'Показать полностью' + (a.input_mode === 'voice' ? ' (расшифровка голоса)' : '')), h('p', { class: 'pre' }, a.text), sol);
}

// Чипы «насколько мешает» / «кого затронет» (одно нажатие, необязательно)
const URGENCY = { now: 'Прямо сейчас мешает', workaround: 'Мешает, но обхожусь', minor: 'Мелочь' };
const SCOPE = { me: 'Меня', department: 'Мой отдел', company: 'Всю компанию' };
function chips(options, onPick) {
  const box = h('div', { class: 'chips' });
  let value = null;
  for (const [code, label] of Object.entries(options)) {
    const b = h('button', { type: 'button', class: 'chip', onclick: () => { value = value === code ? null : code; for (const x of box.children) x.classList.toggle('on', x.dataset.code === value); if (onPick) onPick(value); } }, label);
    b.dataset.code = code;
    box.append(b);
  }
  box.value = () => value;
  return box;
}


// Озвучка сводки директора: OpenAI TTS с кэшем на сервере; если недоступно — голос браузера (если есть русский).
let _summaryAudio = null;
async function speakSummary(btn, sentences) {
  if (_summaryAudio && !_summaryAudio.paused) { _summaryAudio.pause(); _summaryAudio = null; btn.replaceChildren(iconText('volume', 'Озвучить')); return; }
  btn.disabled = true; btn.replaceChildren('…');
  try {
    const r = await fetch('/api/panel/director-summary/audio', { credentials: 'same-origin' });
    if (!r.ok) throw new Error('tts ' + r.status);
    const blob = await r.blob();
    _summaryAudio = new Audio(URL.createObjectURL(blob));
    _summaryAudio.onended = () => { btn.replaceChildren(iconText('volume', 'Озвучить')); };
    await _summaryAudio.play();
    btn.replaceChildren(iconText('square', 'Стоп')); btn.title = 'Озвучка OpenAI' + (r.headers.get('X-TTS-Source') === 'cache' ? ' (из кэша)' : '');
  } catch (e) {
    const ru = window.speechSynthesis && speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith('ru'));
    if (ru) { const u = new SpeechSynthesisUtterance(sentences.map(s => s.text).join(' ')); u.lang = 'ru-RU'; u.voice = ru; u.rate = 1.1; u.onend = () => { btn.replaceChildren(iconText('volume', 'Озвучить')); }; speechSynthesis.cancel(); speechSynthesis.speak(u); btn.replaceChildren(iconText('square', 'Стоп')); btn.title = 'голос браузера: ' + ru.name; }
    else { toast('Озвучка недоступна: нет ключа и русского голоса в браузере', 'bad'); btn.replaceChildren(iconText('volume', 'Озвучить')); }
  }
  btn.disabled = false;
}


// Фирменный блок «логотип МОДУС ТРЕЙД | черта | МОДУС ГОЛОС» — шапка сайта, приложения и панели. «МОДУС ГОЛОС» — не шрифт, а контуры
// букв логотипа (web/a/modus-golos-wordmark.svg, tools/make_wordmark.py; решение владельца 13.11): та же высота картинки — буквы один в один.
function brandLock(href, title, cls) {
  return h('a', { href, class: 'brand-lock' + (cls ? ' ' + cls : ''), title: title || 'Модус Голос' },
    h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' }), h('span', { class: 'div', 'aria-hidden': 'true' }),
    h('img', { src: '/a/modus-golos-wordmark.svg', alt: 'Модус Голос', class: 'wordmark' }));
}

// Шапка публичных страниц (стартовая, «Результаты обращений», /design): фирменный блок слева; справа — одна кнопка «Войти»
// (вход через Битрикс24 — на странице входа; замечание владельца 12.11).
function siteHeader(me, cfg, opts) {
  opts = opts || {};
  const right = me
    ? h('div', { class: 'row' }, h('span', { class: 'small muted' }, me.name.split(' ')[0]), h('a', { href: me.role === 'employee' ? '/app' : '/panel', class: 'btn btn-sm' }, me.role === 'employee' ? 'Приложение' : 'Панель'))
    : h('a', { href: '/login' + (opts.next ? '?next=' + encodeURIComponent(opts.next) : ''), class: 'btn btn-outline' }, iconText('user', 'Войти'));
  return h('header', { class: 'site-head' },
    brandLock('/', 'Модус Голос — на главную'), h('div', { class: 'spacer' }), right);
}


// ---------- стилизованные элементы вместо нативных (правило: выбор файла, списки, галочки — только компоненты из /design) ----------

// Прикрепить фото или файл: кнопка со скрепкой, выбранный файл — чипом с крестиком, превью для фото. На телефоне система сама
// предложит «Камера / Галерея / Файл» (accept image/*,application/pdf). picker.file() — выбранный File или null.
function filePicker(opts) {
  opts = opts || {};
  const input = h('input', { type: 'file', class: 'visually-hidden', accept: opts.accept || 'image/*,application/pdf', tabindex: '-1' });
  const btn = h('button', { type: 'button', class: 'btn btn-sm', onclick: () => input.click() }, iconText('paperclip', opts.label || 'Прикрепить фото или файл'));
  const chip = h('div', { class: 'file-chip hidden' });
  const box = h('div', { class: 'filepick' }, btn, input, chip);
  let url = null;
  const render = () => {
    const f = input.files && input.files[0];
    if (url) { URL.revokeObjectURL(url); url = null; }
    if (!f) { chip.classList.add('hidden'); chip.replaceChildren(); btn.classList.remove('hidden'); return; }
    const isImg = (f.type || '').startsWith('image/');
    if (isImg) url = URL.createObjectURL(f);
    chip.replaceChildren(isImg ? h('img', { src: url, alt: '', class: 'file-preview' }) : icon('file-text', { size: 16 }),
      h('span', { class: 'file-name' }, f.name), h('span', { class: 'small muted' }, Math.max(1, Math.round(f.size / 1024)) + ' КБ'),
      h('button', { type: 'button', class: 'btn btn-sm btn-ghost', title: 'Убрать файл', onclick: () => { input.value = ''; render(); } }, icon('x', { size: 14 })));
    chip.classList.remove('hidden'); btn.classList.add('hidden');
  };
  input.addEventListener('change', render);
  box.file = () => (input.files && input.files[0]) || null;
  box.reset = () => { input.value = ''; render(); };
  return box;
}

// Выпадающий список в стиле системы: кнопка с текущим значением и стрелкой, список — карточкой под ней. el.value — как у select.
function pick(opts) {
  opts = opts || {};
  const options = opts.options || [];
  let value = opts.value === undefined || opts.value === null ? '' : String(opts.value);
  const labelOf = v => { const o = options.find(x => String(x.value) === String(v)); return o ? o.label : (opts.placeholder || '—'); };
  const text = h('span', { class: 'pick-text' + (value ? '' : ' muted') }, labelOf(value));
  const btn = h('button', { type: 'button', class: 'pick', 'aria-haspopup': 'listbox', 'aria-expanded': 'false' }, text, icon('chevron-down', { size: 16, cls: 'pick-chev' }));
  const list = h('div', { class: 'menu pick-menu', role: 'listbox' });
  const wrap = h('div', { class: 'menu-wrap pickwrap' }, btn, list);
  const close = () => { wrap.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); };
  const render = () => {
    list.replaceChildren(...[opts.placeholder ? h('button', { type: 'button', class: value ? '' : 'cur', onclick: () => set('') }, opts.placeholder) : null]
      .concat(options.map(o => h('button', { type: 'button', class: String(o.value) === value ? 'cur' : '', onclick: () => set(o.value) }, o.label, o.hint ? h('span', { class: 'small muted' }, ' ' + o.hint) : null))).filter(Boolean));
  };
  const set = v => { value = v === undefined || v === null ? '' : String(v); text.textContent = labelOf(value); text.classList.toggle('muted', !value); close(); render(); wrap.dispatchEvent(new Event('change')); };
  btn.addEventListener('click', ev => { ev.stopPropagation(); const open = wrap.classList.contains('open'); document.querySelectorAll('.menu-wrap.open').forEach(m => m.classList.remove('open')); if (!open) { wrap.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); } else close(); });
  btn.addEventListener('keydown', ev => { if (ev.key === 'Escape') close(); });
  document.addEventListener('click', ev => { if (!wrap.contains(ev.target)) close(); });
  render();
  Object.defineProperty(wrap, 'value', { get: () => value, set: v => set(v) });
  return wrap;
}

// Поиск адресата «спасибо»: коллега по имени или отдел; выбранный — чипом с крестиком. el.value → {user_id, department_id} или null.
function personPicker(opts) {
  opts = opts || {};
  const input = h('input', { type: 'search', placeholder: opts.placeholder || 'Имя коллеги или отдел (необязательно)', autocomplete: 'off' });
  const list = h('div', { class: 'menu pick-menu' });
  const wrap = h('div', { class: 'menu-wrap pickwrap person' }, h('span', { class: 'pp-ic' }, icon('search', { size: 16 })), input, list);
  const chip = h('div', { class: 'file-chip hidden' });
  const box = h('div', { class: 'personpick' }, wrap, chip);
  let chosen = null, timer = null;
  const close = () => wrap.classList.remove('open');
  const choose = (c) => { chosen = c; input.value = ''; close(); chip.replaceChildren(icon(c.department_id ? 'building' : 'user', { size: 16 }), h('span', { class: 'file-name' }, c.label), c.hint ? h('span', { class: 'small muted' }, c.hint) : null,
    h('button', { type: 'button', class: 'btn btn-sm btn-ghost', title: 'Убрать', onclick: () => { chosen = null; chip.classList.add('hidden'); wrap.classList.remove('hidden'); input.focus(); } }, icon('x', { size: 14 })));
    chip.classList.remove('hidden'); wrap.classList.add('hidden'); box.dispatchEvent(new Event('change')); };
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    timer = setTimeout(async () => {
      let r;
      try { r = await opts.search(q); } catch (e) { r = { users: [], departments: [] }; }
      const items = (r.users || []).map(u => h('button', { type: 'button', onclick: () => choose({ user_id: u.id, label: u.name, hint: [u.position, u.department, u.city].filter(Boolean).join(' · ') }) }, h('b', {}, u.name), h('span', { class: 'small muted' }, ' ' + [u.position, u.department].filter(Boolean).join(' · '))))
        .concat((r.departments || []).map(d => h('button', { type: 'button', onclick: () => choose({ department_id: d.id, label: 'Отдел «' + d.name + '»' }) }, iconText('building', 'Отдел «' + d.name + '»'))));
      list.replaceChildren(...(items.length ? items : [h('div', { class: 'small muted pick-empty' }, 'Никого не нашли — проверьте имя')]));
      wrap.classList.add('open');
    }, 250);
  });
  input.addEventListener('keydown', ev => { if (ev.key === 'Escape') close(); });
  document.addEventListener('click', ev => { if (!wrap.contains(ev.target)) close(); });
  Object.defineProperty(box, 'value', { get: () => chosen });
  return box;
}


// ---------- словарь терминов (пункт 1 очереди 12.11): подсказки «?» и «Справка» из одного источника — GET /api/public/glossary ----------
let GLOSSARY = null, _glossaryP = null, _helpOpenedAt = 0;
function loadGlossary() {
  if (!_glossaryP) _glossaryP = API.get('/api/public/glossary').then(g => { GLOSSARY = g; return g; }).catch(() => { GLOSSARY = { sections: [], terms: {} }; return GLOSSARY; });
  return _glossaryP;
}
function term(key) { return GLOSSARY ? (GLOSSARY.terms[key] || null) : null; }
// Кнопка «?» рядом с метрикой, настройкой или непонятным полем: по нажатию — поповер с 1–2 фразами простым языком (position: fixed —
// не обрезается контейнерами с overflow и не выходит за правый край экрана). Текст — из словаря по ключу; ссылка «Подробнее в справке»,
// если у страницы есть «Справка» (window.HELP_HREF).
function helpBtn(key, opts) {
  opts = opts || {};
  const wrap = h('span', { class: 'help-wrap' });
  const btn = h('button', { type: 'button', class: 'help-btn', title: 'Что это значит', 'aria-label': 'Что это значит', 'data-term': key }, icon('help-circle', { size: opts.size || 15 }));
  const pop = h('div', { class: 'help-pop', role: 'tooltip' });
  wrap.append(btn, pop);
  btn.addEventListener('click', async ev => {
    ev.preventDefault(); ev.stopPropagation();
    const open = wrap.classList.contains('open');
    closeHelp();
    if (open) return;
    await loadGlossary();
    const t = term(key);
    pop.replaceChildren(...[h('b', {}, t ? t.label : key), h('div', {}, t ? t.hint : 'Пояснения пока нет.'),
      window.HELP_HREF ? h('a', { href: window.HELP_HREF + '?t=' + encodeURIComponent(key), class: 'small' }, 'Подробнее в справке') : null].filter(Boolean));
    wrap.classList.add('open'); _helpOpenedAt = Date.now();
    const r = btn.getBoundingClientRect();
    const w = Math.min(300, window.innerWidth - 16);
    pop.style.width = w + 'px';
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
    pop.style.top = (r.bottom + 6) + 'px';
    const pr = pop.getBoundingClientRect();
    if (pr.bottom > window.innerHeight - 8) pop.style.top = Math.max(8, r.top - pr.height - 6) + 'px';
  });
  return wrap;
}
function closeHelp() { document.querySelectorAll('.help-wrap.open').forEach(w => w.classList.remove('open')); }
document.addEventListener('click', ev => { if (!ev.target.closest('.help-wrap')) closeHelp(); });
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') closeHelp(); });
window.addEventListener('scroll', () => { if (Date.now() - _helpOpenedAt > 400) closeHelp(); }, true);   // прокрутка закрывает поповер (он fixed); сразу после открытия — не считается

// ---------- ряд вкладок: если не влезает — затухание у правого края, пока не долистали (замечание владельца 12.11) ----------
function watchTabs(el) {
  if (el.dataset.watched) return;
  el.dataset.watched = '1';
  const upd = () => el.classList.toggle('more-right', el.scrollWidth - el.clientWidth - el.scrollLeft > 2);
  el.addEventListener('scroll', upd, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(upd).observe(el);
  requestAnimationFrame(upd);
}
new MutationObserver(() => document.querySelectorAll('.tabs:not([data-watched])').forEach(watchTabs)).observe(document.documentElement, { childList: true, subtree: true });

// ---------- меню «…» (этап 9, правило 3: одна главная кнопка, остальное в меню) — общее для панели, приложения и совещаний ----------
function closeMenus() { document.querySelectorAll('.menu-wrap.open').forEach(m => m.classList.remove('open')); }
document.addEventListener('click', ev => { if (!ev.target.closest('.menu-wrap')) closeMenus(); });
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') closeMenus(); });
function menuButton(items, opts) {
  opts = opts || {};
  const wrap = h('div', { class: 'menu-wrap' });
  const btn = h('button', { type: 'button', class: 'btn btn-sm' + (opts.ghost === false ? '' : ' btn-ghost'), title: opts.title || 'Ещё действия', 'aria-label': opts.title || 'Ещё действия',
    onclick: ev => { ev.stopPropagation(); const open = wrap.classList.contains('open'); closeMenus(); if (!open) wrap.classList.add('open'); } }, icon('more'));
  wrap.append(btn, h('div', { class: 'menu' }, items.filter(Boolean).map(([label, fn]) => h('button', { type: 'button', onclick: ev => { ev.stopPropagation(); closeMenus(); fn(); } }, label))));
  return wrap;
}

// ---------- выбор даты без нативного календаря (пункт 4 очереди 12.11): список готовых сроков + «другая дата» дд.мм; el.value — ISO или '' ----------
function isoLocal(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
function fmtDay(iso) { if (!iso) return ''; const [, m, d] = iso.split('-'); return d + '.' + m; }
function datePick(opts) {
  opts = opts || {};
  const today = new Date(); today.setHours(12, 0, 0, 0);
  const plus = n => { const d = new Date(today); d.setDate(d.getDate() + n); return d; };
  const friday = plus(((5 - today.getDay()) % 7) || 7);
  const monthEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0, 12);
  const base = [[isoLocal(today), 'сегодня'], [isoLocal(plus(1)), 'завтра'], [isoLocal(friday), 'до пятницы · ' + fmtDay(isoLocal(friday))], [isoLocal(plus(7)), 'через неделю · ' + fmtDay(isoLocal(plus(7)))], [isoLocal(monthEnd), 'до конца месяца · ' + fmtDay(isoLocal(monthEnd))]];
  let value = opts.value || '';
  const options = base.map(([v, l]) => ({ value: v, label: l }));
  if (value && !options.some(o => o.value === value)) options.unshift({ value, label: fmtDay(value) + (value < isoLocal(today) ? ' · прошёл' : '') });
  options.push({ value: '__other', label: 'Другая дата…' });
  const p = pick({ placeholder: opts.placeholder || 'срок не назван', options, value });
  const other = h('input', { type: 'text', inputmode: 'numeric', placeholder: 'дд.мм', class: 'hidden date-other', 'aria-label': 'Дата в формате дд.мм' });
  const box = h('div', { class: 'datepick' }, p, other);
  const emit = () => box.dispatchEvent(new Event('change'));
  p.addEventListener('change', () => {
    if (p.value === '__other') { other.classList.remove('hidden'); other.focus(); return; }
    other.classList.add('hidden'); value = p.value; emit();
  });
  other.addEventListener('change', () => {
    const m = other.value.trim().match(/^(\d{1,2})[.\/-](\d{1,2})(?:[.\/-](\d{2,4}))?$/);
    if (!m) { toast('Дата — в формате дд.мм', 'bad'); return; }
    let y = m[3] ? Number(m[3]) : today.getFullYear(); if (y < 100) y += 2000;
    const d = new Date(y, Number(m[2]) - 1, Number(m[1]), 12);
    if (isNaN(d) || d.getMonth() !== Number(m[2]) - 1) { toast('Такой даты нет', 'bad'); return; }
    if (!m[3] && d < today) d.setFullYear(d.getFullYear() + 1);   // «05.01» зимой — следующий год
    value = isoLocal(d); other.classList.add('hidden'); emit();
  });
  Object.defineProperty(box, 'value', { get: () => value, set: v => { value = v || ''; p.value = value; } });
  return box;
}
