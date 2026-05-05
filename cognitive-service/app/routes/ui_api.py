"""GET /ui/api/* — 为前端可视化提供数据接口。"""

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.lib.config_loader import BACKBONES, DIMENSIONS, detect_orphan_domains
from app.lib.db import get_conn
from app.lib.vector_store import VECTOR_INDEX_PATH, get_store

router = APIRouter(prefix="/ui/api")

_DIM_INTERNAL_KEYS = {"_dir", "_prompt", "_rubric", "prompt_template"}
_BB_INTERNAL_KEYS = {"_dir", "_internal_node_prompt", "_focus_hints_text"}


@router.get("/dimensions")
def list_dimensions():
    return [
        {k: v for k, v in dim.items() if k not in _DIM_INTERNAL_KEYS}
        for dim in DIMENSIONS
        if dim.get("enabled", True)
    ]


@router.get("/backbones")
def list_backbones():
    """Frontend-facing backbone catalog. Drives domain filter buttons, colors, and labels."""
    return {
        "backbones": [
            {k: v for k, v in bb.items() if k not in _BB_INTERNAL_KEYS}
            for bb in BACKBONES
        ],
        "orphan_domains": detect_orphan_domains(),
    }


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


def _serialize_node(r, neighbor_count: int, loaded_neighbor_count: int) -> dict:
    cache = {}
    if r["content_cache_json"]:
        try:
            cache = json.loads(r["content_cache_json"])
        except Exception:
            pass
    return {
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
            "neighbor_count":   neighbor_count,
            "unexpanded_count": max(0, neighbor_count - loaded_neighbor_count),
        }
    }


def _serialize_edge(r) -> dict:
    return {
        "data": {
            "id":             f"e{r['id']}",
            "source":         f"n{r['from_node_id']}",
            "target":         f"n{r['to_node_id']}",
            "relation":       r["relation_type"],
            "weight":         r["weight"],
            "confidence":     r["confidence"],
            "source_entries": json.loads(r["source_entry_ids"] or "[]"),
        }
    }


@router.get("/graph/seed")
def graph_seed(domain: str = "", limit: int = 24):
    """初始焦点视图：返回强度最高的 limit 个节点 + 它们之间的边。"""
    limit = max(1, min(limit, 200))
    with get_conn() as conn:
        node_query = """
            SELECT n.id, n.domain, n.node_type, n.label, n.strength, n.origin,
                   n.hit_count, n.description, n.content_cache_json, n.source_entry_ids,
                   a.user_relevance, a.created_at AS last_activated
            FROM backbone_nodes n
            LEFT JOIN backbone_activations a ON a.id = n.current_activation_id
        """
        params: list = []
        if domain:
            node_query += " WHERE n.domain = ?"
            params.append(domain)
        node_query += " ORDER BY n.strength DESC LIMIT ?"
        params.append(limit)
        node_rows = conn.execute(node_query, params).fetchall()
        node_ids = [r["id"] for r in node_rows]
        if not node_ids:
            return {"nodes": [], "edges": []}

        ph = ",".join("?" * len(node_ids))
        edge_rows = conn.execute(
            f"""SELECT id, from_node_id, to_node_id, relation_type, weight, confidence, source_entry_ids
                FROM backbone_edges
                WHERE from_node_id IN ({ph}) AND to_node_id IN ({ph})""",
            node_ids + node_ids,
        ).fetchall()

        # neighbor counts (degree) for each seed node — total degree, not just within seed
        degree_rows = conn.execute(
            f"""SELECT node_id, COUNT(*) AS c FROM (
                    SELECT from_node_id AS node_id FROM backbone_edges WHERE from_node_id IN ({ph})
                    UNION ALL
                    SELECT to_node_id AS node_id FROM backbone_edges WHERE to_node_id IN ({ph})
                ) GROUP BY node_id""",
            node_ids + node_ids,
        ).fetchall()
        degree_map = {r["node_id"]: r["c"] for r in degree_rows}

        # edges within seed contribute to "loaded_neighbor_count" — counted from each side
        loaded_map: dict[int, int] = {}
        seed_set = set(node_ids)
        for e in edge_rows:
            if e["from_node_id"] in seed_set and e["to_node_id"] in seed_set:
                loaded_map[e["from_node_id"]] = loaded_map.get(e["from_node_id"], 0) + 1
                loaded_map[e["to_node_id"]] = loaded_map.get(e["to_node_id"], 0) + 1

    nodes = [
        _serialize_node(r, degree_map.get(r["id"], 0), loaded_map.get(r["id"], 0))
        for r in node_rows
    ]
    edges = [_serialize_edge(r) for r in edge_rows]
    return {"nodes": nodes, "edges": edges}


