"""Tiny in-memory pub/sub for streaming process-pipeline progress to one HTTP
subscriber. Single-process, single-user; no retention, no fan-out, no GC."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Callable


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


# Max serialized payload bytes per stage event. Beyond this we truncate the
# largest list-typed field and mark "truncated": True so the UI can show a
# "view full via /trace" hint.
_PAYLOAD_MAX_BYTES = 4096


def _truncate_payload(payload: dict) -> dict:
    """Trim oversized payloads. Returns a (possibly) new dict tagged with
    truncated=True when shrinking was needed."""
    serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized) <= _PAYLOAD_MAX_BYTES:
        return payload
    trimmed = dict(payload)
    list_fields = [(k, v) for k, v in trimmed.items() if isinstance(v, list)]
    if list_fields:
        for k, v in list_fields:
            trimmed[k] = v[: max(5, len(v) // 2)]
        if len(json.dumps(trimmed, ensure_ascii=False)) > _PAYLOAD_MAX_BYTES:
            for k, _ in list_fields:
                trimmed[k] = trimmed[k][:5]
    trimmed["truncated"] = True
    return trimmed


def make_emitter(entry_id: int, started_perf: float) -> Callable[..., None]:
    """Return a callable `emit(stage, status, **extra)` bound to this entry.

    `extra` may include `summary: str`, `payload: dict`, `error: dict` plus
    legacy fields for backward compat. `payload` is truncated if it exceeds
    _PAYLOAD_MAX_BYTES when serialized.
    """
    init(entry_id)

    def emit(stage: str, status: str, **extra: Any) -> None:
        if "payload" in extra and isinstance(extra["payload"], dict):
            extra["payload"] = _truncate_payload(extra["payload"])
        event: dict[str, Any] = {
            "type": "stage",
            "stage": stage,
            "status": status,
            "elapsed_ms": int((time.perf_counter() - started_perf) * 1000),
            **extra,
        }
        publish(entry_id, event)

    return emit


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
