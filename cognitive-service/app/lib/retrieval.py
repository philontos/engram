"""消费层召回：正向 top-k + 对立邻居 + 盲区候选 + 子图展开。

对立召回不做反向 embedding（语义不稳），而是利用图中已有的"opposes"边从正向节点跳出。
"""

import json
import math
from datetime import datetime, timezone

import numpy as np

from app.config.graph_rules import EDGE_DECAY, RETRIEVAL
from app.lib.db import get_conn


def _cosine(a: list, b: list) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _edge_decay_factor(last_reinforced_at: str | None) -> float:
    if not last_reinforced_at:
        return 1.0
    try:
        dt = datetime.fromisoformat(last_reinforced_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return 1.0
    lam = EDGE_DECAY["lambda"]
    floor = EDGE_DECAY["floor"]
    return max(floor, math.exp(-lam * days))


def positive_retrieval(
    question_emb: list[float],
    top_k: int = 8,
    exclude_ids: set[int] | None = None,
) -> list[dict]:
    """全域 cosine top-k 入口节点。返回字段含 id, label, domain, origin, strength, sim。

    exclude_ids: 跳过这些节点（多轮探索时避免重复召回）。
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, domain, node_type, label, description, strength, origin, embedding_json "
            "FROM backbone_nodes WHERE embedding_json IS NOT NULL"
        ).fetchall()

    if not rows:
        return []

    q = np.array(question_emb, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []

    skip = exclude_ids or set()
    scored: list[tuple[float, dict]] = []
    for row in rows:
        if row["id"] in skip:
            continue
        try:
            v = np.array(json.loads(row["embedding_json"]), dtype=np.float32)
            v_norm = np.linalg.norm(v)
            if v_norm == 0:
                continue
            sim = float(np.dot(q, v) / (q_norm * v_norm))
        except Exception:
            continue
        scored.append((sim, dict(row)))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {**node, "sim": round(sim, 4)}
        for sim, node in scored[:top_k]
    ]


def opposite_retrieval(seed_nodes: list[dict]) -> list[dict]:
    """沿图中 'opposes' 边从 seed_nodes 跳 1 跳，返回对立邻居。"""
    seed_ids = {n["id"] for n in seed_nodes if n.get("id")}
    if not seed_ids:
        return []

    placeholders = ",".join("?" * len(seed_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT n.id, n.domain, n.node_type, n.label, n.description,
                            n.strength, n.origin,
                            e.weight, e.last_reinforced_at,
                            e.from_node_id, e.to_node_id
            FROM backbone_edges e
            JOIN backbone_nodes n
              ON n.id = CASE
                          WHEN e.from_node_id IN ({placeholders}) THEN e.to_node_id
                          ELSE e.from_node_id
                        END
            WHERE e.relation_type = 'opposes'
              AND (e.from_node_id IN ({placeholders}) OR e.to_node_id IN ({placeholders}))
            """,
            (*seed_ids, *seed_ids, *seed_ids),
        ).fetchall()

    result = []
    seen = set()
    for r in rows:
        if r["id"] in seed_ids or r["id"] in seen:
            continue
        seen.add(r["id"])
        decay = _edge_decay_factor(r["last_reinforced_at"])
        effective_w = round(float(r["weight"]) * decay, 4)
        result.append({
            "id": r["id"], "domain": r["domain"], "node_type": r["node_type"],
            "label": r["label"], "description": r["description"],
            "strength": r["strength"], "origin": r["origin"],
            "opposite_edge_weight": effective_w,
        })
    return result


