'use strict';
// Обёртка над fetch: JSON и multipart, ошибки — текстом из detail. SSE — один канал на страницу.
// Внутри iframe Битрикс24 сессия приходит в адресе (?s=…) и уходит заголовком Authorization — cookie третьей стороны может не дойти.
const SID = new URLSearchParams(location.search).get('s');
if (SID && window.history && history.replaceState) { try { history.replaceState(null, '', location.pathname + location.hash); } catch (e) { /* адрес без токена */ } }
const API = {
  async call(method, url, body, isForm) {
    const opt = { method, headers: {}, credentials: 'same-origin' };
    if (SID) opt.headers['Authorization'] = 'Bearer ' + SID;
    if (isForm) opt.body = body;
    else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    const r = await fetch(url, opt);
    let data = null;
    try { data = await r.json(); } catch (e) { /* не JSON */ }
    if (!r.ok) {
      let msg = 'Ошибка ' + r.status;
      if (data && data.detail) msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      const err = new Error(msg); err.status = r.status; throw err;
    }
    return data;
  },
  get(url) { return this.call('GET', url); },
  post(url, body) { return this.call('POST', url, body === undefined ? {} : body); },
  postForm(url, fd) { return this.call('POST', url, fd, true); },
  async me() { try { return await this.get('/api/me'); } catch (e) { return null; } },
  sse(onEvent) {
    if (!window.EventSource) return null;
    const es = new EventSource('/api/events/stream' + (SID ? '?s=' + encodeURIComponent(SID) : ''));
    es.onmessage = ev => { try { onEvent(JSON.parse(ev.data)); } catch (e) { /* пропуск */ } };
    return es;
  },
};
