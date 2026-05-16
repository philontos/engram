"""问题驱动的 raw 召回。

流程：
  embed(question) → top-K internal 节点 → 节点反查 source_entry_ids ∪ activations
  → 全局去重，记录每条 entry 关联到的节点
  → 排序：max(linked.strength) desc，tiebreak: created_at desc
  → 拆分为初始池 + 候选区，候选区供 explore 阶段 need_more_raw 调用
  → raw 不截断，全文进 prompt；只受总字符预算约束。

设计原则：raw 是消费链路最原汁原味的证据，不做摘要、不截断单条；
只在总量上设上限（默认 40000 字 ≈ 13K tokens）。
"""

from __future__ import annotations

import json
from typing import Any

from app.lib.db import get_conn
from app.lib.embed import embed
from app.lib.retrieval import positive_retrieval

DEFAULT_K_NODES        = 12       # 召回的内部节点数（按 sim 排序）
DEFAULT_INIT_SIZE      = 8        # 初始进 prompt 的 unique entry 数
DEFAULT_TOTAL_BUDGET   = 40000    # 总字符预算（包括追加）
PER_NODE_ACTIVATION_LIMIT = 20    # 单节点反查 activations 的上限


async def build_raw_pool(
    question: str,
    k_nodes: int = DEFAULT_K_NODES,
    init_size: int = DEFAULT_INIT_SIZE,
    total_budget: int = DEFAULT_TOTAL_BUDGET,
) -> dict[str, Any]:
    """构建 raw_pool。返回结构见模块 docstring。

    raw 不截断；超出预算的候选会被裁掉，不会进 prompt。
    """
    q_emb = await embed(question)
    if not q_emb:
        return _empty_pool()

    # 步骤 1：向量召回 top-K 内部节点（filter origin=internal）
    candidate_nodes = positive_retrieval(q_emb, top_k=k_nodes * 2)
    internal_nodes = [n for n in candidate_nodes if n.get("origin") == "internal"][:k_nodes]
    if not internal_nodes:
        return _empty_pool()

    # 步骤 2：对每个节点反查 entry_id 集合
    entry_links: dict[int, list[dict]] = {}  # entry_id -> [{node_id, label, strength, sim}]
    for node in internal_nodes:
        node_id = node["id"]
        entry_ids = _collect_entry_ids_for_node(node_id)
        for eid in entry_ids:
            entry_links.setdefault(eid, []).append({
                "node_id":  node_id,
                "label":    node.get("label", ""),
                "domain":   node.get("domain", ""),
                "strength": float(node.get("strength", 0)),
                "sim":      float(node.get("sim", 0) or 0),
            })

    if not entry_links:
        return _empty_pool()

    # 步骤 3：批量取 entries 全文 + created_at
    entry_rows = _fetch_entries_full(list(entry_links.keys()))

    # 步骤 4：组装 + 排序
    entries: list[dict] = []
    for row in entry_rows:
        eid = row["id"]
        raw = (row["raw"] or "").strip()
        if not raw:
            continue
        links = entry_links.get(eid, [])
        max_strength = max((l["strength"] for l in links), default=0.0)
        entries.append({
            "id":           eid,
            "date":         (row["created_at"] or "")[:10],
            "created_at":   row["created_at"] or "",
            "raw":          raw,                          # 不截断
            "linked_nodes": links,
            "max_strength": round(max_strength, 4),
        })

    entries.sort(
        key=lambda e: (e["max_strength"], e["created_at"]),
        reverse=True,
    )

    # 步骤 5：按总预算切分初始池 / 候选区
    initial: list[dict] = []
    candidates: list[dict] = []
    used_chars = 0
    for e in entries:
        chars = len(e["raw"])
        if len(initial) < init_size and used_chars + chars <= total_budget:
            initial.append(e)
            used_chars += chars
        elif used_chars + chars <= total_budget:
            candidates.append(e)
        # 超出预算的 entry 直接丢（既不是 initial 也不是 candidate）

    return {
        "entries":     initial,
        "candidates":  candidates,
        "total_chars": used_chars,
        "budget":      total_budget,
        "exhausted":   not bool(candidates),
        "k_nodes":     k_nodes,
        "init_size":   init_size,
    }


def append_from_pool(pool: dict[str, Any], count: int = 3) -> list[dict]:
    """从 candidates 弹出 N 条进 entries，受总预算约束。返回新增的 entries。"""
    if not pool.get("candidates"):
        pool["exhausted"] = True
        return []

    added: list[dict] = []
    while len(added) < count and pool["candidates"]:
        e = pool["candidates"][0]
        chars = len(e["raw"])
        if pool["total_chars"] + chars > pool["budget"]:
            pool["exhausted"] = True
            break
        pool["candidates"].pop(0)
        pool["entries"].append(e)
        pool["total_chars"] += chars
        added.append(e)

    if not pool["candidates"]:
        pool["exhausted"] = True
    return added


def _collect_entry_ids_for_node(node_id: int) -> list[int]:
    """source_entry_ids ∪ 最近 N 条 activations。"""
    ids: set[int] = set()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT source_entry_ids FROM backbone_nodes WHERE id=?",
            (node_id,),
        ).fetchone()
        if row:
            try:
                ids.update(int(e) for e in json.loads(row["source_entry_ids"] or "[]"))
            except Exception:
                pass
        rows = conn.execute(
            "SELECT entry_id FROM backbone_activations "
            "WHERE node_id=? ORDER BY created_at DESC LIMIT ?",
            (node_id, PER_NODE_ACTIVATION_LIMIT),
        ).fetchall()
        ids.update(r["entry_id"] for r in rows)
    return sorted(ids)


def _fetch_entries_full(entry_ids: list[int]) -> list[dict]:
    if not entry_ids:
        return []
    placeholders = ",".join("?" * len(entry_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, raw, created_at FROM entries WHERE id IN ({placeholders})",
            entry_ids,
        ).fetchall()
    return [dict(r) for r in rows]


def _empty_pool() -> dict[str, Any]:
    return {
        "entries":     [],
        "candidates":  [],
        "total_chars": 0,
        "budget":      DEFAULT_TOTAL_BUDGET,
        "exhausted":   True,
        "k_nodes":     DEFAULT_K_NODES,
        "init_size":   DEFAULT_INIT_SIZE,
    }


def render_raw_pool(pool: dict[str, Any]) -> str:
    """把 raw_pool 渲染成 prompt 段落。raw 不截断、不摘要。"""
    entries = pool.get("entries") or []
    if not entries:
        return ""
    lines = ["## Relevant raw records (the user's own words — not truncated)",
             "Records below are the most relevant entries retrieved for the current question; each is tagged with its associated core-belief nodes. "
             "When interpreting the user, strictly anchor in their own words — do not infer specific intent backward from node labels.\n"]
    for e in entries:
        date = e.get("date", "")
        eid = e.get("id")
        labels = ", ".join(
            f"{l['label']}(s={l['strength']:.2f})"
            for l in (e.get("linked_nodes") or [])[:5]
        )
        lines.append(f"### Record #{eid} ({date}) — linked nodes: {labels}")
        lines.append(e.get("raw", ""))
        lines.append("")
    return "\n".join(lines)
