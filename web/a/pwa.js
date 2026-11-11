'use strict';
// Регистрация service worker (PWA). Нет HTTPS/localhost — браузер просто не зарегистрирует, страница работает как обычно.
if ('serviceWorker' in navigator) { window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => {}); }); }
