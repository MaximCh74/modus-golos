'use strict';
// Команды директора (этап 6 §2): кнопка «Команда» с микрофоном и поле для текста → /api/director/command/parse (разбор + план) →
// экран подтверждения всегда ([Отправить] / [Изменить] / [Отмена]) → /send → уведомления, события, короткий голосовой ответ.
// Общий код для /app и /panel: использует h, API, toast, icon, iconText, Voice, speakSummary из ui.js/icons.js.
function commandPanel(opts) {
  opts = opts || {};
  const box = h('div', { class: 'card command' });
  const ta = h('textarea', { class: 'cmd-text', rows: 1, placeholder: opts.compact ? 'Команда голосом или текстом: «запроси новости по обращениям в работе в Омске до 18:00»' : 'Например: «запроси новости по обращениям в работе в Омске до 18:00»' });
  const mic = h('button', { type: 'button', class: 'btn mic', title: 'Команда голосом' });
  const run = h('button', { type: 'button', class: 'btn btn-primary' }, iconText('send', 'Выполнить'));
  const result = h('div', { class: 'mt8' });
  let busy = false;
  Voice.attach(mic, ta, { onText: () => parse() });
  run.addEventListener('click', parse);
  ta.addEventListener('keydown', ev => { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); parse(); } });
  if (opts.compact) box.append(h('div', { class: 'row' }, h('div', { class: 'spacer' }, ta), mic, run, helpBtn('command')), result);
  else box.append(h('div', { class: 'row' }, h('div', { class: 'lbl' }, 'Команда'), helpBtn('command'), h('span', { class: 'hint' }, 'голосом или текстом: напоминания, новости по обращениям, «На решение», сводка')),
    h('div', { class: 'row mt8' }, h('div', { class: 'spacer' }, ta), mic, run), result);

  async function parse() {
    const text = ta.value.trim();
    if (!text || busy) return;
    busy = true; run.disabled = true;
    result.replaceChildren(h('div', { class: 'row small muted' }, h('span', { class: 'spin' }), 'Разбираю команду…'));
    try { render(await API.post('/api/director/command/parse', { text })); }
    catch (e) { result.replaceChildren(h('div', { class: 'card card-bad small' }, e.message)); }
    busy = false; run.disabled = false;
  }

  function cancel() { result.replaceChildren(); ta.value = ''; }
  function edit() { ta.focus(); ta.select(); result.replaceChildren(h('div', { class: 'hint' }, 'Исправьте команду и нажмите «Выполнить».')); }

  function render(r) {
    const p = r.plan, cmd = r.command;
    const engine = aiMark(cmd.engine === 'openai', 'разбор ИИ', 'по ключевым словам (без ИИ)');
    if (p.kind === 'unknown') {
      result.replaceChildren(h('div', { class: 'card card-warn' }, h('div', { class: 'row' }, h('b', {}, p.title), engine),
        h('ul', { class: 'small mt8' }, p.help.map(x => h('li', {}, x))),
        h('div', { class: 'chips mt8' }, p.examples.map(x => h('button', { type: 'button', class: 'chip', onclick: () => { ta.value = x; parse(); } }, x))),
        h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm', onclick: cancel }, 'Отмена'))));
      return;
    }
    if (p.kind === 'open') {
      const go = async () => { try { const s = await API.post('/api/director/command/' + r.plan_id + '/send', {}); location.hash = opts.decisionsHref || s.href; } catch (e) { toast(e.message, 'bad'); } };
      result.replaceChildren(h('div', { class: 'card card-info' }, h('div', { class: 'row' }, h('b', {}, p.title), engine),
        p.item ? h('div', { class: 'small mt8' }, (p.item.number ? p.item.number + ' · ' : 'идея с совещания · ') + (p.item.wait_days !== null && p.item.wait_days !== undefined ? 'ждёт решения ' + Math.floor(p.item.wait_days) + ' дн' : '')) : null,
        h('div', { class: 'hint mt8' }, 'Принять или отклонить — только кнопкой на экране «На решение». На решении сейчас: ' + p.pending + '.'),
        h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm btn-primary', onclick: go }, iconText('arrow-right', 'Открыть')), h('button', { class: 'btn btn-sm', onclick: edit }, 'Изменить'), h('button', { class: 'btn btn-sm', onclick: cancel }, 'Отмена'))));
      return;
    }
    if (p.kind === 'briefing') {
      const speak = h('button', { class: 'btn btn-sm btn-primary' }, iconText('volume', 'Прочитать'));
      speak.addEventListener('click', async () => { try { await API.post('/api/director/command/' + r.plan_id + '/send', {}); } catch (e) { /* уже отправлено */ } speakSummary(speak, p.sentences); });
      result.replaceChildren(h('div', { class: 'card card-info' }, h('div', { class: 'row' }, h('b', {}, p.title), aiMark(p.engine === 'openai', 'пересказ ИИ по фактам', 'шаблон без ИИ')),
        p.sentences.map(s => h('p', { class: 'small' }, s.text)),
        h('div', { class: 'row mt8' }, speak, h('button', { class: 'btn btn-sm', onclick: cancel }, 'Отмена'))));
      return;
    }
    if (p.empty) {   // отправлять некому — ответ словами, без карточки команды и неактивной «Отправить» (замечание владельца 12.11)
      result.replaceChildren(h('div', { class: 'card card-info' }, h('div', { class: 'row' }, h('b', {}, p.title), engine),
        h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm', onclick: cancel }, 'Понятно'))));
      return;
    }
    // kind === 'send': список «кто — что», текст сообщения (можно поправить), кнопки
    const edits = {};
    const rows = p.recipients.map(rec => {
      const msg = h('textarea', { class: 'cmd-msg', rows: 2 });
      msg.value = rec.message;
      msg.addEventListener('input', () => { edits[rec.user_id] = msg.value; });
      return h('div', { class: 'cmd-rec' },
        h('div', { class: 'row' }, h('b', {}, rec.name), h('span', { class: 'small muted' }, [rec.position, rec.branch].filter(Boolean).join(' · ')), h('div', { class: 'spacer' }),
          h('span', { class: 'small muted' }, rec.items.length === 1 ? (rec.items[0].number || 'поручение') : plural(rec.items.length, rec.items[0].kind === 'task' ? 'поручение' : 'обращение', rec.items[0].kind === 'task' ? 'поручения' : 'обращения', rec.items[0].kind === 'task' ? 'поручений' : 'обращений'))),
        h('div', { class: 'small' }, rec.items.map(i => h('div', { class: 'muted' }, (i.number ? i.number + ' — ' : '') + i.title + (i.kind === 'task' ? ' (срок был ' + i.due_label + ')' : i.news_days !== undefined && i.news_days !== null ? ' · без новостей ' + i.news_days + ' дн' : i.overdue ? ' · срок первого ответа прошёл' : '')))),
        msg);
    });
    const send = h('button', { class: 'btn btn-sm btn-primary', disabled: p.empty }, iconText('send', 'Отправить'));
    send.addEventListener('click', async () => {
      send.disabled = true;
      try {
        const s = await API.post('/api/director/command/' + r.plan_id + '/send', { messages: edits });
        result.replaceChildren(h('div', { class: 'card card-ok' }, h('div', { class: 'row' }, h('b', {}, s.reply), h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, 'уведомления на сайте' + (opts.bitrix ? ' и в Битрикс24' : '') + ', событие в истории обращений')),
          h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm', onclick: cancel }, 'Готово'))));
        ta.value = '';
        speakReply(r.plan_id, s.reply);
        if (opts.onSent) opts.onSent(s);
      } catch (e) { toast(e.message, 'bad'); send.disabled = false; }
    });
    const scope = [p.scope && p.scope !== 'все' ? 'фильтр: ' + p.scope : 'все', p.deadline && p.deadline.label ? 'срок: ' + p.deadline.label : null].filter(Boolean).join(' · ');
    result.replaceChildren(h('div', { class: 'card ' + (p.empty ? 'card-warn' : 'card-info') }, h('div', { class: 'row' }, h('b', {}, p.title), engine, h('div', { class: 'spacer' }), h('span', { class: 'small muted' }, scope)),
      p.empty ? null : h('div', { class: 'hint mt8' }, 'Проверьте список и текст — отправится только после нажатия «Отправить». Текст можно поправить прямо здесь.'),
      rows,
      h('div', { class: 'row mt8' }, send, h('button', { class: 'btn btn-sm', onclick: edit }, 'Изменить'), h('button', { class: 'btn btn-sm', onclick: cancel }, 'Отмена'))));
  }
  return box;
}

// Голосовой ответ: OpenAI TTS с кэшем; без ключа — голос браузера, если есть русский; иначе молча (текст уже на экране).
async function speakReply(planId, text) {
  try {
    const r = await fetch('/api/director/command/' + planId + '/audio', { credentials: 'same-origin' });
    if (!r.ok) throw new Error('tts ' + r.status);
    const a = new Audio(URL.createObjectURL(await r.blob()));
    await a.play();
  } catch (e) {
    const ru = window.speechSynthesis && speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith('ru'));
    if (ru) { const u = new SpeechSynthesisUtterance(text); u.lang = 'ru-RU'; u.voice = ru; u.rate = 1.1; speechSynthesis.cancel(); speechSynthesis.speak(u); }
  }
}
