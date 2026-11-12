'use strict';
// Раздел «Сотрудники» администратора (этап 8 §4, упрощён по правилам этапа 9): список в пять колонок без редактирования в строках —
// имя (должность мелко), город · отдел, роль, приглашение (чип или «Пригласить»), меню «…». Клик по строке — боковая панель «Сотрудник»
// поверх списка: все поля, блок приглашения (QR, ссылка, «Отправить в WhatsApp», «Скопировать приглашение», карточка PDF, «Выдать заново»),
// «Битрикс24» свёрнуто, «Отключить». Добавление вручную и импорт CSV/Excel — карточками над списком. Горизонтальной прокрутки нет.
const STAFF_UI = { showAdd: false, showImport: false, importResult: null, q: '', showInactive: false, openId: null };

function staffSection(d, reload) {
  const users = d.users || [], invites = d.invites || {};
  const fmtDay = (iso, year) => iso ? new Date(iso).toLocaleDateString('ru-RU', year ? { day: '2-digit', month: '2-digit', year: 'numeric' } : { day: '2-digit', month: '2-digit' }) : '';
  const ROLE_OPTS = [['employee', 'Сотрудник'], ['responsible', 'Ответственный'], ['director', 'Директор'], ['admin', 'Администратор']];
  const ROLE_LBL = Object.fromEntries(ROLE_OPTS);
  const bOf = id => d.branches.find(b => b.id === id) || {}; const dOf = id => (d.departments.find(x => x.id === id) || {}).name || '';
  const post = async (fn, ok) => { try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message, 'bad'); throw e; } };
  const inviteState = u => {
    const inv = invites[u.id];
    if (!u.active) return { code: 'off', label: 'отключён', cls: 'st-rejected' };
    if (u.bitrix_id) return { code: 'bitrix', label: 'Битрикс24', cls: 'st-closed' };
    if (!inv) return { code: 'none' };
    if (inv.status === 'used') return { code: 'used', label: 'в системе с ' + fmtDay(inv.used_at), cls: 'st-done', inv };
    if (inv.status === 'active') return { code: 'active', label: 'до ' + fmtDay(inv.expires_at), cls: 'st-new', inv };
    return { code: inv.status, label: inv.status === 'expired' ? 'истекло' : 'отозвано', cls: 'tag-overdue', inv };
  };
  const issue = async u => { await post(() => API.post('/api/admin/invites', { user_id: u.id }), 'Приглашение выдано: ' + u.name); STAFF_UI.openId = u.id; reload(); };
  const setActive = async (u, active) => {
    await post(() => API.post('/api/admin/users/' + u.id + '/active', { active }), (active ? 'Включён: ' : 'Отключён: ') + u.name);
    STAFF_UI.openId = active ? u.id : null; reload();
  };
  const inviteText = (u, inv) => 'Здравствуйте, ' + u.name.split(' ')[0] + '! Это ваше личное приглашение в «Модус Голос» (ГК «Модус Трейд»): ' + inv.url + ' — откройте ссылку и нажмите «Войти». Паролей нет, ссылка одноразовая, действует до ' + fmtDay(inv.expires_at, true) + '.';
  const waLink = (u, inv) => { const digits = String(u.phone || '').replace(/\D/g, ''); return digits ? 'https://wa.me/' + digits + '?text=' + encodeURIComponent(inviteText(u, inv)) : null; };
  const copy = async (text, ok) => { try { await navigator.clipboard.writeText(text); toast(ok); } catch (e) { toast('Буфер недоступен — скопируйте из ссылки выше'); } };
  const latestInvite = async u => { const inv = invites[u.id]; if (!inv) return null; try { return await API.get('/api/admin/invites/' + inv.id); } catch (e) { return null; } };

  // ---- боковая панель «Сотрудник»
  async function openStaff(u) {
    STAFF_UI.openId = u.id;
    const st = inviteState(u);
    const inv = st.inv && st.code === 'active' ? await latestInvite(u) : null;
    const name = h('input', { type: 'text', value: u.name || '' }); const pos = h('input', { type: 'text', value: u.position || '', placeholder: 'Должность' });
    const role = pick({ value: u.role, options: ROLE_OPTS.map(([v, l]) => ({ value: v, label: l })) });
    const br = pick({ value: u.branch_id || '', placeholder: '— не указан —', options: d.branches.map(b => ({ value: b.id, label: b.city || b.name })) });
    const dep = pick({ value: u.department_id || '', placeholder: '— не указан —', options: d.departments.map(x => ({ value: x.id, label: x.name })) });
    const mgr = pick({ value: u.manager_id || '', placeholder: '— нет —', options: users.filter(x => x.role !== 'employee' && x.active && x.id !== u.id).map(x => ({ value: x.id, label: x.name })) });
    const phone = h('input', { type: 'text', value: u.phone || '', placeholder: '+7 701 000 00 00', inputmode: 'tel' }); const email = h('input', { type: 'text', value: u.email || '', placeholder: 'необязательно' });
    const bx = h('input', { type: 'number', value: u.bitrix_id || '', placeholder: 'ID пользователя портала' });
    const save = h('button', { class: 'btn btn-primary', onclick: async () => {
      save.disabled = true;
      try {
        await API.post('/api/admin/users', { id: u.id, name: name.value, role: role.value, position: pos.value, branch_id: br.value ? Number(br.value) : null, department_id: dep.value ? Number(dep.value) : null, manager_id: mgr.value ? Number(mgr.value) : null, active: !!u.active, email: email.value, bitrix_id: bx.value ? Number(bx.value) : null, phone: phone.value });
        toast('Сохранено: ' + name.value); reload();
      } catch (e) { toast(e.message, 'bad'); save.disabled = false; }
    } }, 'Сохранить');
    const closeBtn = h('button', { class: 'btn btn-sm btn-ghost', title: 'Закрыть (Esc)', onclick: () => { STAFF_UI.openId = null; closeOverlay(); } }, icon('x'));
    let inviteBlock;
    if (st.code === 'bitrix') inviteBlock = h('div', { class: 'card card-info' }, h('b', {}, 'Вход через Битрикс24'), h('div', { class: 'small mt8' }, 'Сотрудник сопоставлен с учётной записью портала — личное приглашение не нужно.'));
    else if (!u.active) inviteBlock = h('div', { class: 'card card-warn' }, h('b', {}, 'Сотрудник отключён'), h('div', { class: 'small mt8' }, 'Не входит ни по приглашению, ни по старой сессии; обращения, баллы и история сохранены.'));
    else if (st.code === 'active' && inv) {
      const link = h('input', { type: 'text', value: inv.url, readonly: true, class: 'inv-link' });
      const wa = waLink(u, inv);
      inviteBlock = h('div', { class: 'card card-ok' },
        h('div', { class: 'row' }, h('b', {}, 'Личное приглашение'), tag('st-new', 'действует до ' + fmtDay(inv.expires_at, true))),
        h('div', { class: 'inv-body mt8' }, h('img', { src: inv.qr_svg, alt: 'QR приглашения', class: 'inv-qr' }),
          h('div', { class: 'inv-text' },
            h('div', { class: 'small' }, 'Сотрудник открывает QR камерой телефона или ссылку, нажимает «Войти» — и телефон запомнил его. Паролей нет, ссылка одноразовая.'),
            h('div', { class: 'row mt8' }, link),
            h('div', { class: 'row mt8' },
              wa ? h('a', { href: wa, class: 'btn btn-sm btn-primary', target: '_blank', rel: 'noopener' }, iconText('message-circle', 'Отправить в WhatsApp')) : h('button', { class: 'btn btn-sm', disabled: true, title: 'Укажите телефон сотрудника' }, iconText('message-circle', 'Отправить в WhatsApp')),
              h('button', { class: 'btn btn-sm', onclick: () => copy(inviteText(u, inv), 'Приглашение скопировано') }, iconText('copy', 'Скопировать приглашение')),
              h('a', { href: inv.card_url, class: 'btn btn-sm', target: '_blank', rel: 'noopener' }, iconText('printer', 'Карточка PDF')),
              h('button', { class: 'btn btn-sm btn-ghost', title: 'Прежняя ссылка сразу перестанет работать, прежний телефон выйдет', onclick: () => issue(u) }, iconText('refresh', 'Выдать заново'))))));
    } else {
      inviteBlock = h('div', { class: 'card card-info' }, h('div', { class: 'row' }, h('b', {}, 'Личное приглашение'), st.label ? tag(st.cls, st.label) : null),
        h('div', { class: 'small mt8' }, st.code === 'used' ? 'Сотрудник уже вошёл по приглашению; «Выдать заново» — если телефон потерян или сменился: прежнее устройство выйдет.' : st.code === 'none' ? 'Ссылка и QR для входа без пароля: сотрудник открывает один раз, устройство запоминает его.' : 'Прежняя ссылка больше не работает — выдайте новую.'),
        h('div', { class: 'row mt8' }, h('button', { class: 'btn btn-sm btn-primary', onclick: () => issue(u) }, iconText('qr', st.code === 'none' ? 'Пригласить' : 'Выдать заново'))));
    }
    const content = h('div', { class: 'staff-drawer' },
      h('div', { class: 'card' },
        h('div', { class: 'row' }, h('span', { class: 'h1 num' }, u.name), tag('tag-type', ROLE_LBL[u.role] || u.role), !u.active ? tag('st-rejected', 'отключён') : null, h('div', { class: 'spacer' }), closeBtn),
        h('div', { class: 'small muted' }, [u.position, bOf(u.branch_id).city || bOf(u.branch_id).name, dOf(u.department_id)].filter(Boolean).join(' · '))),
      inviteBlock,
      h('div', { class: 'card' }, h('b', {}, 'Данные сотрудника'),
        h('div', { class: 'grid2 mt8' }, field('Имя и фамилия', name), field('Должность', pos), field('Роль', role), field('Город / филиал', br), field('Отдел', dep), field('Руководитель', mgr), field('Телефон (WhatsApp)', phone), field('Почта', email)),
        h('details', { class: 'sect mt8' }, h('summary', {}, 'Битрикс24'), h('div', { class: 'mt8' }, field('ID пользователя портала', bx, u.bitrix_id ? 'Сопоставлен с порталом: синхронизация обновляет отдел и должность' : 'Заполняется синхронизацией — по почте или телефону; совпадение только по имени не склеивается — укажите ID вручную'))),
        h('div', { class: 'row mt16' }, save, h('div', { class: 'spacer' }), u.active ? (() => { const off = h('button', { class: 'btn', title: 'Вход закроется, обращения, баллы и история останутся', onclick: () => { if (!off.dataset.armed) { off.dataset.armed = '1'; off.replaceChildren(iconText('user-x', 'Подтвердить отключение')); return; } setActive(u, false); } }, iconText('user-x', 'Отключить')); return off; })() : h('button', { class: 'btn btn-outline', onclick: () => setActive(u, true) }, iconText('user-plus', 'Включить')))));
    openDrawer(content, { label: u.name, onClose: () => { STAFF_UI.openId = null; } });
  }

  // ---- кнопки раздела
  const tools = h('div', { class: 'row staff-tools' },
    h('button', { class: 'btn btn-sm' + (STAFF_UI.showAdd ? ' on' : ''), onclick: () => { STAFF_UI.showAdd = !STAFF_UI.showAdd; reload(); } }, iconText('user-plus', 'Добавить')),
    h('button', { class: 'btn btn-sm' + (STAFF_UI.showImport || STAFF_UI.importResult ? ' on' : ''), onclick: () => { STAFF_UI.showImport = !STAFF_UI.showImport; if (!STAFF_UI.showImport) STAFF_UI.importResult = null; reload(); } }, iconText('upload', 'Импорт CSV или Excel')),
    menuButton([['Шаблон CSV для импорта', () => { location.href = '/api/admin/users/template.csv'; }], ['Карточки PDF: все действующие приглашения', () => window.open('/api/admin/invites/cards.pdf?all=1', '_blank')]], { title: 'Ещё' }));

  // ---- добавить вручную
  let addCard = null;
  if (STAFF_UI.showAdd) {
    const name = h('input', { type: 'text', placeholder: 'Имя Фамилия', autocomplete: 'off' });
    const br = pick({ placeholder: 'Выберите город', options: d.branches.map(b => ({ value: b.id, label: b.city || b.name })) });
    const dep = pick({ placeholder: 'Можно не выбирать', options: d.departments.map(x => ({ value: x.id, label: x.name })) });
    const role = pick({ value: 'employee', options: [{ value: 'employee', label: 'Сотрудник' }, { value: 'responsible', label: 'Ответственный' }] });
    const pos = h('input', { type: 'text', placeholder: 'например, Оператор участка' }); const phone = h('input', { type: 'text', placeholder: '+7 701 000 00 00', inputmode: 'tel' }); const email = h('input', { type: 'text', placeholder: 'необязательно' });
    const inv = h('input', { type: 'checkbox', checked: true });
    const btn = h('button', { class: 'btn btn-primary', onclick: async () => {
      btn.disabled = true;
      try {
        const r = await API.post('/api/admin/users', { name: name.value, role: role.value, position: pos.value, branch_id: br.value ? Number(br.value) : null, department_id: dep.value ? Number(dep.value) : null, manager_id: null, active: true, email: email.value, phone: phone.value, invite: inv.checked });
        toast('Сотрудник добавлен: ' + r.name + (r.invite ? ' — приглашение выдано' : ''));
        STAFF_UI.openId = r.id; STAFF_UI.showAdd = false; reload();
      } catch (e) { toast(e.message, 'bad'); btn.disabled = false; }
    } }, iconText('plus', 'Добавить'));
    addCard = h('div', { class: 'card card-info' }, h('b', {}, 'Новый сотрудник'),
      h('div', { class: 'hint' }, 'Для тех, кого нет в Битрикс24: рабочие, производство, командированные. Телефон нужен, чтобы отправить приглашение в WhatsApp и склеить профиль с порталом, если человек появится и там.'),
      h('div', { class: 'grid3 mt8' }, field('Имя и фамилия', name), field('Город / филиал', br), field('Отдел', dep), field('Роль', role), field('Должность', pos), field('Телефон (WhatsApp)', phone), field('Почта', email)),
      h('div', { class: 'row mt8' }, btn, h('label', { class: 'check small' }, inv, 'сразу выдать личное приглашение — ссылку и QR'), h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-ghost', onclick: () => { STAFF_UI.showAdd = false; reload(); } }, 'Отмена')));
  }

  // ---- импорт списком
  let importCard = null;
  if (STAFF_UI.showImport || STAFF_UI.importResult) {
    const file = filePicker({ accept: '.csv,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', label: 'Выбрать файл CSV или Excel' });
    const inv = h('input', { type: 'checkbox', checked: true });
    const btn = h('button', { class: 'btn btn-primary btn-sm', onclick: async () => {
      if (!file.file()) return toast('Выберите файл CSV или Excel по шаблону', 'bad');
      btn.disabled = true;
      const fd = new FormData(); fd.set('file', file.file()); fd.set('invite', inv.checked ? '1' : '0');
      try { STAFF_UI.importResult = await API.postForm('/api/admin/users/import', fd); STAFF_UI.showImport = true; reload(); } catch (e) { toast(e.message, 'bad'); btn.disabled = false; }
    } }, iconText('upload', 'Импортировать'));
    const r = STAFF_UI.importResult;
    const result = r ? h('div', { class: 'mt8' },
      h('div', { class: 'row' }, r.created ? tag('st-done', 'добавлено ' + r.created) : null, r.updated ? tag('tag-type', 'обновлено ' + r.updated) : null, r.errors.length ? tag('tag-overdue', 'не загружено ' + r.errors.length) : null,
        r.cards_url ? h('a', { href: r.cards_url, class: 'btn btn-sm btn-primary', target: '_blank', rel: 'noopener' }, iconText('printer', 'Карточки для добавленных (' + r.invites.length + ')')) : null,
        h('div', { class: 'spacer' }), h('button', { class: 'btn btn-sm btn-ghost', onclick: () => { STAFF_UI.importResult = null; STAFF_UI.showImport = false; reload(); } }, 'Закрыть')),
      r.errors.length ? h('table', { class: 'tbl mt8' }, h('thead', {}, h('tr', {}, ['Строка', 'Что в файле', 'Почему не загружена'].map(t => h('th', {}, t)))),
        h('tbody', {}, r.errors.map(e => h('tr', { class: 'noclick' }, h('td', { class: 'small' }, String(e.row)), h('td', { class: 'small' }, e.text), h('td', { class: 'small' }, e.error))))) : null,
      r.users.length ? h('div', { class: 'small muted mt8' }, 'Загружены: ' + r.users.map(u => u.name + (u.action === 'updated' ? ' (уже был — дополнен)' : '')).join(', ')) : null) : null;
    importCard = h('div', { class: 'card card-info' }, h('b', {}, 'Импорт списком'),
      h('div', { class: 'hint' }, 'Файл по шаблону: Имя; Город; Отдел; Роль; Телефон; Должность; Почта. Ошибочная строка попадает в отчёт, остальные заводятся; повторы по телефону или почте не плодят дублей.'),
      h('div', { class: 'row mt8' }, file, h('label', { class: 'check small' }, inv, 'новым — сразу приглашения'), btn), result);
  }

  // ---- список
  const counter = h('span', { class: 'small muted' });
  const q = h('input', { type: 'search', class: 'search', placeholder: 'Имя, город, отдел, телефон', value: STAFF_UI.q });
  q.addEventListener('input', () => { STAFF_UI.q = q.value; renderRows(); });
  const showInactive = h('input', { type: 'checkbox', checked: STAFF_UI.showInactive });
  showInactive.addEventListener('change', () => { STAFF_UI.showInactive = showInactive.checked; renderRows(); });
  const tbody = h('tbody', {});
  function row(u) {
    const st = inviteState(u);
    const invCell = st.code === 'none' ? h('button', { class: 'btn btn-sm', onclick: ev => { ev.stopPropagation(); issue(u); } }, iconText('qr', 'Пригласить')) : tag(st.cls, st.label);
    const items = [['Открыть', () => openStaff(u)]];
    if (u.active && st.code !== 'bitrix') items.push([st.code === 'none' ? 'Пригласить' : 'Выдать приглашение заново', () => issue(u)]);
    if (st.code === 'active') items.push(['Скопировать приглашение', async () => { const inv = await latestInvite(u); if (inv) copy(inviteText(u, inv), 'Приглашение скопировано'); }],
      ['Отправить в WhatsApp', async () => { const inv = await latestInvite(u); const wa = inv && waLink(u, inv); if (wa) window.open(wa, '_blank'); else toast('Укажите телефон сотрудника', 'bad'); }],
      ['Карточка PDF', () => window.open('/api/admin/invites/cards.pdf?ids=' + st.inv.id, '_blank')]);
    items.push(u.active ? ['Отключить', () => setActive(u, false)] : ['Включить', () => setActive(u, true)]);
    const menu = menuButton(items);
    menu.addEventListener('click', ev => ev.stopPropagation());
    return h('tr', { class: (u.active ? '' : 'muted') + (STAFF_UI.openId === u.id ? ' sel' : ''), onclick: () => openStaff(u) },
      h('td', {}, h('b', { class: 'num' }, u.name), h('div', { class: 'small muted' }, u.position || '—')),
      h('td', {}, [bOf(u.branch_id).city || bOf(u.branch_id).name, dOf(u.department_id)].filter(Boolean).join(' · ') || '—'),
      h('td', {}, ROLE_LBL[u.role] || u.role),
      h('td', {}, invCell),
      h('td', { class: 'q-menu' }, menu));
  }
  function renderRows() {
    const needle = STAFF_UI.q.trim().toLowerCase();
    const rows = users.filter(u => (STAFF_UI.showInactive || u.active) && (!needle || [u.name, u.position, bOf(u.branch_id).city, bOf(u.branch_id).name, dOf(u.department_id), u.phone, u.email].filter(Boolean).join(' ').toLowerCase().includes(needle)));
    tbody.replaceChildren(...rows.map(row));
    const act = users.filter(u => invites[u.id] && invites[u.id].status === 'active').length;
    counter.textContent = rows.length + ' из ' + users.length + (act ? ' · действующих приглашений ' + act : '');
  }
  renderRows();
  const table = h('table', { class: 'tbl queue staff-tbl' },
    h('colgroup', {}, [null, 220, 150, 190, 56].map(w => { const c = document.createElement('col'); if (w) c.style.width = w + 'px'; return c; })),
    h('thead', {}, h('tr', {}, ['Сотрудник', 'Город · отдел', 'Роль', 'Приглашение', ''].map(t => h('th', {}, t, t === 'Приглашение' ? helpBtn('invite') : null)))), tbody);
  if (STAFF_UI.openId) { const u = users.find(x => x.id === STAFF_UI.openId); if (u) setTimeout(() => openStaff(u), 0); }
  return h('div', { class: 'card staff' },
    h('div', { class: 'row' }, h('b', {}, 'Сотрудники'), counter, h('div', { class: 'spacer' }), tools),
    h('div', { class: 'hint' }, 'Из Битрикс24 сотрудники приходят синхронизацией; рабочих, производство и командированных добавьте здесь и выдайте личное приглашение — ссылку, QR или карточку. Клик по строке — карточка сотрудника.'),
    addCard, importCard,
    h('div', { class: 'row mt8' }, h('div', { class: 'staff-search' }, q), h('label', { class: 'check small' }, showInactive, 'показывать отключённых')),
    h('div', { class: 'mt8' }, table));
}
