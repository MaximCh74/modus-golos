'use strict';
// QR-форма: один экран, одна кнопка. Филиал — из QR (/q/<код>). Без входа — анонимно, с трекинг-ссылкой.
(async function () {
  const root = document.getElementById('root');
  const code = decodeURIComponent(location.pathname.split('/')[2] || '');
  let branch = null;
  try { branch = await API.get('/api/public/branch/' + encodeURIComponent(code)); }
  catch (e) { root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-bad' }, 'QR-код не распознан: ' + e.message))); return; }
  const me = await API.me();
  let type = 'problem';

  const btnProblem = h('button', { type: 'button', class: 'btn on' }, 'Проблема');
  const btnIdea = h('button', { type: 'button', class: 'btn' }, 'Идея');
  const text = h('textarea', { name: 'text', required: true, placeholder: 'Что происходит? Если есть идея, как исправить — напишите.' });
  const mic = h('button', { type: 'button', class: 'btn mic' }, '🎤');
  let inputMode = 'text';
  const understood = h('div', {});
  Voice.attach(mic, text, { public: !me, onText: async () => {
    inputMode = 'voice';
    understood.replaceChildren(h('div', { class: 'hint' }, h('span', { class: 'spin' }), ' Разбираем, что вы сказали…'));
    try { const r = await API.post('/api/public/brief', { text: text.value, type }); understood.replaceChildren(r.brief ? h('div', { class: 'card card-info small' }, h('b', {}, 'Мы поняли так: '), r.brief.gist, r.category ? h('span', { class: 'muted' }, ' · категория: ' + r.category) : null, h('div', { class: 'hint' }, 'Если не так — поправьте текст выше и отправляйте.')) : null); }
    catch (e) { understood.replaceChildren(); }
  } });
  const chipRow = h('div', { class: 'row small' });
  const urg = chips(URGENCY); const sc = chips(SCOPE);
  const chipLabel = h('span', { class: 'muted' });
  const renderChips = () => { chipRow.replaceChildren(chipLabel, type === 'problem' ? urg : sc); chipLabel.textContent = type === 'problem' ? 'Насколько мешает работать?' : 'Кого затронет?'; };
  renderChips();
  let similarShown = false, anyway = false;
  const simBox = h('div', {});
  const file = h('input', { type: 'file', name: 'file', accept: 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt' });
  const site = h('input', { type: 'text', name: 'site_city', placeholder: 'Например: Атырау, объект ТЭЦ-2', maxlength: 80 });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary btn-big' }, 'Отправить');
  const form = h('form', { class: 'card' },
    h('div', { class: 'type-switch' }, btnProblem, btnIdea),
    h('div', { class: 'row' }, h('div', { class: 'spacer' }, text), mic),
    understood,
    chipRow,
    branch.kind === 'field' ? field('Город / объект (необязательно)', site, 'Без геолокации — чтобы не запрашивать разрешений') : null,
    h('div', { class: 'mt8' }, field('Фото или файл (необязательно)', file)),
    simBox,
    submit,
    me ? h('div', { class: 'hint mt8' }, 'Вы вошли как ' + me.name + ' — обращение будет привязано к вам и даст баллы.')
       : h('div', { class: 'hint mt8' }, 'Без входа обращение анонимное. Категорию и ответственного подставит ИИ (без ключа — словарь ключевых слов).'));
  btnProblem.addEventListener('click', () => { type = 'problem'; btnProblem.classList.add('on'); btnIdea.classList.remove('on'); renderChips(); });
  btnIdea.addEventListener('click', () => { type = 'suggestion'; btnIdea.classList.add('on'); btnProblem.classList.remove('on'); renderChips(); });

  root.replaceChildren(h('div', { class: 'wrap' },
    h('div', { class: 'hero dots' }, h('div', { class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })), h('div', { class: 'lbl mt16' }, 'Обратная связь'), h('div', { class: 'h1' }, (branch.kind === 'field' ? '' : 'Филиал: ') + branch.name)),
    form));

  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    if (!anyway && !similarShown && text.value.trim().length >= 8) {
      submit.disabled = true;
      try {
        const r = await API.post('/api/public/similar', { text: text.value });
        if (r.items.length) {
          similarShown = true;
          simBox.replaceChildren(similarBlock(r, { canSupport: !!me, onAnyway: () => { anyway = true; simBox.replaceChildren(); form.requestSubmit(); },
            onSupported: i => { root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-ok' }, h('div', { class: 'h1' }, 'Спасибо — учтено'), h('p', {}, 'Вы поддержали обращение ' + i.number + ': автор получил +2 балла, а ответственный видит, что проблема повторяется.'), h('a', { href: '/app#/appeal/' + i.id, class: 'btn btn-primary' }, 'Открыть ' + i.number)), h('a', { href: location.pathname, class: 'btn btn-outline' }, 'Отправить своё обращение'))); } }));
          submit.disabled = false;
          return;
        }
      } catch (e) { /* похожие не нашлись или сервис недоступен — отправляем как есть */ }
      submit.disabled = false;
    }
    const fd = new FormData();
    fd.set('type', type); fd.set('text', text.value); fd.set('branch_code', branch.code);
    if (branch.kind === 'field') fd.set('site_city', site.value);
    fd.set('author_urgency', urg.value() || ''); fd.set('author_scope', sc.value() || ''); fd.set('input_mode', inputMode);
    if (file.files && file.files[0]) fd.set('file', file.files[0]);
    submit.disabled = true;
    try {
      const r = await API.postForm('/api/public/appeals', fd);
      root.replaceChildren(h('div', { class: 'wrap' },
        h('div', { class: 'card card-ok' },
          h('div', { class: 'h1' }, 'Обращение ' + r.number + ' принято'),
          h('p', {}, 'Спасибо! Его увидит ответственный, а вы сможете следить за статусом по ссылке.'),
          h('p', { class: 'small' }, r.category ? ['Категория: ', h('b', {}, r.category), ' · приоритет: ', h('b', {}, PRIO[r.priority] || r.priority), ' · отвечает: ', h('b', {}, r.responsible || 'администратор (ответственный не назначен)'),
            h('span', { class: 'muted' }, r.ai_engine === 'openai' ? ' — определил ИИ' : ' — по ключевым словам (без ИИ)')]
            : ['Категорию определит администратор', h('span', { class: 'muted' }, r.ai_engine === 'openai' ? ' — ИИ не уверен' : ' — словарь без ИИ не уверен')]),
          h('a', { href: r.track_url, class: 'btn btn-primary btn-big' }, 'Следить за статусом'),
          h('p', { class: 'hint' }, 'Сохраните ссылку: ', h('code', {}, location.origin + r.track_url), r.logged_in ? '' : ' — без входа это единственный способ увидеть ответ.'),
          r.logged_in ? h('p', { class: 'small' }, 'Обращение привязано к вам: ', h('a', { href: '/app#/appeal/' + r.id }, 'открыть в приложении'))
                      : h('p', { class: 'small' }, h('a', { href: '/login?next=' + encodeURIComponent('/app') }, 'Войти, чтобы получать баллы за идеи'), ' · ', h('a', { href: '/rules' }, 'как начисляются баллы'))),
        h('a', { href: location.pathname, class: 'btn btn-outline' }, 'Отправить ещё одно')));
    } catch (e) { toast(e.message, 'bad'); submit.disabled = false; }
  });
})();
