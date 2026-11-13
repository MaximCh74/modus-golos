"""Версия сборки (замечание владельца 13.11, п. 0). Cloudflare подменяет «no-cache» сервера на «max-age=14400» — браузер и офлайн-оболочка
четыре часа брали скрипты из своего кэша, и после обновления владелец видел старые экраны. Поэтому ссылки на статику в страницах
получают отпечаток содержимого (`/a/ui.js?v=…`): изменился файл — изменилась ссылка, никакой кэш не мешает. Номер версии в подвале —
короткий хэш коммита (`commit()`), отпечаток всей статики (`build()`) — по нему открытая страница узнаёт, что пора перезагрузиться."""
from __future__ import annotations

import hashlib
import os
import re

from .config import ROOT

WEB = ROOT / "web"
_files: dict[str, tuple[tuple[int, int], str]] = {}
_REF = re.compile(r'((?:src|href)=")/a/([^"?#]+)(")')


def commit() -> str:
    """Короткий хэш коммита: MF_VERSION (Docker без .git) или .git/HEAD → ветка → хэш. Читается при каждом запросе — после коммита
    подвал меняется без перезапуска сервера."""
    env = os.environ.get("MF_VERSION", "").strip()
    if env:
        return env[:12]
    git = ROOT / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        sha = head
        if head.startswith("ref: "):
            ref = head[5:]
            p = git / ref
            if p.is_file():
                sha = p.read_text(encoding="utf-8").strip()
            else:
                m = re.search(r"^([0-9a-f]{40}) " + re.escape(ref) + r"$", (git / "packed-refs").read_text(encoding="utf-8"), re.M)
                sha = m.group(1) if m else ""
        return sha[:7] if re.fullmatch(r"[0-9a-f]{7,40}", sha) else "dev"
    except OSError:
        return "dev"


def file_ver(rel: str) -> str:
    """Отпечаток файла web/<rel> (10 знаков md5); пересчитывается только при изменении размера или времени файла."""
    p = WEB / rel
    try:
        st = p.stat()
    except OSError:
        return ""
    key = (st.st_mtime_ns, st.st_size)
    c = _files.get(rel)
    if c and c[0] == key:
        return c[1]
    h = hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest()[:10]
    _files[rel] = (key, h)
    return h


def build() -> str:
    """Отпечаток всей статики и страниц: меняется при любой правке web/."""
    acc = hashlib.md5(usedforsecurity=False)
    for p in sorted(WEB.rglob("*")):
        if p.is_file():
            rel = p.relative_to(WEB).as_posix()
            acc.update(f"{rel}:{file_ver(rel)};".encode())
    return acc.hexdigest()[:10]


def stamp(html: str) -> str:
    """Ссылки на /a/… — с отпечатком содержимого; в <head> — отпечаток сборки для pwa.js."""
    def ref(m):
        v = file_ver("a/" + m.group(2))
        return f"{m.group(1)}/a/{m.group(2)}?v={v}{m.group(3)}" if v else m.group(0)
    html = _REF.sub(ref, html)
    meta = f'<meta name="mf-build" content="{build()}">'
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n{meta}', 1)
    return html.replace("<head>", f"<head>\n{meta}", 1)


def page(name: str) -> str:
    return stamp((WEB / name).read_text(encoding="utf-8"))
