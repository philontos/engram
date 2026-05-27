"""persist() + get_cognitive() against a temp DB via the `db` fixture."""

import pytest

from app.lib import entry_signals


def _make_entry(db) -> int:
    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entries (type, raw) VALUES ('text', 'x')")
        return cur.lastrowid


def test_persist_and_get_cognitive(db):
    entry_id = _make_entry(db)
    signals = [
        {"lens": "cognitive", "effort": 0.8, "span": "I think...", "payload": {}},
        {"lens": "cognitive", "effort": 0.2, "span": "weak",       "payload": {}},  # below 0.3
        {"lens": "outcome",   "effort": 0.9, "span": "shipped",    "payload": {"x": 1}},
    ]
    assert entry_signals.persist(entry_id, signals) == 3

    cog = entry_signals.get_cognitive(entry_id)
    assert len(cog) == 1                       # only the cognitive signal > 0.3
    assert cog[0]["span_text"] == "I think..."
    assert cog[0]["lens"] == "cognitive"


def test_persist_empty_is_noop(db):
    entry_id = _make_entry(db)
    assert entry_signals.persist(entry_id, []) == 0
    assert entry_signals.get_cognitive(entry_id) == []


def test_persist_maps_span_and_payload(db):
    entry_id = _make_entry(db)
    entry_signals.persist(entry_id, [
        {"lens": "outcome", "effort": 0.7, "span": "done", "payload": {"k": "v"}},
        {"lens": "cognitive", "effort": 0.6, "span": "hmm", "payload": {}},
    ])
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT lens, span_text, span_start, payload_json FROM entry_signals "
            "WHERE entry_id=? ORDER BY lens", (entry_id,)
        ).fetchall()
    by_lens = {r["lens"]: r for r in rows}
    assert by_lens["outcome"]["span_text"] == "done"
    assert by_lens["outcome"]["span_start"] is None           # offsets left NULL
    assert by_lens["outcome"]["payload_json"] == '{"k": "v"}'
    assert by_lens["cognitive"]["payload_json"] is None       # empty payload → NULL


def test_get_cognitive_respects_min_effort(db):
    entry_id = _make_entry(db)
    entry_signals.persist(entry_id, [
        {"lens": "cognitive", "effort": 0.5, "span": "mid", "payload": {}},
    ])
    assert len(entry_signals.get_cognitive(entry_id, min_effort=0.4)) == 1
    assert len(entry_signals.get_cognitive(entry_id, min_effort=0.6)) == 0
