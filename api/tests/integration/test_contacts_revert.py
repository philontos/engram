"""revert 一条引入新 candidate 的 entry → contact + evidence 清干净；
revert 一条只 match_existing 的 entry → 主行不被删，仅 evidence 删。"""
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture
def client(db, monkeypatch):
    from app.main import app
    return TestClient(app)


@pytest.mark.asyncio
async def test_revert_removes_newly_created_candidate(db, client, monkeypatch):
    """完整跑：capture 触发的 pipeline 不便直接调用，这里直接走 _run_pipeline + /revert。"""
    from app.routes import process_entry as pe
    from app.lib import contacts_pipeline

    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('与小红一起开会', 'text', 'thought')"
        ).lastrowid

    fake_llm = AsyncMock(return_value={
        "mentions": [{
            "verdict": "new_candidate", "matched_contact_id": None, "candidate_contact_ids": [],
            "mention_text": "小红", "excerpt": "与小红一起开会", "interaction_observed": True,
            "suggested_display_name": "小红", "suggested_aliases": [], "suggested_kind": "colleague",
            "context_summary": "", "confidence": 0.8,
        }]
    })

    async def fake_slice(*a, **kw): kw["emit"]("slice", "done"); return 1
    async def fake_backbone(*a, **kw):
        kw["emit"]("backbone", "done")
        return {"rollback_nodes": [], "rollback_edges": [], "activated": [],
                "nodes_upserted": 0, "edges_upserted": 0}

    monkeypatch.setattr(pe, "generate_slice", fake_slice)
    monkeypatch.setattr(pe, "run_backbone_pipeline", fake_backbone)
    monkeypatch.setattr(pe, "_save_profile_snapshot", lambda *a, **kw: None)
    monkeypatch.setattr(pe, "_snapshot_profile", lambda: {})
    monkeypatch.setattr(pe, "_calc_profile_diff", lambda *a, **kw: {})
    monkeypatch.setattr(pe, "_get_slice_features", lambda *a, **kw: {})
    monkeypatch.setattr(contacts_pipeline, "chat_json", fake_llm)
    monkeypatch.setattr(contacts_pipeline, "is_structured_llm_configured", lambda: True)

    row = db.get_conn().execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    await pe._run_pipeline(entry_id, row)

    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM contacts").fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) c FROM contact_evidence").fetchone()["c"] == 1

    resp = client.post(f"/entries/{entry_id}/revert")
    assert resp.status_code == 200, resp.text

    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM contacts").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM contact_evidence").fetchone()["c"] == 0


@pytest.mark.asyncio
async def test_revert_only_deletes_evidence_for_match_existing(db, client, monkeypatch):
    from app.routes import process_entry as pe
    from app.lib import contacts_pipeline

    with db.get_conn() as conn:
        cid = conn.execute(
            "INSERT INTO contacts (display_name, status, relationship_kind) VALUES ('Andy', 'confirmed', 'friend')"
        ).lastrowid
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('Andy 来了', 'text', 'thought')"
        ).lastrowid

    fake_llm = AsyncMock(return_value={
        "mentions": [{
            "verdict": "match_existing", "matched_contact_id": cid, "candidate_contact_ids": [],
            "mention_text": "Andy", "excerpt": "Andy 来了", "interaction_observed": True,
            "suggested_display_name": "Andy", "suggested_aliases": [], "suggested_kind": "friend",
            "context_summary": "", "confidence": 0.9,
        }]
    })
    async def fake_slice(*a, **kw): kw["emit"]("slice", "done"); return 1
    async def fake_backbone(*a, **kw):
        kw["emit"]("backbone", "done")
        return {"rollback_nodes": [], "rollback_edges": [], "activated": [],
                "nodes_upserted": 0, "edges_upserted": 0}
    monkeypatch.setattr(pe, "generate_slice", fake_slice)
    monkeypatch.setattr(pe, "run_backbone_pipeline", fake_backbone)
    monkeypatch.setattr(pe, "_save_profile_snapshot", lambda *a, **kw: None)
    monkeypatch.setattr(pe, "_snapshot_profile", lambda: {})
    monkeypatch.setattr(pe, "_calc_profile_diff", lambda *a, **kw: {})
    monkeypatch.setattr(pe, "_get_slice_features", lambda *a, **kw: {})
    monkeypatch.setattr(contacts_pipeline, "chat_json", fake_llm)
    monkeypatch.setattr(contacts_pipeline, "is_structured_llm_configured", lambda: True)

    row = db.get_conn().execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    await pe._run_pipeline(entry_id, row)

    resp = client.post(f"/entries/{entry_id}/revert")
    assert resp.status_code == 200, resp.text

    with db.get_conn() as conn:
        # contact 主行保留
        assert conn.execute("SELECT COUNT(*) c FROM contacts WHERE id=?", (cid,)).fetchone()["c"] == 1
        # evidence 已删
        assert conn.execute("SELECT COUNT(*) c FROM contact_evidence").fetchone()["c"] == 0
