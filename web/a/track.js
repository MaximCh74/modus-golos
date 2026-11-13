'use strict';
// Страница статуса по трекинг-ссылке (/t/<token>): без входа, автор не раскрывается. Этап 9 (пункт 4 очереди 12.11): один экран —
// один вопрос «что с моим обращением?»: стадия, последняя новость, что сделали; главная кнопка одна — «Ответить», когда ждут ответа;
// история свёрнута; вход в приложение — тихой ссылкой.
(async function () {
  const root = document.getElementById('root');
  const token = location.pathname.split('/')[2] || '';
  const url = '/api/public/track/' + encodeURIComponent(token);

  async function render() {
    let a;
    try { a = await API.get(url); }
    catch (e) { root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-bad' }, e.message))); return; }
    const news = (a.events || []).filter(e => e.kind === 'progress' || e.kind === 'comment' || e.kind === 'discussed_at_meeting').slice(-1)[0];
    const card = h('div', { class: 'card' },
      h('div', { class: 'row' }, h('span', { class: 'h1' }, a.number), tag(a.stage.code === 'rejected' ? 'st-rejected' : a.stage.code === 'done' ? 'st-done' : 'st-review', a.stage.label), helpBtn('stages'), a.is_anonymous ? tag('tag-anon', 'анонимно') : null),
      stageTracker(a.stage),
      h('div', { class: 'small muted' }, [a.type_label, a.category, a.branch].filter(Boolean).join(' · ')),
      h('p', { class: 'pre' }, a.text),
      news ? h('div', { class: 'card card-info small' }, h('b', {}, 'Последняя новость · ' + fmtDate(news.created_at) + ': '), eventText(news).replace(/^(Как идут дела|Комментарий|Обсуждено на совещании[^:]*): /, '')) : null,
      h('div', { class: 'small muted' }, 'Отвечает: ' + (a.responsible ? a.responsible + (a.responsible_position ? ' (' + a.responsible_position + ')' : '') : 'ответственный назначается администратором')),
      a.attachments && a.attachments.length ? h('div', { class: 'small mt8' }, 'Вложения: ', a.attachments.map(f => h('a', { href: '/api/attachments/' + f.id + '?t=' + encodeURIComponent(token), target: '_blank' }, f.filename + ' '))) : null);
    const result = a.status === 'done' || a.status === 'closed' && a.resolution_text
      ? h('div', { class: 'card card-ok' }, h('b', {}, 'Что сделали'), h('p', { class: 'pre' }, a.resolution_text))
      : a.status === 'rejected' ? h('div', { class: 'card card-bad' }, h('b', {}, 'Не принято — причина'), h('p', { class: 'pre' }, a.resolution_text)) : null;
    let answer = null;
    if (a.pending_question) {
      const ta = h('textarea', { placeholder: 'Ваш ответ' });
      const btn = h('button', { class: 'btn btn-primary btn-big' }, 'Ответить');
      answer = h('div', { class: 'card card-warn' }, h('b', {}, 'Ответственный просит уточнить'), h('p', { class: 'pre' }, a.pending_question), ta, h('div', { class: 'mt8' }, btn));
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try { await API.post(url + '/answer', { text: ta.value }); toast('Ответ отправлен'); render(); }
        catch (e) { toast(e.message, 'bad'); btn.disabled = false; }
      });
    }
    root.replaceChildren(h('div', { class: 'wrap' },
      h('div', { class: 'hero' }, h('div', { class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })), h('div', { class: 'lbl mt16' }, 'Статус обращения')),
      answer, card, result,
      h('details', { class: 'card sect' }, h('summary', {}, 'История · ' + (a.events || []).length), h('div', { class: 'mt8' }, history(a.events))),
      h('p', { class: 'hint' }, 'Сохраните эту ссылку — без входа она единственный способ увидеть ответ. ', h('a', { href: '/login?next=' + encodeURIComponent('/app') }, 'Войти в приложение'))));
  }
  render();
})();
