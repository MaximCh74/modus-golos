'use strict';
// Карта городов (этапы 4, 6, 7): SVG-контуры из Natural Earth (web/a/img/map.svg: страны, едва заметные линии регионов) + маркеры поверх.
// Один компонент для стартовой (без входа: /api/public/map) и панели директора (/api/panel/map: просрочки, «мешают сейчас»).
// Рамка — та же, что в tools/make_map.py (lon 45…82, lat 46.5…60.5). Маркеры позиционируются в процентах через CSSOM (CSP без
// inline-стилей). opts: staff — служебные подписи; legend — легенда (по умолчанию нет); countries — подписи стран (по умолчанию есть);
// crop: {aspect, top} — на стартовой карта показывается более широкой полосой (object-fit: cover, верх обрезки top — доля высоты);
// motion — живая карта (наезд/отъезд, метки по одной; класс .live, анимации в style.css); слой объектов (data.sites) — только при staff.
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
  const box = h('div', { class: 'map' + (opts.crop ? ' cropped' : '') + (opts.motion ? ' live' : '') }, scene);
  box.style.setProperty('--map-ratio', String(F.aspect));   // пропорции блока = пропорции рамки, без искажения
  // обрезка: контейнер шире кадра → картинка масштабируется по ширине, видна полоса высотой visible (доля), начиная с top
  let visible = 1, top = 0;
  const cropActive = () => opts.crop && !window.matchMedia('(max-width: 768px)').matches;
  function layout() {
    if (cropActive()) {
      visible = F.aspect / opts.crop.aspect; top = Math.min(opts.crop.top || 0, 1 - visible);
      box.style.setProperty('--map-aspect', String(opts.crop.aspect));
      img.style.setProperty('--map-pos-y', (visible < 1 ? top / (1 - visible) * 100 : 50) + '%');
    } else { visible = 1; top = 0; }
  }
  layout();
  const place = (el, lat, lng, clamp) => {   // → [x, y] в процентах контейнера; за пределами полосы — класс off (подписи стран — к краю)
    const [x, yi] = mapXY(lat, lng, F);
    let y = (yi - top * 100) / visible;
    if (clamp) y = Math.max(6, Math.min(92, y));
    el.style.left = x + '%'; el.style.top = y + '%';
    el.classList.toggle('off', !clamp && (y < 3 || y > 99));
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
  for (const s of staff ? data.sites || [] : []) {   // объекты командированных — только в панели директора
    if (!mapInside(s.lat, s.lng, F)) { outside.push(s); continue; }
    // объект командированных — точно как город (замечание владельца 13.11): такая же большая метка того же цвета по тому же правилу
    // (зелёная — просрочек нет, красная — есть) и такая же карточка-подпись; отличие — «объект» мелко серым во второй строке
    const sState = s.overdue ? ' m-late' : ' m-ok';
    const sm = h('button', { type: 'button', class: 'marker site' + sState, title: 'Объект командированных: ' + s.city, onclick: () => { if (opts.onSite) opts.onSite(s, sm); } },
      h('span', { class: 'pin' }, icon('map-pin', { size: 30, fill: true, width: 1.5 })),
      h('span', { class: 'mlabel' }, h('b', {}, s.city), h('span', { class: 'm-site' }, 'объект', h('span', { class: 'm-rest' }, ' · ' + s.open + ' откр.' + (s.overdue ? ' · просрочено ' + s.overdue : '')))));
    placed.push([sm, s.lat, s.lng]);
    layerSites.append(sm);
  }
  const order = (data.branches || []).map(b => b.lng).sort((a, b) => a - b);   // порядок появления меток — с запада на восток
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
  // подписи меток не обрезаются краем (замечание владельца 13.11): не влезает справа — ставим слева от метки, у верхнего края — ниже,
  // у нижнего — выше; на телефоне (подпись под булавкой) — к краю или над булавкой. Из вариантов берём первый, где подпись целиком
  // на карте и не закрывает чужие булавки и уже поставленные подписи.
  const FLIPS = ['flip-x', 'flip-r', 'flip-down', 'flip-up'];
  const fitLabels = () => {
    const br = box.getBoundingClientRect();
    if (!br.width || !br.height) return;
    const pad = 4;
    const markers = [...layerBranches.children, ...layerSites.children].filter(m => !m.classList.contains('off') && m.querySelector('.mlabel'));
    const pins = markers.map(m => [m, m.querySelector('.pin').getBoundingClientRect()]);
    const labels = [];
    const inside = r => r.left >= br.left + pad && r.right <= br.right - pad && r.top >= br.top + pad && r.bottom <= br.bottom - pad;
    const cross = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    for (const m of markers) {
      const lab = m.querySelector('.mlabel');
      m.classList.remove(...FLIPS);
      const column = getComputedStyle(m).flexDirection.startsWith('column');
      const variants = column ? ['', 'flip-x', 'flip-r', 'flip-up', 'flip-up flip-x', 'flip-up flip-r'] : ['', 'flip-x', 'flip-down', 'flip-up', 'flip-x flip-down', 'flip-x flip-up'];
      let best = null;
      for (const v of variants) {
        m.classList.remove(...FLIPS);
        if (v) m.classList.add(...v.split(' '));
        const r = lab.getBoundingClientRect();
        const score = (inside(r) ? 0 : 4) + pins.filter(([o, pr]) => o !== m && cross(r, pr)).length + labels.filter(l => cross(r, l)).length;
        if (!best || score < best.score) best = { v, score, r };
        if (!score) break;
      }
      m.classList.remove(...FLIPS);
      if (best.v) m.classList.add(...best.v.split(' '));
      labels.push(best.r);
    }
  };
  const relayout = () => { layout(); for (const [el, lat, lng, clamp] of placed) place(el, lat, lng, clamp); fitLabels(); };
  relayout();
  scene.append(layerCountries, layerSites, layerBranches);
  // пересчёт при любом изменении размеров: карта вставлена или изменилась, подпись стала шире (догрузился шрифт — так «Павлодар»
  // и обрезался у владельца), окно повернули; один раз за кадр
  let fitQueued = false;
  const refit = () => { if (fitQueued) return; fitQueued = true; requestAnimationFrame(() => { fitQueued = false; fitLabels(); }); };
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(refit);
    ro.observe(box);
    for (const lab of scene.querySelectorAll('.mlabel')) ro.observe(lab);
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => fitLabels());   // шрифт догрузился — подписи шире
  window.addEventListener('resize', refit);
  const wrap = h('div', { class: 'mapwrap' }, box);
  if (opts.legend) {
    wrap.append(h('div', { class: 'row small muted mt8 legend' },
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
  return wrap;
}