def find_blindspots(seed_nodes: list[dict], min_strength: float = 0.5) -> list[dict]:
    """盲区候选：内源 + 高 strength + 无对立边 → 用户自认为确定但缺乏张力的节点。"""
    candidates = [
        n for n in seed_nodes
        if n.get("origin") == "internal"
        and float(n.get("strength", 0)) >= min_strength
    ]
    if not candidates:
        return []

    ids = [n["id"] for n in candidates]
    placeholders = ",".join("?" * len(ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT CASE
                              WHEN from_node_id IN ({placeholders}) THEN from_node_id
                              ELSE to_node_id
                            END AS node_id
            FROM backbone_edges
            WHERE relation_type = 'opposes'
              AND (from_node_id IN ({placeholders}) OR to_node_id IN ({placeholders}))
            """,
            (*ids, *ids, *ids),
        ).fetchall()
    has_opposite = {r["node_id"] for r in rows}
    return [n for n in candidates if n["id"] not in has_opposite]


def expand_subgraph(seed_nodes: list[dict], hop_per_relation: dict[str, int] | None = None) -> dict:
    """按 relation 类型分别展开子图（类型感知遍历）。

    默认：对立 2-hop（矛盾放大）、推导 3-hop（因果链）、支撑 2-hop（背景）、相似 1-hop（跨域）。
    """
    hops = hop_per_relation or {"opposes": 2, "derives": 3, "supports": 2, "similar": 1}
    seed_ids = [n["id"] for n in seed_nodes if n.get("id")]
    if not seed_ids:
        return {"nodes": [], "edges": []}

    nodes_out: dict[int, dict] = {}
    edges_out: list[dict] = []
    seen_edges: set[int] = set()

    # 初始化 seed 节点
    for n in seed_nodes:
        nodes_out[n["id"]] = {
            "id": n["id"], "label": n.get("label", ""), "domain": n.get("domain", ""),
            "node_type": n.get("node_type", ""), "origin": n.get("origin", "internal"),
            "strength": float(n.get("strength", 0)),
        }

    frontier_by_relation: dict[str, set[int]] = {r: set(seed_ids) for r in hops}

    for relation, max_hop in hops.items():
        visited = set()
        frontier = frontier_by_relation[relation]
        for _ in range(max_hop):
            if not frontier:
                break
            next_frontier: set[int] = set()
            for node_id in frontier:
                if node_id in visited:
                    continue
                visited.add(node_id)
                _step_expand(node_id, relation, nodes_out, edges_out, seen_edges, next_frontier)
            frontier = next_frontier

    return {"nodes": list(nodes_out.values()), "edges": edges_out}


def _step_expand(
    node_id: int, relation: str,
    nodes_out: dict, edges_out: list, seen_edges: set, next_frontier: set,
) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT e.id, e.from_node_id, e.to_node_id, e.relation_type,
                      e.weight, e.last_reinforced_at, e.edge_source,
                      n1.label AS from_label, n2.label AS to_label,
                      n1.domain AS from_domain, n2.domain AS to_domain,
                      n1.node_type AS from_type, n2.node_type AS to_type,
                      n1.origin AS from_origin, n2.origin AS to_origin,
                      n1.strength AS from_strength, n2.strength AS to_strength,
                      n1.description AS from_description,
                      n2.description AS to_description
               FROM backbone_edges e
               JOIN backbone_nodes n1 ON n1.id = e.from_node_id
               JOIN backbone_nodes n2 ON n2.id = e.to_node_id
               WHERE e.relation_type = ?
                 AND (e.from_node_id = ? OR e.to_node_id = ?)
               LIMIT ?""",
            (relation, node_id, node_id, RETRIEVAL["max_edges_per_node"]),
        ).fetchall()

    for edge in rows:
        if edge["id"] in seen_edges:
            continue
        seen_edges.add(edge["id"])
        decay = _edge_decay_factor(edge["last_reinforced_at"])
        edges_out.append({
            "from_id": edge["from_node_id"], "to_id": edge["to_node_id"],
            "from_label": edge["from_label"], "to_label": edge["to_label"],
            "relation_type": edge["relation_type"],
            "weight": round(float(edge["weight"]) * decay, 4),
            "edge_source": edge["edge_source"],
        })
        neighbor_id = edge["to_node_id"] if edge["from_node_id"] == node_id else edge["from_node_id"]
        if neighbor_id not in nodes_out:
            is_from = edge["from_node_id"] == neighbor_id
            nodes_out[neighbor_id] = {
                "id": neighbor_id,
                "label": edge["from_label" if is_from else "to_label"],
                "domain": edge["from_domain" if is_from else "to_domain"],
                "node_type": edge["from_type" if is_from else "to_type"],
                "origin": edge["from_origin" if is_from else "to_origin"],
                "strength": float(edge["from_strength" if is_from else "to_strength"]),
                "description": edge["from_description" if is_from else "to_description"] or "",
            }
        next_frontier.add(neighbor_id)
