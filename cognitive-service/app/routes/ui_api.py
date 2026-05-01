"""GET /ui/api/* — 为前端可视化提供数据接口。"""

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.lib.db import get_conn
from app.lib.vector_store import VECTOR_INDEX_PATH, get_store

router = APIRouter(prefix="/ui/api")


@router.get("/stats")
def stats():
    with get_conn() as conn:
        return {
            "entries":        conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            "entries_done":   conn.execute("SELECT COUNT(*) FROM entries WHERE processing_status='processed'").fetchone()[0],
            "slices":         conn.execute("SELECT COUNT(*) FROM slices").fetchone()[0],
            "nodes":          conn.execute("SELECT COUNT(*) FROM backbone_nodes").fetchone()[0],
            "edges":          conn.execute("SELECT COUNT(*) FROM backbone_edges").fetchone()[0],
            "activations":    conn.execute("SELECT COUNT(*) FROM backbone_activations").fetchone()[0],
            "memos":          conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0],
        }


@router.get("/entries")
def list_entries(limit: int = 100, offset: int = 0):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.raw, e.created_at, e.processing_status
            FROM entries e
            ORDER BY e.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()

        latest_processed = conn.execute(
            "SELECT id FROM entries WHERE processing_status='processed' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        latest_processed_id = latest_processed["id"] if latest_processed else None

        result = []
        for r in rows:
            domains = conn.execute(
                """
                SELECT DISTINCT n.domain
                FROM backbone_activations a
                JOIN backbone_nodes n ON n.id = a.node_id
                WHERE a.entry_id = ?
                """,
                (r["id"],),
            ).fetchall()
            has_rollback = (
                r["processing_status"] == "processed" and
                conn.execute(
                    "SELECT 1 FROM pipeline_traces WHERE entry_id=? AND rollback_json IS NOT NULL",
                    (r["id"],),
                ).fetchone() is not None
            )
            newer_processed_count = 0
            if has_rollback and r["id"] != latest_processed_id:
                newer_processed_count = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE processing_status='processed' AND id > ?",
                    (r["id"],),
                ).fetchone()[0]
            result.append({
                "id":                    r["id"],
                "preview":               (r["raw"] or "")[:120],
                "created_at":            r["created_at"],
                "processing_status":     r["processing_status"] or "captured",
                "domains":               [d["domain"] for d in domains],
                "can_revert":            has_rollback,
                "newer_processed_count": newer_processed_count,
            })
    return result


@router.get("/entry/{entry_id}")
def entry_detail(entry_id: int):
    with get_conn() as conn:
        entry = conn.execute(
            "SELECT id, raw, created_at, processing_status, memory_type, metadata_json, situation_json FROM entries WHERE id=?",
            (entry_id,),
        ).fetchone()
        if not entry:
            return {"error": "not found"}

        # Slice features
        slice_row = conn.execute("SELECT id FROM slices WHERE entry_id=?", (entry_id,)).fetchone()
        features = []
        if slice_row:
            features = [
                dict(r)
                for r in conn.execute(
                    "SELECT dimension, content_json, confidence FROM slice_features WHERE slice_id=?",
                    (slice_row["id"],),
                ).fetchall()
            ]

        # Backbone activations
        activations = conn.execute(
            """
            SELECT a.user_relevance, a.profile_match_score, a.created_at,
                   n.label, n.domain, n.node_type
            FROM backbone_activations a
            JOIN backbone_nodes n ON n.id = a.node_id
            WHERE a.entry_id = ?
            ORDER BY a.created_at
            """,
            (entry_id,),
        ).fetchall()

    entry_dict = dict(entry)
    raw_sit = entry_dict.pop("situation_json", None)
    entry_dict["situation"] = json.loads(raw_sit) if raw_sit else None

    return {
        "entry":       entry_dict,
        "features":    [
            {**f, "content_json": json.loads(f["content_json"])}
            for f in features
        ],
        "activations": [dict(a) for a in activations],
    }


