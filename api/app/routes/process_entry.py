"""POST /entries/{entry_id}/process — 手动触发 V2 管线处理一条 entry。"""

import asyncio
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.lib.backbone_pipeline import run_backbone_pipeline
from app.lib.contacts_pipeline import run_contacts_pipeline
from app.lib.db import get_conn
from app.lib import process_events
from app.lib.slice_pipeline import generate_slice
from shared.llm import capture_llm_calls

router = APIRouter()

# 全局串行锁：pipeline 是"先查后写"，并发会产生重复节点和丢失更新
_PIPELINE_LOCK = asyncio.Lock()


class ProcessResult(BaseModel):
    entry_id:       int
    slice_id:       int | None
    activated:      list[str]
    nodes_upserted: int
    edges_upserted: int
    status:         str


def _snapshot_profile() -> dict:
    """读取当前 profile_dimensions 作为快照，用于计算 diff。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dimension, content_json FROM profile_dimensions"
        ).fetchall()
    return {r["dimension"]: json.loads(r["content_json"]) for r in rows}


def _calc_profile_diff(before: dict, after: dict) -> dict:
    """逐维度逐子项计算 before→after 的 diff。"""
    diff: dict = {}
    all_dims = set(before) | set(after)
    for dim in all_dims:
        b = before.get(dim, {})
        a = after.get(dim, {})
        all_keys = set(b) | set(a)
        dim_diff: dict = {}
        for k in all_keys:
            bv = b.get(k)
            av = a.get(k)
            if isinstance(bv, dict) and "score" in bv and isinstance(av, dict) and "score" in av:
                bs, as_ = float(bv["score"]), float(av["score"])
                bc, ac = float(bv.get("confidence", 0)), float(av.get("confidence", 0))
                delta = round(as_ - bs, 2)
                if abs(delta) > 0.01 or abs(ac - bc) > 0.001:
                    dim_diff[k] = {
                        "score_before": round(bs, 2), "score_after": round(as_, 2), "delta": delta,
                        "conf_before": round(bc, 3), "conf_after": round(ac, 3),
                    }
            elif av != bv:
                dim_diff[k] = {"before": bv, "after": av}
        if dim_diff:
            diff[dim] = dim_diff
    return diff


def _save_profile_snapshot(entry_id: int) -> None:
    """处理完成后保存一次全量 profile 快照，用于演化分析。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dimension, content_json FROM profile_dimensions"
        ).fetchall()
    snapshot = {r["dimension"]: json.loads(r["content_json"]) for r in rows}
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO profile_snapshots (entry_id, snapshot_json, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (entry_id, json.dumps(snapshot, ensure_ascii=False)),
        )


