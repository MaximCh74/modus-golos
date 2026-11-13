'use strict';
// Личное приглашение сотрудника без Битрикса (этап 8 §4): /i/<token> → кто приглашён → одна кнопка «Войти» (ссылка одноразовая)
// → долгая сессия, телефон помнит сотрудника → приложение. Состояния: использована, истекла, отозвана, учётка отключена, нет такой.
(async function () {
  const root = document.getElementById('root');
  const token = decodeURIComponent((location.pathname.split('/i/')[1] || '').split('/')[0]);
  const api = '/api/public/invite/' + encodeURIComponent(token);
  const brand = () => h('div', { class: 'hero dots' }, h('a', { href: '/', class: 'brand' }, h('img', { src: '/a/img/logo.svg', alt: 'Модус Трейд' })), h('div', { class: 'lbl mt16' }, 'Модус Голос · каждый голос услышан'));
  const page = h('div', { class: 'wrap invite' }, brand());
  root.replaceChildren(page);
  let info;
  try { info = await API.get(api); } catch (e) { info = { status: e.status === 429 ? 'busy' : 'missing', text: e.message }; }
  render(info);

  function fmtDay(iso) { return iso ? new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' }) : ''; }

  function render(info) {
    page.replaceChildren(brand());
    const u = info.user || null;
    if (info.status === 'active') {
      const btn = h('button', { class: 'btn btn-primary btn-big mt16' }, 'Войти');
      btn.addEventListener('click', async () => {
        btn.disabled = true; btn.replaceChildren('Входим…');
        try {
          const me = await API.post(api + '/accept');
          page.replaceChildren(brand(), h('div', { class: 'h1' }, 'Готово'), h('div', { class: 'card card-ok' }, h('b', {}, 'Вы вошли как ' + me.name + '.'),
            h('div', { class: 'small mt8' }, 'Телефон запомнил вас: в следующий раз просто откройте «Модус Голос». Открываем приложение…')));
          setTimeout(() => { location.href = me.home || '/app'; }, 900);
        } catch (e) {
          toast(e.message, 'bad'); btn.disabled = false; btn.replaceChildren(iconText('log-in', 'Войти'));
          if (e.status === 410 || e.status === 403 || e.status === 404) setTimeout(() => location.reload(), 1600);
        }
      });
      page.append(h('div', { class: 'h1' }, 'Здравствуйте, ' + u.first_name + '!'),
        h('div', { class: 'card card-info' }, h('div', {}, 'Это ваше личное приглашение в «Модус Голос» — здесь вопрос или идея сотрудника не теряется: видно, кто отвечает и что уже сделано.'),
          h('div', { class: 'mt8' }, h('b', {}, u.name), h('div', { class: 'small muted' }, [u.branch || u.city, u.department, u.position].filter(Boolean).join(' · ')))),
        h('p', { class: 'muted small' }, 'Паролей нет: нажмите кнопку — и телефон запомнит вас. Ссылка работает один раз' + (info.expires_at ? ', до ' + fmtDay(info.expires_at) : '') + '.'),
        btn);
    } else if (info.status === 'already_in') {
      page.append(h('div', { class: 'h1' }, 'Вы уже вошли'),
        h('div', { class: 'card card-ok' }, h('b', {}, u ? u.name : ''), h('div', { class: 'small mt8' }, 'Это устройство уже помнит вас — приглашение не нужно открывать снова.')),
        h('a', { href: info.home || '/app', class: 'btn btn-primary btn-big mt16' }, 'Открыть приложение'));
    } else {
      const titles = { used: 'Ссылка уже использована', expired: 'Срок приглашения истёк', revoked: 'Приглашение отозвано', deactivated: 'Учётная запись отключена', missing: 'Приглашение не найдено', busy: 'Слишком много попыток' };
      page.append(h('div', { class: 'h1' }, titles[info.status] || 'Приглашение недействительно'),
        h('div', { class: 'card card-warn' }, info.text || 'Попросите администратора выдать новое приглашение.', u ? h('div', { class: 'small muted mt8' }, 'Приглашение для: ' + u.name) : null),
        h('p', { class: 'muted small' }, 'Сообщить о проблеме или идее можно и без входа — по QR-плакату филиала. Вход нужен для «Моих обращений», баллов и наград.'));
    }
    page.append(h('div', { class: 'dev' }, 'разработано ', h('b', {}, 'Cyber QALQAN Systems'), ' · «Модус Голос» — каждый голос услышан'));
  }
})();