@router.get("/graph")
def graph_data(domain: str = ""):
    with get_conn() as conn:
        node_query = """
            SELECT n.id, n.domain, n.node_type, n.label, n.strength, n.origin,
                   n.hit_count, n.description, n.content_cache_json,
                   n.source_entry_ids,
                   a.user_relevance, a.created_at AS last_activated
            FROM backbone_nodes n
            LEFT JOIN backbone_activations a ON a.id = n.current_activation_id
        """
        params: list = []
        if domain:
            node_query += " WHERE n.domain = ?"
            params.append(domain)
        node_query += " ORDER BY n.strength DESC"

        node_rows = conn.execute(node_query, params).fetchall()
        node_ids = {r["id"] for r in node_rows}

        edge_rows = conn.execute(
            """
            SELECT e.id, e.from_node_id, e.to_node_id, e.relation_type,
                   e.weight, e.confidence, e.source_entry_ids
            FROM backbone_edges e
            """,
        ).fetchall()

    nodes = []
    for r in node_rows:
        cache = {}
        if r["content_cache_json"]:
            try:
                cache = json.loads(r["content_cache_json"])
            except Exception:
                pass
        nodes.append({
            "data": {
                "id":               f"n{r['id']}",
                "db_id":            r["id"],
                "label":            r["label"],
                "node_type":        r["node_type"],
                "domain":           r["domain"],
                "origin":           r["origin"] or "internal",
                "weight":           r["strength"],
                "activation_count": r["hit_count"],
                "source_entries":   json.loads(r["source_entry_ids"] or "[]"),
                "user_relevance":   r["user_relevance"] or "",
                "factual_summary":  cache.get("factual_summary", ""),
                "last_activated":   r["last_activated"] or "",
            }
        })

    edges = []
    for r in edge_rows:
        if r["from_node_id"] not in node_ids or r["to_node_id"] not in node_ids:
            continue
        edges.append({
            "data": {
                "id":           f"e{r['id']}",
                "source":       f"n{r['from_node_id']}",
                "target":       f"n{r['to_node_id']}",
                "relation":     r["relation_type"],
                "weight":       r["weight"],
                "confidence":   r["confidence"],
                "source_entries": json.loads(r["source_entry_ids"] or "[]"),
            }
        })

    return {"nodes": nodes, "edges": edges}


@router.get("/node/{node_id}/provenance")
def node_provenance(node_id: int):
    """返回节点的全部溯源信息：source entries + activations + 原始 raw 片段。"""
    with get_conn() as conn:
        node = conn.execute(
            "SELECT id, label, domain, node_type, origin, strength, hit_count, "
            "description, source_entry_ids FROM backbone_nodes WHERE id=?",
            (node_id,),
        ).fetchone()
        if not node:
            return {"error": "not found"}

        source_ids = json.loads(node["source_entry_ids"] or "[]")
        entries = []
        if source_ids:
            placeholders = ",".join("?" * len(source_ids))
            rows = conn.execute(
                f"SELECT id, created_at, raw FROM entries WHERE id IN ({placeholders}) "
                f"ORDER BY created_at DESC",
                source_ids,
            ).fetchall()
            entries = [
                {"id": r["id"], "created_at": r["created_at"],
                 "preview": (r["raw"] or "")[:200]}
                for r in rows
            ]

        activations = conn.execute(
            """SELECT a.entry_id, a.user_relevance, a.profile_match_score,
                      a.created_at, e.raw
               FROM backbone_activations a
               JOIN entries e ON e.id = a.entry_id
               WHERE a.node_id = ?
               ORDER BY a.created_at DESC""",
            (node_id,),
        ).fetchall()

    return {
        "node": dict(node),
        "source_entries": entries,
        "activations": [
            {"entry_id": a["entry_id"], "user_relevance": a["user_relevance"],
             "profile_match_score": a["profile_match_score"],
             "created_at": a["created_at"],
             "raw_preview": (a["raw"] or "")[:200]}
            for a in activations
        ],
    }


