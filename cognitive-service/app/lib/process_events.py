"""Tiny in-memory pub/sub for streaming process-pipeline progress to one HTTP
subscriber. Single-process, single-user; no retention, no fan-out, no GC."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator


class _Channel:
    __slots__ = ("events", "wake", "done")
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.wake: asyncio.Event = asyncio.Event()
        self.done: bool = False


_channels: dict[int, _Channel] = {}


def init(entry_id: int) -> None:
    _channels.setdefault(entry_id, _Channel())


def publish(entry_id: int, event: dict[str, Any]) -> None:
    ch = _channels.setdefault(entry_id, _Channel())
    ch.events.append(event)
    ch.wake.set()


def finish(entry_id: int) -> None:
    ch = _channels.get(entry_id)
    if ch:
        ch.done = True
        ch.wake.set()


async def subscribe(entry_id: int) -> AsyncIterator[dict[str, Any]]:
    ch = _channels.get(entry_id)
    if not ch:
        return
    cursor = 0
    try:
        while True:
            while cursor < len(ch.events):
                yield ch.events[cursor]
                cursor += 1
            if ch.done:
                return
            ch.wake.clear()
            await ch.wake.wait()
    finally:
        if ch.done:
            _channels.pop(entry_id, None)
