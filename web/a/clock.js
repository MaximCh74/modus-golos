'use strict';
// Часы по городам на «Сводке» директора (ТЗ владельца 13.11, п. 3). Время — только через зоны IANA (Intl.DateTimeFormat с timeZone),
// никаких зашитых смещений: сменит страна пояс — браузер подтянет это из своей базы часовых поясов. Города — из данных карты
// (/api/panel/map: филиалы и объекты, у каждого timezone), по умолчанию — головной офис (is_hq), выбор запоминается на устройстве.
// Тикает раз в секунду по границе секунды; вкладка скрыта — таймер стоит, вернулись — сразу пересчёт.
const CLOCK_FMT = {};
function clockFmt(tz, kind) {
  const key = tz + '|' + kind;
  if (!CLOCK_FMT[key]) {
    CLOCK_FMT[key] = new Intl.DateTimeFormat('ru-RU', kind === 'time' ? { timeZone: tz, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }
      : kind === 'date' ? { timeZone: tz, weekday: 'long', day: 'numeric', month: 'long' }
      : { timeZone: tz, year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric', hourCycle: 'h23' });
  }
  return CLOCK_FMT[key];
}
// смещение зоны от UTC в минутах на момент date — из правил базы часовых поясов (с переходами на летнее время, если они есть)
function zoneOffsetMin(date, tz) {
  const p = {};
  for (const x of clockFmt(tz, 'parts').formatToParts(date)) p[x.type] = Number(x.value);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour === 24 ? 0 : p.hour, p.minute, p.second);
  return Math.round((asUtc - Math.floor(date.getTime() / 1000) * 1000) / 60000);
}
// «+1 ч к вашему», «то же время», «−1 ч к вашему», «+30 мин к вашему»; deviceOffsetMin — смещение устройства (по умолчанию — текущее)
function zoneDiffText(date, tz, deviceOffsetMin) {
  const dev = deviceOffsetMin === undefined ? -date.getTimezoneOffset() : deviceOffsetMin;
  const d = zoneOffsetMin(date, tz) - dev;
  if (!d) return 'то же время';
  const a = Math.abs(d), hh = Math.floor(a / 60), mm = a % 60;
  return (d > 0 ? '+' : '−') + [hh ? hh + ' ч' : '', mm ? mm + ' мин' : ''].filter(Boolean).join(' ') + ' к вашему';
}
// время в зоне: { hm: '15:04', ss: '07', date: 'пятница, 13 ноября' }
function clockAt(date, tz) {
  const p = {};
  for (const x of clockFmt(tz, 'time').formatToParts(date)) p[x.type] = x.value;
  return { hm: p.hour + ':' + p.minute, ss: p.second, date: clockFmt(tz, 'date').format(date) };
}
// города для часов из данных карты: филиалы и объекты с запада на восток (как метки на карте), без повторов
function clockCities(md) {
  const seen = new Set(), out = [];
  const add = (city, tz, lng, hq) => { if (!city || !tz || seen.has(city)) return; seen.add(city); out.push({ city, tz, lng: lng === null || lng === undefined ? 999 : lng, hq: !!hq }); };
  for (const b of (md && md.branches) || []) add(b.city, b.timezone, b.lng, b.is_hq);
  for (const s of (md && md.sites) || []) add(s.city, s.timezone, s.lng, false);
  return out.sort((a, b) => a.lng - b.lng);
}

function cityClock(md, opts) {
  opts = opts || {};
  const cities = clockCities(md);
  if (!cities.length) return null;
  const key = 'mf.clock.city.' + (opts.userId || 0);
  let saved = null;
  try { saved = localStorage.getItem(key); } catch (e) { /* приватный режим — без памяти */ }
  const hq = cities.find(c => c.hq) || cities[0];
  let cur = cities.find(c => c.city === saved) || hq;
  const hm = h('span', { class: 'clock-hm' }), ss = h('span', { class: 'clock-ss' }), diff = h('span', { class: 'clock-diff' }), date = h('div', { class: 'clock-date' });
  const chips = cities.map(c => h('button', { type: 'button', class: 'chip', 'aria-pressed': 'false', onclick: () => choose(c) }, c.city));
  const box = h('div', { class: 'clock', role: 'group', 'aria-label': 'Часы по городам' },
    h('div', { class: 'clock-face' }, h('span', { class: 'clock-time', 'aria-live': 'off' }, hm, ss), diff), date,
    h('div', { class: 'chips clock-cities' }, chips));
  function render() {
    const now = new Date(), t = clockAt(now, cur.tz);
    hm.textContent = t.hm; ss.textContent = ':' + t.ss; date.textContent = t.date;
    diff.textContent = zoneDiffText(now, cur.tz);
    box.dataset.city = cur.city; box.dataset.tz = cur.tz;
  }
  function choose(c) {
    cur = c;
    try { localStorage.setItem(key, c.city); } catch (e) { /* без памяти */ }
    chips.forEach((el, i) => { const on = cities[i] === c; el.classList.toggle('on', on); el.setAttribute('aria-pressed', on ? 'true' : 'false'); });
    render();
  }
  let timer = null, mounted = false;
  function stop() { clearTimeout(timer); timer = null; }
  function tick() {
    if (box.isConnected) mounted = true;
    else if (mounted) { stop(); document.removeEventListener('visibilitychange', onVis); return; }   // ушли со «Сводки» — часы больше не нужны
    render();
    stop();
    if (!document.hidden) timer = setTimeout(tick, 1000 - (Date.now() % 1000) + 15);   // по границе секунды
  }
  function onVis() { if (document.hidden) stop(); else tick(); }
  document.addEventListener('visibilitychange', onVis);
  choose(cur);
  tick();
  return box;
}
