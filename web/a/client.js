'use strict';
// Обратная связь для клиентов (решение владельца 13.11, минимум): без входа — «Благодарность / Вопрос / Замечание», текст, город или объект,
// имя и телефон или почта с галочкой согласия, фото; всё, кроме текста, необязательно. После отправки — «Спасибо, ваше сообщение получено».
// Город можно подставить ссылкой (/c?city=Атырау, объект ТЭЦ-2) — для QR на акте сдачи объекта или на шкафу оборудования.
(function () {
  const root = document.getElementById('root');
  // на телефоне кнопка — «Спасибо»: «Благодарность» не влезает (замечание владельца 13.11); на компьютере — полностью
  const KINDS = [['thanks', [h('span', { class: 'k-full' }, 'Благодарность'), h('span', { class: 'k-short' }, 'Спасибо')], 'За что благодарите — коротко, своими словами'],
     ['question', 'Вопрос', 'Что хотите узнать'],
    ['remark', 'Замечание', 'Что не так и где — постараемся исправить']];
  let kind = 'thanks';
  const btns = KINDS.map(([k, label]) => { const b = h('button', { type: 'button', class: 'btn', onclick: () => setKind(k) }, label); b.dataset.kind = k; return b; });
  const text = h('textarea', { name: 'text', required: true, maxlength: 4000 });
  const place = h('input', { type: 'text', name: 'place', maxlength: 120, placeholder: 'Например: Павлодар или Атырау, объект ТЭЦ-2' });
  place.value = (new URLSearchParams(location.search).get('city') || '').trim().slice(0, 120);
  const name = h('input', { type: 'text', name: 'name', maxlength: 80, placeholder: 'Как к вам обращаться', autocomplete: 'name' });
  const contact = h('input', { type: 'text', name: 'contact', maxlength: 120, placeholder: 'Телефон или почта', autocomplete: 'tel' });
  const consent = h('input', { type: 'checkbox', name: 'consent' });
  const hp = h('input', { type: 'text', name: 'website', tabindex: '-1', autocomplete: 'off' });   // ловушка для ботов: человек это поле не видит
  const file = filePicker({ accept: 'image/jpeg,image/png,image/webp', label: 'Прикрепить фото' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary btn-big' }, 'Отправить');
  const form = h('form', { class: 'card client-form' },
    h('div', { class: 'type-switch three' }, btns),
    text,
    field('Город или объект (необязательно)', place),
    h('div', { class: 'grid2' }, field('Имя (необязательно)', name), field('Телефон или почта (необязательно)', contact)),
    h('label', { class: 'check mb8' }, consent, 'Согласен на обработку имени и контакта, чтобы со мной связались по этому сообщению'),
    field('Фото (необязательно)', file),
    h('div', { class: 'hp-field', 'aria-hidden': 'true' }, h('label', {}, 'Сайт', hp)),
    submit,
    h('div', { class: 'hint mt8' }, 'Без входа и регистрации. Сообщение увидят руководитель и администратор компании.'));
  function setKind(k) {
    kind = k;
    for (const b of btns) b.classList.toggle('on', b.dataset.kind === k);
    text.placeholder = KINDS.find(x => x[0] === k)[2];
  }
  setKind('thanks');

  const hero = h('div', { class: 'hero dots' }, h('div', { class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })),
    h('div', { class: 'lbl mt16' }, 'Модус Голос · обратная связь для клиентов'), h('div', { class: 'h1' }, 'Отзыв, вопрос или благодарность'));
  root.replaceChildren(h('div', { class: 'wrap' }, hero, form));

  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    if (text.value.trim().length < 3) { toast('Напишите несколько слов', 'bad'); text.focus(); return; }
    if ((name.value.trim() || contact.value.trim()) && !consent.checked) { toast('Отметьте согласие — или оставьте имя и контакт пустыми', 'bad'); consent.focus(); return; }
    const fd = new FormData();
    fd.set('kind', kind); fd.set('text', text.value); fd.set('place', place.value); fd.set('name', name.value); fd.set('contact', contact.value);
    fd.set('consent', consent.checked ? '1' : ''); fd.set('website', hp.value);
    if (file.file()) fd.set('file', file.file());
    submit.disabled = true;
    try {
      await API.postForm('/api/public/client-messages', fd);
      root.replaceChildren(h('div', { class: 'wrap' }, hero,
        h('div', { class: 'card card-ok' }, h('div', { class: 'h1' }, 'Спасибо, ваше сообщение получено'),
          h('p', {}, (name.value.trim() || contact.value.trim()) && consent.checked ? 'Если нужен ответ — свяжемся с вами по оставленному контакту.' : 'Его прочитают руководитель и администратор компании.')),
        h('a', { href: location.pathname + location.search, class: 'btn btn-outline' }, 'Отправить ещё одно')));
    } catch (e) { toast(e.message, 'bad'); submit.disabled = false; }
  });
})();