@router.get("/graph/expand")
def graph_expand(node_id: int, loaded: str = ""):
    """展开某节点的邻居：返回新邻居节点 + 所有连到已加载节点的边。

    loaded: 当前已加载的节点 db_id 列表，逗号分隔。新邻居 = 直接相邻 - 已加载。
    """
    loaded_ids = {int(x) for x in loaded.split(",") if x.strip().isdigit()}
    loaded_ids.add(node_id)

    with get_conn() as conn:
        # 找所有直接邻居（从 edges 双向）
        neighbor_rows = conn.execute(
            """SELECT DISTINCT to_node_id AS nid FROM backbone_edges WHERE from_node_id = ?
               UNION
               SELECT DISTINCT from_node_id AS nid FROM backbone_edges WHERE to_node_id = ?""",
            (node_id, node_id),
        ).fetchall()
        neighbor_ids = [r["nid"] for r in neighbor_rows]
        new_ids = [nid for nid in neighbor_ids if nid not in loaded_ids]

        if not new_ids:
            return {"nodes": [], "edges": []}

        ph = ",".join("?" * len(new_ids))
        node_rows = conn.execute(
            f"""SELECT n.id, n.domain, n.node_type, n.label, n.strength, n.origin,
                       n.hit_count, n.description, n.content_cache_json, n.source_entry_ids,
                       a.user_relevance, a.created_at AS last_activated
                FROM backbone_nodes n
                LEFT JOIN backbone_activations a ON a.id = n.current_activation_id
                WHERE n.id IN ({ph})
                ORDER BY n.strength DESC""",
            new_ids,
        ).fetchall()

        # 拉所有 edges where 一端是新节点 AND 另一端在 (loaded ∪ new)
        all_known = loaded_ids | set(new_ids)
        all_ph = ",".join("?" * len(all_known))
        new_ph = ",".join("?" * len(new_ids))
        edge_rows = conn.execute(
            f"""SELECT id, from_node_id, to_node_id, relation_type, weight, confidence, source_entry_ids
                FROM backbone_edges
                WHERE (from_node_id IN ({new_ph}) AND to_node_id IN ({all_ph}))
                   OR (to_node_id IN ({new_ph}) AND from_node_id IN ({all_ph}))""",
            new_ids + list(all_known) + new_ids + list(all_known),
        ).fetchall()
        # 去重
        seen_eids = set()
        unique_edges = []
        for e in edge_rows:
            if e["id"] not in seen_eids:
                seen_eids.add(e["id"])
                unique_edges.append(e)

        # 给每个新节点算 degree 和已加载邻居数（基于 all_known + new_ids）
        all_known_after = all_known
        degree_rows = conn.execute(
            f"""SELECT node_id, COUNT(*) AS c FROM (
                    SELECT from_node_id AS node_id FROM backbone_edges WHERE from_node_id IN ({new_ph})
                    UNION ALL
                    SELECT to_node_id AS node_id FROM backbone_edges WHERE to_node_id IN ({new_ph})
                ) GROUP BY node_id""",
            new_ids + new_ids,
        ).fetchall()
        degree_map = {r["node_id"]: r["c"] for r in degree_rows}

        loaded_map: dict[int, int] = {}
        for e in unique_edges:
            if e["from_node_id"] in all_known_after and e["to_node_id"] in all_known_after:
                if e["from_node_id"] in new_ids:
                    loaded_map[e["from_node_id"]] = loaded_map.get(e["from_node_id"], 0) + 1
                if e["to_node_id"] in new_ids:
                    loaded_map[e["to_node_id"]] = loaded_map.get(e["to_node_id"], 0) + 1

    nodes = [
        _serialize_node(r, degree_map.get(r["id"], 0), loaded_map.get(r["id"], 0))
        for r in node_rows
    ]
    edges = [_serialize_edge(r) for r in unique_edges]
    return {"nodes": nodes, "edges": edges}


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


