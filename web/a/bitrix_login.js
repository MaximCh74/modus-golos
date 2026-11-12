'use strict';
// /bitrix/login без заголовка Sec-Fetch-Dest: в обычном окне — на страницу авторизации портала; внутри фрейма портала OAuth запускать нельзя
// (auth2.bitrix24.net запрещает встраивание — в Firefox это была ошибка «will not allow … to display the page») → восстановление входа.
(function () {
  const meta = document.querySelector('meta[name="mf-authorize"]');
  if (window.self !== window.top) { location.replace('/bitrix/app'); return; }
  if (meta && meta.content) location.replace(meta.content);
})();
