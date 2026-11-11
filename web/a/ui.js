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
function tag(cls, text) { return h('span', { class: 'badge ' + cls }, text); }

function tracker(status) {
  const steps = [['new', 'Новое'], ['review', 'Рассмотрение'], ['in_progress', 'В работе'], ['done', 'Реализовано'], ['closed', 'Закрыто']];
  let cur = status === 'clarify' ? 'review' : status;
  let idx = steps.findIndex(s => s[0] === cur);
  if (status === 'rejected') idx = 4;
  const el = h('div', { class: 'tracker ' + (status === 'rejected' ? 'rejected' : status === 'clarify' ? 'clarify' : '') });
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
    case 'escalated': return 'Просрочено: нет первого ответа при SLA ' + p.sla_hours + ' ч — уведомлён руководитель';
    case 'discussed_at_meeting': return 'Обсуждено на совещании' + (p.meeting_title ? ' «' + p.meeting_title + '»' : '') + (p.text ? ': ' + p.text : '');
    case 'director_requested': return 'Вынесено на решение директора' + (p.text ? ': ' + p.text : '');
    case 'director_decided': return 'Директор ' + (p.decision === 'accepted' ? 'принял' : 'отклонил') + ' предложение' + (p.text ? ': ' + p.text : '');
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

let _toastTimer = null;
function toast(msg, kind) {
  let t = document.getElementById('toast');
  if (!t) { t = h('div', { id: 'toast', class: 'toast' }); document.body.append(t); }
  t.textContent = msg;
  t.className = 'toast show' + (kind === 'bad' ? ' bad' : '');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { t.className = 'toast'; }, 3500);
}
function qs(name) { return new URLSearchParams(location.search).get(name); }
function field(label, input, hint) { return h('label', { class: 'field' }, h('span', {}, label), input, hint ? h('div', { class: 'hint' }, hint) : null); }

// Голосовой ввод (этап 3): кнопка-микрофон → MediaRecorder → /api/stt (или /api/public/stt без входа) → текст в поле.
const Voice = {
  pick() { return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', ''].find(m => !m || (window.MediaRecorder && MediaRecorder.isTypeSupported(m))); },
  supported() { return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder); },
  attach(btn, textarea, opts) {
    opts = opts || {};
    let rec = null, chunks = [], stream = null, timer = null, t0 = 0;
    const idle = () => { btn.textContent = '🎤'; btn.classList.remove('recording'); btn.disabled = false; btn.title = 'Голосовой ввод: нажмите и говорите, нажмите ещё раз — стоп'; };
    if (!this.supported()) { btn.disabled = true; btn.title = 'Голосовой ввод доступен по HTTPS (адрес туннеля) или на localhost'; return; }
    idle();
    btn.addEventListener('click', async () => {
      if (rec && rec.state === 'recording') { clearInterval(timer); rec.stop(); btn.disabled = true; btn.textContent = '…'; return; }
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
      timer = setInterval(() => { const s = Math.round((Date.now() - t0) / 1000); btn.textContent = '■ ' + s; }, 500);
      btn.textContent = '■ 0';
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
      opts.canSupport ? h('button', { class: 'btn btn-sm', onclick: async ev => { ev.preventDefault(); try { await API.post('/api/appeals/' + i.id + '/support'); toast('«У меня так же» учтено — автору ' + i.number + ' начислены баллы'); if (opts.onSupported) opts.onSupported(i); } catch (e) { toast(e.message, 'bad'); } } }, '👍 У меня так же') : null),
    h('div', { class: 'small' }, i.text)));
  return h('div', { class: 'card card-warn' }, h('b', {}, 'Похоже, об этом уже сообщали'), h('div', { class: 'hint' }, note + '. Если это то же самое — отметьте «У меня так же» вместо нового обращения' + (opts.canSupport ? '' : ' (нужен вход)') + '.'),
    h('div', { class: 'list mt8' }, items),
    h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-outline', onclick: ev => { ev.preventDefault(); if (opts.onAnyway) opts.onAnyway(); } }, 'Всё равно отправить')));
}
