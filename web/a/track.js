'use strict';
// Страница статуса по трекинг-ссылке (/t/<token>): без входа, автор не раскрывается.
(async function () {
  const root = document.getElementById('root');
  const token = location.pathname.split('/')[2] || '';
  const url = '/api/public/track/' + encodeURIComponent(token);

  async function render() {
    let a;
    try { a = await API.get(url); }
    catch (e) { root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-bad' }, e.message))); return; }
    const card = h('div', { class: 'card' },
      h('div', { class: 'row' }, h('span', { class: 'h1' }, a.number), tag(a.stage.code === 'rejected' ? 'st-rejected' : a.stage.code === 'done' ? 'st-done' : 'st-review', a.stage.label), a.is_anonymous ? tag('tag-anon', 'анонимно') : null),
      stageTracker(a.stage),
      h('div', { class: 'small muted' }, [a.type_label, a.category, a.branch].filter(Boolean).join(' · ')),
      h('p', { class: 'pre' }, a.text),
      h('div', { class: 'small muted' }, 'Отвечает: ' + (a.responsible ? a.responsible + (a.responsible_position ? ' (' + a.responsible_position + ')' : '') : 'ответственный назначается администратором')),
      a.attachments && a.attachments.length ? h('div', { class: 'small mt8' }, 'Вложения: ', a.attachments.map(f => h('a', { href: '/api/attachments/' + f.id + '?t=' + encodeURIComponent(token), target: '_blank' }, f.filename + ' '))) : null);
    const result = a.status === 'done' || a.status === 'closed' && a.resolution_text
      ? h('div', { class: 'card card-ok' }, h('b', {}, 'Что сделали'), h('p', { class: 'pre' }, a.resolution_text))
      : a.status === 'rejected' ? h('div', { class: 'card card-bad' }, h('b', {}, 'Отклонено — причина'), h('p', { class: 'pre' }, a.resolution_text)) : null;
    let answer = null;
    if (a.pending_question) {
      const ta = h('textarea', { placeholder: 'Ваш ответ' });
      const btn = h('button', { class: 'btn btn-primary' }, 'Ответить');
      answer = h('div', { class: 'card card-warn' }, h('b', {}, 'Ответственный просит уточнить'), h('p', { class: 'pre' }, a.pending_question), ta, h('div', { class: 'mt8' }, btn));
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try { await API.post(url + '/answer', { text: ta.value }); toast('Ответ отправлен'); render(); }
        catch (e) { toast(e.message, 'bad'); btn.disabled = false; }
      });
    }
    root.replaceChildren(h('div', { class: 'wrap' },
      h('div', { class: 'hero' }, h('div', { class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })), h('div', { class: 'lbl mt16' }, 'Статус обращения')),
      card, result, answer,
      h('div', { class: 'card' }, h('div', { class: 'h2' }, 'История'), history(a.events)),
      h('p', { class: 'hint' }, 'Сохраните эту ссылку — без входа она единственный способ увидеть ответ. ', h('a', { href: '/login?next=' + encodeURIComponent('/app') }, 'Войти в приложение'))));
  }
  render();
})();
