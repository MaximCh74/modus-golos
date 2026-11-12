'use strict';
// Стартовая «Модус Голос» (этап 7, шаг 1; правки владельца 12.11): шапка, заголовок с красной чертой, живая карта на реальных контурах (одно смелое место страницы),
// карточка города рядом с меткой (на телефоне — снизу листом), три тихие карточки-входа. Данные — /api/public/map без входа.
(async function () {
  const root = document.getElementById('root');
  const hero = h('section', { class: 'hero-text' }, h('span', { class: 'dash' }), h('h1', { class: 'display' }, 'Есть идея или ', h('em', {}, 'проблема?')),
    h('p', { class: 'lead' }, 'Выберите город или отсканируйте QR — без установки и регистрации'));
  const mapSlot = h('div', { class: 'home-map' }, h('div', { class: 'skeleton', style: null }));
  mapSlot.firstChild.style.aspectRatio = '2.25';
  const featsSlot = h('div', { class: 'feats' }, [1, 2, 3].map(() => { const k = h('div', { class: 'skeleton' }); k.style.height = '76px'; return k; }));
  const main = h('main', { class: 'home' }, h('div', { class: 'home-arc', 'aria-hidden': 'true' }, h('i'), h('i')), hero, mapSlot, featsSlot);
  root.replaceChildren(siteHeader(null, {}), main);

  const [map, me, cfg] = await Promise.all([API.get('/api/public/map'), API.me(), API.get('/api/public/config').catch(() => ({}))]);
  root.firstChild.replaceWith(siteHeader(me, cfg));
  let selected = null;
  const isMobile = () => window.matchMedia('(max-width: 768px)').matches;
  const mapEl = mapView(map, { crop: { aspect: 2.25, top: 0.1 }, motion: true, onBranch: b => select(b) });   // объекты — только у директора
  const pop = h('div', { class: 'citypop hidden' });
  mapEl.scene.append(pop);   // карточка города едет вместе с картой при наезде
  const pills = h('div', { class: 'city-pills' });
  for (const b of map.branches) { const bt = h('button', { type: 'button', class: 'btn', onclick: () => select(b) }, b.city + (b.kind === 'production' ? ' · производство' : '')); bt.dataset.id = b.id; pills.append(bt); }
  if (map.field) { const bt = h('button', { type: 'button', class: 'btn', onclick: () => select(map.field) }, 'Я на объекте'); bt.dataset.id = map.field.id; pills.append(bt); }
  mapSlot.replaceChildren(mapEl, pills);

  function cityCard(b) {
    const field = b.kind === 'field';
    return h('div', { class: 'citycard' },
      h('div', { class: 'cc-head' }, h('div', { class: 'cc-name' }, h('b', {}, field ? 'Объект' : b.city), h('span', {}, field ? 'командировка, любой город' : b.kind_label)),
        h('img', { class: 'cc-qr', src: b.qr_svg, alt: 'QR ' + (b.city || b.name) })),
      field ? h('p', { class: 'small muted' }, 'Для командированных на объектах по всему Казахстану: город или объект укажете в форме.')
        : h('div', { class: 'cc-tiles' },
          h('div', { class: 'tile' }, icon('folder', { size: 22 }), h('span', {}, 'Открытых'), h('b', {}, String(b.open))),
          h('div', { class: 'tile' }, icon('check-circle', { size: 22 }), h('span', {}, 'Решено за месяц'), h('b', {}, String(b.done_month)))),
      field ? null : h('div', { class: 'cc-theme' }, icon('layers', { size: 18 }), h('span', {}, 'Главная тема: ', h('b', {}, b.top_category || 'открытых обращений нет'))),
      h('a', { href: b.form_url, class: 'btn btn-primary btn-big' }, iconText('pencil', 'Подать обращение')));
  }
  function closeAll() { pop.classList.add('hidden'); const s = document.querySelector('.sheet'); if (s) { s.remove(); } const bd = document.querySelector('.sheet-back'); if (bd) bd.remove(); }
  function select(b) {
    selected = b;
    mapEl.select(b.kind === 'field' ? null : b.id);
    for (const x of pills.children) x.classList.toggle('on', String(x.dataset.id) === String(b.id));
    closeAll();
    if (isMobile()) {
      const back = h('div', { class: 'sheet-back', onclick: closeAll });
      const sheet = h('div', { class: 'sheet', role: 'dialog', 'aria-label': b.city || b.name }, h('div', { class: 'grip' }), h('button', { type: 'button', class: 'btn btn-ghost btn-sm close', onclick: closeAll, 'aria-label': 'Закрыть' }, icon('x')), cityCard(b));
      document.body.append(back, sheet);
      return;
    }
    const pos = b.kind === 'field' ? null : mapEl.pos(b.id);
    pop.replaceChildren(h('button', { type: 'button', class: 'btn btn-ghost btn-sm close', onclick: closeAll, 'aria-label': 'Закрыть' }, icon('x')), cityCard(b));
    if (!pos) { pop.className = 'citypop pop-right'; pop.style.left = '58%'; pop.style.top = '50%'; pop.style.setProperty('--tail', '50%'); return; }
    const left = pos.x > 52;
    const tail = Math.max(14, Math.min(86, pos.y));   // хвостик смотрит на метку, карточка не выходит за карту
    pop.className = 'citypop ' + (left ? 'pop-left' : 'pop-right');
    pop.style.left = pos.x + '%'; pop.style.top = pos.y + '%';
    pop.style.setProperty('--tail', tail + '%');
  }
  window.addEventListener('resize', () => { if (selected) { const b = selected; closeAll(); select(b); } });
  mapEl.map.addEventListener('click', e => { if (e.target === mapEl.map || e.target === mapEl.scene || e.target.classList.contains('map-bg') || e.target.classList.contains('map-layer')) closeAll(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });

  const submit = h('button', { type: 'button', class: 'feat', onclick: () => { if (selected) location.href = selected.form_url; else { toast('Сначала выберите город на карте или в списке'); pills.firstChild.focus(); pills.scrollIntoView({ behavior: 'smooth', block: 'center' }); } } },
    icon('message-circle', { size: 26 }), h('div', {}, h('b', {}, 'Подать обращение'), h('span', {}, 'Идеи, вопросы, проблемы')), icon('chevron-right', { size: 20, cls: 'chev' }));
  const changes = h('a', { href: '/changes', class: 'feat' }, icon('layers', { size: 26 }), h('div', {}, h('b', {}, 'Результаты обращений'), h('span', {}, 'Что уже сделано по вашим идеям')), icon('chevron-right', { size: 20, cls: 'chev' }));
  const statsHref = me && me.role !== 'employee' ? '/panel#/summary' : '/login?next=' + encodeURIComponent('/panel#/summary');
  const stats = h('a', { href: statsHref, class: 'feat' }, icon('bar-chart', { size: 26 }), h('div', {}, h('b', {}, 'Статистика'), h('span', {}, 'Открытые и решённые')), icon('chevron-right', { size: 20, cls: 'chev' }));
  featsSlot.replaceChildren(submit, changes, stats);
  main.append(h('div', { class: 'home-foot' }, h('span', {}, h('a', { href: '/rules' }, 'Как начисляются баллы'), ' — прозрачные правила вместо разовых премий'),
    h('span', {}, 'разработано ', h('b', {}, 'Cyber QALQAN Systems'), ' · данные демонстрационные')));
  if (!isMobile() && map.branches.length) select(map.branches[0]);   // на ноутбуке сразу показываем головной офис, как на макете
})();