@router.get("/entry/{entry_id}/trace")
def entry_trace(entry_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT trace_json, updated_at FROM pipeline_traces WHERE entry_id=?",
            (entry_id,),
        ).fetchone()
    if not row:
        return {"entry_id": entry_id, "trace": None}
    return {"entry_id": entry_id, "updated_at": row["updated_at"], "trace": json.loads(row["trace_json"])}


@router.get("/profile/evolution")
def profile_evolution():
    """返回 OCEAN 和 Schwartz 各子维度随时间的分数序列，基于 profile_snapshots。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ps.entry_id, ps.snapshot_json, e.created_at
               FROM profile_snapshots ps
               JOIN entries e ON e.id = ps.entry_id
               ORDER BY e.created_at ASC"""
        ).fetchall()

    ocean_keys    = ["O", "C", "E", "A", "N"]
    schwartz_keys = ["universalism", "benevolence", "conformity", "tradition",
                     "security", "power", "achievement", "hedonism",
                     "stimulation", "self_direction"]

    ocean_series:    dict[str, list] = {k: [] for k in ocean_keys}
    schwartz_series: dict[str, list] = {k: [] for k in schwartz_keys}

    for row in rows:
        try:
            snap = json.loads(row["snapshot_json"])
        except Exception:
            continue
        date = (row["created_at"] or "")[:10]
        entry_id = row["entry_id"]

        ocean = snap.get("ocean", {})
        for k in ocean_keys:
            v = ocean.get(k)
            if isinstance(v, dict) and "score" in v:
                ocean_series[k].append({
                    "entry_id": entry_id,
                    "date": date,
                    "score": round(float(v["score"]), 2),
                    "confidence": round(float(v.get("confidence", 0)), 3),
                })

        schwartz = snap.get("schwartz", {})
        for k in schwartz_keys:
            v = schwartz.get(k)
            if isinstance(v, dict) and "score" in v:
                schwartz_series[k].append({
                    "entry_id": entry_id,
                    "date": date,
                    "score": round(float(v["score"]), 2),
                    "confidence": round(float(v.get("confidence", 0)), 3),
                })

    # 过滤掉全程没有数据的子维度
    ocean_series    = {k: v for k, v in ocean_series.items() if v}
    schwartz_series = {k: v for k, v in schwartz_series.items() if v}

    return {"ocean": ocean_series, "schwartz": schwartz_series}


@router.get("/profile")
def profile():
    with get_conn() as conn:
        dim_rows = conn.execute(
            "SELECT dimension, content_json, sample_count, updated_at FROM profile_dimensions"
        ).fetchall()

        # 聚合所有 slice_features，按维度 → 子键 → entry 列表
        sf_rows = conn.execute(
            """SELECT sf.dimension, sf.content_json,
                      s.entry_id, e.created_at
               FROM slice_features sf
               JOIN slices s ON s.id = sf.slice_id
               JOIN entries e ON e.id = s.entry_id
               ORDER BY e.created_at ASC"""
        ).fetchall()

    # build: dim → sub_key → [{entry_id, evidence, score, confidence, created_at}]
    sub_sources: dict[str, dict[str, list]] = {}
    for sf in sf_rows:
        dim = sf["dimension"]
        entry_id = sf["entry_id"]
        created_at = sf["created_at"]
        try:
            content = json.loads(sf["content_json"])
        except Exception:
            continue
        if not isinstance(content, dict):
            continue
        sub_sources.setdefault(dim, {})
        for sub_key, val in content.items():
            if not isinstance(val, dict):
                continue
            conf = float(val.get("confidence", 0))
            score = float(val.get("score", 50))
            # 只收录有实质信号的（confidence > 0.3 或 score 偏离均值 ≥ 10）
            if conf < 0.3 and abs(score - 50) < 10:
                continue
            sub_sources[dim].setdefault(sub_key, []).append({
                "entry_id":   entry_id,
                "score":      round(score, 1),
                "confidence": round(conf, 3),
                "evidence":   val.get("evidence") or "",
                "created_at": created_at,
            })

    result = []
    for r in dim_rows:
        dim = r["dimension"]
        result.append({
            "dimension":    dim,
            "content":      json.loads(r["content_json"]),
            "sample_count": r["sample_count"],
            "updated_at":   r["updated_at"],
            "sub_sources":  sub_sources.get(dim, {}),
        })
    return result


