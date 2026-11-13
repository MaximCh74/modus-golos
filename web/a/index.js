'use strict';
// Стартовая «Модус Голос» (этап 7, шаг 1; правки владельца 12.11): шапка, заголовок с красной чертой, живая карта на реальных контурах (одно смелое место страницы),
// карточка города рядом с меткой (на телефоне — снизу листом), три тихие карточки-входа. Данные — /api/public/map без входа.
(async function () {
  const root = document.getElementById('root');
  const hero = h('section', { class: 'hero-text' }, h('span', { class: 'dash' }), h('h1', { class: 'display' }, 'Есть идея или ', h('em', {}, 'проблема?')),
    h('p', { class: 'lead' }, 'Выберите город или отсканируйте QR — без установки и регистрации'));
  const mapSlot = h('div', { class: 'home-map' }, h('div', { class: 'skeleton', style: null }));
  mapSlot.firstChild.style.aspectRatio = '900 / 643';   // та же рамка, что у карты директора
  const featsSlot = h('div', { class: 'feats' }, [1, 2, 3].map(() => { const k = h('div', { class: 'skeleton' }); k.style.height = '76px'; return k; }));
  const main = h('main', { class: 'home' }, h('div', { class: 'home-arc', 'aria-hidden': 'true' }, h('i'), h('i')), hero, mapSlot, featsSlot);
  root.replaceChildren(siteHeader(null, {}), main);

  const [map, me, cfg] = await Promise.all([API.get('/api/public/map'), API.me(), publicConfig()]);
  root.firstChild.replaceWith(siteHeader(me, cfg));
  let selected = null;
  const isMobile = () => window.matchMedia('(max-width: 768px)').matches;
  // одна подложка и одна рамка карты везде (замечание владельца 13.11): как у директора — 46…86° в. д., 45…62° с. ш., на всю ширину блока;
  // на главной — только филиалы (объекты — у директора)
  const mapEl = mapView(map, { frame: MAP_DIRECTOR, motion: true, onBranch: b => select(b) });
  const pop = h('div', { class: 'citypop hidden', role: 'dialog' });
  mapEl.map.append(pop);   // окно города — в рамке карты (не в движущейся сцене): так оно не вылезает за края
  const pills = h('div', { class: 'city-pills' });
  for (const b of map.branches) { const bt = h('button', { type: 'button', class: 'btn', onclick: () => select(b) }, b.city); bt.dataset.id = b.id; pills.append(bt); }
  if (map.field) { const bt = h('button', { type: 'button', class: 'btn', onclick: () => select(map.field) }, 'Я на объекте'); bt.dataset.id = map.field.id; pills.append(bt); }
  mapSlot.replaceChildren(mapEl, pills);

  // окно города по образцу владельца (13.11): шапка — метка в мягком квадрате, город крупно, крестик в мягкой квадратной кнопке; тонкая линия;
  // плитки «Открытых» (светло-голубая, папка) и «Решено за месяц» (светло-зелёная, галочка); справа QR на своей светлой подложке; «Главная
  // тема» со значком слоёв; внизу на всю ширину главная кнопка «Подать обращение»
  function cityCard(b) {
    const field = b.kind === 'field';
    const tile = (ic, cls, label, n) => h('div', { class: 'cc-tile ' + cls }, icon(ic, { size: 26 }), h('span', {}, label), h('b', {}, String(n)));   // плитки одного размера
    return h('div', { class: 'citycard' },
      h('div', { class: 'cc-head' }, h('span', { class: 'cc-pin' }, icon('map-pin', { size: 22 })),
        h('div', { class: 'cc-name' }, h('b', {}, field ? 'Объект' : b.city), field ? h('span', {}, 'любой город') : null),
        h('button', { type: 'button', class: 'cc-close', onclick: closeAll, 'aria-label': 'Закрыть' }, icon('x', { size: 20 }))),
      h('div', { class: 'cc-line' }),
      h('div', { class: 'cc-body' },
        field ? h('p', { class: 'small muted cc-field' }, 'Для командированных на объектах по всему Казахстану: город или объект укажете в форме.')
          : h('div', { class: 'cc-tiles' }, tile('folder', 'cc-open', 'Открытых', b.open), tile('check-circle', 'cc-done', ['Решено', h('br'), 'за месяц'], b.done_month)),
        h('div', { class: 'cc-qr-wrap' }, h('img', { class: 'cc-qr', src: b.qr_svg, alt: 'QR ' + (b.city || b.name) })),
        field ? null : h('div', { class: 'cc-theme' }, icon('layers', { size: 22 }), h('span', {}, 'Главная тема: ', h('b', {}, b.top_category || 'открытых обращений нет')))),
      h('a', { href: b.form_url, class: 'btn btn-primary btn-big cc-go' }, 'Подать обращение'));
  }
  function closeAll() { pop.classList.add('hidden'); const s = document.querySelector('.sheet'); if (s) { s.remove(); } const bd = document.querySelector('.sheet-back'); if (bd) bd.remove(); }
  function select(b) {
    selected = b;
    mapEl.select(b.kind === 'field' ? null : b.id);
    for (const x of pills.children) x.classList.toggle('on', String(x.dataset.id) === String(b.id));
    closeAll();
    if (isMobile()) {
      const back = h('div', { class: 'sheet-back', onclick: closeAll });
      const sheet = h('div', { class: 'sheet', role: 'dialog', 'aria-label': b.city || b.name }, h('div', { class: 'grip' }), cityCard(b));   // телефон — шторкой снизу
      document.body.append(back, sheet);
      return;
    }
    // рядом с меткой, но целиком внутри карты: справа от метки, не влезает — слева; по высоте — у метки, прижато к краям с отступом 12 px
    pop.replaceChildren(cityCard(b));
    pop.className = 'citypop measuring';
    const box = mapEl.map.getBoundingClientRect(), pr = pop.getBoundingClientRect(), pad = 12;
    const pos = b.kind === 'field' ? null : mapEl.pos(b.id);
    const mk = pos ? mapEl.map.querySelector('[data-branch="' + b.id + '"]') : null;   // метка вместе с подписью — окно её не закрывает
    const mr = mk ? mk.getBoundingClientRect() : null;
    const my = pos ? pos.y / 100 * box.height : box.height / 2;
    let left = mr ? mr.right - box.left + 16 : (box.width - pr.width) / 2;
    if (mr && left + pr.width > box.width - pad) left = mr.left - box.left - 16 - pr.width;
    left = Math.max(pad, Math.min(box.width - pr.width - pad, left));
    const top = Math.max(pad, Math.min(box.height - pr.height - pad, my - pr.height / 2));
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
    pop.className = 'citypop';
  }
  window.addEventListener('resize', () => { if (selected) { const b = selected; closeAll(); select(b); } });
  mapEl.map.addEventListener('click', e => { if (e.target === mapEl.map || e.target === mapEl.scene || e.target.classList.contains('map-bg') || e.target.classList.contains('map-layer')) closeAll(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });

  const submit = h('button', { type: 'button', class: 'feat', onclick: () => { if (selected) location.href = selected.form_url; else { toast('Сначала выберите город на карте или в списке'); pills.firstChild.focus(); pills.scrollIntoView({ behavior: 'smooth', block: 'center' }); } } },
    h('div', {}, h('b', {}, 'Подать обращение'), h('span', {}, 'Идеи, вопросы, проблемы')));
  const changes = h('a', { href: '/changes', class: 'feat' }, h('div', {}, h('b', {}, 'Результаты обращений'), h('span', {}, 'Что уже сделано по вашим идеям')));
  const statsHref = me && me.role !== 'employee' ? '/panel#/summary' : '/login?next=' + encodeURIComponent('/panel#/summary');
  const stats = h('a', { href: statsHref, class: 'feat' }, h('div', {}, h('b', {}, 'Статистика'), h('span', {}, 'Открытые и решённые')));
  featsSlot.replaceChildren(submit, changes, stats);
  main.append(h('div', { class: 'home-foot' }, h('span', {}, h('a', { href: '/rules' }, 'Как начисляются баллы'), ' — прозрачные правила вместо разовых премий'),
    h('span', {}, 'разработано ', h('b', {}, 'Cyber QALQAN Systems'), ' · данные демонстрационные · ', versionTag())));
  if (!isMobile() && map.branches.length) select(map.branches[0]);   // на ноутбуке сразу показываем головной офис, как на макете
})();
