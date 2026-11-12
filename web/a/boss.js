'use strict';
// «Директор в кармане» (пункт 2 очереди 12.11): отдельная PWA только для директора. Один экран без прокрутки на телефоне:
// приветствие по имени-отчеству (ИИ, числа сверены), «Сегодня / Неделя», четыре цифры (нажатие — короткий список, у решений
// «Принять / Отклонить»), большая кнопка микрофона «Спросить» и поле текста, ссылка «Подробнее на сайте».
// Вопрос → /api/boss/ask: факты считает сервер, ИИ только пересказывает; команда → план → подтверждение → /api/director/command/{id}/send.
(async function () {
  const root = document.getElementById('root');
  const S = { period: 'week', home: null, sheet: null };
  try { S.period = localStorage.getItem('mf.boss.period') || 'week'; } catch (e) { /* без хранилища */ }
  const ME = await API.me();
  if (!ME) { location.href = '/login?next=' + encodeURIComponent('/boss'); return; }
  if (ME.role !== 'director') {
    root.replaceChildren(h('div', { class: 'boss-gate' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд', class: 'boss-logo' }),
      h('div', { class: 'card card-warn' }, h('b', {}, 'Только для директора. '), 'Вы вошли как ', h('b', {}, ME.name), ' (' + ME.role_label.toLowerCase() + ').'),
      h('div', { class: 'row' }, h('a', { href: '/login?next=' + encodeURIComponent('/boss'), class: 'btn btn-primary' }, iconText('log-in', 'Войти как директор')),
        h('a', { href: ME.role === 'employee' ? '/app' : '/panel', class: 'btn btn-outline' }, ME.role === 'employee' ? 'В приложение' : 'В панель'))));
    return;
  }
  loadGlossary();

  // ---------- каркас экрана ----------
  const greetText = h('div', { class: 'boss-greet-text' }, 'Загружаем…');
  const greetMark = h('span', { class: 'boss-greet-mark' });
  const speakGreet = h('button', { type: 'button', class: 'btn btn-sm btn-ghost boss-speak', title: 'Озвучить приветствие', 'aria-label': 'Озвучить' }, icon('volume', { size: 18 }));
  const seg = h('div', { class: 'seg', role: 'tablist' },
    ['today', 'week'].map(p => h('button', { type: 'button', role: 'tab', class: 'seg-btn' + (S.period === p ? ' on' : ''), 'data-period': p, onclick: () => setPeriod(p) }, p === 'today' ? 'Сегодня' : 'Неделя')));
  const TILES = [['new', 'пришло'], ['done', 'решено'], ['decisions', 'ждут вашего решения'], ['overdue', 'просрочено']];
  const tiles = {};
  const tilesEl = h('div', { class: 'boss-tiles' }, TILES.map(([k, label]) => { const b = h('b', {}, '…'); tiles[k] = b; return h('button', { type: 'button', class: 'boss-tile tile-' + k, 'data-tile': k, onclick: () => openList(k) }, b, h('span', {}, label)); }));
  const ta = h('textarea', { class: 'boss-ask-text', rows: 1, placeholder: 'Что нового? Кто просрочил? Что по Омску?', 'aria-label': 'Вопрос' });
  const mic = h('button', { type: 'button', class: 'btn mic boss-mic', title: 'Спросить голосом', 'aria-label': 'Спросить голосом' });
  const send = h('button', { type: 'button', class: 'btn btn-primary boss-send', title: 'Спросить', 'aria-label': 'Спросить' }, icon('send', { size: 20 }));
  Voice.attach(mic, ta, { onText: () => ask() });
  send.addEventListener('click', ask);
  ta.addEventListener('keydown', ev => { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); ask(); } });
  const askBox = h('div', { class: 'boss-ask' }, h('div', { class: 'boss-ask-row' }, ta, send), h('div', { class: 'boss-mic-row' }, mic, h('span', { class: 'boss-mic-label' }, 'Спросить')));
  const screen = h('main', { class: 'boss' },
    h('header', { class: 'boss-head' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' }), h('span', { class: 'boss-title' }, 'Директор в кармане'), h('div', { class: 'spacer' }),
      h('a', { href: '/panel#/summary', class: 'btn btn-sm btn-ghost', title: 'Панель на сайте', 'aria-label': 'Панель на сайте' }, icon('external-link', { size: 18 })),
      h('a', { href: '/login?next=' + encodeURIComponent('/boss'), class: 'btn btn-sm btn-ghost', title: 'Сменить пользователя', 'aria-label': 'Сменить пользователя' }, icon('log-out', { size: 18 }))),
    h('section', { class: 'card boss-greet' }, h('div', { class: 'boss-greet-row' }, h('span', { class: 'boss-name' }, ME.name), greetMark, h('div', { class: 'spacer' }), speakGreet), greetText),
    seg, tilesEl, askBox,
    h('footer', { class: 'boss-foot' }, h('a', { href: '/panel#/summary' }, iconText('external-link', 'Подробнее на сайте')), h('span', { class: 'muted' }, 'голосом или текстом · только директору')));
  root.replaceChildren(screen);

  // ---------- данные ----------
  let loadSeq = 0;   // быстрые переключения «Сегодня / Неделя»: поздний ответ не перекрывает свежий
  async function load() {
    const seq = ++loadSeq;
    let home;
    try {
      home = await API.get('/api/boss/home?period=' + S.period);
    } catch (e) { toast(e.message, 'bad'); return; }
    if (seq !== loadSeq) return;
    S.home = home;
    for (const [k] of TILES) { tiles[k].textContent = String(S.home.tiles[k]); tiles[k].parentElement.classList.toggle('zero', !S.home.tiles[k]); }
    greetText.textContent = S.home.greeting.text;
    greetMark.replaceChildren(aiMark(S.home.greeting.engine === 'openai', 'приветствие ИИ, числа сверены с сервером', 'шаблон без ИИ'));
  }
  function setPeriod(p) {
    S.period = p;
    try { localStorage.setItem('mf.boss.period', p); } catch (e) { /* нет хранилища */ }
    for (const b of seg.children) b.classList.toggle('on', b.dataset.period === p);
    load();
  }
  speakGreet.addEventListener('click', () => speakText(speakGreet, '/api/panel/director-summary/audio', S.home ? S.home.greeting.text : ''));
  await load();
  API.sse(ev => { if (['appeal_created', 'appeal_updated', 'escalated', 'idea_pending', 'tasks_overdue', 'meeting_sent'].includes(ev.type)) load(); });

  // ---------- нижний лист: списки за цифрами, ответ на вопрос, подтверждение команды ----------
  function closeSheet() { if (S.sheet) { S.sheet.back.remove(); S.sheet.el.remove(); S.sheet = null; } }
  function sheet(title, content, opts) {
    closeSheet();
    opts = opts || {};
    const back = h('div', { class: 'sheet-back', onclick: closeSheet });
    const el = h('div', { class: 'sheet boss-sheet', role: 'dialog', 'aria-label': title },
      h('div', { class: 'grip' }), h('button', { type: 'button', class: 'btn btn-ghost btn-sm close', onclick: closeSheet, 'aria-label': 'Закрыть' }, icon('x')),
      h('div', { class: 'row' }, h('div', { class: 'h2 boss-sheet-title' }, title), opts.mark || null), content);
    document.body.append(back, el);
    S.sheet = { back, el };
    return el;
  }
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape') closeSheet(); });

  const TITLES = { new: 'Пришло', done: 'Решено', decisions: 'Ждут вашего решения', overdue: 'Просрочено' };
  function openList(k) {
    const items = (S.home && S.home.lists[k]) || [];
    const link = h('a', { href: S.home.links[k], class: 'btn btn-outline btn-sm' }, iconText('external-link', 'Подробнее на сайте'));
    let body;
    if (!items.length) body = h('div', { class: 'card muted' }, k === 'overdue' ? 'Просрочек нет.' : k === 'decisions' ? 'Вашего решения ничего не ждёт.' : 'Пока пусто.');
    else if (k === 'decisions') body = h('div', { class: 'boss-list' }, items.map(decisionRow));
    else body = h('div', { class: 'boss-list' }, items.map(i => h('a', { class: 'boss-item', href: i.kind === 'task' ? '/panel#/meetings/' + i.meeting_id : '/panel#/appeal/' + i.id },
      h('div', { class: 'row' }, i.kind === 'task' ? h('b', {}, 'Поручение') : h('b', {}, i.number), i.kind === 'task' ? h('span', { class: 'small muted' }, 'срок был ' + i.due_label + ' · ' + (i.assignee || 'без исполнителя')) : h('span', { class: 'small muted' }, [i.status, i.branch].filter(Boolean).join(' · ')),
        h('div', { class: 'spacer' }), i.overdue ? h('span', { class: 'dot-overdue', title: 'просрочено' }) : null, i.age_days !== undefined && i.kind !== 'task' ? h('span', { class: 'small muted' }, i.age_days + ' дн') : null),
      h('div', { class: 'small' }, i.text), i.resolution ? h('div', { class: 'small card-ok boss-res' }, i.resolution) : null, i.responsible && k !== 'done' ? h('div', { class: 'small muted' }, 'отвечает ' + i.responsible) : null)));
    sheet(TITLES[k] + (k === 'new' || k === 'done' ? ' · ' + S.home.period_label : ''), h('div', {}, body, h('div', { class: 'row mt8' }, link)));   // решения и просрочки — не за период, а сейчас
  }

  function decisionRow(i) {
    const comment = h('textarea', { class: 'hidden boss-reason', rows: 2, placeholder: 'Комментарий (необязательно)' });
    const reason = h('textarea', { class: 'hidden boss-reason', rows: 2, placeholder: 'Причина отклонения — её увидят автор и ответственный (обязательно)' });
    const row = h('div', { class: 'boss-item' + (i.over_threshold ? ' late' : '') });
    const done = (msg) => { toast(msg); row.classList.add('done'); row.replaceChildren(h('div', { class: 'small muted' }, msg)); load(); };
    const act = async (fn, msg) => { try { await fn(); done(msg); } catch (e) { toast(e.message, 'bad'); } };
    const accept = h('button', { type: 'button', class: 'btn btn-sm btn-primary', onclick: () => {
      if (comment.classList.contains('hidden') && i.source === 'appeal') { comment.classList.remove('hidden'); accept.replaceChildren('Подтвердить'); return; }
      if (i.source === 'appeal') act(() => API.post('/api/director/appeals/' + i.appeal_id + '/decide', { decision: 'accepted', comment: comment.value }), 'Принято — ответственный и автор уведомлены');
      else {
        if (!i.category_id) { toast('У идеи нет категории — выберите её в «На решение» на сайте', 'bad'); return; }
        act(() => API.post('/api/director/ideas/' + i.id + '/accept', {}), 'Принято — идея ушла ответственному');
      }
    } }, 'Принять');
    const reject = h('button', { type: 'button', class: 'btn btn-sm', onclick: () => {
      if (reason.classList.contains('hidden')) { reason.classList.remove('hidden'); reason.focus(); reject.replaceChildren('Подтвердить отклонение'); return; }
      if (!reason.value.trim()) { toast('Нужна причина', 'bad'); return; }
      if (i.source === 'appeal') act(() => API.post('/api/director/appeals/' + i.appeal_id + '/decide', { decision: 'rejected', comment: reason.value }), 'Отклонено');
      else act(() => API.post('/api/director/ideas/' + i.id + '/reject', { reason: reason.value }), 'Отклонено');
    } }, 'Отклонить');
    row.append(h('div', { class: 'row' }, i.number ? h('b', {}, i.number) : h('b', {}, 'Идея с совещания'), h('span', { class: 'small muted' }, [i.category, i.branch || i.meeting_title].filter(Boolean).join(' · ')), h('div', { class: 'spacer' }),
      h('span', { class: 'small ' + (i.over_threshold ? 'boss-late' : 'muted') }, 'ждёт ' + i.wait_days + ' дн')),
      h('div', { class: 'small' }, i.text), i.request ? h('div', { class: 'small muted' }, 'Что требуется: ' + i.request) : null, comment, reason,
      h('div', { class: 'row mt8' }, accept, reject));
    return row;
  }

  // ---------- спросить ----------
  let busy = false;
  async function ask() {
    const text = ta.value.trim();
    if (!text || busy) return;
    busy = true; send.disabled = true;
    const wait = sheet('Думаю…', h('div', { class: 'row small muted' }, h('span', { class: 'spin' }), 'Считаю факты и собираю ответ'));
    try {
      const r = await API.post('/api/boss/ask', { text, period: S.period });
      render(text, r);
      ta.value = '';
    } catch (e) { wait.remove(); toast(e.message, 'bad'); }
    busy = false; send.disabled = false;
  }

  function render(text, r) {
    const q = h('div', { class: 'small muted boss-q' }, iconText('message-circle', text));
    if (r.kind === 'question') {
      const speak = h('button', { type: 'button', class: 'btn btn-sm', title: 'Озвучить ответ' }, iconText('volume', 'Озвучить'));
      speak.addEventListener('click', () => speakText(speak, r.audio ? '/api/boss/answer/' + r.id + '/audio' : null, r.answer));
      sheet(r.question_label[0].toUpperCase() + r.question_label.slice(1), h('div', {}, q, h('p', { class: 'boss-answer' }, r.answer),
        h('div', { class: 'row mt8' }, speak, r.link ? h('a', { href: r.link, class: 'btn btn-outline btn-sm' }, iconText('external-link', r.link_label || 'Подробнее на сайте')) : null)),
        { mark: aiMark(r.engine === 'openai', 'пересказ ИИ по фактам сервера, числа сверены', 'шаблон без ИИ — те же факты') });
      if (r.audio) speakText(null, '/api/boss/answer/' + r.id + '/audio', r.answer);
      return;
    }
    if (r.kind === 'unknown') {
      sheet('Не знаю, вот где посмотреть', h('div', {}, q, h('p', { class: 'boss-answer' }, 'Могу ответить на вопросы о системе и выполнить команды с подтверждением. Например:'),
        h('div', { class: 'chips' }, r.can.map(x => h('button', { type: 'button', class: 'chip', onclick: () => { closeSheet(); ta.value = x; ask(); } }, x))),
        h('div', { class: 'boss-links mt8' }, r.links.map(l => h('a', { href: l.href, class: 'btn btn-outline btn-sm' }, iconText('external-link', l.label))))));
      return;
    }
    // команда: существующий план с обязательным подтверждением
    const p = r.plan;
    if (p.kind === 'unknown') { render(text, { kind: 'unknown', can: p.examples, links: [{ href: '/panel#/summary', label: 'Сводка' }] }); return; }
    if (p.kind === 'briefing') {
      const speak = h('button', { type: 'button', class: 'btn btn-sm btn-primary' }, iconText('volume', 'Прочитать'));
      speak.addEventListener('click', async () => { try { await API.post('/api/director/command/' + r.plan_id + '/send', {}); } catch (e) { /* уже отправлено */ } speakText(speak, '/api/panel/director-summary/audio', p.sentences.map(s => s.text).join(' ')); });
      sheet('Сводка', h('div', {}, q, p.sentences.map(s => h('p', { class: 'boss-answer small' }, s.text)), h('div', { class: 'row mt8' }, speak)), { mark: aiMark(p.engine === 'openai', 'пересказ ИИ по фактам', 'шаблон без ИИ') });
      return;
    }
    if (p.kind === 'open') {
      sheet('На решение', h('div', {}, q, h('p', { class: 'boss-answer' }, p.title), h('div', { class: 'row mt8' }, h('button', { type: 'button', class: 'btn btn-primary btn-sm', onclick: async () => { try { await API.post('/api/director/command/' + r.plan_id + '/send', {}); } catch (e) { /* уже */ } closeSheet(); openList('decisions'); } }, 'Открыть'), h('button', { type: 'button', class: 'btn btn-sm', onclick: closeSheet }, 'Отмена'))));
      return;
    }
    const sendBtn = h('button', { type: 'button', class: 'btn btn-primary btn-sm', disabled: p.empty }, iconText('send', 'Отправить'));
    sendBtn.addEventListener('click', async () => {
      sendBtn.disabled = true;
      try { const s = await API.post('/api/director/command/' + r.plan_id + '/send', {}); sheet('Отправлено', h('div', {}, h('p', { class: 'boss-answer' }, s.reply), h('div', { class: 'row mt8' }, h('button', { type: 'button', class: 'btn btn-sm', onclick: closeSheet }, 'Готово')))); speakText(null, '/api/director/command/' + r.plan_id + '/audio', s.reply); load(); }
      catch (e) { toast(e.message, 'bad'); sendBtn.disabled = false; }
    });
    sheet(p.empty ? 'Некому отправлять' : 'Подтвердите команду', h('div', {}, q, h('p', { class: 'boss-answer' }, p.title),
      p.empty ? null : h('div', { class: 'hint' }, 'Отправится только после «Отправить». Получателей посчитал сервер.'),
      h('div', { class: 'boss-list' }, (p.recipients || []).map(rec => h('div', { class: 'boss-item' }, h('div', { class: 'row' }, h('b', {}, rec.name), h('span', { class: 'small muted' }, [rec.position, rec.branch].filter(Boolean).join(' · '))), h('div', { class: 'small muted' }, rec.message)))),
      h('div', { class: 'row mt8' }, sendBtn, h('button', { type: 'button', class: 'btn btn-sm', onclick: closeSheet }, 'Отмена'))),
      { mark: aiMark(r.command.engine === 'openai', 'разбор ИИ', 'по ключевым словам (без ИИ)') });
  }

  // ---------- озвучка: нейтральный голос OpenAI с кэшем; без ключа — голос браузера, если есть русский; иначе молча ----------
  let audio = null;
  async function speakText(btn, url, text) {
    if (audio && !audio.paused) { audio.pause(); audio = null; if (btn) btn.replaceChildren(iconText('volume', 'Озвучить')); return; }
    try {
      if (!url) throw new Error('нет озвучки');
      const r = await fetch(url, { credentials: 'same-origin' });
      if (!r.ok) throw new Error('tts ' + r.status);
      audio = new Audio(URL.createObjectURL(await r.blob()));
      audio.onended = () => { if (btn) btn.replaceChildren(iconText('volume', 'Озвучить')); };
      await audio.play();
      if (btn) btn.replaceChildren(iconText('square', 'Стоп'));
    } catch (e) {
      const ru = window.speechSynthesis && speechSynthesis.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith('ru'));
      if (ru && text) { const u = new SpeechSynthesisUtterance(text); u.lang = 'ru-RU'; u.voice = ru; speechSynthesis.cancel(); speechSynthesis.speak(u); }
    }
  }
})();