# ---------------------------------------------------------------------------
# 查询历史
# ---------------------------------------------------------------------------

@router.get("/query-logs")
def query_logs(limit: int = 50, offset: int = 0):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, session_id, question, mode, seeds_json, turns_json, updated_at, created_at "
            "FROM query_logs ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM query_logs").fetchone()[0]
    return {
        "total": total,
        "logs": [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "question": r["question"],
                "mode": r["mode"],
                "seeds": json.loads(r["seeds_json"] or "[]"),
                "turn_count": len(json.loads(r["turns_json"] or "[]")),
                "updated_at": r["updated_at"] or r["created_at"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }


@router.get("/query-logs/{log_id}")
def query_log_detail(log_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM query_logs WHERE id=?", (log_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "question": row["question"],
        "mode": row["mode"],
        "seeds": json.loads(row["seeds_json"] or "[]"),
        "q1_text": row["q1_text"],
        "q2_text": row["q2_text"],
        "q3_text": row["q3_text"],
        "q4_text": row["q4_text"],
        "turns_json": json.loads(row["turns_json"] or "[]"),
        "updated_at": row["updated_at"] or row["created_at"],
        "created_at": row["created_at"],
    }


@router.delete("/query-logs/{log_id}")
def delete_query_log(log_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM query_logs WHERE id=?", (log_id,))
    return {"deleted": True}


@router.delete("/query-logs")
def clear_query_logs():
    with get_conn() as conn:
        conn.execute("DELETE FROM query_logs")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# 管理操作
# ---------------------------------------------------------------------------

@router.post("/entry/{entry_id}/revert")
async def revert_entry_ui(entry_id: int):
    """级联 revert：先将所有 id > entry_id 的 processed entry 按降序依次 revert，再 revert 目标。"""
    from app.routes.revert_entry import revert_entry

    with get_conn() as conn:
        newer_rows = conn.execute(
            "SELECT id FROM entries WHERE processing_status='processed' AND id > ? ORDER BY id DESC",
            (entry_id,),
        ).fetchall()

    cascade_ids = [r["id"] for r in newer_rows]
    cascade_results = []
    for cid in cascade_ids:
        cascade_results.append({"id": cid, "result": revert_entry(cid)})

    final = revert_entry(entry_id)
    return {
        "cascade_count": len(cascade_ids),
        "cascade_ids":   cascade_ids,
        "reverted":      final,
    }


@router.delete("/entry/{entry_id}")
def delete_entry(entry_id: int):
    """删除 entry 及其全部衍生数据（slice / activations / trace / snapshots）。
    backbone nodes/edges 不删除（可能被其他 entry 共享）。
    """
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entry not found")

        slice_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM slices WHERE entry_id=?", (entry_id,)
        ).fetchall()]
        if slice_ids:
            sph = ",".join("?" * len(slice_ids))
            conn.execute(f"DELETE FROM slice_features WHERE slice_id IN ({sph})", slice_ids)
        conn.execute("DELETE FROM slices WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM backbone_activations WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM profile_snapshots WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM pipeline_traces WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))

    return {"deleted": entry_id}


@router.get("/export")
def export_entries():
    """导出全部 entries 为 JSON，格式与 /import/entries 兼容。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, type, raw, source, memory_type, mood, "
            "tags, context_json, metadata_json, processing_status FROM entries ORDER BY created_at ASC"
        ).fetchall()

    entries = []
    for r in rows:
        def _j(v):
            try:
                return json.loads(v) if v else None
            except Exception:
                return v
        entries.append({
            "id":               r["id"],
            "created_at":       r["created_at"],
            "type":             r["type"],
            "raw":              r["raw"],
            "source":           r["source"],
            "memory_type":      r["memory_type"],
            "mood":             r["mood"],
            "tags":             _j(r["tags"]) or [],
            "context":          _j(r["context_json"]) or {},
            "metadata":         _j(r["metadata_json"]) or {},
            "processing_status": r["processing_status"],
        })

    return JSONResponse(
        content={"entry_count": len(entries), "entries": entries},
        headers={"Content-Disposition": "attachment; filename=cognitive_entries.json"},
    )


class ResetRequest(BaseModel):
    scope: str  # "derived" | "all"
    confirm: str  # must equal "yes"


@router.post("/admin/reset")
def admin_reset(req: ResetRequest):
    """清除数据库数据。scope=derived 保留 entries，scope=all 清空一切含 entries。"""
    if req.confirm != "yes":
        raise HTTPException(status_code=400, detail="confirm must be 'yes'")
    if req.scope not in ("derived", "all"):
        raise HTTPException(status_code=400, detail="scope must be 'derived' or 'all'")

    with get_conn() as conn:
        conn.execute("DELETE FROM backbone_activations")
        conn.execute("DELETE FROM backbone_edges")
        conn.execute("DELETE FROM backbone_nodes")
        conn.execute("DELETE FROM pipeline_traces")
        conn.execute("DELETE FROM profile_snapshots")
        conn.execute("DELETE FROM slice_features")
        conn.execute("DELETE FROM slices")
        conn.execute("DELETE FROM profile_dimensions")
        if req.scope == "all":
            conn.execute("DELETE FROM entries")
            for t in ["backbone_activations", "backbone_edges", "backbone_nodes",
                      "pipeline_traces", "profile_snapshots", "slice_features",
                      "slices", "profile_dimensions", "entries"]:
                conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (t,))
        else:
            for t in ["backbone_activations", "backbone_edges", "backbone_nodes",
                      "pipeline_traces", "profile_snapshots", "slice_features",
                      "slices", "profile_dimensions"]:
                conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (t,))

    # 重置向量索引
    vp = Path(VECTOR_INDEX_PATH)
    if vp.exists():
        shutil.rmtree(vp)
    vp.mkdir(parents=True, exist_ok=True)

    # 重置内存中的 vector store 单例
    import app.lib.vector_store as vs_mod
    vs_mod._store = None

    return {"scope": req.scope, "status": "done"}


@router.get("/memos")
def list_memos(limit: int = 200, offset: int = 0):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, raw, source, keywords_json, metadata_json, created_at FROM memos ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0]
    return {
        "total": total,
        "memos": [
            {
                "id":           r["id"],
                "raw":          r["raw"],
                "source":       r["source"],
                "keywords":     json.loads(r["keywords_json"] or "[]"),
                "metadata":     json.loads(r["metadata_json"] or "{}"),
                "created_at":   r["created_at"],
            }
            for r in rows
        ],
    }


@router.post("/admin/process-pending")
async def process_pending():
    """对所有 processing_status='captured' 的 entry 依次触发 pipeline。"""
    from app.routes.process_entry import run_pipeline_bg

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, raw, created_at, processing_status FROM entries WHERE processing_status='captured' ORDER BY created_at ASC"
        ).fetchall()

    results = []
    for row in rows:
        entry_id = row["id"]
        try:
            await run_pipeline_bg(entry_id)
            results.append({"id": entry_id, "status": "queued"})
        except Exception as exc:
            results.append({"id": entry_id, "status": "error", "error": str(exc)})

    return {"processed": len(results), "results": results}
