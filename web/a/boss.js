'use strict';
// «Директор в кармане» (пункт 2 очереди 12.11): отдельная PWA только для директора. Один экран без прокрутки на телефоне:
// приветствие по имени-отчеству (ИИ, числа сверены), «Сегодня / Неделя», четыре цифры (нажатие — короткий список, у решений
// «Принять / Отклонить»), большая кнопка микрофона «Спросить» и поле текста, ссылка «Подробнее на сайте».
// Вопрос → /api/boss/ask: факты считает сервер, ИИ только пересказывает; команда → план → подтверждение → /api/director/command/{id}/send.
(async function () {
  const root = document.getElementById('root');
  const S = { period: 'week', home: null, sheet: null };
  try { const saved = localStorage.getItem('mf.boss.period'); S.period = ['week', 'month'].includes(saved) ? saved : 'week'; } catch (e) { /* без хранилища */ }   // «Неделя / Месяц» (13.11)
  const ME = await API.me();
  if (!ME) { location.href = '/login?next=' + encodeURIComponent('/boss'); return; }
  if (ME.role !== 'director') {
    root.replaceChildren(h('div', { class: 'boss-gate' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд', class: 'boss-logo' }),
      h('div', { class: 'card card-warn' }, h('b', {}, 'Только для директора. '), 'Вы вошли как ', h('b', {}, ME.name), ' (' + ME.role_label.toLowerCase() + ').'),
      h('div', { class: 'row' }, h('a', { href: '/login?next=' + encodeURIComponent('/boss'), class: 'btn btn-primary' }, 'Войти как директор'),
        h('a', { href: ME.role === 'employee' ? '/app' : '/panel', class: 'btn btn-outline' }, ME.role === 'employee' ? 'В приложение' : 'В панель'))));
    return;
  }
  loadGlossary();

  // ---------- каркас экрана ----------
  // приветствие — до трёх строк; если длиннее, нажатие раскрывает целиком (замечание владельца 12.11)
  const greetText = h('div', { class: 'boss-greet-text', role: 'button', tabindex: '0', title: 'Показать полностью', 'aria-expanded': 'false' }, 'Загружаем…');
  const toggleGreet = () => { const open = greetText.classList.toggle('open'); greetText.setAttribute('aria-expanded', open ? 'true' : 'false'); const bx = greetText.closest('.boss'); if (bx) bx.classList.toggle('greet-open', open); };
  greetText.addEventListener('click', toggleGreet);
  greetText.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggleGreet(); } });
  const speakGreet = h('button', { type: 'button', class: 'btn btn-sm btn-ghost boss-speak', title: 'Озвучить приветствие', 'aria-label': 'Озвучить' }, icon('volume', { size: 18 }));
  const seg = h('div', { class: 'seg', role: 'tablist' },
    ['week', 'month'].map(p => h('button', { type: 'button', role: 'tab', class: 'seg-btn' + (S.period === p ? ' on' : ''), 'data-period': p, onclick: () => setPeriod(p) }, p === 'week' ? 'Неделя' : 'Месяц')));   // без календарей (образец 13.11)
  // плитки по образцу владельца (13.11): иконка в круге на мягком фоне; «ждут решения» и «просрочено» — текущее состояние («сейчас»)
  const TILES = [['new', 'поступило', 'inbox'], ['done', 'решено', 'check-circle'], ['decisions', 'ждут вашего решения', 'send'], ['overdue', 'просрочено', 'clock']];
  const tiles = {};
  const tilesEl = h('div', { class: 'boss-tiles' }, TILES.map(([k, label, ic]) => { const b = h('b', {}, '…'); tiles[k] = b; return h('button', { type: 'button', class: 'boss-tile tile-' + k, 'data-tile': k, onclick: () => openList(k) }, h('span', { class: 'tile-ic' }, icon(ic, { size: 24, width: 1.5 })), h('span', { class: 'tile-body' }, b, h('span', { class: 'tile-label' }, label), k === 'decisions' || k === 'overdue' ? h('small', { class: 'tile-now' }, 'сейчас') : null)); }));
  const ta = h('textarea', { class: 'boss-ask-text', rows: 1, placeholder: 'Спросите, например: что по Омску?', 'aria-label': 'Вопрос' });
  const mic = h('button', { type: 'button', class: 'btn mic boss-mic', title: 'Спросить голосом', 'aria-label': 'Спросить голосом' });
  const send = h('button', { type: 'button', class: 'btn btn-primary boss-send', title: 'Спросить', 'aria-label': 'Спросить' }, icon('send', { size: 20 }));
  Voice.attach(mic, ta, { onText: () => ask() });
  send.addEventListener('click', ask);
  ta.addEventListener('keydown', ev => { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); ask(); } });
  const askBox = h('div', { class: 'boss-ask' }, h('div', { class: 'boss-ask-row' }, ta, send), h('div', { class: 'boss-mic-row' }, mic, h('span', { class: 'boss-mic-label' }, 'Спросить')));
  const screen = h('main', { class: 'boss' },
    // на телефоне у логотипа только знак — заголовок «Директор в кармане» влезает целиком на 360–390 (образец 13.11)
    h('header', { class: 'boss-head' }, h('span', { class: 'boss-mark' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })), h('span', { class: 'boss-title' }, 'Директор в кармане'), h('div', { class: 'spacer' }),
      h('a', { href: '/panel#/notifications', class: 'btn btn-sm btn-ghost bell', title: 'Уведомления', 'aria-label': 'Уведомления' }, icon('bell', { size: 18 }), ME.unread ? h('span', { class: 'n' }, String(ME.unread)) : null),   // красный счётчик, как в панели (13.11); «Панель на сайте» — ссылкой внизу
      h('a', { href: '/login?next=' + encodeURIComponent('/boss'), class: 'btn btn-sm btn-ghost', title: 'Сменить пользователя', 'aria-label': 'Сменить пользователя' }, icon('log-out', { size: 18 }))),
    h('section', { class: 'card boss-greet' }, h('div', { class: 'boss-greet-row' }, h('span', { class: 'boss-name' }, ME.name), helpBtn('boss_greeting'), h('div', { class: 'spacer' }), speakGreet), greetText),
    seg, tilesEl, askBox,
    h('footer', { class: 'boss-foot' }, h('a', { href: '/panel#/summary' }, iconText('external-link', 'Подробнее на сайте')), h('span', { class: 'muted' }, 'голосом или текстом · только директору · ', versionTag())));
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
    for (const [k] of TILES) { tiles[k].textContent = String(S.home.tiles[k]); tiles[k].closest('.boss-tile').classList.toggle('zero', !S.home.tiles[k]); }
    // приветствие списком из чисел сервера, как сводка в панели (замечание 13.11); строка «Поступило / Решено / Ждут решения» — список внутри /boss
    const g = S.home.greeting;
    if (g.items) {
      const LIST = { new: 'new', done: 'done', decisions: 'decisions' };
      greetText.replaceChildren(h('p', { class: 'boss-greet-hi' }, g.greeting), h('div', { class: 'boss-greet-period' }, g.period),
        h('ul', { class: 'boss-greet-list' }, g.items.map(it => {
          const kids = sumParts(it.parts);
          const sub = it.sub ? h('ul', { class: 'sum-sub' }, h('li', {}, sumParts(it.sub))) : null;   // «из них мешают работать» — вложенной строкой
          if (!LIST[it.key]) return h('li', {}, h('span', {}, kids), sub);
          const go = ev => { ev.stopPropagation(); openList(LIST[it.key]); };   // строчный элемент, а не кнопка: маркер списка — у первой строки
          return h('li', {}, h('span', { class: 'linkish', role: 'button', tabindex: '0', onclick: go, onkeydown: ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); go(ev); } } }, kids), sub);
        })));
    } else greetText.textContent = g.text;
    requestAnimationFrame(markFit);
  }
  // затухание внизу приветствия — только если список не влез целиком
  function markFit() { greetText.classList.toggle('fits', greetText.scrollHeight <= greetText.clientHeight + 1); }
  window.addEventListener('resize', () => requestAnimationFrame(markFit));
  function setPeriod(p) {
    S.period = p;
    try { localStorage.setItem('mf.boss.period', p); } catch (e) { /* нет хранилища */ }
    for (const b of seg.children) b.classList.toggle('on', b.dataset.period === p);
    load();
  }
  speakGreet.addEventListener('click', () => speakText(speakGreet, '/api/boss/greeting/audio?period=' + S.period, S.home ? S.home.greeting.text : ''));   // тот же текст списком
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
  // Списки и карточки — внутри /boss (замечание владельца 12.11: панель на телефоне неудобна): номер, «Коротко» одной строкой, статус,
  // ответственный; нажатие — карточка, «К списку» — назад.
  function openList(k) {
    const items = (S.home && S.home.lists[k]) || [];
    const title = TITLES[k] + (k === 'new' || k === 'done' ? ' · ' + S.home.period_label : '');   // решения и просрочки — не за период, а сейчас
    if (!items.length) { sheet(title, h('div', { class: 'card muted' }, k === 'overdue' ? 'Просрочек нет.' : k === 'decisions' ? 'Вашего решения ничего не ждёт.' : 'Пока пусто.')); return; }
    if (k === 'decisions') { sheet(title, h('div', { class: 'boss-list' }, items.map(decisionRow))); return; }
    openItems(title, items.map(i => ({ ...i, kind: i.kind || 'appeal' })), k === 'done');
  }

  function openItems(title, items, showResult) {
    const back = () => openItems(title, items, showResult);
    sheet(title, h('div', { class: 'boss-list' }, items.map(i => i.kind === 'decision' ? decisionRow(i) : itemRow(i, back, showResult))));
  }

  function itemRow(i, back, showResult) {
    const task = i.kind === 'task';
    return h('button', { type: 'button', class: 'boss-item boss-item-btn', onclick: () => openCard(i, back) },
      h('div', { class: 'row' }, h('b', {}, task ? 'Поручение' : i.number), i.overdue || task ? h('span', { class: 'dot-overdue', title: 'просрочено' }) : null, h('div', { class: 'spacer' }),
        h('span', { class: 'small muted' }, task ? 'срок был ' + i.due_label : (i.age_days !== undefined ? i.age_days + ' дн' : ''))),
      h('div', { class: 'small one-line' }, i.text),
      task ? h('div', { class: 'small muted one-line' }, (i.assignee || 'без исполнителя') + (i.meeting_title ? ' · «' + i.meeting_title + '»' : ''))
        : h('div', { class: 'row small boss-st' }, i.status_code ? badge(i.status_code) : null, h('span', { class: 'muted one-line' }, i.responsible ? 'отвечает ' + i.responsible : 'без ответственного')),   // статус — та же цветная метка, что в очереди
      showResult && i.resolution ? h('div', { class: 'small boss-res one-line' }, i.resolution) : null);
  }

  function backBtn(back) { return back ? h('button', { type: 'button', class: 'btn btn-sm btn-ghost boss-back', onclick: back }, 'К списку') : null; }

  async function openCard(i, back) {
    if (i.kind === 'task') {
      sheet('Поручение с совещания', h('div', {}, backBtn(back), h('p', { class: 'boss-answer' }, i.text),
        h('div', { class: 'small muted' }, ['срок был ' + i.due_label, i.assignee ? 'исполнитель ' + i.assignee : 'без исполнителя', i.meeting_title ? '«' + i.meeting_title + '»' : null].filter(Boolean).join(' · '))));
      return;
    }
    sheet(i.number || 'Обращение', h('div', { class: 'row small muted' }, h('span', { class: 'spin' }), 'Открываю…'));
    let a;
    try { a = await API.get('/api/appeals/' + (i.appeal_id || i.id)); } catch (e) { toast(e.message, 'bad'); if (back) back(); return; }
    const b = a.brief && !a.brief.unclear ? a.brief : null;
    const news = (a.events || []).filter(e => ['progress', 'comment', 'status_changed', 'discussed_at_meeting', 'director_decided'].includes(e.kind)).slice(-1)[0];
    sheet(a.number, h('div', { class: 'boss-card' }, backBtn(back),
      h('div', { class: 'row' }, badge(a.status), a.overdue ? h('span', { class: 'dot-overdue', title: 'просрочено' }) : null,
        h('span', { class: 'small muted' }, [a.type_label, a.category, brCity(a.branch)].filter(Boolean).join(' · '))),
      h('p', { class: 'boss-answer' }, b ? b.gist : a.text),
      b ? h('details', { class: 'small' }, h('summary', {}, 'Полный текст'), h('p', { class: 'pre' }, a.text)) : null,
      h('div', { class: 'small mt8' }, h('b', {}, 'Отвечает: '), a.responsible || 'не назначен'),
      h('div', { class: 'small muted' }, 'Подано ' + plural(Math.floor(a.age_hours / 24), 'день', 'дня', 'дней') + ' назад' + (a.overdue ? ' · срок первого ответа прошёл' : '')),
      news ? h('div', { class: 'small mt8' }, h('b', {}, 'Последнее: '), eventText(news)) : null,
      a.resolution_text ? h('div', { class: 'small card-ok boss-res mt8' }, a.resolution_text) : null,
      h('div', { class: 'row mt8' }, h('a', { href: '/panel#/appeal/' + a.id, class: 'small muted' }, 'Открыть в панели'))));
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
    row.append(h('div', { class: 'row' }, i.number ? h('b', {}, i.number) : h('b', {}, 'Идея с совещания'), h('span', { class: 'small muted' }, [i.category, brCity(i.branch) || i.meeting_title].filter(Boolean).join(' · ')), h('div', { class: 'spacer' }),
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

  function speakBtn(r) {
    const speak = h('button', { type: 'button', class: 'btn btn-sm', title: 'Озвучить ответ' }, 'Озвучить');
    speak.addEventListener('click', () => speakText(speak, r.audio ? '/api/boss/answer/' + r.id + '/audio' : null, r.answer));
    return speak;
  }

  function render(text, r) {
    const q = h('div', { class: 'small muted boss-q' }, iconText('message-circle', text));
    if (r.kind === 'question' || r.kind === 'answer') {
      const parts = r.parts || [];
      const lists = parts.filter(p => p.list && p.list.items && p.list.items.length).map(p => h('button', { type: 'button', class: 'btn btn-sm btn-outline', onclick: () => openItems(p.list.title, p.list.items) },
        iconText('list', p.list.title + ' · ' + p.list.items.length)));
      const body = parts.length > 1 ? parts.map(p => h('p', { class: 'boss-answer' }, p.answer)) : [h('p', { class: 'boss-answer' }, r.answer)];
      sheet(r.kind === 'answer' ? 'Ответ' : r.question_label[0].toUpperCase() + r.question_label.slice(1), h('div', {}, q, body,
        h('div', { class: 'row mt8 row-wrap' }, speakBtn(r), lists)),
        { mark: helpBtn('boss_answer') });
      if (r.audio) speakText(null, '/api/boss/answer/' + r.id + '/audio', r.answer);
      return;
    }
    if (r.kind === 'unknown') {
      sheet('Не понял вопрос', h('div', {}, q, h('p', { class: 'boss-answer' }, 'Спросите про цифры на экране, город, отдел или обращение — например:'),
        h('div', { class: 'chips' }, r.can.map(x => h('button', { type: 'button', class: 'chip', onclick: () => { closeSheet(); ta.value = x; ask(); } }, x)))));
      return;
    }
    // команда: существующий план с обязательным подтверждением
    const p = r.plan;
    if (p.kind === 'unknown') { render(text, { kind: 'unknown', can: p.examples, links: [] }); return; }
    if (p.empty) { render(text, { kind: 'answer', answer: p.title, parts: [], engine: r.engine, audio: false }); return; }   // отправлять некому — словами
    if (p.kind === 'briefing') {
      const speak = h('button', { type: 'button', class: 'btn btn-sm btn-primary' }, 'Прочитать');
      speak.addEventListener('click', async () => { try { await API.post('/api/director/command/' + r.plan_id + '/send', {}); } catch (e) { /* уже отправлено */ } speakText(speak, '/api/panel/director-summary/audio', p.sentences.map(s => s.text).join(' ')); });
      sheet('Сводка', h('div', {}, q, p.sentences.map(s => h('p', { class: 'boss-answer small' }, s.text)), h('div', { class: 'row mt8' }, speak)), { mark: helpBtn('summary') });
      return;
    }
    if (p.decision && (p.kind === 'open' || p.kind === 'clarify')) {   // отсылка к «На решение» (13.11): строка решения с «Принять / Отклонить»
      const d = { ...p.decision, wait_days: Math.floor(p.decision.wait_days || 0) };
      const showRow = () => { API.post('/api/director/command/' + r.plan_id + '/send', {}).catch(() => null); sheet('На решение', h('div', { class: 'boss-list' }, decisionRow(d))); };
      if (p.kind === 'open') { showRow(); return; }
      sheet('Уточните', h('div', {}, q, h('p', { class: 'boss-answer' }, p.title), h('div', { class: 'small muted' }, p.item.text),
        h('div', { class: 'row mt8' }, h('button', { type: 'button', class: 'btn btn-primary btn-sm', onclick: showRow }, 'Да, открыть'), h('button', { type: 'button', class: 'btn btn-sm', onclick: closeSheet }, 'Нет'))));
      return;
    }
    if (p.kind === 'open') {
      sheet('На решение', h('div', {}, q, h('p', { class: 'boss-answer' }, p.title), h('div', { class: 'row mt8' }, h('button', { type: 'button', class: 'btn btn-primary btn-sm', onclick: async () => { try { await API.post('/api/director/command/' + r.plan_id + '/send', {}); } catch (e) { /* уже */ } closeSheet(); openList('decisions'); } }, 'Открыть'), h('button', { type: 'button', class: 'btn btn-sm', onclick: closeSheet }, 'Отмена'))));
      return;
    }
    const sendBtn = h('button', { type: 'button', class: 'btn btn-primary btn-sm' }, 'Отправить');
    sendBtn.addEventListener('click', async () => {
      sendBtn.disabled = true;
      try { const s = await API.post('/api/director/command/' + r.plan_id + '/send', {}); sheet('Отправлено', h('div', {}, h('p', { class: 'boss-answer' }, s.reply), h('div', { class: 'row mt8' }, h('button', { type: 'button', class: 'btn btn-sm', onclick: closeSheet }, 'Готово')))); speakText(null, '/api/director/command/' + r.plan_id + '/audio', s.reply); load(); }
      catch (e) { toast(e.message, 'bad'); sendBtn.disabled = false; }
    });
    sheet('Подтвердите команду', h('div', {}, q, h('p', { class: 'boss-answer' }, p.title),
      h('div', { class: 'hint' }, 'Отправится только после «Отправить». Получателей посчитал сервер.'),
      h('div', { class: 'boss-list' }, (p.recipients || []).map(rec => h('div', { class: 'boss-item' }, h('div', { class: 'row' }, h('b', {}, rec.name), h('span', { class: 'small muted' }, [rec.position, brCity(rec.branch)].filter(Boolean).join(' · '))), h('div', { class: 'small muted' }, rec.message)))),
      h('div', { class: 'row mt8' }, sendBtn, h('button', { type: 'button', class: 'btn btn-sm', onclick: closeSheet }, 'Отмена'))),
      { mark: helpBtn('command_result') });
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
      if (ru && text) { const u = new SpeechSynthesisUtterance(text); u.lang = 'ru-RU'; u.voice = ru; u.rate = 1.1; speechSynthesis.cancel(); speechSynthesis.speak(u); }
    }
  }
})();
