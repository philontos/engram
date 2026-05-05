"""Stage 1–7: 主干网构建管线。

Pipeline:
  Stage 1  Activation        → {domain: effort_weight}
  Stage 2  全域粗召回         → rough_nodes（全域 top-k 存量节点）
  Stage 3  各域 Node Extract  → 各域候选节点（并发）
  Stage 4  Node Resolution   → confirmed_nodes（全域混合）+ cross_sim_pairs
  Stage 5  精召回             → 局部子图（per-node 3-hop/1-hop 展开）
  Stage 6  各域 Edge Extract  → 写边（effort 降序，顺序执行）
  Stage 7  跨域相似边写入

trace 参数：可选 dict，管线各阶段会原地填充，供可观测性使用。
"""

import asyncio
import json
import math
from datetime import datetime, timezone
from string import Template

import numpy as np

from app.config.graph_rules import (
    ALGO_EDGE,
    CROSS_DOMAIN_SIM_THRESHOLD,
    DEDUP_THRESHOLD,
    EDGE_WEIGHT,
    NODE_STRENGTH,
    OPPOSITION_PROPAGATION,
    RETRIEVAL,
    SOURCE_ENTRIES_MAX,
)
from app.lib.config_loader import BACKBONE_MAP, BACKBONES, load_shared_backbone_prompt
from app.lib.db import get_conn
from app.lib.embed import embed
from app.lib.slice_pipeline import get_profile_summary, get_situation_context, get_slice_summary
from shared.llm import StructuredLLMError, chat_json, is_structured_llm_configured

_ACTIVATION_PROMPT = load_shared_backbone_prompt("activation.spt")
_EDGE_PROMPT = load_shared_backbone_prompt("edge_extract.spt")
_EXTERNAL_NODE_PROMPT = load_shared_backbone_prompt("node_extract_external.spt")


def _ts(dt: datetime | None) -> str:
    """返回用于写入 DB 的时间戳字符串，dt 为 None 时取当前时间。"""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

