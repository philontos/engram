"""Best-effort LIFO 回退脚本，用于处理没有 rollback_json 的历史 entries。

用法（按倒序传入 entry_id，即从最新到最旧）：
  python scripts/revert_entries_besteffort.py 42 41 40

能还原：
  - profile（从前一条 profile_snapshot 恢复）
  - 新建的节点（删除，trace 中有 id）
  - 已更新节点的 strength（还原 strength_before，hit_count-1，source_entry_ids 去除该 entry）
  - 新建的边（通过 label 反查 id 删除）
  - 已更新边的 weight（还原 weight_before，source_entry_ids 去除该 entry）
  - slices / activations 等衍生数据

不能还原（接受的折中）：
  - 节点 hit_count 精度（-1 近似）
  - 节点 last_hit_at（保留当前值）
  - 边的 confidence / last_reinforced_at / edge_source
  - source_entry_ids 被 cap 挤出的历史 id
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.lib.db import get_conn, init_db


def _remove_from_source_ids(src_json: str | None, entry_id: int) -> str:
    try:
        arr = json.loads(src_json or "[]")
    except Exception:
        arr = []
    arr = [x for x in arr if x != entry_id]
    return json.dumps(arr)


def revert_best_effort(entry_id: int) -> dict:
    with get_conn() as conn:
        entry_row = conn.execute(
            "SELECT id, processing_status FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
    if not entry_row:
        return {"error": f"Entry {entry_id} not found"}
    if entry_row["processing_status"] == "reverted":
        return {"error": f"Entry {entry_id} already reverted"}

    with get_conn() as conn:
        trace_row = conn.execute(
            "SELECT trace_json, rollback_json FROM pipeline_traces WHERE entry_id=?", (entry_id,)
        ).fetchone()

    if trace_row and trace_row["rollback_json"]:
        return {"error": f"Entry {entry_id} has full rollback_json — use the API endpoint instead"}

    if not trace_row or not trace_row["trace_json"]:
        return {"error": f"Entry {entry_id} has no trace data, cannot revert"}

    trace = json.loads(trace_row["trace_json"])
    db_diff = trace.get("db_diff", {})
    nodes_new = db_diff.get("nodes_new", [])
    nodes_updated = db_diff.get("nodes_updated", [])
    edges_new = db_diff.get("edges_new", [])
    edges_updated = db_diff.get("edges_updated", [])

    stats = {
        "entry_id": entry_id,
        "nodes_deleted": 0, "nodes_strength_restored": 0,
        "edges_deleted": 0, "edges_weight_restored": 0,
        "profile_restored": False, "warnings": [],
    }

    with get_conn() as conn:
        # 1. profile：恢复到前一条 profile_snapshot
        prev_snap = conn.execute(
            "SELECT id, snapshot_json FROM profile_snapshots WHERE entry_id != ? ORDER BY created_at DESC LIMIT 1",
            (entry_id,),
        ).fetchone()
        if prev_snap:
            snapshot = json.loads(prev_snap["snapshot_json"])
            conn.execute("DELETE FROM profile_dimensions")
            for dimension, content in snapshot.items():
                conn.execute(
                    "INSERT INTO profile_dimensions (dimension, content_json, sample_count, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (dimension, json.dumps(content, ensure_ascii=False), 0),
                )
            stats["profile_restored"] = True
        else:
            conn.execute("DELETE FROM profile_dimensions")
            stats["profile_restored"] = True

        # 2. 新建节点：直接删
        for n in nodes_new:
            node_id = n.get("id")
            if not node_id:
                continue
            conn.execute("DELETE FROM backbone_edges WHERE from_node_id=? OR to_node_id=?", (node_id, node_id))
            conn.execute("DELETE FROM backbone_activations WHERE node_id=?", (node_id,))
            conn.execute("DELETE FROM backbone_nodes WHERE id=?", (node_id,))
            stats["nodes_deleted"] += 1

        # 3. 已更新节点：还原 strength，hit_count-1，摘除 source_entry_ids
        for n in nodes_updated:
            node_id = n.get("id")
            s_before = n.get("strength_before")
            if not node_id or s_before is None:
                continue
            row = conn.execute(
                "SELECT hit_count, source_entry_ids FROM backbone_nodes WHERE id=?", (node_id,)
            ).fetchone()
            if not row:
                continue
            new_hit = max(0, int(row["hit_count"] or 0) - 1)
            new_src = _remove_from_source_ids(row["source_entry_ids"], entry_id)
            conn.execute(
                "UPDATE backbone_nodes SET strength=?, hit_count=?, source_entry_ids=? WHERE id=?",
                (s_before, new_hit, new_src, node_id),
            )
            stats["nodes_strength_restored"] += 1

        # 4. 新建边：通过 label 反查 id 删除
        label_to_id: dict[str, int] = {}
        for n_row in conn.execute("SELECT id, label FROM backbone_nodes").fetchall():
            label_to_id[n_row["label"]] = n_row["id"]

        for e in edges_new:
            from_id = label_to_id.get(e.get("from_label", ""))
            to_id = label_to_id.get(e.get("to_label", ""))
            rel = e.get("relation_type", "")
            if not from_id or not to_id or not rel:
                stats["warnings"].append(f"Could not resolve edge: {e}")
                continue
            conn.execute(
                "DELETE FROM backbone_edges WHERE from_node_id=? AND to_node_id=? AND relation_type=?",
                (from_id, to_id, rel),
            )
            stats["edges_deleted"] += 1

        # 5. 已更新边：还原 weight，摘除 source_entry_ids
        for e in edges_updated:
            from_id = label_to_id.get(e.get("from_label", ""))
            to_id = label_to_id.get(e.get("to_label", ""))
            rel = e.get("relation_type", "")
            w_before = e.get("weight_before")
            if not from_id or not to_id or not rel or w_before is None:
                stats["warnings"].append(f"Could not restore edge: {e}")
                continue
            row = conn.execute(
                "SELECT id, source_entry_ids FROM backbone_edges WHERE from_node_id=? AND to_node_id=? AND relation_type=?",
                (from_id, to_id, rel),
            ).fetchone()
            if not row:
                continue
            new_src = _remove_from_source_ids(row["source_entry_ids"], entry_id)
            conn.execute(
                "UPDATE backbone_edges SET weight=?, source_entry_ids=? WHERE id=?",
                (w_before, new_src, row["id"]),
            )
            stats["edges_weight_restored"] += 1

        # 6. 清理衍生数据
        slice_ids = [r["id"] for r in conn.execute("SELECT id FROM slices WHERE entry_id=?", (entry_id,)).fetchall()]
        if slice_ids:
            ph = ",".join("?" * len(slice_ids))
            conn.execute(f"DELETE FROM slice_features WHERE slice_id IN ({ph})", slice_ids)
        conn.execute("DELETE FROM slices WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM backbone_activations WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM profile_snapshots WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM pipeline_traces WHERE entry_id=?", (entry_id,))

        conn.execute("UPDATE entries SET processing_status='reverted' WHERE id=?", (entry_id,))

    return stats


if __name__ == "__main__":
    init_db()
    entry_ids = [int(x) for x in sys.argv[1:]]
    if not entry_ids:
        print("Usage: python revert_entries_besteffort.py <entry_id> [entry_id ...]")
        print("Pass entry IDs in LIFO order (newest first).")
        sys.exit(1)

    for eid in entry_ids:
        result = revert_best_effort(eid)
        print(f"Entry {eid}: {json.dumps(result, ensure_ascii=False, indent=2)}")
