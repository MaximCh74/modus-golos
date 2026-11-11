'use strict';
// «Как начисляются баллы» — простыми словами, без входа (ТЗ v2 §2.7): прозрачные правила вместо разовых премий.
(async function () {
  const root = document.getElementById('root');
  const d = await API.get('/api/public/rules');
  const p = d.points;
  root.replaceChildren(h('div', { class: 'wrap' },
    h('div', { class: 'hero' }, h('a', { href: '/', class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })), h('div', { class: 'lbl mt16' }, 'Прозрачные правила вместо разовых премий'), h('div', { class: 'h1' }, 'Как начисляются баллы')),
    h('div', { class: 'card' },
      h('div', { class: 'lbl' }, 'За что'),
      h('div', { class: 'list mt8' },
        h('div', { class: 'item' }, h('div', { class: 'row' }, h('b', { class: 'big' }, '+' + p.accepted), h('div', {}, h('b', {}, 'Обращение принято к рассмотрению'), h('div', { class: 'small muted' }, 'Ответственный перевёл его из «Новое» в «На рассмотрении»')))),
        h('div', { class: 'item' }, h('div', { class: 'row' }, h('b', { class: 'big' }, '+' + p.done), h('div', {}, h('b', {}, 'Реализовано'), h('div', { class: 'small muted' }, 'Проблема решена или идея внедрена — это попадает в ленту «Что изменили»')))),
        h('div', { class: 'item' }, h('div', { class: 'row' }, h('b', { class: 'big' }, '+' + p.support), h('div', {}, h('b', {}, 'Коллега нажал «У меня так же»'), h('div', { class: 'small muted' }, 'За каждого, но не больше +' + p.support_cap + ' на одно обращение'))))),
      h('div', { class: 'hint mt8' }, 'Баллы получает автор. За отправку обращения баллов нет — важен результат, а не количество.')),
    h('div', { class: 'card' },
      h('div', { class: 'lbl' }, 'За что не начисляется'),
      h('ul', { class: 'small' }, h('li', {}, 'за отправку — пока обращение не принято'), h('li', {}, 'за отклонённые обращения'), h('li', {}, 'за положительные отзывы («Спасибо»)'), h('li', {}, 'за анонимные обращения — автор неизвестен'))),
    h('div', { class: 'card' },
      h('div', { class: 'lbl' }, 'На что обменять'),
      h('div', { class: 'list mt8' }, d.rewards.map(r => h('div', { class: 'item' }, h('div', { class: 'row' }, h('b', {}, r.title), h('div', { class: 'spacer' }), tag('tag-type', r.cost_points + ' баллов')), h('div', { class: 'small muted' }, r.description)))),
      h('div', { class: 'hint mt8' }, 'Состав наград — демонстрационный, определяет компания. Премия за внедрённую идею — привычная форма поощрения, теперь по понятным правилам.')),
    h('div', { class: 'card card-info small' }, h('b', {}, 'Путь идеи. '), 'Предложение попадает в отдел развития, оттуда при необходимости — директору в «На решение». Идея, которая ждёт решения дольше ' + d.director_wait_days + ' дней, подсвечивается директору.'),
    h('div', { class: 'dev' }, h('a', { href: '/app' }, 'Открыть приложение'), ' · ', h('a', { href: '/' }, 'На стартовую'))));
})();