def _build_trace_bundle(entry_row, trace_row) -> dict:
    """组装单条 entry 的完整 trace bundle（entry + trace + rollback）。"""
    def _j(v):
        try:
            return json.loads(v) if v else None
        except Exception:
            return v

    entry = {
        "id":                entry_row["id"],
        "created_at":        entry_row["created_at"],
        "type":              entry_row["type"],
        "raw":               entry_row["raw"],
        "source":            entry_row["source"],
        "memory_type":       entry_row["memory_type"],
        "mood":              entry_row["mood"],
        "tags":              _j(entry_row["tags"]) or [],
        "context":           _j(entry_row["context_json"]) or {},
        "metadata":          _j(entry_row["metadata_json"]) or {},
        "processing_status": entry_row["processing_status"],
    }
    if trace_row is None:
        return {"entry": entry, "trace": None, "rollback": None, "trace_updated_at": None}
    return {
        "entry":            entry,
        "trace":            _j(trace_row["trace_json"]),
        "rollback":         _j(trace_row["rollback_json"]),
        "trace_updated_at": trace_row["updated_at"],
    }


@router.get("/entry/{entry_id}/trace/export")
def export_entry_trace(entry_id: int):
    """单条 entry 的完整 process trace 下载（JSON 文件）。"""
    with get_conn() as conn:
        entry_row = conn.execute(
            "SELECT id, created_at, type, raw, source, memory_type, mood, "
            "tags, context_json, metadata_json, processing_status "
            "FROM entries WHERE id=?",
            (entry_id,),
        ).fetchone()
        if not entry_row:
            raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
        trace_row = conn.execute(
            "SELECT trace_json, rollback_json, updated_at FROM pipeline_traces WHERE entry_id=?",
            (entry_id,),
        ).fetchone()

    bundle = _build_trace_bundle(entry_row, trace_row)
    return JSONResponse(
        content=bundle,
        headers={"Content-Disposition": f"attachment; filename=entry_{entry_id}_trace.json"},
    )


@router.get("/traces/export")
def export_all_traces():
    """全量 process trace 打包下载，便于离线评测。"""
    with get_conn() as conn:
        entry_rows = conn.execute(
            "SELECT id, created_at, type, raw, source, memory_type, mood, "
            "tags, context_json, metadata_json, processing_status "
            "FROM entries ORDER BY created_at ASC"
        ).fetchall()
        trace_rows = conn.execute(
            "SELECT entry_id, trace_json, rollback_json, updated_at FROM pipeline_traces"
        ).fetchall()

    trace_by_entry = {r["entry_id"]: r for r in trace_rows}
    items = [_build_trace_bundle(er, trace_by_entry.get(er["id"])) for er in entry_rows]

    from datetime import datetime, timezone
    return JSONResponse(
        content={
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count":       len(items),
            "with_trace":  sum(1 for it in items if it["trace"] is not None),
            "items":       items,
        },
        headers={"Content-Disposition": "attachment; filename=process_traces.json"},
    )


