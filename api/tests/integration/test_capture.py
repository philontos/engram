"""/capture always creates an entry now — no reject branch (router never rejects)."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_capture_always_creates_entry_no_reject(db):
    from app.routes import capture as capture_mod
    from app.routes.capture import capture, CaptureRequest

    with patch.object(capture_mod, "embed", new=AsyncMock(return_value=[0.0] * 16)), \
         patch.object(capture_mod, "get_store"), \
         patch.object(capture_mod, "_trigger_process", new=AsyncMock()):
        # A pure event log — the old gate would have rejected this.
        resp = await capture(CaptureRequest(content="bought groceries and paid the rent"))

    assert resp.track == "entry"
    assert resp.id is not None
    assert resp.reason == ""

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT raw, processing_status FROM entries WHERE id=?", (resp.id,)
        ).fetchone()
    assert row is not None
    assert row["raw"] == "bought groceries and paid the rent"
