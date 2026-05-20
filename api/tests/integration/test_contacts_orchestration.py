"""验证 _run_pipeline 并行启动 slice + contacts，并在 rollback 含 contacts 字段。"""
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_run_pipeline_emits_contacts_stage_and_rolls_up(db, monkeypatch):
    from app.routes import process_entry as pe
    from app.lib import contacts_pipeline

    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('hi', 'text', 'thought')"
        ).lastrowid

    async def fake_slice(eid, raw, *, trace, emit):
        emit("slice", "start"); emit("slice", "done")
        return 1
    async def fake_backbone(eid, sid, raw, *, trace, entry_dt, emit):
        emit("backbone", "start"); emit("backbone", "done")
        return {"activated": [], "nodes_upserted": 0, "edges_upserted": 0,
                "rollback_nodes": [], "rollback_edges": []}
    async def fake_contacts(eid, raw, *, trace, emit):
        emit("contacts", "start"); emit("contacts", "done")
        return {"candidates_created": [42], "evidence_attached": [7],
                "matched_existing": [], "rollback_contacts": [42], "rollback_evidence": [7]}

    monkeypatch.setattr(pe, "generate_slice", fake_slice)
    monkeypatch.setattr(pe, "run_backbone_pipeline", fake_backbone)
    monkeypatch.setattr(pe, "run_contacts_pipeline", fake_contacts)
    monkeypatch.setattr(pe, "_save_profile_snapshot", lambda *a, **kw: None)
    monkeypatch.setattr(pe, "_snapshot_profile", lambda: {})
    monkeypatch.setattr(pe, "_calc_profile_diff", lambda *a, **kw: {})
    monkeypatch.setattr(pe, "_get_slice_features", lambda *a, **kw: {})

    row = db.get_conn().execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    result = await pe._run_pipeline(entry_id, row)
    assert result.status in ("done", "processed")

    trace = db.get_conn().execute(
        "SELECT rollback_json FROM pipeline_traces WHERE entry_id=?", (entry_id,)
    ).fetchone()
    import json
    rollback = json.loads(trace["rollback_json"])
    assert rollback["contacts"] == [42]
    assert rollback["contact_evidence"] == [7]


@pytest.mark.asyncio
async def test_contacts_failure_does_not_break_entry(db, monkeypatch):
    """contacts 抛异常 → entry 终态仍 processed，trace 含 contacts_error。"""
    from app.routes import process_entry as pe

    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('hi', 'text', 'thought')"
        ).lastrowid

    async def fake_slice(*a, **kw): kw["emit"]("slice", "done"); return 1
    async def fake_backbone(*a, **kw):
        kw["emit"]("backbone", "done")
        return {"activated": [], "nodes_upserted": 0, "edges_upserted": 0,
                "rollback_nodes": [], "rollback_edges": []}
    async def boom_contacts(*a, **kw): raise RuntimeError("nope")

    monkeypatch.setattr(pe, "generate_slice", fake_slice)
    monkeypatch.setattr(pe, "run_backbone_pipeline", fake_backbone)
    monkeypatch.setattr(pe, "run_contacts_pipeline", boom_contacts)
    monkeypatch.setattr(pe, "_save_profile_snapshot", lambda *a, **kw: None)
    monkeypatch.setattr(pe, "_snapshot_profile", lambda: {})
    monkeypatch.setattr(pe, "_calc_profile_diff", lambda *a, **kw: {})
    monkeypatch.setattr(pe, "_get_slice_features", lambda *a, **kw: {})

    row = db.get_conn().execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    result = await pe._run_pipeline(entry_id, row)
    # contacts 失败不污染：slice 成功 → done/processed
    assert result.status in ("done", "processed")
    trace = db.get_conn().execute("SELECT trace_json FROM pipeline_traces WHERE entry_id=?", (entry_id,)).fetchone()
    import json
    j = json.loads(trace["trace_json"])
    assert "contacts_error" in j
