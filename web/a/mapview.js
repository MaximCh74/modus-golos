'use strict';
// Карта филиалов (этап 4): SVG-контуры из Natural Earth (web/a/img/map.svg, без внешних тайлов) + маркеры в стиле сайта
// (красная метка в круге). Проекция та же, что в tools/make_map.py. Клик по городу → очередь филиала; новое обращение — маркер мигает.
const MAP = { lon0: 44, lon1: 92, lat0: 38, lat1: 64, w: 900, h: 520 };
function mapXY(lat, lng) { return [(lng - MAP.lon0) / (MAP.lon1 - MAP.lon0) * 100, (MAP.lat1 - lat) / (MAP.lat1 - MAP.lat0) * 100]; }

function mapView(data, opts) {
  opts = opts || {};
  const box = h('div', { class: 'map' }, h('img', { src: '/a/img/map.svg', alt: 'Карта', class: 'map-bg' }));
  const layerSites = h('div', { class: 'map-layer' });
  const layerBranches = h('div', { class: 'map-layer' });
  for (const b of data.branches) {
    const [x, y] = mapXY(b.lat, b.lng);
    const m = h('div', { class: 'marker' + (b.overdue ? ' warn' : '') + (b.kind === 'production' ? ' prod' : ''), style: 'left:' + x + '%;top:' + y + '%', title: b.name, onclick: () => { if (opts.onBranch) opts.onBranch(b); } },
      h('div', { class: 'pin' }, h('span', {}, '●')),
      h('div', { class: 'mlabel' }, h('b', {}, b.city), h('span', {}, ' ' + b.open + ' откр.' + (b.overdue ? ' · ⚠ ' + b.overdue : ''))));
    m.dataset.branch = b.id;
    layerBranches.append(m);
  }
  for (const s of data.sites) {
    if (!s.lat) continue;
    const [x, y] = mapXY(s.lat, s.lng);
    layerSites.append(h('div', { class: 'marker site', style: 'left:' + x + '%;top:' + y + '%', title: 'Объект: ' + s.city + ' · ' + s.numbers.join(', '), onclick: () => { if (opts.onSite) opts.onSite(s); } },
      h('div', { class: 'pin' }, h('span', {}, '▲')), h('div', { class: 'mlabel' }, h('b', {}, s.city), h('span', {}, ' ' + s.open))));
  }
  box.append(layerSites, layerBranches);
  const legend = h('div', { class: 'row small muted mt8' }, h('span', {}, h('span', { class: 'lg-dot' }), ' офис / производство'), h('span', {}, h('span', { class: 'lg-dot site' }), ' слой «Объекты» — командированные (по городу из QR)'), h('span', {}, '⚠ — есть просроченные'));
  const wrap = h('div', {}, box, legend);
  wrap.flash = branchId => { const m = layerBranches.querySelector('[data-branch="' + branchId + '"]'); if (m) { m.classList.add('blink'); setTimeout(() => m.classList.remove('blink'), 6000); } };
  return wrap;
}
