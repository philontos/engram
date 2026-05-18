"""Verify generate_slice emits per-sub-stage events via the optional `emit` callable."""

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_generate_slice_emits_per_dimension(db):
    """Each enabled dimension (situation + 5 personality) should produce
    start+done events with summary and payload."""
    from app.lib import slice_pipeline

    with db.get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES (?, 'text', 'thought')",
            ("今天重读 Kahneman 双系统理论",),
        )
        entry_id = cursor.lastrowid

    emit_calls: list[tuple] = []
    def emit(stage, status, **extra):
        emit_calls.append((stage, status, extra))

    async def fake_extract(dim, raw, profile_summary):
        if dim["key"] == "facts":
            return {"name": None, "age": None}
        return {"a_axis": {"score": 50, "confidence": 0.5, "evidence": "stub"}}

    with patch.object(slice_pipeline, "_extract_dimension", new=fake_extract), \
         patch.object(slice_pipeline, "is_structured_llm_configured", return_value=True), \
         patch.object(slice_pipeline, "get_profile_summary", return_value=""), \
         patch.object(slice_pipeline, "merge_dimension", lambda *a, **kw: None):
        slice_id = await slice_pipeline.generate_slice(entry_id, "今天重读 Kahneman", trace={}, emit=emit)

    assert slice_id is not None
    stages_done = [c[0] for c in emit_calls if c[1] == "done"]
    assert "slice:situation" in stages_done
    # 至少有一个人格维度 done
    assert any(s.startswith("slice:") and s != "slice:situation" for s in stages_done)
    # 每个 done 事件都带 summary + payload
    for stage, status, extra in emit_calls:
        if status == "done":
            assert "summary" in extra, f"{stage} done event missing summary"
            assert "payload" in extra, f"{stage} done event missing payload"


@pytest.mark.asyncio
async def test_generate_slice_without_emit_still_works(db):
    """emit 参数可选 —— 不传也得正常跑（向后兼容）。"""
    from app.lib import slice_pipeline

    with db.get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES (?, 'text', 'thought')",
            ("x",),
        )
        entry_id = cursor.lastrowid

    async def fake_extract(dim, raw, profile_summary):
        return None  # 全 None → 不写 slice_features，但 slice 行还是会建

    with patch.object(slice_pipeline, "_extract_dimension", new=fake_extract), \
         patch.object(slice_pipeline, "is_structured_llm_configured", return_value=True), \
         patch.object(slice_pipeline, "get_profile_summary", return_value=""):
        slice_id = await slice_pipeline.generate_slice(entry_id, "x", trace={})
    assert slice_id is not None
