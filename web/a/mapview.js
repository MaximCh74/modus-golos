'use strict';
// Карта городов (этапы 4, 6, 7): SVG-контуры из Natural Earth (web/a/img/map.svg: страны, едва заметные линии регионов) + маркеры поверх.
// Один компонент для стартовой (без входа: /api/public/map) и панели директора (/api/panel/map: просрочки, «мешают сейчас»).
// Рамка — та же, что в tools/make_map.py (lon 45…82, lat 46.5…60.5). Маркеры позиционируются в процентах через CSSOM (CSP без
// inline-стилей). opts: staff — служебные подписи; legend — легенда (по умолчанию нет); countries — подписи стран (по умолчанию есть);
// crop: {aspect, top} — на стартовой карта показывается более широкой полосой (object-fit: cover, верх обрезки top — доля высоты);
// motion — живая карта (наезд/отъезд, метки по одной; класс .live, анимации в style.css); слой объектов (data.sites) — везде: у директора
// с цифрами и цветом по просрочкам, на главной — только город и мелко «объект» (замечание владельца 13.11: Атырау вернуть на главную).
// onBranch(b, el), onSite(s, el). Методы: flash(id), select(id|null), pos(id) → {x, y} в процентах контейнера.
// Подписи стран не прячутся за обрезкой: прижимаются к краю полосы (clamp), чтобы «Казахстан» был виден и на широкой ленте ноутбука.
const MAP = { lon0: 45, lon1: 82, lat0: 46.5, lat1: 60.5, aspect: 900 / 579, src: '/a/img/map.svg',
  countries: [{ name: 'Россия', lat: 57.3, lng: 52.5 }, { name: 'Казахстан', lat: 48.3, lng: 66.5 }] };   // «Казахстан» — в центре страны, ниже меток
// карта директора (замечание владельца 13.11): больше России сверху, страны в балансе — 46…86° в. д., 45…62° с. ш. (tools/make_map.py
// --frame); подписи стран — в центре видимой части страны («Россия» чуть выше центроида, чтобы не лечь на Тюмень)
const MAP_DIRECTOR = { lon0: 46, lon1: 86, lat0: 45, lat1: 62, aspect: 900 / 643, src: '/a/img/map-director.svg',
  countries: [{ name: 'Россия', lat: 59.4, lng: 65.1 }, { name: 'Казахстан', lat: 49.15, lng: 67.3 }] };
function mapXY(lat, lng, f) { f = f || MAP; return [(lng - f.lon0) / (f.lon1 - f.lon0) * 100, (f.lat1 - lat) / (f.lat1 - f.lat0) * 100]; }
function mapInside(lat, lng, f) { f = f || MAP; return lat !== null && lat !== undefined && lat >= f.lat0 && lat <= f.lat1 && lng >= f.lon0 && lng <= f.lon1; }

