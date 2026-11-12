// Service worker (PWA, этап 5): оболочка кэшируется, данные всегда из сети; при потере связи — понятный экран «Нет связи с сервером».
const CACHE = 'mf-shell-v3';   // этап 8 §4: staff.js, invite.js — обновить оболочку у установленных PWA
const SHELL = ['/offline', '/a/style.css', '/a/api.js', '/a/ui.js', '/a/app.js', '/a/panel.js', '/a/meeting.js', '/a/mapview.js', '/a/qr.js', '/a/track.js', '/a/login.js', '/a/index.js', '/a/staff.js', '/a/invite.js', '/a/icons.js', '/a/command.js',
  '/a/img/logo.svg', '/a/fonts/Montserrat.ttf', '/a/img/icons/icon-192.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return;   // данные — только из сети
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/offline')));
    return;
  }
  e.respondWith(fetch(e.request).then(r => { if (r.ok && url.pathname.startsWith('/a/')) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); } return r; })
    .catch(() => caches.match(e.request)));
});
