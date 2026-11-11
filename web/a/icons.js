'use strict';
// Один набор линейных SVG-иконок для всего интерфейса (этап 6 §4): контуры Lucide (ISC, web/a/icons/LICENSE), встроены в страницу,
// цвет наследуется от текста (currentColor) — тёмно-синий или серый. Эмодзи и символы-заменители в интерфейсе не используются.
const ICON_PATHS = {
  mic: ['M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z', 'M19 10v2a7 7 0 0 1-14 0v-2', 'M12 19v3'],
  square: ['M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z'],
  circle: ['M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z'],
  dot: ['M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z'],
  bell: ['M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9', 'M10.3 21a1.94 1.94 0 0 0 3.4 0'],
  star: ['M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2Z'],
  'thumbs-up': ['M7 10v12', 'M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z'],
  heart: ['M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z'],
  sparkles: ['m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3Z', 'M5 3v4', 'M19 17v4', 'M3 5h4', 'M17 19h4'],
  refresh: ['M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8', 'M21 3v5h-5', 'M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16', 'M8 16H3v5'],
  alert: ['m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z', 'M12 9v4', 'M12 17h.01'],
  x: ['M18 6 6 18', 'm6 6 12 12'],
  check: ['M20 6 9 17l-5-5'],
  plus: ['M5 12h14', 'M12 5v14'],
  'arrow-left': ['m12 19-7-7 7-7', 'M19 12H5'],
  'arrow-right': ['M5 12h14', 'm12 5 7 7-7 7'],
  volume: ['M11 5 6 9H2v6h4l5 4V5Z', 'M15.54 8.46a5 5 0 0 1 0 7.07', 'M19.07 4.93a10 10 0 0 1 0 14.14'],
  play: ['m6 3 14 9-14 9V3Z'],
  user: ['M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2', 'M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z'],
  'log-in': ['M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4', 'm10 17 5-5-5-5', 'M15 12H3'],
  send: ['m22 2-7 20-4-9-9-4Z', 'M22 2 11 13'],
  'map-pin': ['M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z', 'M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z'],
  factory: ['M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z', 'M17 18h1', 'M12 18h1', 'M7 18h1'],
  building: ['M4 2h16v20H4z', 'M9 22v-4h6v4', 'M8 6h.01', 'M16 6h.01', 'M12 6h.01', 'M12 10h.01', 'M12 14h.01', 'M16 10h.01', 'M16 14h.01', 'M8 10h.01', 'M8 14h.01'],
  'message': ['M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'],
  'arrows-lr': ['M8 3 4 7l4 4', 'M4 7h16', 'm16 21 4-4-4-4', 'M20 17H4'],
  'qr': ['M3 3h6v6H3z', 'M15 3h6v6h-6z', 'M3 15h6v6H3z', 'M15 15h2v2h-2z', 'M19 15h2v2h-2z', 'M15 19h2v2h-2z', 'M19 19h2v2h-2z'],
  'wand': ['M15 4V2', 'M15 16v-2', 'M8 9h2', 'M20 9h2', 'M17.8 11.8 19 13', 'M15 9h.01', 'M17.8 6.2 19 5', 'm3 21 9-9', 'M12.2 6.2 11 5'],
};
const SVG_NS = 'http://www.w3.org/2000/svg';
// icon('bell') → <svg class="ic">…</svg>; opts: { size, cls, fill, title }
function icon(name, opts) {
  opts = opts || {};
  const paths = ICON_PATHS[name] || ICON_PATHS.circle;
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(opts.size || 18));
  svg.setAttribute('height', String(opts.size || 18));
  svg.setAttribute('fill', opts.fill ? 'currentColor' : 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', String(opts.width || 2));
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', opts.title ? 'false' : 'true');
  svg.setAttribute('class', 'ic' + (opts.cls ? ' ' + opts.cls : ''));
  if (opts.title) { const t = document.createElementNS(SVG_NS, 'title'); t.textContent = opts.title; svg.append(t); }
  for (const d of paths) { const p = document.createElementNS(SVG_NS, 'path'); p.setAttribute('d', d); svg.append(p); }
  return svg;
}
// Иконка + подпись в одной кнопке/строке: iconText('bell', 'Уведомления')
function iconText(name, text, opts) { const s = document.createElement('span'); s.className = 'ict'; s.append(icon(name, opts), document.createTextNode(text)); return s; }
