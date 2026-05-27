"""Persist + query entry_signals rows. DB-only, so router.py stays LLM-only
and unit-testable. Signals come from router.route() as
{lens, effort, span, payload} dicts; we map span -> span_text and leave the
span_start/span_end offsets NULL (LLM offsets are unreliable; span_text is the
source of truth)."""

import json

from app.lib.db import get_conn
from app.lib.router import COGNITIVE_MIN_EFFORT


def persist(entry_id: int, signals: list[dict]) -> int:
    """Insert router signals for an entry. Returns the number of rows inserted."""
    if not signals:
        return 0
    rows = []
    for s in signals:
        payload = s.get("payload")
        rows.append((
            entry_id,
            s["lens"],
            s.get("span_start"),
            s.get("span_end"),
            s.get("span"),
            float(s.get("effort", 0.0)),
            json.dumps(payload, ensure_ascii=False) if payload else None,
        ))
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO entry_signals
               (entry_id, lens, span_start, span_end, span_text, effort, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


def get_cognitive(entry_id: int, min_effort: float = COGNITIVE_MIN_EFFORT) -> list[dict]:
    """Return this entry's cognitive-lens signals with effort > min_effort,
    strongest first. Empty list when there are none."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, lens, span_text, effort, payload_json
               FROM entry_signals
               WHERE entry_id=? AND lens='cognitive' AND effort > ?
               ORDER BY effort DESC""",
            (entry_id, min_effort),
        ).fetchall()
    return [dict(r) for r in rows]
