'use strict';
// Карта городов (этапы 4 и 6): SVG-контуры из Natural Earth (web/a/img/map.svg, без внешних тайлов) + маркеры поверх. Один компонент
// для стартовой страницы (без входа: /api/public/map) и панели директора (/api/panel/map: просрочки, «мешают сейчас»).
// Рамка — та же, что в tools/make_map.py (lon 45…82, lat 46.5…60.5): маркеры позиционируются в процентах через CSSOM
// (CSP без inline-стилей запрещает атрибут style). Клик по городу → opts.onBranch(b); новое обращение → flash(id).
const MAP = { lon0: 45, lon1: 82, lat0: 46.5, lat1: 60.5 };
function mapXY(lat, lng) { return [(lng - MAP.lon0) / (MAP.lon1 - MAP.lon0) * 100, (MAP.lat1 - lat) / (MAP.lat1 - MAP.lat0) * 100]; }
function mapInside(lat, lng) { return lat !== null && lat !== undefined && lat >= MAP.lat0 && lat <= MAP.lat1 && lng >= MAP.lon0 && lng <= MAP.lon1; }

function mapView(data, opts) {
  opts = opts || {};
  const staff = !!opts.staff;
  const box = h('div', { class: 'map' }, h('img', { src: '/a/img/map.svg', alt: 'Карта городов', class: 'map-bg' }));
  const layerSites = h('div', { class: 'map-layer' });
  const layerBranches = h('div', { class: 'map-layer' });
  const outside = [];
  for (const s of data.sites || []) {
    if (!mapInside(s.lat, s.lng)) { outside.push(s); continue; }
    const [x, y] = mapXY(s.lat, s.lng);
    const sm = h('button', { type: 'button', class: 'marker site', title: 'Объект: ' + s.city + ' · открытых ' + s.open, onclick: () => { if (opts.onSite) opts.onSite(s); } },
      h('span', { class: 'sdot' }), staff ? h('span', { class: 'mlabel' }, s.city + ' · ' + s.open) : null);
    sm.style.left = x + '%'; sm.style.top = y + '%';
    layerSites.append(sm);
  }
  for (const b of data.branches || []) {
    if (!mapInside(b.lat, b.lng)) continue;
    const [x, y] = mapXY(b.lat, b.lng);
    const sub = b.kind === 'production' ? 'производство' : staff ? b.open + ' откр.' + (b.overdue ? ' · просрочено ' + b.overdue : '') : (b.code === 'OMSK' ? 'головной офис' : null);
    const m = h('button', { type: 'button', class: 'marker' + (staff && b.overdue ? ' warn' : '') + (b.kind === 'production' ? ' prod' : ''), title: b.name, onclick: () => { if (opts.onBranch) opts.onBranch(b); } },
      h('span', { class: 'pin' }, icon('map-pin', { size: 30, fill: true, width: 1.5 })),
      h('span', { class: 'mlabel' }, h('b', {}, b.city), sub ? h('span', {}, sub) : null, staff && b.overdue ? icon('alert', { size: 12, cls: 'warn-ic' }) : null));
    m.style.left = x + '%'; m.style.top = y + '%';
    m.dataset.branch = b.id;
    layerBranches.append(m);
  }
  box.append(layerSites, layerBranches);
  const legend = h('div', { class: 'row small muted mt8 legend' },
    h('span', { class: 'ict' }, icon('map-pin', { size: 16, fill: true, cls: 'lg-pin' }), 'офис / производство'),
    h('span', { class: 'ict' }, h('span', { class: 'sdot lg' }), 'объекты — командированные (по городу из QR)'),
    staff ? h('span', { class: 'ict' }, icon('alert', { size: 14 }), 'есть просроченные') : null,
    outside.length ? h('span', {}, 'вне рамки: ' + outside.map(s => s.city + ' (' + s.open + ')').join(', ')) : null);
  const wrap = h('div', { class: 'mapwrap' }, box, legend);
  wrap.flash = branchId => { const m = layerBranches.querySelector('[data-branch="' + branchId + '"]'); if (m) { m.classList.add('blink'); setTimeout(() => m.classList.remove('blink'), 6000); } };
  wrap.select = branchId => { for (const m of layerBranches.children) m.classList.toggle('sel', String(m.dataset.branch) === String(branchId)); };
  return wrap;
}