async def run_backbone_pipeline(
    entry_id: int, slice_id: int, raw: str, trace: dict | None = None,
    entry_dt: datetime | None = None,
) -> dict:
    """完整主干网管线，返回简单统计。trace 若传入则原地填充各阶段数据。"""
    t = trace if trace is not None else {}
    entry_ts = _ts(entry_dt)

    if not is_structured_llm_configured():
        return {"activated": [], "nodes_upserted": 0, "edges_upserted": 0, "rollback_nodes": [], "rollback_edges": []}

    profile_summary = get_profile_summary()
    slice_summary = get_slice_summary(slice_id)
    situation_ctx = get_situation_context(entry_id)

    # 将情境上下文拼入 slice_summary，所有需要 slice_summary 的 LLM 步骤都能感知
    if situation_ctx:
        slice_summary = f"{slice_summary}\n[Entry context: {situation_ctx}]"

    # Stage 1: Activation
    activations = await _activate_backbones(raw, slice_summary, profile_summary)
    t["activation"] = activations
    if not activations:
        return {"activated": [], "nodes_upserted": 0, "edges_upserted": 0, "rollback_nodes": [], "rollback_edges": []}

    # Rollback: 边的 pre-snapshot（在任何边写入之前）
    with get_conn() as conn:
        _pre_edge_rows = conn.execute(
            "SELECT id, weight, confidence, source_entry_ids, last_reinforced_at, edge_source FROM backbone_edges"
        ).fetchall()
    _before_edges: dict[int, dict] = {r["id"]: dict(r) for r in _pre_edge_rows}

    # Stage 2: 全域粗召回
    raw_emb = await embed(raw)
    rough_nodes = _rough_retrieval(raw_emb, top_k=RETRIEVAL["rough_top_k"])
    t["rough_retrieval"] = [
        {"id": n["id"], "label": n["label"], "domain": n["domain"],
         "node_type": n.get("node_type", ""), "strength": round(float(n.get("strength", 0)), 4),
         "sim": round(float(n.get("rough_sim", 0)), 4)}
        for n in rough_nodes
    ]

    # Stage 3a: 内源节点抽取（各域并发，只基于 raw_entry 显式表达）
    internal_tasks = [
        _extract_internal_candidates(
            domain, effort, raw, slice_summary, profile_summary,
            [n for n in rough_nodes if n["domain"] == domain],
        )
        for domain, effort in activations.items()
    ]
    internal_results = await asyncio.gather(*internal_tasks, return_exceptions=True)
    internal_candidates: list[dict] = []
    t["node_extract_internal"] = {}
    for domain, r in zip(activations.keys(), internal_results):
        candidates = r if isinstance(r, list) else []
        internal_candidates.extend(candidates)
        t["node_extract_internal"][domain] = [
            {"label": c.get("label", ""), "node_type": c.get("node_type", ""),
             "confidence": round(float(c.get("confidence", 0)), 4),
             "description": c.get("description", ""),
             "user_relevance": c.get("user_relevance", "")}
            for c in candidates
        ]

    # Stage 3b: 外源节点扩展（基于内源种子向外发散，各域并发）
    external_tasks = [
        _extract_external_candidates(
            domain, effort, raw, slice_summary, profile_summary,
            [c for c in internal_candidates if c["domain"] == domain],
            [n for n in rough_nodes if n["domain"] == domain],
        )
        for domain, effort in activations.items()
    ]
    external_results = await asyncio.gather(*external_tasks, return_exceptions=True)
    external_candidates: list[dict] = []
    t["node_extract_external"] = {}
    for domain, r in zip(activations.keys(), external_results):
        candidates = r if isinstance(r, list) else []
        external_candidates.extend(candidates)
        t["node_extract_external"][domain] = [
            {"label": c.get("label", ""), "node_type": c.get("node_type", ""),
             "confidence": round(float(c.get("confidence", 0)), 4),
             "description": c.get("description", ""),
             "user_relevance": c.get("user_relevance", "")}
            for c in candidates
        ]

    # Stage 4: Node Resolution（内源优先，外源命中已有内源不降级）
    all_candidates = internal_candidates + external_candidates
    confirmed, emb_cache, new_count, diff_nodes, node_rollback = await _resolve_nodes(
        all_candidates, rough_nodes, entry_id, entry_ts, entry_dt
    )
    t["confirmed_nodes"] = [
        {"id": n["id"], "label": n["label"], "domain": n["domain"],
         "node_type": n.get("node_type", ""),
         "origin": n.get("origin", "internal"),
         "strength": round(float(n.get("strength", 0)), 4),
         "new_conf": round(float(n.get("new_conf") or 0), 4),
         "is_new": bool(n.get("is_new", False))}
        for n in confirmed
    ]
    t.setdefault("db_diff", {})
    t["db_diff"]["nodes_new"] = diff_nodes["new"]
    t["db_diff"]["nodes_updated"] = diff_nodes["updated"]
    t["db_diff"]["edges_new"] = []
    t["db_diff"]["edges_updated"] = []

    # Rollback: 记录 confirmed 节点写 activation 之前的 current_activation_id
    _confirmed_act_ids = [n["id"] for n in confirmed if n.get("id")]
    if _confirmed_act_ids:
        with get_conn() as conn:
            for _nid in _confirmed_act_ids:
                _arow = conn.execute(
                    "SELECT current_activation_id FROM backbone_nodes WHERE id=?", (_nid,)
                ).fetchone()
                if _arow:
                    for _nr in node_rollback:
                        if _nr.get("id") == _nid and not _nr.get("is_new") and "current_activation_id" not in _nr:
                            _nr["current_activation_id"] = _arow["current_activation_id"]

    # Write backbone_activations（带情境上下文）
    _write_activations(entry_id, confirmed, entry_ts, situation_ctx)

    # Stage 5: 精召回
    subgraph = _precise_retrieval(confirmed)
    seed_meta = subgraph.get("seed_meta", {})
    t["subgraph"] = {
        "nodes": [{
            "id": n.get("id"), "label": n.get("label", ""), "domain": n.get("domain", ""),
            "strength": round(float(n.get("strength", 0)), 4),
            **seed_meta.get(n.get("id"), {}),
        } for n in subgraph["nodes"]],
        "edges": [{"from_label": e.get("from_label", ""), "to_label": e.get("to_label", ""),
                   "relation_type": e.get("relation_type", ""),
                   "weight": round(float(e.get("weight") or 0), 4)}
                  for e in subgraph["edges"]],
    }

    # Stage 6a: 算法相似边（同域 + 跨域，不调 LLM）
    algo_edges, algo_new, algo_updated = _write_algo_similarity_edges(confirmed, emb_cache, entry_id, entry_ts)
    t["algo_edges"] = algo_edges
    t["db_diff"]["edges_new"].extend(algo_new)
    t["db_diff"]["edges_updated"].extend(algo_updated)

    # Stage 6b: LLM Edge Extract（一次性处理所有 confirmed，跳过相似类）
    t["edge_extract"] = []
    total_edges = len(algo_edges)
    if confirmed:
        count, extracted, new_edges, upd_edges = await _extract_and_persist_edges(
            entry_id, confirmed, subgraph, raw, slice_summary, entry_ts
        )
        total_edges += count
        t["edge_extract"].extend(extracted)
        t["db_diff"]["edges_new"].extend(new_edges)
        t["db_diff"]["edges_updated"].extend(upd_edges)

    # Stage 6c: 算法共现 — confirmed 两两共现产出'related'边，重复共现累加权重
    assoc_edges, assoc_new, assoc_upd = _write_association_edges(confirmed, emb_cache, entry_id, entry_ts)
    t["association_edges"] = assoc_edges
    t["db_diff"]["edges_new"].extend(assoc_new)
    t["db_diff"]["edges_updated"].extend(assoc_upd)
    total_edges += len(assoc_edges)

    # Stage 6d: 对立传染 — A⟷B 对立 且 A→C 支撑 ⇒ 推导 B⟷C 对立
    opp_edges, opp_new = _propagate_opposition_edges(confirmed, entry_id, entry_ts)
    t["opposition_propagation"] = opp_edges
    t["db_diff"]["edges_new"].extend(opp_new)
    total_edges += len(opp_edges)

    # Rollback: 边的 post-scan，找出本次写入涉及的所有边
    with get_conn() as conn:
        _post_edge_rows = conn.execute(
            "SELECT id, source_entry_ids FROM backbone_edges"
        ).fetchall()
    edge_rollback: list[dict] = []
    for _er in _post_edge_rows:
        try:
            _src = json.loads(_er["source_entry_ids"] or "[]")
        except Exception:
            _src = []
        if entry_id not in _src:
            continue
        _eid = _er["id"]
        if _eid in _before_edges:
            _b = _before_edges[_eid]
            edge_rollback.append({
                "id": _eid, "is_new": False,
                "weight": _b["weight"],
                "confidence": _b["confidence"],
                "source_entry_ids": _b["source_entry_ids"],
                "last_reinforced_at": _b["last_reinforced_at"],
                "edge_source": _b["edge_source"],
            })
        else:
            edge_rollback.append({"id": _eid, "is_new": True})

    return {
        "activated": list(activations.keys()),
        "nodes_upserted": new_count,
        "edges_upserted": total_edges,
        "rollback_nodes": node_rollback,
        "rollback_edges": edge_rollback,
    }


# ---------------------------------------------------------------------------
# Stage 1: Activation
# ---------------------------------------------------------------------------

async def _activate_backbones(raw: str, slice_summary: str, profile_summary: str) -> dict[str, float]:
    domain_list = "\n".join(f"- {b['key']}: {b['description']}" for b in BACKBONES)
    system_prompt = Template(_ACTIVATION_PROMPT).safe_substitute(
        domain_list=domain_list,
        profile_summary=profile_summary,
        slice_summary=slice_summary,
    )
    try:
        result = await chat_json(
            system_prompt=system_prompt, user_prompt=raw,
            stage="activation",
            context={"domains": len(BACKBONES), "raw_chars": len(raw)},
        )
        return {
            item["domain"]: float(item.get("effort_weight", 0.5))
            for item in (result.get("activations") or [])
            if item.get("domain") in BACKBONE_MAP
        }
    except (StructuredLLMError, Exception):
        return {}


# ---------------------------------------------------------------------------
# Stage 2: 全域粗召回
# ---------------------------------------------------------------------------

def _rough_retrieval(raw_emb: list[float], top_k: int = 30) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, domain, label, node_type, description, strength, origin, embedding_json FROM backbone_nodes WHERE embedding_json IS NOT NULL"
        ).fetchall()

    if not rows:
        return []

    q = np.array(raw_emb, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []

    scored: list[tuple[float, dict]] = []
    for row in rows:
        try:
            v = np.array(json.loads(row["embedding_json"]), dtype=np.float32)
            v_norm = np.linalg.norm(v)
            if v_norm == 0:
                continue
            sim = float(np.dot(q, v) / (q_norm * v_norm))
            scored.append((sim, dict(row)))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**node, "rough_sim": sim, "new_conf": 0.0} for sim, node in scored[:top_k]]


