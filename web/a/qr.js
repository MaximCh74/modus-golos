'use strict';
// QR-форма: один экран, одна кнопка. Филиал — из QR (/q/<код>). Без входа — анонимно, с трекинг-ссылкой.
// «Спасибо» — короткая форма: текст или голос, кому (необязательно), файл, «Отправить». Служебных пояснений про ИИ нет.
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
  const btnPraise = h('button', { type: 'button', class: 'btn' }, 'Спасибо');
  const text = h('textarea', { name: 'text', required: true, placeholder: 'Что происходит? Если есть идея, как исправить — напишите.' });
  const mic = h('button', { type: 'button', class: 'btn mic', title: 'Голосовой ввод' });
  let inputMode = 'text';
  const understood = h('div', {});
  Voice.attach(mic, text, { public: !me, onText: async () => {
    inputMode = 'voice';
    if (type === 'praise') return;
    understood.replaceChildren(h('div', { class: 'hint' }, h('span', { class: 'spin' }), ' Разбираем, что вы сказали…'));
    try {
      const r = await API.post('/api/public/brief', { text: text.value, type });
      understood.replaceChildren(r.brief ? h('div', { class: 'card card-info small' }, h('b', {}, 'Мы поняли так: '), r.brief.gist, r.category ? h('span', { class: 'muted' }, ' · категория: ' + r.category) : null,
        h('div', { class: 'hint mt8' }, 'Если что-то не так — поправьте текст выше.')) : null);
    } catch (e) { understood.replaceChildren(); }
  } });
  const chipRow = h('div', { class: 'row small' });
  const urg = chips(URGENCY); const sc = chips(SCOPE);
  const chipLabel = h('span', { class: 'muted' });
  const renderChips = () => { chipRow.replaceChildren(chipLabel, type === 'problem' ? urg : sc); chipLabel.textContent = type === 'problem' ? 'Насколько мешает работать?' : 'Кого затронет?'; };
  let similarShown = false, anyway = false;
  const simBox = h('div', {});
  const file = filePicker();
  const to = personPicker({ search: q => API.get('/api/public/staff?q=' + encodeURIComponent(q)) });
  const toField = field('Кому спасибо', to, 'Коллега или отдел — адресат и его руководитель получат уведомление');
  const site = h('input', { type: 'text', name: 'site_city', placeholder: 'Например: Атырау, объект ТЭЦ-2', maxlength: 80 });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary btn-big' }, 'Отправить');
  // F-08: вошедший сотрудник тоже может отправить анонимно — без связи с ним, только ссылка на статус
  const anon = h('input', { type: 'checkbox' });
  const footText = h('span', {});
  const renderFoot = () => { footText.textContent = !me ? 'Без входа обращение анонимное. Категорию и ответственного система определит сама.'
    : anon.checked ? 'Анонимно: обращение не будет связано с вами и не даст баллов — статус по ссылке после отправки.'
      : 'Вы вошли как ' + me.name + ' — обращение будет привязано к вам и даст баллы.'; };
  anon.addEventListener('change', renderFoot);
  renderFoot();
  const anonRow = me ? h('label', { class: 'check mt8 mb8' }, anon, 'Анонимно') : null;
  const foot = h('div', { class: 'hint mt8' }, footText);
  const form = h('form', { class: 'card' },
    h('div', { class: 'type-switch three' }, btnProblem, btnIdea, btnPraise),
    h('div', { class: 'row' }, h('div', { class: 'spacer' }, text), mic),
    understood,
    chipRow,
    toField,
    branch.kind === 'field' ? field('Город / объект (необязательно)', site, 'Без геолокации — чтобы не запрашивать разрешений') : null,
    h('div', { class: 'mt8' }, field('Фото или файл (необязательно)', file)),
    simBox,
    anonRow,
    submit,
    foot);
  const setType = t => {
    type = t;
    btnProblem.classList.toggle('on', t === 'problem'); btnIdea.classList.toggle('on', t === 'suggestion'); btnPraise.classList.toggle('on', t === 'praise');
    chipRow.classList.toggle('hidden', t === 'praise'); understood.classList.toggle('hidden', t === 'praise'); toField.classList.toggle('hidden', t !== 'praise');
    if (anonRow) anonRow.classList.toggle('hidden', t === 'praise');
    text.placeholder = t === 'praise' ? 'Кому и за что спасибо — текстом или голосом' : t === 'suggestion' ? 'Что предлагаете и что это даст' : 'Что происходит? Если есть идея, как исправить — напишите.';
    renderChips();
  };
  btnProblem.addEventListener('click', () => setType('problem'));
  btnIdea.addEventListener('click', () => setType('suggestion'));
  btnPraise.addEventListener('click', () => setType('praise'));
  setType('problem');

  root.replaceChildren(h('div', { class: 'wrap' },
    h('div', { class: 'hero dots' }, h('div', { class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })), h('div', { class: 'lbl mt16' }, 'Модус Голос · каждый голос услышан'), h('div', { class: 'h1' }, (branch.kind === 'field' ? '' : 'Филиал: ') + branch.name)),
    form));

  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    if (!anyway && !similarShown && type !== 'praise' && text.value.trim().length >= 8) {
      submit.disabled = true;
      try {
        const r = await API.post('/api/public/similar', { text: text.value });
        if (r.items.length) {
          similarShown = true;
          simBox.replaceChildren(similarBlock(r, { canSupport: !!me, onAnyway: () => { anyway = true; simBox.replaceChildren(); form.requestSubmit(); },
            onSupported: i => { root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-ok' }, h('div', { class: 'h1' }, 'Спасибо — учтено'), h('p', {}, 'Вы поддержали обращение ' + i.number + ': автор получил +2 балла, а ответственный видит, что это не единичный случай.'), h('a', { href: location.pathname, class: 'btn btn-outline' }, 'Отправить своё')))); } }));
          submit.disabled = false;
          return;
        }
      } catch (e) { /* похожие не нашлись или сервис недоступен — отправляем как есть */ }
      submit.disabled = false;
    }
    const fd = new FormData();
    fd.set('type', type); fd.set('text', text.value); fd.set('branch_code', branch.code); fd.set('input_mode', inputMode);
    if (me && anon.checked && type !== 'praise') fd.set('is_anonymous', '1');
    if (branch.kind === 'field') fd.set('site_city', site.value);
    if (type === 'praise') {
      const t = to.value;
      if (t && t.user_id) fd.set('praise_to_user_id', String(t.user_id));
      if (t && t.department_id) fd.set('praise_to_department_id', String(t.department_id));
    } else { fd.set('author_urgency', urg.value() || ''); fd.set('author_scope', sc.value() || ''); }
    if (file.file()) fd.set('file', file.file());
    submit.disabled = true;
    try {
      const r = await API.postForm('/api/public/appeals', fd);
      if (r.type === 'praise') {
        root.replaceChildren(h('div', { class: 'wrap' },
          h('div', { class: 'card card-ok' }, h('div', { class: 'h1' }, 'Спасибо передано'),
            h('p', {}, to.value ? 'Адресат и его руководитель получат уведомление, запись появится в профиле.' : 'Ваше спасибо увидят в компании.'),
            r.logged_in ? h('p', { class: 'small' }, h('a', { href: '/app#/appeal/' + r.id }, 'Открыть в приложении')) : null),
          h('a', { href: location.pathname, class: 'btn btn-outline' }, 'Отправить ещё одно')));
        return;
      }
      root.replaceChildren(h('div', { class: 'wrap' },
        h('div', { class: 'card card-ok' },
          h('div', { class: 'h1' }, 'Обращение ' + r.number + ' принято'),
          h('p', {}, 'Спасибо! Его увидит ответственный, а вы сможете следить за статусом по ссылке.'),
          h('p', { class: 'small' }, r.category ? ['Категория: ', h('b', {}, r.category), ' · приоритет: ', h('b', {}, PRIO[r.priority] || r.priority), ' · отвечает: ', h('b', {}, r.responsible || 'администратор (ответственный не назначен)')]
            : ['Категорию уточнит администратор']),
          h('a', { href: r.track_url, class: 'btn btn-primary btn-big' }, 'Следить за статусом'),
          h('p', { class: 'hint' }, 'Сохраните ссылку: ', h('code', {}, location.origin + r.track_url), r.logged_in ? '' : ' — без входа это единственный способ увидеть ответ.'),
          r.logged_in ? h('p', { class: 'small' }, 'Обращение привязано к вам: ', h('a', { href: '/app#/appeal/' + r.id }, 'открыть в приложении'))
                      : h('p', { class: 'small' }, h('a', { href: '/login?next=' + encodeURIComponent('/app') }, 'Войти, чтобы получать баллы за идеи'), ' · ', h('a', { href: '/rules' }, 'как начисляются баллы'))),
        h('a', { href: location.pathname, class: 'btn btn-outline' }, 'Отправить ещё одно')));
    } catch (e) { toast(e.message, 'bad'); submit.disabled = false; }
  });
})();
