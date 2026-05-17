"""Verify run_backbone_pipeline emits per-sub-stage events."""

import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_backbone_pipeline_emits_all_stages(db):
    """所有 10 个子 stage 都应该产生 done 事件。"""
    from app.lib import backbone_pipeline

    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entries (raw, type, memory_type) VALUES (?, 'text', 'thought')", ("x",))
        entry_id = cur.lastrowid
        cur = conn.execute("INSERT INTO slices (entry_id) VALUES (?)", (entry_id,))
        slice_id = cur.lastrowid

    emit_calls = []
    def emit(stage, status, **extra):
        emit_calls.append((stage, status, extra))

    with patch.object(backbone_pipeline, "is_structured_llm_configured", return_value=True), \
         patch.object(backbone_pipeline, "get_profile_summary", return_value=""), \
         patch.object(backbone_pipeline, "get_slice_summary", return_value=""), \
         patch.object(backbone_pipeline, "get_situation_context", return_value=""), \
         patch.object(backbone_pipeline, "_activate_backbones", new=AsyncMock(return_value={"psychology": 0.7})), \
         patch.object(backbone_pipeline, "embed", new=AsyncMock(return_value=[0.0] * 16)), \
         patch.object(backbone_pipeline, "_rough_retrieval", return_value=[]), \
         patch.object(backbone_pipeline, "_extract_internal_candidates", new=AsyncMock(return_value=[])), \
         patch.object(backbone_pipeline, "_extract_external_candidates", new=AsyncMock(return_value=[])), \
         patch.object(backbone_pipeline, "_resolve_nodes", new=AsyncMock(return_value=([], {}, 0, {"new": [], "updated": []}, []))), \
         patch.object(backbone_pipeline, "_precise_retrieval", return_value={"nodes": [], "edges": [], "seed_meta": {}}), \
         patch.object(backbone_pipeline, "_write_algo_similarity_edges", return_value=([], [], [])), \
         patch.object(backbone_pipeline, "_extract_and_persist_edges", new=AsyncMock(return_value=(0, [], [], []))), \
         patch.object(backbone_pipeline, "_write_association_edges", return_value=([], [], [])), \
         patch.object(backbone_pipeline, "_propagate_opposition_edges", return_value=([], [])), \
         patch.object(backbone_pipeline, "_write_activations", lambda *a, **kw: None):

        await backbone_pipeline.run_backbone_pipeline(entry_id, slice_id, "x", trace={}, emit=emit)

    stages_done = [c[0] for c in emit_calls if c[1] == "done"]
    expected = {
        "activation",
        "rough_retrieval",
        "node_extract:psychology",
        "node_external:psychology",
        "node_resolution",
        "precise_retrieval",
        "algo_edges",
        "association",
        "opposition_propagation",
    }
    missing = expected - set(stages_done)
    assert not missing, f"Missing stage done events: {missing}. Got: {stages_done}"


@pytest.mark.asyncio
async def test_backbone_pipeline_empty_activation_emits_skipped(db):
    """当 activation 返回空时，整个 backbone 应该跳过。"""
    from app.lib import backbone_pipeline

    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entries (raw, type, memory_type) VALUES (?, 'text', 'thought')", ("x",))
        entry_id = cur.lastrowid
        cur = conn.execute("INSERT INTO slices (entry_id) VALUES (?)", (entry_id,))
        slice_id = cur.lastrowid

    emit_calls = []
    def emit(stage, status, **extra):
        emit_calls.append((stage, status, extra))

    with patch.object(backbone_pipeline, "is_structured_llm_configured", return_value=True), \
         patch.object(backbone_pipeline, "get_profile_summary", return_value=""), \
         patch.object(backbone_pipeline, "get_slice_summary", return_value=""), \
         patch.object(backbone_pipeline, "get_situation_context", return_value=""), \
         patch.object(backbone_pipeline, "_activate_backbones", new=AsyncMock(return_value={})):

        await backbone_pipeline.run_backbone_pipeline(entry_id, slice_id, "x", trace={}, emit=emit)

    activation_done = next((c for c in emit_calls if c[0] == "activation" and c[1] == "done"), None)
    assert activation_done is not None
    assert activation_done[2].get("payload") == {}
    skipped = [c for c in emit_calls if c[1] == "skipped"]
    assert len(skipped) >= 1, "expected at least one downstream skipped event"
