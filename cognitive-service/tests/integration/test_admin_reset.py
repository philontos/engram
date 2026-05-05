"""/admin/reset 行为测试。

直接调用 endpoint 函数（不走 TestClient + 整个 app），避免 app.main 启动时
需要 static/ 目录的麻烦。endpoint 本身只是 DB 操作，不需要走 HTTP。

scope=derived: 保留 entries 行，但重置它们的派生字段（processing_status / situation_json）
scope=all:     清空一切，包括 entries
"""

import pytest

from app.lib.db import get_conn
from app.routes.ui_api import ResetRequest, admin_reset


def _seed_entry(processing_status: str = "processed", situation_json: str | None = None) -> int:
    """Insert one entry with a given processing_status + situation_json."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entries (type, raw, processing_status, situation_json) VALUES (?, ?, ?, ?)",
            ("thought", "x", processing_status, situation_json),
        )
        return cur.lastrowid


def _seed_slice_and_features(entry_id: int) -> None:
    """Insert one slice + one slice_feature for the given entry."""
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO slices (entry_id) VALUES (?)", (entry_id,))
        slice_id = cur.lastrowid
        conn.execute(
            "INSERT INTO slice_features (slice_id, dimension, content_json) VALUES (?, ?, ?)",
            (slice_id, "ocean", '{"O": null}'),
        )


def test_reset_derived_resets_processing_status_and_situation(db):
    """Bug fix: reset?scope=derived must reset entries.processing_status and situation_json.

    Before this fix, after Admin → Reset derived data, entries kept their old
    'processed' status even though their slices/features were wiped, so the UI
    showed all entries as 已处理 with no way to re-process them in bulk.
    """
    e_processed = _seed_entry("processed", '{"emotional_state": "calm"}')
    e_failed    = _seed_entry("slice_failed", None)
    e_captured  = _seed_entry("captured", None)
    _seed_slice_and_features(e_processed)

    admin_reset(ResetRequest(scope="derived", confirm="yes"))

    # entries themselves remain
    with get_conn() as conn:
        ids = {row["id"] for row in conn.execute("SELECT id FROM entries").fetchall()}
        statuses = {row["id"]: row["processing_status"]
                    for row in conn.execute("SELECT id, processing_status FROM entries").fetchall()}
        situations = {row["id"]: row["situation_json"]
                      for row in conn.execute("SELECT id, situation_json FROM entries").fetchall()}

    assert ids == {e_processed, e_failed, e_captured}, "entries rows must be preserved"

    # All entries should be back to 'captured' regardless of prior status
    for eid, status in statuses.items():
        assert status == "captured", f"entry {eid} status should be reset to 'captured', got {status!r}"

    # situation_json wiped (it's written by slice_pipeline → derivative)
    for eid, sit in situations.items():
        assert sit is None, f"entry {eid} situation_json should be NULL, got {sit!r}"

    # Derived tables wiped
    with get_conn() as conn:
        for table in ("slices", "slice_features", "profile_dimensions",
                      "profile_snapshots", "pipeline_traces", "backbone_nodes",
                      "backbone_edges", "backbone_activations"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table} should be empty after derived reset, got {count} rows"


def test_reset_all_wipes_everything_including_entries(db):
    e1 = _seed_entry("processed")
    _seed_slice_and_features(e1)

    admin_reset(ResetRequest(scope="all", confirm="yes"))

    with get_conn() as conn:
        for table in ("entries", "slices", "slice_features", "profile_dimensions",
                      "profile_snapshots", "pipeline_traces", "backbone_nodes",
                      "backbone_edges", "backbone_activations"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table} should be empty after scope=all, got {count} rows"


def test_reset_requires_confirm(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        admin_reset(ResetRequest(scope="derived", confirm="no"))
    assert exc.value.status_code == 400


def test_reset_rejects_invalid_scope(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        admin_reset(ResetRequest(scope="everything", confirm="yes"))
    assert exc.value.status_code == 400