@router.get("/profile/evolution")
def profile_evolution():
    """Time series of every score-format dimension's sub-keys.

    Driven by config — any enabled dimension with summary_format='scores' and
    merge=True automatically shows up. Shape:
        { "<dim_key>": { "<sub_key>": [{entry_id, date, score, confidence}] } }
    Sub-keys with no datapoints across all snapshots are pruned.
    """
    score_dims = [
        d for d in DIMENSIONS
        if d.get("enabled", True)
        and d.get("merge", True)
        and d.get("summary_format") == "scores"
    ]
    if not score_dims:
        return {}

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ps.entry_id, ps.snapshot_json, e.created_at
               FROM profile_snapshots ps
               JOIN entries e ON e.id = ps.entry_id
               ORDER BY e.created_at ASC"""
        ).fetchall()

    # Pre-build empty series per (dim, sub_key) when sub_dimensions are declared.
    # When a dimension declares no sub_dimensions, we discover keys from the
    # snapshot data on the fly.
    series: dict[str, dict[str, list]] = {}
    declared_subs: dict[str, list[str] | None] = {}
    for d in score_dims:
        dim_key = d["key"]
        subs = d.get("sub_dimensions") or []
        sub_keys = [s["key"] for s in subs if s.get("key")]
        declared_subs[dim_key] = sub_keys or None
        series[dim_key] = {k: [] for k in sub_keys}

    for row in rows:
        try:
            snap = json.loads(row["snapshot_json"])
        except Exception:
            continue
        date = (row["created_at"] or "")[:10]
        entry_id = row["entry_id"]

        for dim_key, sub_map in series.items():
            data = snap.get(dim_key, {})
            if not isinstance(data, dict):
                continue
            keys_to_walk = declared_subs[dim_key] or list(data.keys())
            for k in keys_to_walk:
                v = data.get(k)
                if not isinstance(v, dict) or "score" not in v:
                    continue
                sub_map.setdefault(k, []).append({
                    "entry_id":   entry_id,
                    "date":       date,
                    "score":      round(float(v["score"]), 2),
                    "confidence": round(float(v.get("confidence", 0)), 3),
                })

    # prune empty sub-keys; prune dims that ended up entirely empty
    pruned: dict[str, dict[str, list]] = {}
    for dim_key, sub_map in series.items():
        filtered = {k: v for k, v in sub_map.items() if v}
        if filtered:
            pruned[dim_key] = filtered
    return pruned


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


# ── Pipeline 可视化 / 算法 replay ────────────────────────────────────────────


@router.get("/pipeline/entries")
def pipeline_entries(limit: int = 50):
    """最近 N 条 entry 的轻量列表，供 Pipeline 面板下拉选择。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT e.id, e.created_at, e.processing_status,
                      substr(coalesce(e.raw, ''), 1, 80) AS preview,
                      pt.updated_at AS trace_updated_at
               FROM entries e
               LEFT JOIN pipeline_traces pt ON pt.entry_id = e.id
               ORDER BY e.created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [
        {
            "id":                r["id"],
            "created_at":        r["created_at"],
            "processing_status": r["processing_status"],
            "preview":           r["preview"],
            "has_trace":         r["trace_updated_at"] is not None,
        }
        for r in rows
    ]


@router.get("/pipeline/health")
def pipeline_health(limit: int = 100):
    """聚合最近 N 条 entry 的 slice_extraction_health 计数。

    每个维度返回总计数和占比，用于观测 prompt 质量趋势：
    - high null_count_ratio = LLM 学会了 abstain（好）
    - high low_conf_count_ratio = LLM 仍走旧 prompt 行为（坏）
    - high midpoint_hedge_ratio = anchoring 残留，可能需要进一步 prompt 调整
    """
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT pt.entry_id, pt.trace_json, e.created_at
               FROM pipeline_traces pt
               JOIN entries e ON e.id = pt.entry_id
               ORDER BY e.created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

    # dim_key -> {total, null_count, low_conf_count, midpoint_hedge_count, entries_with_data}
    agg: dict[str, dict[str, int]] = {}
    entries_seen = 0
    for r in rows:
        try:
            trace = json.loads(r["trace_json"])
        except Exception:
            continue
        health = trace.get("slice_extraction_health") or {}
        if not isinstance(health, dict) or not health:
            continue
        entries_seen += 1
        for dim_key, h in health.items():
            if not isinstance(h, dict):
                continue
            slot = agg.setdefault(dim_key, {
                "total": 0, "null_count": 0, "low_conf_count": 0,
                "midpoint_hedge_count": 0, "entries_with_data": 0,
            })
            slot["total"] += int(h.get("total", 0))
            slot["null_count"] += int(h.get("null_count", 0))
            slot["low_conf_count"] += int(h.get("low_conf_count", 0))
            slot["midpoint_hedge_count"] += int(h.get("midpoint_hedge_count", 0))
            slot["entries_with_data"] += 1

    # ratios
    out = []
    for dim_key, slot in sorted(agg.items()):
        total = max(slot["total"], 1)
        out.append({
            "dimension": dim_key,
            "entries_with_data":     slot["entries_with_data"],
            "subdim_observations":   slot["total"],
            "null_count":            slot["null_count"],
            "low_conf_count":        slot["low_conf_count"],
            "midpoint_hedge_count":  slot["midpoint_hedge_count"],
            "null_ratio":            round(slot["null_count"] / total, 3),
            "low_conf_ratio":        round(slot["low_conf_count"] / total, 3),
            "midpoint_hedge_ratio":  round(slot["midpoint_hedge_count"] / total, 3),
        })
    return {"entries_scanned": len(rows), "entries_with_health": entries_seen, "by_dimension": out}


