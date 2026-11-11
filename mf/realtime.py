"""Real-time: SSE-канал на пользователя. Подписчики живут в памяти процесса (один воркер — для демо и пилота достаточно)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field


@dataclass
class Sub:
    user_id: int
    role: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=200))
    loop: asyncio.AbstractEventLoop | None = None


_subs: list[Sub] = []


def _put_now(sub: Sub, event: dict) -> None:
    try:
        sub.queue.put_nowait(event)
    except asyncio.QueueFull:
        pass


def _put(sub: Sub, event: dict) -> None:
    """Из потока обработки совещания (threadpool) — через call_soon_threadsafe, иначе очередь не разбудит поток SSE."""
    loop = sub.loop
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if loop is not None and running is not loop:
        loop.call_soon_threadsafe(_put_now, sub, event)
    else:
        _put_now(sub, event)


def publish(user_id: int | None, event: dict) -> None:
    if user_id is None:
        return
    for s in _subs:
        if s.user_id == user_id:
            _put(s, event)


def publish_roles(roles, event: dict) -> None:
    for s in _subs:
        if s.role in roles:
            _put(s, event)


def publish_all(event: dict) -> None:
    for s in _subs:
        _put(s, event)


async def stream(user: dict, request):
    sub = Sub(user["id"], user["role"], loop=asyncio.get_running_loop())
    _subs.append(sub)
    try:
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                ev = await asyncio.wait_for(sub.queue.get(), timeout=15)
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": ping\n\n"
    finally:
        if sub in _subs:
            _subs.remove(sub)