def _save_trace(entry_id: int, trace: dict, rollback: dict | None = None) -> None:
    trace_json = json.dumps(trace, ensure_ascii=False)
    rollback_json = json.dumps(rollback, ensure_ascii=False) if rollback else None
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO pipeline_traces (entry_id, trace_json, rollback_json, created_at, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
               ON CONFLICT(entry_id) DO UPDATE SET
                 trace_json = excluded.trace_json,
                 rollback_json = excluded.rollback_json,
                 updated_at = CURRENT_TIMESTAMP""",
            (entry_id, trace_json, rollback_json),
        )


def _summarize_llm_calls(calls: list[dict]) -> dict:
    """聚合 LLM 调用统计，便于一眼看出是否接近上下文极限。"""
    if not calls:
        return {"count": 0, "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0, "prompt_chars": 0, "duration_ms": 0,
                "max_prompt_tokens": 0, "failures": 0}
    total = len(calls)
    pt = sum(int(c.get("prompt_tokens", 0)) for c in calls)
    ct = sum(int(c.get("completion_tokens", 0)) for c in calls)
    tt = sum(int(c.get("total_tokens", 0)) for c in calls)
    pc = sum(int(c.get("prompt_chars", 0)) for c in calls)
    dur = sum(int(c.get("duration_ms", 0)) for c in calls)
    max_prompt = max((int(c.get("prompt_tokens", 0)) for c in calls), default=0)
    failures = sum(1 for c in calls if c.get("status") != "ok")
    return {
        "count": total,
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": tt,
        "prompt_chars": pc,
        "duration_ms": dur,
        "max_prompt_tokens": max_prompt,
        "failures": failures,
    }


def _compute_metrics(trace: dict, raw: str) -> dict:
    """从 trace 各字段聚合客观度量（可数硬数据，不做主观判断）。"""
    def _len(v) -> int:
        if v is None: return 0
        if isinstance(v, list): return len(v)
        if isinstance(v, dict): return len(v)
        return 0

    def _sum_by_domain(d: dict | None) -> int:
        if not isinstance(d, dict): return 0
        return sum(len(v) if isinstance(v, list) else 0 for v in d.values())

    def _changed_subdims(profile_diff: dict | None) -> int:
        if not isinstance(profile_diff, dict): return 0
        return sum(len(v) if isinstance(v, dict) else 0 for v in profile_diff.values())

    db_diff = trace.get("db_diff") or {}
    return {
        "raw_chars": len(raw or ""),
        "duration_ms": trace.get("duration_ms", 0),
        "slice_feature_count": _len(trace.get("slice")),
        "profile_changed_subdims": _changed_subdims(trace.get("profile_diff")),
        "activation_count": _len(trace.get("activation")),
        "rough_retrieval_count": _len(trace.get("rough_retrieval")),
        "node_extract_internal_count": _sum_by_domain(trace.get("node_extract_internal")),
        "node_extract_external_count": _sum_by_domain(trace.get("node_extract_external")),
        "confirmed_nodes_count": _len(trace.get("confirmed_nodes")),
        "db_nodes_new": _len(db_diff.get("nodes_new")),
        "db_nodes_updated": _len(db_diff.get("nodes_updated")),
        "db_edges_new": _len(db_diff.get("edges_new")),
        "db_edges_updated": _len(db_diff.get("edges_updated")),
        "algo_edges_count": _len(trace.get("algo_edges")),
        "edge_extract_count": _len(trace.get("edge_extract")),
        "association_edges_count": _len(trace.get("association_edges")),
        "opposition_propagation_count": _len(trace.get("opposition_propagation")),
        "llm": trace.get("llm_summary") or {},
    }


def _get_slice_features(slice_id: int) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dimension, content_json, confidence FROM slice_features WHERE slice_id=?",
            (slice_id,),
        ).fetchall()
    return {r["dimension"]: {"content": json.loads(r["content_json"]), "confidence": r["confidence"]}
            for r in rows}


@router.post("/entries/{entry_id}/process", response_model=ProcessResult)
async def process_entry(entry_id: int, force: bool = False):
    with get_conn() as conn:
        row = conn.execute("SELECT id, raw, created_at, processing_status FROM entries WHERE id = ?", (entry_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")

    if row["processing_status"] == "processed" and not force:
        raise HTTPException(status_code=409, detail="Already processed. Use ?force=true to reprocess.")

    async with _PIPELINE_LOCK:
        return await _run_pipeline(entry_id, row)


async def run_pipeline_bg(entry_id: int) -> None:
    """供 capture 路由异步触发，不抛异常（失败只更新状态）。"""
    with get_conn() as conn:
        row = conn.execute("SELECT id, raw, created_at, processing_status FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return
    async with _PIPELINE_LOCK:
        try:
            await _run_pipeline(entry_id, row)
        except Exception:
            pass


async def _run_pipeline(entry_id: int, row) -> ProcessResult:
    raw = row["raw"]
    entry_dt: datetime | None = None
    try:
        entry_dt = datetime.fromisoformat(row["created_at"].replace(" ", "T"))
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    started_at = datetime.now(timezone.utc)
    started_perf = time.perf_counter()
    trace: dict = {
        "entry_id": entry_id,
        "started_at": started_at.isoformat(),
    }
    llm_calls: list[dict] = []

    emit = process_events.make_emitter(entry_id, started_perf)
    emit("pipeline", "start", raw_chars=len(raw or ""))

    # Mark the entry as in-flight so the UI can show a distinct "processing"
    # badge instead of the misleading "captured / pending" one. The terminal
    # status (processed / slice_failed / failed) is set later in this function.
    with get_conn() as conn:
        conn.execute(
            "UPDATE entries SET processing_status='processing' WHERE id=?",
            (entry_id,),
        )

    # Rollback: 记录处理前的 profile_snapshot_id
    with get_conn() as conn:
        _prev_snap = conn.execute(
            "SELECT id FROM profile_snapshots WHERE entry_id != ? ORDER BY created_at DESC LIMIT 1",
            (entry_id,),
        ).fetchone()
    prev_snapshot_id = _prev_snap["id"] if _prev_snap else None

    slice_id: int | None = None
    backbone_stats: dict = {}
    contacts_stats: dict = {}
    error_payload: dict | None = None
    try:
        with capture_llm_calls(llm_calls):
            profile_before = _snapshot_profile()

            slice_task    = asyncio.create_task(generate_slice(entry_id, raw, trace=trace, emit=emit))
            contacts_task = asyncio.create_task(run_contacts_pipeline(entry_id, raw, trace=trace, emit=emit))

            # 等 slice
            try:
                slice_id = await slice_task
            except Exception:
                # 让上层异常处理走原逻辑
                raise

            profile_after = _snapshot_profile()
            if slice_id:
                trace["slice"] = _get_slice_features(slice_id)
                trace["profile_diff"] = _calc_profile_diff(profile_before, profile_after)
                _save_profile_snapshot(entry_id)

                backbone_task = asyncio.create_task(
                    run_backbone_pipeline(entry_id, slice_id, raw, trace=trace, entry_dt=entry_dt, emit=emit)
                )

                # 等 backbone + contacts，独立 swallow
                bres, cres = await asyncio.gather(backbone_task, contacts_task, return_exceptions=True)
                if isinstance(bres, Exception):
                    trace["backbone_error"] = {"message": str(bres), "type": bres.__class__.__name__}
                    emit("backbone", "error", message=str(bres), type=bres.__class__.__name__)
                    backbone_stats = {}
                else:
                    backbone_stats = bres
                if isinstance(cres, Exception):
                    trace["contacts_error"] = {"message": str(cres), "type": cres.__class__.__name__}
                    emit("contacts", "error", message=str(cres), type=cres.__class__.__name__)
                    contacts_stats = {}
                else:
                    contacts_stats = cres

                with get_conn() as conn:
                    conn.execute("UPDATE entries SET processing_status='processed' WHERE id=?", (entry_id,))
            else:
                # slice 返回 None：取消 contacts，标 slice_failed
                try:
                    contacts_task.cancel()
                    await asyncio.gather(contacts_task, return_exceptions=True)
                except Exception:
                    pass
                with get_conn() as conn:
                    conn.execute("UPDATE entries SET processing_status='slice_failed' WHERE id=?", (entry_id,))
                emit("slice", "skipped", reason="slice_generation_failed")
    except Exception as exc:
        error_payload = {"message": str(exc), "type": exc.__class__.__name__}
        emit("pipeline", "error", **error_payload)
        with get_conn() as conn:
            conn.execute(
                "UPDATE entries SET processing_status='failed' WHERE id=?", (entry_id,)
            )

    trace["llm_calls"] = llm_calls
    trace["llm_summary"] = _summarize_llm_calls(llm_calls)

    finished_at = datetime.now(timezone.utc)
    trace["finished_at"] = finished_at.isoformat()
    trace["duration_ms"] = int((time.perf_counter() - started_perf) * 1000)
    trace["metrics"] = _compute_metrics(trace, raw)

    rollback = {
        "prev_profile_snapshot_id": prev_snapshot_id,
        "nodes": backbone_stats.get("rollback_nodes", []),
        "edges": backbone_stats.get("rollback_edges", []),
        "contacts":         contacts_stats.get("rollback_contacts", []),
        "contact_evidence": contacts_stats.get("rollback_evidence", []),
    } if slice_id else None

    _save_trace(entry_id, trace, rollback)

    final_status = "failed" if error_payload else ("done" if slice_id else "slice_failed")
    emit("pipeline", "done",
         final_status=final_status,
         duration_ms=trace["duration_ms"],
         metrics=trace["metrics"])
    process_events.finish(entry_id)

    return ProcessResult(
        entry_id=entry_id,
        slice_id=slice_id,
        activated=backbone_stats.get("activated", []),
        nodes_upserted=backbone_stats.get("nodes_upserted", 0),
        edges_upserted=backbone_stats.get("edges_upserted", 0),
        status=final_status,
    )


@router.get("/entries/{entry_id}/process/stream")
async def stream_process(entry_id: int):
    """NDJSON stream of pipeline stage events for a single entry.

    Subscribers opened after the pipeline finishes (within the channel
    retention window) get a full replay; otherwise the response is empty
    and the caller should fall back to fetching the persisted trace.

    NOTE: this endpoint **only subscribes** — it does not start processing.
    Callers must first POST /entries/{id}/process/start (or rely on /capture
    auto-trigger) to actually trigger the pipeline.
    """
    async def gen():
        try:
            async for ev in process_events.subscribe(entry_id):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps(
                {"type": "stream_error", "message": str(exc)},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.post("/entries/{entry_id}/process/start")
async def start_process(entry_id: int, force: bool = False):
    """Trigger pipeline processing for a single entry in the background.

    Mirrors what /capture does after saving a new entry: init the events
    channel + asyncio.create_task. UI can then GET /process/stream to watch
    progress in real time.

    Use this when the entry already exists in DB (e.g., after admin reset
    derived data, or for slice_failed / failed / reverted entries). For
    new captures, use POST /capture which auto-triggers; you don't need
    /start in that case.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, processing_status FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")

    if row["processing_status"] == "processed" and not force:
        raise HTTPException(status_code=409, detail="Already processed. Use ?force=true to reprocess.")
    if row["processing_status"] == "processing":
        raise HTTPException(status_code=409, detail="Already in progress.")

    process_events.init(entry_id)
    asyncio.create_task(run_pipeline_bg(entry_id))
    return {"entry_id": entry_id, "status": "started"}
