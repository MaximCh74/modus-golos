'use strict';
// Регистрация service worker (PWA). Нет HTTPS/localhost — браузер просто не зарегистрирует, страница работает как обычно.
// updateViaCache: 'none' — sw.js всегда сверяется с сервером, а не с кэшем браузера (Cloudflare даёт статике 4 часа кэша).
if ('serviceWorker' in navigator) { window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' }).catch(() => {}); }); }

// Обновление само (13.11, п. 0): приложение на телефоне неделями живёт в фоне и не перезагружается. Вернулись на вкладку — сверяем
// отпечаток сборки со своим (meta mf-build, его ставит сервер); другой — перезагружаемся, если ничего не потеряется: нет набранного
// текста, не идёт запись голоса или совещания. Иначе — сверим в следующий раз.
(function () {
  const meta = document.querySelector('meta[name="mf-build"]');
  const mine = meta && meta.content;
  if (!mine) return;
  let last = Date.now();
  const busy = () => !!document.querySelector('.recording')
    || (typeof MEETING !== 'undefined' && MEETING.rec && MEETING.rec.state !== 'inactive')
    || [...document.querySelectorAll('textarea, input:not([type]), input[type=text], input[type=search], input[type=tel]')].some(el => el.value && el.value.trim());
  async function check() {
    if (document.visibilityState !== 'visible' || Date.now() - last < 60000) return;
    last = Date.now();
    try {
      const cfg = await (await fetch('/api/public/config', { cache: 'no-store', credentials: 'same-origin' })).json();
      if (cfg.build && cfg.build !== mine && !busy()) location.reload();
    } catch (_) { /* нет связи — сверим позже */ }
  }
  document.addEventListener('visibilitychange', check);
  window.addEventListener('focus', check);
})();