class ReplayRequest(BaseModel):
    dimension: str | None = None
    limit:     int | None = None


@router.post("/admin/replay/profile-merge")
def admin_replay_profile_merge(req: ReplayRequest):
    """从 slice_features 重算 profile_dimensions + profile_snapshots，零 LLM 调用。

    用于：改了融合公式或 PROFILE_MERGE 配置后，想在已有数据上看新曲线。
    可选 dimension（只重算某维度）和 limit（只重算前 N 条 entry）。
    """
    from scripts.replay_profile_merge import replay
    stats = replay(dimension=req.dimension, limit=req.limit)
    return {
        "entries_processed":       stats.entries_processed,
        "slice_features_replayed": stats.slice_features_replayed,
        "dimensions_touched":      stats.dimensions_touched,
        "snapshots_written":       stats.snapshots_written,
    }


# ── Prompt Sandbox ──────────────────────────────────────────────────────────
# 在不污染生产数据的前提下，对指定 entry 子集用候选 prompt 跑抽取，并与
# 现有 slice_features（基线）做 diff。仅调 LLM，不写 slice_features /
# profile_dimensions。供改 prompt 时低成本验证效果。


@router.get("/sandbox/dimensions")
def sandbox_dimensions():
    """列出 score-format 维度（sandbox 一次只调一个），含当前 prompt + rubric 文本。"""
    from app.lib.config_loader import DIMENSIONS as _DIMS
    out = []
    for d in _DIMS:
        if d.get("summary_format") != "scores" or not d.get("enabled", True):
            continue
        out.append({
            "key":             d["key"],
            "name":            d.get("name", d["key"]),
            "sub_dimensions":  d.get("sub_dimensions") or [],
            "score_range":     d.get("score_range") or [0, 100],
            "current_prompt":  d.get("_prompt", ""),
            "current_rubric":  d.get("_rubric", ""),
        })
    return out


class SandboxExtractRequest(BaseModel):
    dimension:        str
    entry_ids:        list[int]
    prompt_template:  str | None = None  # if None, use current
    rubric:           str | None = None  # if None, use current


