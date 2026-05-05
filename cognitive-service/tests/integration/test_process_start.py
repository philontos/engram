"""POST /entries/{id}/process/start 端点回归测试。

这个端点是为 EntriesTab 上的"Process"按钮服务的：当 entry 已经在 DB 里
（captured / failed / reverted 等状态），用户点 Process 时前端先 POST
/process/start 触发后台 pipeline，再 GET /process/stream 订阅事件。

之前 PR #10 的 Process 按钮只调了 /stream（订阅），没人触发处理，结果
"显示 processing 一会就没响应"。

测试用 asyncio.run 直接 await 端点函数（绕开 TestClient 不需要 static/）。
"""

import asyncio

import pytest
from fastapi import HTTPException

from app.lib.db import get_conn
from app.routes.process_entry import start_process


def _seed_entry(processing_status: str = "captured") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entries (type, raw, processing_status) VALUES (?, ?, ?)",
            ("thought", "x", processing_status),
        )
        return cur.lastrowid


def _run(coro):
    """Helper to run an async function in tests without pytest-asyncio."""
    return asyncio.new_event_loop().run_until_complete(coro)


def test_start_for_captured_entry_returns_started(db, monkeypatch):
    """captured 状态 → 应当成功 schedule + return 'started'."""
    eid = _seed_entry("captured")

    # Stub run_pipeline_bg so the test doesn't actually try to call LLM
    triggered: list[int] = []

    async def fake_bg(entry_id: int) -> None:
        triggered.append(entry_id)

    import app.routes.process_entry as pe
    monkeypatch.setattr(pe, "run_pipeline_bg", fake_bg)

    async def go():
        result = await start_process(eid)
        await asyncio.sleep(0)  # let the scheduled task run
        return result

    result = _run(go())
    assert result == {"entry_id": eid, "status": "started"}
    assert triggered == [eid], "background task must have been scheduled"


def test_start_for_processed_rejects_without_force(db):
    eid = _seed_entry("processed")
    with pytest.raises(HTTPException) as exc:
        _run(start_process(eid))
    assert exc.value.status_code == 409
    assert "Already processed" in exc.value.detail


def test_start_for_processed_with_force_works(db, monkeypatch):
    eid = _seed_entry("processed")

    async def fake_bg(entry_id: int) -> None: pass
    import app.routes.process_entry as pe
    monkeypatch.setattr(pe, "run_pipeline_bg", fake_bg)

    result = _run(start_process(eid, force=True))
    assert result["status"] == "started"


def test_start_for_in_progress_rejects(db):
    eid = _seed_entry("processing")
    with pytest.raises(HTTPException) as exc:
        _run(start_process(eid))
    assert exc.value.status_code == 409
    assert "in progress" in exc.value.detail


def test_start_for_missing_entry_returns_404(db):
    with pytest.raises(HTTPException) as exc:
        _run(start_process(99999))
    assert exc.value.status_code == 404