function mapView(data, opts) {
  opts = opts || {};
  const staff = !!opts.staff;
  const F = opts.frame || MAP;
  const img = h('img', { src: F.src, alt: 'Карта городов', class: 'map-bg' });
  const scene = h('div', { class: 'map-scene' }, img);   // всё, что едет вместе с картой при наезде: подложка, слои, карточка города
  const box = h('div', { class: 'map' + (opts.crop ? ' cropped' : '') + (opts.motion ? ' live' : '') + (opts.fill ? ' fill' : '') }, scene);
  box.style.setProperty('--map-ratio', String(F.aspect));   // пропорции блока = пропорции рамки, без искажения
  // обрезка: контейнер шире кадра → картинка масштабируется по ширине, видна полоса высотой visible (доля), начиная с top
  // fill (сводка директора, ТЗ владельца 13.11): блок карты тянется на высоту правой колонки — картинка обрезается по краям (object-fit:
  // cover), окно — по центру разброса меток; колонка ниже — обрезка сверху и снизу. Только от 1200 px, ниже — обычные пропорции рамки
  let visible = 1, top = 0, visX = 1, left = 0;
  const cropActive = () => opts.crop && !window.matchMedia('(max-width: 768px)').matches;
  const fillActive = () => opts.fill && window.matchMedia('(min-width: 900px)').matches;   // телефон — пропорции рамки
  let wrapEl = null, legendEl = null;
  const spanMid = vals => vals.length ? (Math.min(...vals) + Math.max(...vals)) / 2 : 0.5;
  function layout() {
    visX = 1; left = 0;
    if (cropActive()) {
      visible = F.aspect / opts.crop.aspect; top = Math.min(opts.crop.top || 0, 1 - visible);
      box.style.setProperty('--map-aspect', String(opts.crop.aspect));
      img.style.setProperty('--map-pos-y', (visible < 1 ? top / (1 - visible) * 100 : 50) + '%');
    } else if (fillActive() && wrapEl && box.clientWidth && wrapEl.clientHeight) {
      // доступная высота — у обёртки (она тянется на высоту колонки), а не у самой карты: так нет качелей «растянул — сжал»
      const W = box.clientWidth, H = wrapEl.clientHeight - (legendEl ? legendEl.offsetHeight + 8 : 0);
      const ba = W / Math.max(1, H);
      const pts = [...(data.branches || []), ...(data.sites || [])].filter(p => mapInside(p.lat, p.lng, F)).map(p => mapXY(p.lat, p.lng, F));
      const xs = pts.map(p => p[0] / 100), need = xs.length ? Math.min(1, Math.max(...xs) - Math.min(...xs) + 0.06) : 0;   // поля — по полбулавки
      const tooTall = ba / F.aspect < need - 0.01;   // окно уже разброса меток — карту не тянем, метки дороже ровного края (допуск — округление)
      box.classList.toggle('nofill', tooTall);
      if (tooTall) { visible = 1; top = 0; img.style.removeProperty('--map-pos-x'); img.style.removeProperty('--map-pos-y'); return; }
      if (ba > F.aspect) { visible = F.aspect / ba; top = Math.max(0, Math.min(1 - visible, spanMid(pts.map(p => p[1] / 100)) - visible / 2)); }
      else { visible = 1; top = 0; visX = ba / F.aspect; left = Math.max(0, Math.min(1 - visX, spanMid(pts.map(p => p[0] / 100)) - visX / 2)); }
      img.style.setProperty('--map-pos-x', (visX < 1 ? left / (1 - visX) * 100 : 50) + '%');
      img.style.setProperty('--map-pos-y', (visible < 1 ? top / (1 - visible) * 100 : 50) + '%');
    } else { visible = 1; top = 0; img.style.removeProperty('--map-pos-x'); if (opts.fill) img.style.removeProperty('--map-pos-y'); }
  }
  layout();
  const place = (el, lat, lng, clamp) => {   // → [x, y] в процентах контейнера; за пределами окна — класс off (подписи стран — к краю)
    const [xi, yi] = mapXY(lat, lng, F);
    let x = (xi - left * 100) / visX, y = (yi - top * 100) / visible;
    if (clamp) { y = Math.max(6, Math.min(92, y)); x = Math.max(10, Math.min(90, x)); }
    el.style.left = x + '%'; el.style.top = y + '%';
    el.classList.toggle('off', !clamp && (y < 3 || y > 99 || x < 1 || x > 99));
    el.dataset.x = x.toFixed(2); el.dataset.y = y.toFixed(2);
    return [x, y];
  };
  const layerCountries = h('div', { class: 'map-layer' });
  const layerSites = h('div', { class: 'map-layer' });
  const layerBranches = h('div', { class: 'map-layer' });
  const placed = [];
  if (opts.countries !== false) {
    for (const c of F.countries) { const el = h('span', { class: 'map-country' }, c.name); placed.push([el, c.lat, c.lng, true]); layerCountries.append(el); }
  }
  const outside = [];
  const order = [...(data.branches || []), ...(data.sites || [])].map(p => p.lng).sort((a, b) => a - b);   // порядок появления меток — с запада на восток
  for (const s of data.sites || []) {   // объекты командированных — у директора и на главной
    if (!mapInside(s.lat, s.lng, F)) { outside.push(s); continue; }
    // объект командированных — точно как город (замечание владельца 13.11): такая же большая метка того же цвета по тому же правилу
    // (у директора зелёная — просрочек нет, красная — есть; на главной — как города) и такая же карточка-подпись; отличие — «объект»
    // мелко серым во второй строке; служебные цифры (открытые, просрочки) — только у директора
    const sState = !staff ? '' : s.overdue ? ' m-late' : ' m-ok';
    const sm = h('button', { type: 'button', class: 'marker site' + sState, title: 'Объект командированных: ' + s.city, onclick: () => { if (opts.onSite) opts.onSite(s, sm); } },
      h('span', { class: 'pin' }, icon('map-pin', { size: 30, fill: true, width: 1.5 })),
      h('span', { class: 'mlabel' }, h('b', {}, s.city), h('span', { class: 'm-site' }, 'объект',
        staff ? h('span', { class: 'm-rest' }, ' · ' + s.open + ' откр.' + (s.overdue ? ' · просрочено ' + s.overdue : '')) : null)));
    sm.dataset.site = s.city;
    sm.style.setProperty('--i', String(order.indexOf(s.lng)));
    placed.push([sm, s.lat, s.lng]);
    layerSites.append(sm);
  }
  for (const b of data.branches || []) {
    if (!mapInside(b.lat, b.lng, F)) continue;
    const sub = staff ? b.open + ' откр.' + (b.overdue ? ' · просрочено ' + b.overdue : '') : null;   // на главной — только город (замечание 13.11)
    // у директора цвет метки — два цвета (замечание 13.11): зелёная — просрочек нет, красная — есть просрочки
    const state = !staff ? '' : b.overdue ? ' m-late' : ' m-ok';
    const m = h('button', { type: 'button', class: 'marker' + state + (b.kind === 'production' ? ' prod' : ''), title: b.city || brCity(b.name), onclick: () => { if (opts.onBranch) opts.onBranch(b, m); } },
      h('span', { class: 'pin' }, icon('map-pin', { size: 30, fill: true, width: 1.5 })),
      h('span', { class: 'mlabel' }, h('b', {}, b.city), sub ? h('span', {}, sub) : null));   // без «⚠»: «5 откр. · просрочено 2»
    m.dataset.branch = b.id;
    m.style.setProperty('--i', String(order.indexOf(b.lng)));
    placed.push([m, b.lat, b.lng]);
    layerBranches.append(m);
  }
  // подписи меток не обрезаются краем и не наезжают друг на друга (замечания владельца 13.11): у каждой подписи — варианты места (справа,
  // слева, ниже, выше; на телефоне подпись под булавкой — по центру, к краю или над булавкой). Сначала жадно по очереди, потом проходы
  // улучшения: каждая подпись пересматривается при уже стоящих остальных, пока есть пересечения (так «Караганда» уступает место
  // «Усть-Каменогорску»). Где тесно и так (Караганда в 190 км от Астаны — на телефоне это ~25 px), подпись отводится дальше с тонкой
  // линией к булавке (flip-far) — только если без отвода не разойтись; на живой карте стартовой отвода нет.
  const FLIPS = ['flip-x', 'flip-r', 'flip-down', 'flip-up', 'flip-far', 'flip-far2', 'lift-s', 'lift-l', 'flip-side', 'flip-compact'];
  const fitLabels = () => {
    const br = box.getBoundingClientRect();
    if (!br.width || !br.height) return;
    const pad = 4;
    const markers = [...layerBranches.children, ...layerSites.children].filter(m => !m.classList.contains('off') && m.querySelector('.mlabel'));
    if (!markers.length) return;
    for (const m of markers) m.classList.remove(...FLIPS);
    const column = getComputedStyle(markers[0]).flexDirection.startsWith('column');
    // компьютер: сбоку от булавки, выше или ниже на трёх высотах (lift-s / обычная / lift-l); телефон: под булавкой, над ней или сбоку
    const lifts = ['lift-s', '', 'lift-l'];
    const near = column ? ['', 'flip-x', 'flip-r', 'flip-up', 'flip-up flip-x', 'flip-up flip-r', 'flip-side', 'flip-side flip-x']
      : ['', 'flip-x', ...['flip-down', 'flip-up'].flatMap(d => ['', 'flip-x'].flatMap(x => lifts.map(l => [x, d, l].filter(Boolean).join(' '))))];
    const along = column ? near.filter(v => !v.includes('flip-side')) : ['', 'flip-x'];   // отвод — вдоль линии от булавки к подписи
    const far = opts.motion ? [] : [...along.map(v => (v + ' flip-far').trim()), ...along.map(v => (v + ' flip-far flip-far2').trim())];
    const variants = [...near, ...far];
    // самый узкий телефон (360): у объекта, если иначе не разойтись, — только город, без строки «объект» (крайний вариант, штраф 3)
    const variantsFor = i => column && markers[i].querySelector('.m-site') ? [...variants, ...variants.map(v => (v + ' flip-compact').trim())] : variants;
    const pins = markers.map(m => m.querySelector('.pin').getBoundingClientRect());
    const labs = markers.map(m => m.querySelector('.mlabel'));
    const inside = r => r.left >= br.left + pad && r.right <= br.right - pad && r.top >= br.top + pad && r.bottom <= br.bottom - pad;
    const cross = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    const put = (i, v) => { markers[i].classList.remove(...FLIPS); if (v) markers[i].classList.add(...v.split(' ')); };
    const rectOf = {};   // подпись i в варианте v — размер подписи от варианта не зависит, булавки на месте: меряем один раз
    const measure = (i, v) => { const k = i + '|' + v; if (!rectOf[k]) { put(i, v); rectOf[k] = labs[i].getBoundingClientRect(); } return rectOf[k]; };
    // штраф: за краем — 40, за каждую чужую булавку или подпись под подписью — 10, отвод с линией — 1, дальний — 1,5: любой расклад без
    // пересечений лучше любого с пересечением, а отводов — как можно меньше
    const score = (i, v, cur) => {
      const r = measure(i, v);
      return (inside(r) ? 0 : 40) + 10 * pins.filter((p, j) => j !== i && cross(r, p)).length
        + 10 * cur.filter((o, j) => j !== i && o !== null && cross(r, measure(j, o))).length + (v.includes('flip-far2') ? 1.5 : v.includes('flip-far') ? 1 : 0)
        + (v.includes('flip-compact') ? 3 : 0);
    };
    const run = order => {
      const cur = markers.map(() => null);
      const pick = i => { let top = null; for (const v of variantsFor(i)) { const sc = score(i, v, cur); if (!top || sc < top.sc) top = { v, sc }; if (!sc) break; } return top; };
      for (const i of order) cur[i] = pick(i).v;
      for (let pass = 0; pass < 6; pass++) {
        let changed = false;
        for (const i of order) { const now = score(i, cur[i], cur); if (now < 1) continue; const b = pick(i); if (b.sc < now) { cur[i] = b.v; changed = true; } }
        if (!changed) break;
      }
      return { cur, total: order.reduce((n, i) => n + score(i, cur[i], cur), 0) };
    };
    // самые стеснённые (больше всего булавок рядом) — первыми; не разошлись — ещё несколько проходов в другом порядке
    const near2 = i => pins.filter((p, j) => j !== i && Math.abs(p.left - pins[i].left) < 160 && Math.abs(p.top - pins[i].top) < 90).length;
    const base = markers.map((m, i) => i).sort((a, b) => near2(b) - near2(a));
    let best = run(base);
    let seed = 7;
    const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    for (let k = 0; k < 80 && best.total >= 10; k++) {   // замеры закэшированы — перезапуски почти бесплатны
      const order = base.slice();
      for (let i = order.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [order[i], order[j]] = [order[j], order[i]]; }
      const r = run(order);
      if (r.total < best.total) best = r;
    }
    best.cur.forEach((v, i) => put(i, v));
  };
  const relayout = () => { layout(); for (const [el, lat, lng, clamp] of placed) place(el, lat, lng, clamp); fitLabels(); };
  relayout();
  scene.append(layerCountries, layerSites, layerBranches);
  // пересчёт при любом изменении размеров: карта вставлена или изменилась, подпись стала шире (догрузился шрифт — так «Павлодар»
  // и обрезался у владельца), окно повернули; один раз за кадр
  let fitQueued = false;   // в режиме fill размер блока меняет и окно карты — пересчёт меток целиком
  const refit = () => { if (fitQueued) return; fitQueued = true; requestAnimationFrame(() => { fitQueued = false; if (opts.fill) relayout(); else fitLabels(); }); };
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(refit);
    ro.observe(box);
    for (const lab of scene.querySelectorAll('.mlabel')) ro.observe(lab);
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => fitLabels());   // шрифт догрузился — подписи шире
  window.addEventListener('resize', refit);
  const wrap = h('div', { class: 'mapwrap' + (opts.fill ? ' fill' : '') }, box);
  wrapEl = wrap;
  if (opts.legend) {
    wrap.append(legendEl = h('div', { class: 'row small muted mt8 legend' },
      staff ? h('span', { class: 'ict' }, icon('map-pin', { size: 16, fill: true, cls: 'lg-pin m-ok' }), 'просрочек нет') : null,
      staff ? h('span', { class: 'ict' }, icon('map-pin', { size: 16, fill: true, cls: 'lg-pin m-late' }), 'есть просрочки') : h('span', { class: 'ict' }, icon('map-pin', { size: 16, fill: true, cls: 'lg-pin' }), 'офис / производство'),
      staff && (data.unplaced || []).length ? h('span', {}, 'без метки: ' + data.unplaced.map(s => s.city + ' (' + s.total + ')').join(', ') + ' — точку ставит администратор') : null,
      outside.length ? h('span', {}, 'вне рамки: ' + outside.map(s => s.city + ' (' + s.open + ')').join(', ')) : null));
  }
  if (opts.crop) window.addEventListener('resize', relayout);
  wrap.map = box; wrap.scene = scene;
  wrap.flash = branchId => { const m = layerBranches.querySelector('[data-branch="' + branchId + '"]'); if (m) { m.classList.add('blink'); setTimeout(() => m.classList.remove('blink'), 6000); } };
  wrap.select = branchId => { for (const m of layerBranches.children) m.classList.toggle('sel', branchId !== null && String(m.dataset.branch) === String(branchId)); };
  wrap.pos = branchId => { const m = layerBranches.querySelector('[data-branch="' + branchId + '"]'); return m ? { x: Number(m.dataset.x), y: Number(m.dataset.y) } : null; };
  wrap.relayout = relayout;
  // fill: наибольшая высота блока карты, при которой все метки ещё в окне (для сводки: длиннее — прокрутка внутри сводки)
  wrap.fillLimit = () => {
    const xs = [...(data.branches || []), ...(data.sites || [])].filter(p => mapInside(p.lat, p.lng, F)).map(p => mapXY(p.lat, p.lng, F)[0] / 100);
    const need = xs.length ? Math.min(1, Math.max(...xs) - Math.min(...xs) + 0.06) : 1;
    return box.clientWidth / (F.aspect * need);
  };
  // насколько доступная высота (обёртка тянется на высоту колонки) больше этой наибольшей: > 0 — колонку надо укоротить
  wrap.fillExcess = () => wrapEl.clientHeight - (legendEl ? legendEl.offsetHeight + 8 : 0) - wrap.fillLimit();
  return wrap;
}
