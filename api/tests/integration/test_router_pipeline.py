"""Router step + cognitive gate in the orchestrator.

A non-cognitive entry (only an `outcome` signal) must: persist the signal,
emit a `router` done event, skip slice + backbone, and end `processed`.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.lib import process_events
from app.routes.process_entry import _run_pipeline


@pytest.mark.asyncio
async def test_non_cognitive_entry_skips_slice_and_processes(db):
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entries (raw, type, memory_type, created_at) "
            "VALUES (?, 'text', 'thought', CURRENT_TIMESTAMP)",
            ("ran 5km this morning",),
        )
        entry_id = cur.lastrowid
        row = conn.execute(
            "SELECT id, raw, created_at, processing_status FROM entries WHERE id=?",
            (entry_id,),
        ).fetchone()

    process_events.init(entry_id)

    fake_signals = [{"lens": "outcome", "effort": 0.7, "span": "ran 5km", "payload": {}}]
    slice_mock = AsyncMock()

    with patch("app.routes.process_entry.route", new=AsyncMock(return_value=fake_signals)), \
         patch("app.routes.process_entry.generate_slice", new=slice_mock):
        result = await _run_pipeline(entry_id, row)

    slice_mock.assert_not_called()
    assert result.slice_id is None
    assert result.status == "skipped"

    with db.get_conn() as conn:
        status = conn.execute(
            "SELECT processing_status FROM entries WHERE id=?", (entry_id,)
        ).fetchone()["processing_status"]
        n = conn.execute(
            "SELECT COUNT(*) c FROM entry_signals WHERE entry_id=?", (entry_id,)
        ).fetchone()["c"]
    assert status == "processed"
    assert n == 1

    stages = [(e.get("stage"), e.get("status"))
              for e in process_events._channels[entry_id].events
              if e.get("type") == "stage"]
    assert ("router", "done") in stages
    assert ("slice", "skipped") in stages
