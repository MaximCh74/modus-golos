'use strict';
// Страница /bitrix/app без сессии в cookie (перезагрузка фрейма, браузер без партиционированных cookie): если во фрейме ещё жив токен
// сессии (sessionStorage), открываем приложение или панель; иначе просим открыть «Модус Голос» из меню портала — вход произойдёт сам.
(async function () {
  const root = document.getElementById('root');
  const me = await API.me();
  if (me) { location.replace(me.role === 'employee' ? '/app' : '/panel'); return; }
  root.replaceChildren(h('div', { class: 'wrap' }, h('div', { class: 'card card-info' }, h('b', {}, 'Сессия не найдена. '),
    'Откройте «Модус Голос» из левого меню Битрикс24 ещё раз — вход произойдёт автоматически, без пароля.',
    h('div', { class: 'hint mt8' }, 'Если это повторяется — сообщите администратору: портал не передал токен входа.'))));
})();
