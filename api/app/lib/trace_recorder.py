"""TraceRecorder — buffered writer for agent execution traces.

One TraceRecorder corresponds to one user-question turn. It collects events
(LLM rounds and tool calls) with monotonic seq numbers, then bulk-writes to
the query_traces table on flush().

Usage::

    rec = TraceRecorder(session_id, turn_index)
    async with rec.llm_round(round_num=1) as ev:
        ev.set_request({"system": ..., "messages": [...], "tools": [...]})
        result = await call_llm(...)
        ev.set_response({"finish_reason": ..., "message": ..., "usage": ...})

    async with rec.tool_call(round_num=1, tool="recall_raw") as ev:
        ev.set_request({"query": "..."})
        out = await execute_tool(...)
        ev.set_response({"summary": ..., "detail": ...})

    rec.flush()  # one bulk INSERT

Exceptions inside the `async with` blocks are captured into ev.error and the
event is still persisted on flush — so trace contains failures too.

Field size cap: each request_json / response_json is capped at 512 KB. When a
payload exceeds that it is replaced with a small marker JSON containing a size
hint and a 2KB preview, so the row stays small but you know data was dropped.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from app.lib.db import get_conn

_MAX_FIELD_BYTES = 512 * 1024


def _safe_dump(obj: Any) -> str:
    if obj is None:
        return "null"
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps(
            {"_error": f"json_encode_failed: {exc}"}, ensure_ascii=False
        )
    if len(s.encode("utf-8")) <= _MAX_FIELD_BYTES:
        return s
    return json.dumps(
        {
            "_truncated": True,
            "_size_bytes": len(s.encode("utf-8")),
            "_preview": s[:2000],
        },
        ensure_ascii=False,
    )


class _Event:
    __slots__ = (
        "seq", "round_num", "event_type", "tool_name",
        "request", "response", "latency_ms", "error", "_started",
    )

    def __init__(self, seq: int, round_num: int | None, event_type: str,
                 tool_name: str | None = None) -> None:
        self.seq = seq
        self.round_num = round_num
        self.event_type = event_type
        self.tool_name = tool_name
        self.request: Any = None
        self.response: Any = None
        self.latency_ms: int | None = None
        self.error: str | None = None
        self._started = time.monotonic()

    def set_request(self, req: Any) -> None:
        self.request = req

    def set_response(self, resp: Any) -> None:
        self.response = resp


class TraceRecorder:
    def __init__(self, session_id: str, turn_index: int) -> None:
        self.session_id = session_id
        self.turn_index = turn_index
        self._events: list[_Event] = []
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    @asynccontextmanager
    async def llm_round(self, round_num: int):
        ev = _Event(self._next_seq(), round_num, "llm_round")
        self._events.append(ev)
        try:
            yield ev
        except Exception as exc:
            ev.error = repr(exc)[:1000]
            raise
        finally:
            ev.latency_ms = int((time.monotonic() - ev._started) * 1000)

    @asynccontextmanager
    async def tool_call(self, round_num: int, tool: str):
        ev = _Event(self._next_seq(), round_num, "tool_call", tool_name=tool)
        self._events.append(ev)
        try:
            yield ev
        except Exception as exc:
            ev.error = repr(exc)[:1000]
            raise
        finally:
            ev.latency_ms = int((time.monotonic() - ev._started) * 1000)

    def flush(self) -> int:
        if not self._events:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                self.session_id, self.turn_index, ev.round_num, ev.seq,
                ev.event_type, ev.tool_name,
                _safe_dump(ev.request), _safe_dump(ev.response),
                ev.latency_ms, ev.error, now,
            )
            for ev in self._events
        ]
        with get_conn() as conn:
            conn.executemany(
                """INSERT INTO query_traces
                   (session_id, turn_index, round_num, seq, event_type, tool_name,
                    request_json, response_json, latency_ms, error, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        n = len(self._events)
        self._events.clear()
        return n