# ---------------------------------------------------------------------------
# Stage 3: 各域 Node Extract
# ---------------------------------------------------------------------------

async def _extract_internal_candidates(
    domain: str,
    effort: float,
    raw: str,
    slice_summary: str,
    profile_summary: str,
    domain_rough_nodes: list[dict],
) -> list[dict]:
    """Stage 3a：只从 raw_entry 显式表达中抽取内源节点。"""
    backbone = BACKBONE_MAP.get(domain)
    if not backbone:
        return []
    node_prompt = backbone.get("_internal_node_prompt", "")
    if not node_prompt:
        return []

    system_prompt = Template(node_prompt).safe_substitute(
        profile_summary=profile_summary,
        slice_summary=slice_summary,
        existing_nodes=_format_existing_nodes(domain_rough_nodes),
        effort_weight=str(round(effort, 2)),
        raw_entry=raw,
    )

    try:
        result = await chat_json(
            system_prompt=system_prompt, user_prompt="",
            stage=f"node_internal:{domain}",
            context={
                "rough_nodes_injected": len(domain_rough_nodes),
                "effort": round(effort, 2),
                "raw_chars": len(raw),
            },
        )
        candidates = result.get("nodes") or []
    except StructuredLLMError:
        return []

    return [
        {**c, "domain": domain, "origin": "internal"}
        for c in candidates if (c.get("label") or "").strip()
    ]


async def _extract_external_candidates(
    domain: str,
    effort: float,
    raw: str,
    slice_summary: str,
    profile_summary: str,
    internal_seeds: list[dict],
    domain_rough_nodes: list[dict],
) -> list[dict]:
    """Stage 3b：以内源节点为种子向外发散，补充外源节点。"""
    backbone = BACKBONE_MAP.get(domain)
    if not backbone or not _EXTERNAL_NODE_PROMPT:
        return []
    # 内源种子为空时不扩展（无锚点可依）
    if not internal_seeds:
        return []

    seeds_text = "\n".join(
        f"- [{c.get('node_type', '')}] {c.get('label', '')}：{c.get('description', '')}"
        for c in internal_seeds
    )

    system_prompt = Template(_EXTERNAL_NODE_PROMPT).safe_substitute(
        domain_key=domain,
        profile_summary=profile_summary,
        slice_summary=slice_summary,
        raw_entry=raw,
        internal_seeds=seeds_text,
        focus_hints=backbone.get("_focus_hints_text", "(no extra guidance)"),
        existing_nodes=_format_existing_nodes(domain_rough_nodes),
        effort_weight=str(round(effort, 2)),
    )

    try:
        result = await chat_json(
            system_prompt=system_prompt, user_prompt="",
            stage=f"node_external:{domain}",
            context={
                "internal_seeds": len(internal_seeds),
                "rough_nodes_injected": len(domain_rough_nodes),
                "effort": round(effort, 2),
            },
        )
        candidates = result.get("nodes") or []
    except StructuredLLMError:
        return []

    # 去重：外源候选与内源候选同 label 时剔除（避免重复抽取）
    seed_labels = {(c.get("label") or "").strip() for c in internal_seeds}
    return [
        {**c, "domain": domain, "origin": "external"}
        for c in candidates
        if (c.get("label") or "").strip()
        and (c.get("label") or "").strip() not in seed_labels
    ]


# ---------------------------------------------------------------------------
# Stage 4: Node Resolution
# ---------------------------------------------------------------------------

async def _resolve_nodes(
    new_candidates: list[dict],
    rough_nodes: list[dict],
    entry_id: int,
    entry_ts: str = "",
    entry_dt: datetime | None = None,
) -> tuple[list[dict], dict[int, list], int, dict, list[dict]]:
    """返回 (confirmed, emb_cache, new_count, diff_nodes, node_rollback)"""
    confirmed: list[dict] = list(rough_nodes)
    confirmed_ids: set[int] = {n["id"] for n in rough_nodes}
    emb_cache: dict[int, list] = {}
    diff_nodes: dict[str, list] = {"new": [], "updated": []}
    node_rollback: list[dict] = []
    node_rollback_ids: set[int] = set()

    for n in rough_nodes:
        emb_str = n.get("embedding_json")
        if emb_str:
            try:
                emb_cache[n["id"]] = json.loads(emb_str)
            except Exception:
                pass

    new_count = 0

    for candidate in new_candidates:
        label = (candidate.get("label") or "").strip()
        if not label:
            continue

        domain = candidate["domain"]
        origin = candidate.get("origin", "internal")
        user_relevance = candidate.get("user_relevance", "") or ""
        new_conf = float(candidate.get("confidence", 0.5))
        label_emb = await embed(label)

        matched_id = _find_similar_node(domain, label_emb)

        if matched_id:
            old_s, new_s, node_before = _update_node_strength(matched_id, new_conf, entry_id, origin, entry_ts, entry_dt)
            if node_before and matched_id not in node_rollback_ids:
                node_rollback.append(node_before)
                node_rollback_ids.add(matched_id)
            if matched_id not in confirmed_ids:
                with get_conn() as conn:
                    row = conn.execute(
                        "SELECT id, domain, label, node_type, description, strength, origin FROM backbone_nodes WHERE id=?",
                        (matched_id,),
                    ).fetchone()
                    if row:
                        confirmed.append({
                            **dict(row),
                            "new_conf": new_conf,
                            "user_relevance": user_relevance,
                            "embedding_json": None,
                        })
                        confirmed_ids.add(matched_id)
                        emb_cache[matched_id] = label_emb
            else:
                for n in confirmed:
                    if n["id"] == matched_id:
                        n["new_conf"] = max(float(n.get("new_conf") or 0), new_conf)
                        # 每次命中叠加 user_relevance（取最高 confidence 的那条）
                        if user_relevance and new_conf >= float(n.get("new_conf") or 0):
                            n["user_relevance"] = user_relevance
                        # 命中的节点若被内源候选匹配且当前还是 external，升级为 internal
                        if origin == "internal":
                            n["origin"] = "internal"
                        break
            if old_s is not None:
                diff_nodes["updated"].append({
                    "id": matched_id, "label": label, "domain": domain,
                    "strength_before": round(old_s, 4), "strength_after": round(new_s, 4),
                })
        else:
            node_id = _insert_new_node(domain, candidate, label_emb, new_conf, entry_id, origin, entry_ts)
            if node_id:
                node_rollback.append({"id": node_id, "is_new": True})
                node_rollback_ids.add(node_id)
                confirmed.append({
                    "id": node_id, "label": label,
                    "node_type": candidate.get("node_type", ""),
                    "domain": domain,
                    "description": candidate.get("description", ""),
                    "strength": new_conf, "new_conf": new_conf, "is_new": True,
                    "origin": origin,
                    "user_relevance": user_relevance,
                    "embedding_json": None,
                })
                confirmed_ids.add(node_id)
                emb_cache[node_id] = label_emb
                new_count += 1
                diff_nodes["new"].append({
                    "id": node_id, "label": label, "domain": domain,
                    "node_type": candidate.get("node_type", ""),
                    "origin": origin,
                    "strength": round(new_conf, 4),
                })

    # 补全缺失 embedding
    missing_ids = [nid for nid in confirmed_ids if nid not in emb_cache]
    if missing_ids:
        with get_conn() as conn:
            for nid in missing_ids:
                row = conn.execute(
                    "SELECT embedding_json FROM backbone_nodes WHERE id=?", (nid,)
                ).fetchone()
                if row and row["embedding_json"]:
                    try:
                        emb_cache[nid] = json.loads(row["embedding_json"])
                    except Exception:
                        pass

    return confirmed, emb_cache, new_count, diff_nodes, node_rollback


