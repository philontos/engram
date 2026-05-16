"""POST /entries/{entry_id}/revert — 精准 LIFO 回滚一条 entry 的全部影响。

要求：pipeline_traces 中有 rollback_json（新链路处理的 entry 才有）。
调用方应保证 LIFO 顺序，即每次只回退最近一条 processed entry。
"""

import json
from fastapi import APIRouter, HTTPException
from app.lib.db import get_conn

router = APIRouter()


@router.post("/entries/{entry_id}/revert")
def revert_entry(entry_id: int):
    with get_conn() as conn:
        entry_row = conn.execute(
            "SELECT id, processing_status FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
    if not entry_row:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry_row["processing_status"] == "reverted":
        raise HTTPException(status_code=409, detail="Entry already reverted")
    if entry_row["processing_status"] not in ("processed",):
        raise HTTPException(status_code=422, detail=f"Entry status '{entry_row['processing_status']}' is not revertible")

    with get_conn() as conn:
        latest = conn.execute(
            "SELECT id FROM entries WHERE processing_status='processed' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not latest or latest["id"] != entry_id:
        hint = f" Revert entry {latest['id']} first." if latest else ""
        raise HTTPException(status_code=422, detail=f"LIFO order required: this is not the latest processed entry.{hint}")

    with get_conn() as conn:
        trace_row = conn.execute(
            "SELECT rollback_json FROM pipeline_traces WHERE entry_id=?", (entry_id,)
        ).fetchone()

    if not trace_row or not trace_row["rollback_json"]:
        raise HTTPException(
            status_code=422,
            detail="No rollback data available for this entry. Use the best-effort script for older entries.",
        )

    rollback = json.loads(trace_row["rollback_json"])
    prev_snapshot_id = rollback.get("prev_profile_snapshot_id")
    nodes = rollback.get("nodes", [])
    edges = rollback.get("edges", [])

    with get_conn() as conn:
        # 1. 恢复 profile_dimensions
        if prev_snapshot_id:
            snap_row = conn.execute(
                "SELECT snapshot_json FROM profile_snapshots WHERE id=?", (prev_snapshot_id,)
            ).fetchone()
            if snap_row:
                snapshot = json.loads(snap_row["snapshot_json"])
                conn.execute("DELETE FROM profile_dimensions")
                for dimension, content in snapshot.items():
                    conn.execute(
                        "INSERT INTO profile_dimensions (dimension, content_json, sample_count, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                        (dimension, json.dumps(content, ensure_ascii=False), 0),
                    )
        elif not prev_snapshot_id:
            # 这是第一条 entry，profile 回到空
            conn.execute("DELETE FROM profile_dimensions")

        # 2. 处理节点
        new_node_ids = [n["id"] for n in nodes if n.get("is_new")]
        updated_nodes = [n for n in nodes if not n.get("is_new")]

        if new_node_ids:
            ph = ",".join("?" * len(new_node_ids))
            conn.execute(f"DELETE FROM backbone_edges WHERE from_node_id IN ({ph}) OR to_node_id IN ({ph})", (*new_node_ids, *new_node_ids))
            conn.execute(f"DELETE FROM backbone_activations WHERE node_id IN ({ph})", new_node_ids)
            conn.execute(f"DELETE FROM backbone_nodes WHERE id IN ({ph})", new_node_ids)

        for n in updated_nodes:
            conn.execute(
                """UPDATE backbone_nodes SET
                   strength=?, hit_count=?, last_hit_at=?,
                   source_entry_ids=?, origin=?, current_activation_id=?,
                   updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (n["strength"], n["hit_count"], n["last_hit_at"],
                 n["source_entry_ids"], n["origin"], n["current_activation_id"],
                 n["id"]),
            )

        # 3. 处理边
        new_edge_ids = [e["id"] for e in edges if e.get("is_new")]
        updated_edges = [e for e in edges if not e.get("is_new")]

        if new_edge_ids:
            ph = ",".join("?" * len(new_edge_ids))
            conn.execute(f"DELETE FROM backbone_edges WHERE id IN ({ph})", new_edge_ids)

        for e in updated_edges:
            conn.execute(
                """UPDATE backbone_edges SET
                   weight=?, confidence=?, source_entry_ids=?,
                   last_reinforced_at=?, edge_source=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (e["weight"], e["confidence"], e["source_entry_ids"],
                 e["last_reinforced_at"], e["edge_source"], e["id"]),
            )

        # 4. 删除衍生数据
        slice_ids = [r["id"] for r in conn.execute("SELECT id FROM slices WHERE entry_id=?", (entry_id,)).fetchall()]
        if slice_ids:
            ph = ",".join("?" * len(slice_ids))
            conn.execute(f"DELETE FROM slice_features WHERE slice_id IN ({ph})", slice_ids)
        conn.execute("DELETE FROM slices WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM backbone_activations WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM profile_snapshots WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM pipeline_traces WHERE entry_id=?", (entry_id,))

        # 5. 标记 entry
        conn.execute("UPDATE entries SET processing_status='reverted' WHERE id=?", (entry_id,))

    return {
        "reverted": entry_id,
        "nodes_restored": len(updated_nodes),
        "nodes_deleted": len(new_node_ids),
        "edges_restored": len(updated_edges),
        "edges_deleted": len(new_edge_ids),
        "profile_restored": prev_snapshot_id is not None,
    }
