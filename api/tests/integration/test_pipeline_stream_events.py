"""End-to-end: trigger pipeline and verify the SSE event stream contains
all the expected fine-grained stage events with summaries and payloads."""

import contextlib
import pytest
from unittest.mock import AsyncMock, patch

from app.lib import process_events
from app.routes.process_entry import _run_pipeline


@pytest.mark.asyncio
async def test_full_pipeline_emits_fine_grained_events(db):
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entries (raw, type, memory_type, created_at) VALUES (?, 'text', 'thought', CURRENT_TIMESTAMP)",
            ("knowledge-dense entry about psychology and LLM cognition",),
        )
        entry_id = cur.lastrowid
        row = conn.execute("SELECT id, raw, created_at, processing_status FROM entries WHERE id=?", (entry_id,)).fetchone()

    # Clear any stale channel state left by prior tests (global dict pollution).
    process_events._channels.pop(entry_id, None)
    process_events.init(entry_id)

    async def fake_extract_dim(dim, raw, profile_summary):
        if dim["key"] == "situation":
            return {"temporal_frame": "present", "narrator_stance": "present_reflection",
                    "pressure_level": "low", "energy_level": "medium"}
        return {"a": {"score": 60, "confidence": 0.7, "evidence": "x"}}

    async def _fake_contacts(eid, raw, *, trace, emit):
        # Mock run_contacts_pipeline so it doesn't emit bare stage events that
        # would fail the summary/payload assertion on all non-pipeline stage:done events.
        return {"candidates_created": [], "evidence_attached": [],
                "matched_existing": [], "rollback_contacts": [], "rollback_evidence": []}

    patches = [
        patch("app.routes.process_entry.run_contacts_pipeline", new=_fake_contacts),
        patch("app.lib.slice_pipeline._extract_dimension", new=fake_extract_dim),
        patch("app.lib.slice_pipeline.is_structured_llm_configured", return_value=True),
        patch("app.lib.slice_pipeline.get_profile_summary", return_value=""),
        patch("app.lib.slice_pipeline.merge_dimension", lambda *a, **kw: None),
        patch("app.lib.backbone_pipeline.is_structured_llm_configured", return_value=True),
        patch("app.lib.backbone_pipeline.get_profile_summary", return_value=""),
        patch("app.lib.backbone_pipeline.get_slice_summary", return_value=""),
        patch("app.lib.backbone_pipeline.get_situation_context", return_value=""),
        patch("app.lib.backbone_pipeline._activate_backbones", new=AsyncMock(return_value={"psychology": 0.7})),
        patch("app.lib.backbone_pipeline.embed", new=AsyncMock(return_value=[0.0] * 16)),
        patch("app.lib.backbone_pipeline._rough_retrieval", return_value=[]),
        patch("app.lib.backbone_pipeline._extract_internal_candidates", new=AsyncMock(return_value=[])),
        patch("app.lib.backbone_pipeline._extract_external_candidates", new=AsyncMock(return_value=[])),
        patch("app.lib.backbone_pipeline._resolve_nodes", new=AsyncMock(return_value=([], {}, 0, {"new": [], "updated": []}, []))),
        patch("app.lib.backbone_pipeline._precise_retrieval", return_value={"nodes": [], "edges": [], "seed_meta": {}}),
        patch("app.lib.backbone_pipeline._write_algo_similarity_edges", return_value=([], [], [])),
        patch("app.lib.backbone_pipeline._extract_and_persist_edges", new=AsyncMock(return_value=(0, [], [], []))),
        patch("app.lib.backbone_pipeline._write_association_edges", return_value=([], [], [])),
        patch("app.lib.backbone_pipeline._propagate_opposition_edges", return_value=([], [])),
        patch("app.lib.backbone_pipeline._write_activations", lambda *a, **kw: None),
    ]

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        await _run_pipeline(entry_id, row)

    events = process_events._channels[entry_id].events
    stage_dones = [e for e in events if e.get("type") == "stage" and e.get("status") == "done"]
    stage_names = [e["stage"] for e in stage_dones]

    assert "pipeline" in stage_names
    assert "slice:situation" in stage_names
    for required in ("activation", "rough_retrieval", "node_extract:psychology", "node_resolution"):
        assert required in stage_names, f"missing {required} in stream. got: {stage_names}"

    for e in stage_dones:
        if e["stage"] == "pipeline":
            continue
        assert "summary" in e, f"{e['stage']} missing summary"
        assert "payload" in e, f"{e['stage']} missing payload"