# ---------------------------------------------------------------------------
# Stage 5: 精召回
# ---------------------------------------------------------------------------

def _precise_retrieval(confirmed: list[dict]) -> dict:
    ws = NODE_STRENGTH["rank_strength_weight"]
    wc = NODE_STRENGTH["rank_new_conf_weight"]
    wr = NODE_STRENGTH["rank_rough_sim_weight"]

    def rank(n: dict) -> float:
        return (ws * float(n.get("strength", 0))
                + wc * float(n.get("new_conf") or 0)
                + wr * float(n.get("rough_sim") or 0))

    existing = [n for n in confirmed if not n.get("is_new")]
    new_nodes = [n for n in confirmed if n.get("is_new")]

    sorted_existing = sorted(existing, key=rank, reverse=True)
    top_n = max(1, min(5, len(sorted_existing) // 3)) if sorted_existing else 0

    seed_meta: dict[int, dict] = {}
    for i, node in enumerate(sorted_existing):
        seed_meta[node["id"]] = {
            "expand_type": "top_n_3hop" if i < top_n else "existing_1hop",
            "rank": round(rank(node), 4),
        }
    for node in new_nodes:
        seed_meta[node["id"]] = {"expand_type": "new_1hop", "rank": round(rank(node), 4)}

    subgraph_nodes: dict[int, dict] = {}
    subgraph_edges: list[dict] = []
    seen_edge_ids: set[int] = set()
    visited: set[int] = set()

    for i, node in enumerate(sorted_existing):
        hops = 3 if i < top_n else 1
        _expand_subgraph(node["id"], hops, subgraph_nodes, subgraph_edges, seen_edge_ids, visited,
                         RETRIEVAL["max_edges_per_node"])

    for node in new_nodes:
        _expand_subgraph(node["id"], 1, subgraph_nodes, subgraph_edges, seen_edge_ids, visited,
                         RETRIEVAL["max_edges_per_node"])

    return {"nodes": list(subgraph_nodes.values()), "edges": subgraph_edges, "seed_meta": seed_meta}


def _expand_subgraph(
    node_id: int, hops: int,
    nodes_out: dict, edges_out: list, seen_edges: set,
    visited: set, max_edges: int,
) -> None:
    if node_id in visited or hops < 0:
        return
    visited.add(node_id)

    if node_id not in nodes_out:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, label, domain, node_type, strength FROM backbone_nodes WHERE id=?",
                (node_id,),
            ).fetchone()
            if row:
                nodes_out[node_id] = dict(row)

    if hops == 0:
        return

    with get_conn() as conn:
        edge_rows = conn.execute(
            """SELECT e.id, e.from_node_id, e.to_node_id, e.relation_type,
                      e.weight, e.last_reinforced_at,
                      n1.label AS from_label, n2.label AS to_label
               FROM backbone_edges e
               JOIN backbone_nodes n1 ON n1.id = e.from_node_id
               JOIN backbone_nodes n2 ON n2.id = e.to_node_id
               WHERE e.from_node_id = ? OR e.to_node_id = ?
               LIMIT ?""",
            (node_id, node_id, max_edges),
        ).fetchall()

    for edge in edge_rows:
        eid = edge["id"]
        if eid not in seen_edges:
            seen_edges.add(eid)
            edges_out.append(dict(edge))
        neighbor_id = edge["to_node_id"] if edge["from_node_id"] == node_id else edge["from_node_id"]
        if hops > 1:
            _expand_subgraph(neighbor_id, hops - 1, nodes_out, edges_out, seen_edges, visited, max_edges)


# ---------------------------------------------------------------------------
# Stage 6: Edge Extract + 算法融合
# ---------------------------------------------------------------------------

async def _extract_and_persist_edges(
    entry_id: int,
    all_confirmed: list[dict],
    subgraph: dict,
    raw: str,
    slice_summary: str,
    entry_ts: str = "",
) -> tuple[int, list[dict], list[dict], list[dict]]:
    """返回 (count, extracted_list, new_edges, updated_edges)"""
    confirmed_json = json.dumps(
        [{"id": n["id"], "label": n["label"], "node_type": n.get("node_type", ""),
          "domain": n["domain"], "origin": n.get("origin", "internal")}
         for n in all_confirmed],
        ensure_ascii=False, indent=2,
    )
    system_prompt = Template(_EDGE_PROMPT).safe_substitute(
        confirmed_nodes=confirmed_json,
        subgraph=_format_subgraph(subgraph),
        raw_entry=raw,
        slice_summary=slice_summary,
    )

    sg_nodes = len(subgraph.get("nodes", []) or [])
    sg_edges = len(subgraph.get("edges", []) or [])

    try:
        result = await chat_json(
            system_prompt=system_prompt, user_prompt="",
            stage="edge_extract",
            context={
                "confirmed_nodes": len(all_confirmed),
                "subgraph_nodes": sg_nodes,
                "subgraph_edges": sg_edges,
            },
        )
        edges = result.get("edges") or []
    except StructuredLLMError:
        return 0, [], [], []

    label_to_id = {n["label"]: n["id"] for n in all_confirmed}
    base_delta = EDGE_WEIGHT["base_delta"]
    min_delta = EDGE_WEIGHT["min_delta"]

    extracted_list: list[dict] = []
    new_edges: list[dict] = []
    updated_edges: list[dict] = []
    count = 0

    for edge in edges:
        from_label = edge.get("from_label", "")
        to_label = edge.get("to_label", "")
        relation = (edge.get("relation_type") or "").strip()
        if not from_label or not to_label or not relation:
            continue
        # 相似/关联由算法负责建连，LLM 输出的这两类忽略
        if relation in ("similar", "related"):
            continue

        from_id = label_to_id.get(from_label)
        to_id = label_to_id.get(to_label)
        if not from_id or not to_id or from_id == to_id:
            continue

        confidence = float(edge.get("confidence", 0.5))
        increment = round(min_delta + (base_delta - min_delta) * confidence, 4)

        direction = edge.get("direction", "A→B")
        if direction == "B→A":
            from_id, to_id = to_id, from_id
            from_label, to_label = to_label, from_label

        extracted_list.append({
            "from_label": from_label, "to_label": to_label,
            "relation_type": relation, "direction": edge.get("direction", "A→B"),
            "confidence": round(confidence, 4),
            "evidence": edge.get("evidence", ""),
        })

        pairs = [(from_id, to_id, from_label, to_label)]
        if direction == "bidirectional":
            pairs.append((to_id, from_id, to_label, from_label))

        for fid, tid, fl, tl in pairs:
            with get_conn() as conn:
                existing = conn.execute(
                    "SELECT id, weight, source_entry_ids FROM backbone_edges WHERE from_node_id=? AND to_node_id=? AND relation_type=?",
                    (fid, tid, relation),
                ).fetchone()

            merged_src = _accumulate_source_entries(
                existing["source_entry_ids"] if existing else None, entry_id
            )

            ts = entry_ts or _ts(None)
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO backbone_edges
                        (from_node_id, to_node_id, relation_type, edge_source,
                         confidence, last_reinforced_at, weight, source_entry_ids,
                         created_at, updated_at)
                    VALUES (?, ?, ?, 'llm', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(from_node_id, to_node_id, relation_type) DO UPDATE SET
                        weight             = weight + excluded.weight,
                        confidence         = (confidence + excluded.confidence) / 2.0,
                        edge_source        = 'llm',
                        last_reinforced_at = excluded.last_reinforced_at,
                        source_entry_ids   = excluded.source_entry_ids,
                        updated_at         = excluded.updated_at
                    """,
                    (fid, tid, relation, round(confidence, 4), ts, increment, merged_src, ts, ts),
                )

            if existing:
                updated_edges.append({
                    "from_label": fl, "to_label": tl, "relation_type": relation,
                    "weight_before": round(float(existing["weight"]), 4),
                    "weight_after": round(float(existing["weight"]) + increment, 4),
                })
            else:
                new_edges.append({
                    "from_label": fl, "to_label": tl, "relation_type": relation,
                    "weight": increment,
                })
            count += 1

    return count, extracted_list, new_edges, updated_edges


# ---------------------------------------------------------------------------
# Stage 6a: 算法相似边（同域 + 跨域，不调 LLM）
# ---------------------------------------------------------------------------

def _write_algo_similarity_edges(
    confirmed: list[dict], emb_cache: dict[int, list], entry_id: int, entry_ts: str = "",
) -> tuple[list[dict], list[dict], list[dict]]:
    """同域 sim ≥ intra_domain_sim_threshold 或跨域 sim ≥ CROSS_DOMAIN_SIM_THRESHOLD 建 'similar' 算法边。

    - 已存在 LLM 边：跳过（算法不覆盖 LLM）
    - 已存在 algo 边：累加 source_entry_ids，不改 weight（sim 静态）
    - 不存在：INSERT，weight = min(sim, weight_cap)

    返回 (algo_edges_for_trace, new_rows, updated_rows)
    """
    intra_thr = ALGO_EDGE["intra_domain_sim_threshold"]
    cross_thr = CROSS_DOMAIN_SIM_THRESHOLD
    cap = ALGO_EDGE["weight_cap"]

    label_by_id = {n["id"]: n.get("label", "") for n in confirmed}
    domain_by_id = {n["id"]: n.get("domain", "") for n in confirmed}

    algo_edges: list[dict] = []
    new_rows: list[dict] = []
    updated_rows: list[dict] = []

    conf_ids = [n["id"] for n in confirmed if n.get("id") and n["id"] in emb_cache]
    for i, a_id in enumerate(conf_ids):
        for b_id in conf_ids[i + 1:]:
            a_domain = domain_by_id[a_id]
            b_domain = domain_by_id[b_id]
            threshold = intra_thr if a_domain == b_domain else cross_thr
            sim = _cosine_sim(emb_cache[a_id], emb_cache[b_id])
            if sim < threshold:
                continue
            # 同域已在 DEDUP_THRESHOLD (0.92) 合并，这里只会落 [intra_thr, DEDUP_THRESHOLD)
            if a_domain == b_domain and sim >= DEDUP_THRESHOLD:
                continue

            weight = round(min(float(sim), cap), 4)
            confidence = round(float(sim), 4)

            with get_conn() as conn:
                existing = conn.execute(
                    "SELECT id, edge_source, weight, source_entry_ids FROM backbone_edges "
                    "WHERE from_node_id=? AND to_node_id=? AND relation_type='similar'",
                    (a_id, b_id),
                ).fetchone()

            if existing and existing["edge_source"] == "llm":
                # LLM 边优先，算法不覆盖
                continue

            merged_src = _accumulate_source_entries(
                existing["source_entry_ids"] if existing else None, entry_id
            )

            ts = entry_ts or _ts(None)
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO backbone_edges
                        (from_node_id, to_node_id, relation_type, edge_source,
                         confidence, weight,
                         last_reinforced_at, source_entry_ids, created_at, updated_at)
                    VALUES (?, ?, 'similar', 'algo', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(from_node_id, to_node_id, relation_type) DO UPDATE SET
                        source_entry_ids   = excluded.source_entry_ids,
                        last_reinforced_at = excluded.last_reinforced_at,
                        updated_at         = excluded.updated_at
                    """,
                    (a_id, b_id, confidence, weight, ts, merged_src, ts, ts),
                )

            entry = {
                "from_label": label_by_id[a_id], "to_label": label_by_id[b_id],
                "relation_type": "similar", "edge_source": "algo",
                "weight": weight, "sim": round(float(sim), 4),
                "cross_domain": a_domain != b_domain,
            }
            algo_edges.append(entry)
            if existing:
                updated_rows.append({
                    "from_label": entry["from_label"], "to_label": entry["to_label"],
                    "relation_type": "similar",
                    "weight_before": round(float(existing["weight"]), 4),
                    "weight_after": weight,
                })
            else:
                new_rows.append({
                    "from_label": entry["from_label"], "to_label": entry["to_label"],
                    "relation_type": "similar", "weight": weight,
                })

    return algo_edges, new_rows, updated_rows


# ---------------------------------------------------------------------------
# Stage 6c: 算法共现 — 所有 confirmed 两两共现产出'related'边，重复共现累加权重
# ---------------------------------------------------------------------------

def _write_association_edges(
    confirmed: list[dict], emb_cache: dict[int, list], entry_id: int, entry_ts: str = "",
) -> tuple[list[dict], list[dict], list[dict]]:
    """confirmed 两两检查，产出'related'边以反映用户思维中的共激活。

    规则：
    - 若该对 (A, B) 已存在任何关系的边 (支撑/对立/推导/相似) → 跳过（不污染）
    - 若不存在且 sim ≥ association_min_sim → 建立 'related' 边，weight = min(sim, initial_cap)
    - 若已存在 'related' 边 → 累加 weight += co_increment（上限 weight_cap_max）
    - 单次最多 association_pairs_per_entry 条，按 sim 降序

    返回 (assoc_edges_for_trace, new_rows, updated_rows)
    """
    min_sim = ALGO_EDGE["association_min_sim"]
    initial_cap = ALGO_EDGE["association_initial_cap"]
    max_cap = ALGO_EDGE["association_weight_cap_max"]
    co_inc = ALGO_EDGE["association_co_increment"]
    max_per = ALGO_EDGE["association_pairs_per_entry"]

    label_by_id = {n["id"]: n.get("label", "") for n in confirmed}
    node_ids = [n["id"] for n in confirmed if n.get("id") and n["id"] in emb_cache]
    if len(node_ids) < 2:
        return [], [], []

    # 预取：该 confirmed 集合涉及的所有现有边（关系不限），避免污染
    placeholders = ",".join("?" * len(node_ids))
    with get_conn() as conn:
        edge_rows = conn.execute(
            f"""
            SELECT from_node_id, to_node_id, relation_type, weight, source_entry_ids
            FROM backbone_edges
            WHERE (from_node_id IN ({placeholders}) AND to_node_id IN ({placeholders}))
               OR (to_node_id IN ({placeholders}) AND from_node_id IN ({placeholders}))
            """,
            (*node_ids, *node_ids, *node_ids, *node_ids),
        ).fetchall()

    # canonical pair key → {relation_type: {weight, source}}
    existing_map: dict[tuple[int, int], dict] = {}
    for r in edge_rows:
        key = tuple(sorted([r["from_node_id"], r["to_node_id"]]))
        existing_map.setdefault(key, {})[r["relation_type"]] = {
            "weight": float(r["weight"]),
            "source_entry_ids": r["source_entry_ids"],
        }

    # 枚举所有两两对，按 sim 降序取前 max_per 条
    pairs: list[tuple[float, int, int]] = []
    for i, a_id in enumerate(node_ids):
        for b_id in node_ids[i + 1:]:
            key = tuple(sorted([a_id, b_id]))
            relations = existing_map.get(key, {})
            # 若该对已存在非 'related' 关系，跳过（LLM/相似边有优先权）
            other_relations = [r for r in relations if r != "related"]
            if other_relations:
                continue
            sim = _cosine_sim(emb_cache[a_id], emb_cache[b_id])
            if sim < min_sim and "related" not in relations:
                continue  # 无历史共现且相似度不够
            pairs.append((sim, a_id, b_id))

    pairs.sort(key=lambda x: x[0], reverse=True)
    pairs = pairs[:max_per]

    assoc_edges: list[dict] = []
    new_rows: list[dict] = []
    updated_rows: list[dict] = []

    for sim, a_id, b_id in pairs:
        key = tuple(sorted([a_id, b_id]))
        existing = existing_map.get(key, {}).get("related")

        if existing:
            # 共现累加
            old_w = float(existing["weight"])
            new_w = round(min(max_cap, old_w + co_inc), 4)
            merged_src = _accumulate_source_entries(existing["source_entry_ids"], entry_id)
            ts = entry_ts or _ts(None)
            with get_conn() as conn:
                conn.execute(
                    """UPDATE backbone_edges SET
                        weight = ?, source_entry_ids = ?,
                        last_reinforced_at = ?, updated_at = ?
                      WHERE from_node_id=? AND to_node_id=? AND relation_type='related'""",
                    (new_w, merged_src, ts, ts, a_id, b_id),
                )
            updated_rows.append({
                "from_label": label_by_id.get(a_id, ""), "to_label": label_by_id.get(b_id, ""),
                "relation_type": "related",
                "weight_before": round(old_w, 4), "weight_after": new_w,
            })
            assoc_edges.append({
                "from_label": label_by_id.get(a_id, ""), "to_label": label_by_id.get(b_id, ""),
                "relation_type": "related", "edge_source": "algo",
                "weight": new_w, "sim": round(float(sim), 4),
                "co_activation": True,
            })
        else:
            # 首次共现
            weight = round(min(float(sim), initial_cap), 4)
            confidence = round(float(sim), 4)
            merged_src = _accumulate_source_entries(None, entry_id)
            ts = entry_ts or _ts(None)
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO backbone_edges
                        (from_node_id, to_node_id, relation_type, edge_source,
                         confidence, weight, last_reinforced_at, source_entry_ids,
                         created_at, updated_at)
                      VALUES (?, ?, 'related', 'algo', ?, ?, ?, ?, ?, ?)""",
                    (a_id, b_id, confidence, weight, ts, merged_src, ts, ts),
                )
            new_rows.append({
                "from_label": label_by_id.get(a_id, ""), "to_label": label_by_id.get(b_id, ""),
                "relation_type": "related", "weight": weight,
            })
            assoc_edges.append({
                "from_label": label_by_id.get(a_id, ""), "to_label": label_by_id.get(b_id, ""),
                "relation_type": "related", "edge_source": "algo",
                "weight": weight, "sim": round(float(sim), 4),
                "co_activation": False,
            })

    return assoc_edges, new_rows, updated_rows


# ---------------------------------------------------------------------------
# Stage 6d: 对立传染 — A⟷B 对立 且 A→C 支撑 ⇒ B⟷C 倾向对立
# ---------------------------------------------------------------------------

def _propagate_opposition_edges(
    confirmed: list[dict], entry_id: int, entry_ts: str = "",
) -> tuple[list[dict], list[dict]]:
    """图论规则推导对立：通过本次 confirmed 节点做传染中心。

    对每个 confirmed 节点 A：取 A 的对立邻居集合 OPP、支撑邻居集合 SUP。
    对每对 (B ∈ OPP, C ∈ SUP)：若 B-C 间无任何边，写入推导出的对立算法边。
    weight = min(cap, w_AB × w_AC)；confidence = weight。
    """
    min_w = OPPOSITION_PROPAGATION["min_source_weight"]
    cap = OPPOSITION_PROPAGATION["weight_cap"]
    max_per = OPPOSITION_PROPAGATION["max_per_entry"]

    inferred: list[dict] = []
    new_rows: list[dict] = []

    label_cache: dict[int, str] = {n["id"]: n.get("label", "") for n in confirmed if n.get("id")}

    for node in confirmed:
        if len(inferred) >= max_per:
            break
        a_id = node.get("id")
        if not a_id:
            continue

        with get_conn() as conn:
            oppose_rows = conn.execute(
                """SELECT CASE WHEN from_node_id=? THEN to_node_id ELSE from_node_id END AS nb_id,
                          weight FROM backbone_edges
                   WHERE relation_type='opposes' AND weight >= ?
                     AND (from_node_id=? OR to_node_id=?)""",
                (a_id, min_w, a_id, a_id),
            ).fetchall()
            support_rows = conn.execute(
                """SELECT CASE WHEN from_node_id=? THEN to_node_id ELSE from_node_id END AS nb_id,
                          weight FROM backbone_edges
                   WHERE relation_type='supports' AND weight >= ?
                     AND (from_node_id=? OR to_node_id=?)""",
                (a_id, min_w, a_id, a_id),
            ).fetchall()

        if not oppose_rows or not support_rows:
            continue

        for op in oppose_rows:
            for sup in support_rows:
                if len(inferred) >= max_per:
                    break
                b_id = op["nb_id"]
                c_id = sup["nb_id"]
                if b_id == c_id or a_id in (b_id, c_id):
                    continue

                f_id, t_id = (b_id, c_id) if b_id < c_id else (c_id, b_id)

                with get_conn() as conn:
                    # B 和 C 之间若已有任何边（任何关系），跳过，不重复推导
                    exists = conn.execute(
                        """SELECT 1 FROM backbone_edges
                           WHERE ((from_node_id=? AND to_node_id=?)
                               OR (from_node_id=? AND to_node_id=?))""",
                        (f_id, t_id, t_id, f_id),
                    ).fetchone()
                if exists:
                    continue

                w = round(min(cap, float(op["weight"]) * float(sup["weight"])), 4)
                conf = w

                # 补齐 label cache（B/C 可能不在本次 confirmed 里）
                if b_id not in label_cache or c_id not in label_cache:
                    with get_conn() as conn:
                        rows = conn.execute(
                            f"SELECT id, label FROM backbone_nodes WHERE id IN (?, ?)",
                            (b_id, c_id),
                        ).fetchall()
                        for r in rows:
                            label_cache[r["id"]] = r["label"]

                merged_src = _accumulate_source_entries(None, entry_id)
                ts = entry_ts or _ts(None)
                with get_conn() as conn:
                    conn.execute(
                        """INSERT INTO backbone_edges
                            (from_node_id, to_node_id, relation_type, edge_source,
                             confidence, weight, last_reinforced_at, source_entry_ids,
                             created_at, updated_at)
                          VALUES (?, ?, 'opposes', 'algo', ?, ?, ?, ?, ?, ?)
                          ON CONFLICT(from_node_id, to_node_id, relation_type) DO NOTHING""",
                        (f_id, t_id, conf, w, ts, merged_src, ts, ts),
                    )

                row = {
                    "from_label": label_cache.get(f_id, ""),
                    "to_label": label_cache.get(t_id, ""),
                    "via_label": label_cache.get(a_id, ""),
                    "weight": w,
                    "w_oppose": round(float(op["weight"]), 4),
                    "w_support": round(float(sup["weight"]), 4),
                }
                inferred.append(row)
                new_rows.append({
                    "from_label": row["from_label"], "to_label": row["to_label"],
                    "relation_type": "opposes", "weight": w,
                })

    return inferred, new_rows


# ---------------------------------------------------------------------------
# Backbone Activations
# ---------------------------------------------------------------------------

def _write_activations(entry_id: int, confirmed: list[dict], entry_ts: str = "", situation_ctx: str = "") -> None:
    ts = entry_ts or _ts(None)
    with get_conn() as conn:
        for node in confirmed:
            node_id = node.get("id")
            if not node_id:
                continue
            new_conf = round(float(node.get("new_conf") or 0), 4)
            # 将情境上下文追加到 user_relevance，消费层召回时可感知
            base_relevance = node.get("user_relevance", "") or ""
            relevance = f"{base_relevance} [{situation_ctx}]".strip() if situation_ctx else base_relevance
            activation_id = conn.execute(
                """INSERT INTO backbone_activations
                   (node_id, entry_id, user_relevance, profile_match_score, profile_snapshot_json, created_at)
                   VALUES (?, ?, ?, ?, '{}', ?)""",
                (node_id, entry_id, relevance, new_conf, ts),
            ).lastrowid
            conn.execute(
                "UPDATE backbone_nodes SET current_activation_id=? WHERE id=?",
                (activation_id, node_id),
            )


# ---------------------------------------------------------------------------
# Node 持久化
# ---------------------------------------------------------------------------

def effective_strength(stored_strength: float, last_hit_at: str | None, now: datetime | None = None) -> float:
    """读取时衰减：返回当前等效 strength。

    存储的 strength 是 last_hit_at 时刻的累积值；自那之后没新激活 → 按
    exp(-λ × days_since_last_hit) 衰减。这样召回排序自然反映"近期热度"。

    存储值不变（落库的是历史快照），仅用于 query / retrieval 时显示和排序。
    """
    if not last_hit_at or stored_strength <= 0:
        return float(stored_strength or 0.0)
    try:
        last = datetime.fromisoformat(last_hit_at)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except Exception:
        return float(stored_strength)
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    days = max(0, (ref - last).days)
    return float(stored_strength) * math.exp(-NODE_STRENGTH["lambda"] * days)


def _insert_new_node(domain: str, candidate: dict, label_emb: list, new_conf: float, entry_id: int, origin: str, entry_ts: str = "") -> int | None:
    label = (candidate.get("label") or "").strip()
    if not label:
        return None
    conf = round(new_conf, 4)
    ts = entry_ts or _ts(None)
    # 外源节点不累加 source_entry_ids（非用户原文）
    source_ids = json.dumps([entry_id]) if origin == "internal" else "[]"
    with get_conn() as conn:
        try:
            cursor = conn.execute(
                """INSERT INTO backbone_nodes
                   (domain, node_type, label, description, embedding_json, origin,
                    strength, hit_count, last_hit_at, source_entry_ids,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                (domain, candidate.get("node_type", ""), label,
                 candidate.get("description", ""), json.dumps(label_emb), origin,
                 conf, ts, source_ids, ts, ts),
            )
            return cursor.lastrowid
        except Exception:
            return None


def _update_node_strength(node_id: int, new_conf: float, entry_id: int, origin: str, entry_ts: str = "", entry_dt: datetime | None = None) -> tuple[float | None, float, dict | None]:
    """更新节点 strength + 累加 source_entry_ids（仅内源触达），返回 (old_strength, new_strength, before_state)。

    DWAS（Decay-Weighted Activation Sum）：
        strength_new = strength_old × exp(-λ × days_since_last_hit) + new_conf

    每次激活在衰减后的旧值上"累加"一次置信度，自然反映"近期反复出现 = 高 strength"
    的产品语义。strength 不再被锁死在 [0, 1]，而是反映累积关注度（典型 0-5）。
    上限可选：NODE_STRENGTH.cap 设为 None 不限，或浮点数硬截断。

    详细推导见 cognitive-service/README.md "节点 Strength 衰减"。
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT strength, hit_count, last_hit_at, source_entry_ids, origin, current_activation_id FROM backbone_nodes WHERE id=?",
            (node_id,),
        ).fetchone()
        if not row:
            return None, new_conf, None

    old_strength = float(row["strength"] or 0.0)
    hit_count = int(row["hit_count"] or 0)
    last_hit_str = row["last_hit_at"]
    existing_origin = row["origin"] or "internal"
    before_state = {
        "id": node_id, "is_new": False,
        "strength": old_strength,
        "hit_count": hit_count,
        "last_hit_at": last_hit_str,
        "source_entry_ids": row["source_entry_ids"],
        "origin": existing_origin,
        "current_activation_id": row["current_activation_id"],
    }
    final_origin = "internal" if (origin == "internal" or existing_origin == "internal") else "external"
    # 只在结果为 internal 时累加 source_entry_ids
    if final_origin == "internal" and origin == "internal":
        new_source_ids = _accumulate_source_entries(row["source_entry_ids"], entry_id)
    else:
        new_source_ids = row["source_entry_ids"] or "[]"

    days = 0
    if last_hit_str:
        try:
            last = datetime.fromisoformat(last_hit_str)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            ref_dt = entry_dt if entry_dt else datetime.now(timezone.utc)
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=timezone.utc)
            days = max(0, (ref_dt - last).days)
        except Exception:
            pass

    # DWAS 核心公式：先按 days 衰减老 strength，再加上本次激活的 conf
    lam = NODE_STRENGTH["lambda"]
    decayed = old_strength * math.exp(-lam * days)
    new_strength = decayed + float(new_conf)

    # 可选硬上限（防极端积累）；None 不截断
    cap = NODE_STRENGTH.get("cap")
    if cap is not None:
        new_strength = min(new_strength, float(cap))

    ts = entry_ts or _ts(None)
    with get_conn() as conn:
        conn.execute(
            """UPDATE backbone_nodes SET
               strength = ?, hit_count = hit_count + 1, last_hit_at = ?,
               source_entry_ids = ?, origin = ?, updated_at = ?
               WHERE id = ?""",
            (round(new_strength, 4), ts, new_source_ids, final_origin, ts, node_id),
        )
    return old_strength, new_strength, before_state


def _accumulate_source_entries(existing_json: str | None, new_entry_id: int) -> str:
    """追加 entry_id 到 source_entry_ids（去重，保留最近 SOURCE_ENTRIES_MAX 条）。"""
    try:
        arr = json.loads(existing_json or "[]")
        if not isinstance(arr, list):
            arr = []
    except Exception:
        arr = []
    if new_entry_id in arr:
        arr.remove(new_entry_id)
    arr.append(new_entry_id)
    if len(arr) > SOURCE_ENTRIES_MAX:
        arr = arr[-SOURCE_ENTRIES_MAX:]
    return json.dumps(arr)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_similar_node(domain: str, query_emb: list[float]) -> int | None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, embedding_json FROM backbone_nodes WHERE domain=? AND embedding_json IS NOT NULL",
            (domain,),
        ).fetchall()

    if not rows:
        return None

    q = np.array(query_emb, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return None

    for row in rows:
        try:
            v = np.array(json.loads(row["embedding_json"]), dtype=np.float32)
            v_norm = np.linalg.norm(v)
            if v_norm == 0:
                continue
            if float(np.dot(q, v) / (q_norm * v_norm)) >= DEDUP_THRESHOLD:
                return row["id"]
        except Exception:
            continue

    return None


def _cosine_sim(a: list, b: list) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _format_existing_nodes(nodes: list[dict]) -> str:
    if not nodes:
        return "（暂无已有节点）"
    return "\n".join(
        f"[{n.get('node_type', '')}] {n.get('label', '')} (strength:{float(n.get('strength', 0)):.2f})"
        for n in nodes
    )


def _format_subgraph(subgraph: dict) -> str:
    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])
    if not nodes and not edges:
        return "（暂无存量关系）"
    lines = []
    if nodes:
        lines.append("存量节点：")
        for n in nodes[:20]:
            lines.append(f"  [{n.get('domain', '')}] {n.get('label', '')} (strength:{float(n.get('strength', 0)):.2f})")
    if edges:
        lines.append("存量边：")
        for e in edges[:30]:
            w = float(e.get("weight") or 0)
            lines.append(
                f"  {e.get('from_label', '')} --[{e.get('relation_type', '')}]--> "
                f"{e.get('to_label', '')} (weight:{w:.2f})"
            )
    return "\n".join(lines)