@router.post("/sandbox/extract")
async def sandbox_extract(req: SandboxExtractRequest):
    """对指定 entry 跑候选 prompt，返回逐条 baseline vs candidate 抽取 + 聚合 health。

    完全不写 DB。每条 entry 1 次 LLM 调用 × len(entry_ids) 次总调用。
    建议 entry 数 ≤ 10 控制成本。
    """
    from string import Template

    from app.lib.config_loader import DIMENSION_MAP
    from app.lib.slice_pipeline import _extraction_health, _normalize_extraction
    from shared.llm import StructuredLLMError, chat_json, is_structured_llm_configured

    if not is_structured_llm_configured():
        raise HTTPException(status_code=400, detail="LLM not configured")

    dim_cfg = DIMENSION_MAP.get(req.dimension)
    if not dim_cfg or dim_cfg.get("summary_format") != "scores":
        raise HTTPException(status_code=400, detail=f"unknown or non-score dimension: {req.dimension}")

    if not req.entry_ids:
        raise HTTPException(status_code=400, detail="entry_ids must be non-empty")
    if len(req.entry_ids) > 30:
        raise HTTPException(status_code=400, detail="entry_ids capped at 30 to control LLM cost")

    prompt_tmpl = req.prompt_template if req.prompt_template is not None else dim_cfg.get("_prompt", "")
    rubric_text = req.rubric          if req.rubric          is not None else dim_cfg.get("_rubric", "")
    if not prompt_tmpl:
        raise HTTPException(status_code=400, detail="empty prompt template")

    # Pull raw + baseline (existing slice_features for this dim) per entry
    placeholders = ",".join(["?"] * len(req.entry_ids))
    with get_conn() as conn:
        entry_rows = conn.execute(
            f"SELECT id, raw FROM entries WHERE id IN ({placeholders})",
            req.entry_ids,
        ).fetchall()
        baseline_rows = conn.execute(
            f"""SELECT s.entry_id, sf.content_json
                FROM slice_features sf
                JOIN slices s ON s.id = sf.slice_id
                WHERE s.entry_id IN ({placeholders}) AND sf.dimension = ?""",
            [*req.entry_ids, req.dimension],
        ).fetchall()
    raw_by_id     = {r["id"]: r["raw"] or "" for r in entry_rows}
    baseline_by_id: dict[int, dict] = {}
    for r in baseline_rows:
        try:
            baseline_by_id[r["entry_id"]] = json.loads(r["content_json"])
        except Exception:
            baseline_by_id[r["entry_id"]] = {}

    results = []
    baseline_health_agg = {"total": 0, "null_count": 0, "low_conf_count": 0, "midpoint_hedge_count": 0}
    candidate_health_agg = {"total": 0, "null_count": 0, "low_conf_count": 0, "midpoint_hedge_count": 0}

    for eid in req.entry_ids:
        raw = raw_by_id.get(eid, "")
        if not raw:
            results.append({"entry_id": eid, "raw": "", "baseline": None, "candidate": None,
                            "candidate_health": {}, "error": "entry not found"})
            continue

        # Baseline: existing extraction (may be empty if never processed)
        baseline = baseline_by_id.get(eid)
        b_normalized = _normalize_extraction(dim_cfg, baseline) if baseline is not None else {}
        b_health = _extraction_health(dim_cfg, b_normalized) if b_normalized else {}

        # Candidate: run LLM with the candidate prompt+rubric (no profile_summary
        # injected — sandbox tests the prompt in isolation, not its interaction
        # with current profile)
        system_prompt = Template(prompt_tmpl).safe_substitute(
            rubric=rubric_text, profile_summary="(sandbox — no profile context)", raw_entry=raw,
        )
        try:
            raw_candidate = await chat_json(
                system_prompt=system_prompt, user_prompt="",
                stage=f"sandbox:{req.dimension}",
                context={"entry_id": eid, "raw_chars": len(raw)},
            )
        except StructuredLLMError as e:
            results.append({"entry_id": eid, "raw": raw[:200], "baseline": b_normalized or None,
                            "candidate": None, "candidate_health": {}, "error": str(e)})
            continue

        c_normalized = _normalize_extraction(dim_cfg, raw_candidate)
        c_health = _extraction_health(dim_cfg, c_normalized)

        # Aggregate
        for slot, h in [(baseline_health_agg, b_health), (candidate_health_agg, c_health)]:
            for k in ("total", "null_count", "low_conf_count", "midpoint_hedge_count"):
                slot[k] += int(h.get(k, 0))

        results.append({
            "entry_id":         eid,
            "raw":              raw[:300],   # preview, not full
            "baseline":         b_normalized if b_normalized else None,
            "candidate":        c_normalized,
            "candidate_health": c_health,
            "error":            None,
        })

    def _ratios(agg):
        total = max(agg["total"], 1)
        return {
            **agg,
            "null_ratio":           round(agg["null_count"] / total, 3),
            "low_conf_ratio":       round(agg["low_conf_count"] / total, 3),
            "midpoint_hedge_ratio": round(agg["midpoint_hedge_count"] / total, 3),
        }

    return {
        "dimension":         req.dimension,
        "results":           results,
        "baseline_health":   _ratios(baseline_health_agg),
        "candidate_health":  _ratios(candidate_health_agg),
    }
