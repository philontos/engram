"""Entry 聚合层：把累积节点映射到原始记录全文。

对每个 internal 节点，从两个来源取 entry_id：
  1. backbone_nodes.source_entry_ids（生成该节点的原始 entries）
  2. backbone_activations（后续激活该节点的所有 entries）
取并集，按 created_at 排序，返回结构化数据。
"""

import json

from app.lib.db import get_conn

ENTRY_MAX_CHARS = 800
TOP_NODES_N = 12


def aggregate_entries(all_nodes: dict[int, dict]) -> list[dict]:
    """
    输入：all_nodes = {id: node_dict}（来自 run_query 累积的图谱节点）
    输出：[
      {
        "node": {id, label, domain, node_type, origin, strength, description},
        "entries": [{"id", "date", "raw", "relevance"}]
      }
    ]
    只处理 internal 节点，按 strength 降序取 TOP_NODES_N 个。
    """
    internal_nodes = sorted(
        [n for n in all_nodes.values() if n.get("origin") == "internal"],
        key=lambda n: float(n.get("strength", 0)),
        reverse=True,
    )[:TOP_NODES_N]

    if not internal_nodes:
        return []

    result = []
    for node in internal_nodes:
        node_id = node["id"]
        entry_ids = _collect_entry_ids(node_id)
        if not entry_ids:
            continue
        entries = _fetch_entries(node_id, entry_ids)
        if not entries:
            continue
        result.append({
            "node": {
                "id": node_id,
                "label": node.get("label", ""),
                "domain": node.get("domain", ""),
                "node_type": node.get("node_type", ""),
                "origin": "internal",
                "strength": float(node.get("strength", 0)),
                "description": node.get("description", ""),
            },
            "entries": entries,
        })

    return result


def _collect_entry_ids(node_id: int) -> list[int]:
    """取节点关联的全部 entry_id。"""
    ids: set[int] = set()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT source_entry_ids FROM backbone_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if row:
            try:
                ids.update(int(e) for e in json.loads(row["source_entry_ids"] or "[]"))
            except Exception:
                pass

        rows = conn.execute(
            "SELECT entry_id FROM backbone_activations "
            "WHERE node_id = ? ORDER BY created_at DESC LIMIT 20",
            (node_id,),
        ).fetchall()
        ids.update(r["entry_id"] for r in rows)

    return sorted(ids)


def _fetch_entries(node_id: int, entry_ids: list[int]) -> list[dict]:
    """取 entries 全文，按时间排序；顺带取 user_relevance。"""
    if not entry_ids:
        return []

    placeholders = ",".join("?" * len(entry_ids))
    with get_conn() as conn:
        entry_rows = conn.execute(
            f"SELECT id, raw, created_at FROM entries "
            f"WHERE id IN ({placeholders}) ORDER BY created_at ASC",
            entry_ids,
        ).fetchall()

        rel_rows = conn.execute(
            f"SELECT entry_id, user_relevance FROM backbone_activations "
            f"WHERE node_id = ? AND entry_id IN ({placeholders}) "
            f"ORDER BY created_at DESC",
            (node_id, *entry_ids),
        ).fetchall()

    relevance_map: dict[int, str] = {}
    for r in rel_rows:
        if r["entry_id"] not in relevance_map:
            relevance_map[r["entry_id"]] = r["user_relevance"]

    result = []
    for row in entry_rows:
        raw = (row["raw"] or "").strip()
        if not raw:
            continue
        result.append({
            "id": row["id"],
            "date": (row["created_at"] or "")[:10],
            "raw": raw[:ENTRY_MAX_CHARS],
            "relevance": relevance_map.get(row["id"], ""),
        })

    return result
