'use strict';
// Карта городов (этапы 4, 6, 7): SVG-контуры из Natural Earth (web/a/img/map.svg: страны, едва заметные линии регионов) + маркеры поверх.
// Один компонент для стартовой (без входа: /api/public/map) и панели директора (/api/panel/map: просрочки, «мешают сейчас»).
// Рамка — та же, что в tools/make_map.py (lon 45…82, lat 46.5…60.5). Маркеры позиционируются в процентах через CSSOM (CSP без
// inline-стилей). opts: staff — служебные подписи; legend — легенда (по умолчанию нет); countries — подписи стран (по умолчанию есть);
// crop: {aspect, top} — на стартовой карта показывается более широкой полосой (object-fit: cover, верх обрезки top — доля высоты);
// onBranch(b, el), onSite(s, el). Методы: flash(id), select(id|null), pos(id) → {x, y} в процентах контейнера.
const MAP = { lon0: 45, lon1: 82, lat0: 46.5, lat1: 60.5, aspect: 900 / 579 };
// Подписи стран не прячутся за обрезкой: прижимаются к краю полосы (clamp), чтобы «Казахстан» был виден и на широкой ленте ноутбука.
const MAP_COUNTRIES = [{ name: 'Россия', lat: 57.3, lng: 52.5 }, { name: 'Казахстан', lat: 48.3, lng: 66.5 }];   // «Казахстан» — в центре страны, ниже меток
function mapXY(lat, lng) { return [(lng - MAP.lon0) / (MAP.lon1 - MAP.lon0) * 100, (MAP.lat1 - lat) / (MAP.lat1 - MAP.lat0) * 100]; }
function mapInside(lat, lng) { return lat !== null && lat !== undefined && lat >= MAP.lat0 && lat <= MAP.lat1 && lng >= MAP.lon0 && lng <= MAP.lon1; }

function mapView(data, opts) {
  opts = opts || {};
  const staff = !!opts.staff;
  const img = h('img', { src: '/a/img/map.svg', alt: 'Карта городов', class: 'map-bg' });
  const box = h('div', { class: 'map' + (opts.crop ? ' cropped' : '') }, img);
  // обрезка: контейнер шире кадра → картинка масштабируется по ширине, видна полоса высотой visible (доля), начиная с top
  let visible = 1, top = 0;
  const cropActive = () => opts.crop && !window.matchMedia('(max-width: 768px)').matches;
  function layout() {
    if (cropActive()) {
      visible = MAP.aspect / opts.crop.aspect; top = Math.min(opts.crop.top || 0, 1 - visible);
      box.style.setProperty('--map-aspect', String(opts.crop.aspect));
      img.style.setProperty('--map-pos-y', (visible < 1 ? top / (1 - visible) * 100 : 50) + '%');
    } else { visible = 1; top = 0; }
  }
  layout();
  const place = (el, lat, lng, clamp) => {   // → [x, y] в процентах контейнера; за пределами полосы — класс off (подписи стран — к краю)
    const [x, yi] = mapXY(lat, lng);
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
    for (const c of MAP_COUNTRIES) { const el = h('span', { class: 'map-country' }, c.name); placed.push([el, c.lat, c.lng, true]); layerCountries.append(el); }
  }
  const outside = [];
  for (const s of staff ? data.sites || [] : []) {   // объекты командированных — только в панели директора
    if (!mapInside(s.lat, s.lng)) { outside.push(s); continue; }
    const sm = h('button', { type: 'button', class: 'marker site', title: 'Объект: ' + s.city + ' · открытых ' + s.open, onclick: () => { if (opts.onSite) opts.onSite(s, sm); } },
      h('span', { class: 'sdot' }), staff ? h('span', { class: 'mlabel' }, s.city + ' · ' + s.open) : null);
    placed.push([sm, s.lat, s.lng]);
    layerSites.append(sm);
  }
  for (const b of data.branches || []) {
    if (!mapInside(b.lat, b.lng)) continue;
    const sub = b.kind === 'production' ? 'производство' : staff ? b.open + ' откр.' + (b.overdue ? ' · просрочено ' + b.overdue : '') : (b.code === 'OMSK' ? 'головной офис' : null);
    const m = h('button', { type: 'button', class: 'marker' + (staff && b.overdue ? ' warn' : '') + (b.kind === 'production' ? ' prod' : ''), title: b.name, onclick: () => { if (opts.onBranch) opts.onBranch(b, m); } },
      h('span', { class: 'pin' }, icon('map-pin', { size: 30, fill: true, width: 1.5 })),
      h('span', { class: 'mlabel' }, h('b', {}, b.city), sub ? h('span', {}, sub) : null, staff && b.overdue ? icon('alert', { size: 12, cls: 'warn-ic' }) : null));
    m.dataset.branch = b.id;
    placed.push([m, b.lat, b.lng]);
    layerBranches.append(m);
  }
  const relayout = () => { layout(); for (const [el, lat, lng, clamp] of placed) place(el, lat, lng, clamp); };
  relayout();
  box.append(layerCountries, layerSites, layerBranches);
  const wrap = h('div', { class: 'mapwrap' }, box);
  if (opts.legend) {
    wrap.append(h('div', { class: 'row small muted mt8 legend' },
      h('span', { class: 'ict' }, icon('map-pin', { size: 16, fill: true, cls: 'lg-pin' }), 'офис / производство'),
      h('span', { class: 'ict' }, h('span', { class: 'sdot lg' }), 'объекты — командированные (по городу из QR)'),
      staff ? h('span', { class: 'ict' }, icon('alert', { size: 14 }), 'есть просроченные') : null,
      outside.length ? h('span', {}, 'вне рамки: ' + outside.map(s => s.city + ' (' + s.open + ')').join(', ')) : null));
  }
  if (opts.crop) window.addEventListener('resize', relayout);
  wrap.map = box;
  wrap.flash = branchId => { const m = layerBranches.querySelector('[data-branch="' + branchId + '"]'); if (m) { m.classList.add('blink'); setTimeout(() => m.classList.remove('blink'), 6000); } };
  wrap.select = branchId => { for (const m of layerBranches.children) m.classList.toggle('sel', branchId !== null && String(m.dataset.branch) === String(branchId)); };
  wrap.pos = branchId => { const m = layerBranches.querySelector('[data-branch="' + branchId + '"]'); return m ? { x: Number(m.dataset.x), y: Number(m.dataset.y) } : null; };
  wrap.relayout = relayout;
  return wrap;
}
