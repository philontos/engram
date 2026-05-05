"""Agent tool layer.

Thin wrappers over the existing retrieval / raw_recall / web_search libs,
exposed as OpenAI-style function-calling tools. The agent runtime wires these
up; nothing in this module knows about LLMs.

State that needs to persist across tool calls within one turn (visited nodes,
accumulated edges, the cached raw_pool, the cached persona lens) lives on
ToolContext, which the runtime instantiates per turn and passes here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.config.graph_rules import EDGE_DECAY  # noqa: F401  (decay logic lives in retrieval helpers)
from app.lib.config_loader import DIMENSIONS
from app.lib.db import get_conn
from app.lib.embed import embed
from app.lib.raw_recall import (
    PER_NODE_ACTIVATION_LIMIT,
    build_raw_pool,
    render_raw_pool,
)
from app.lib.retrieval import (
    expand_subgraph,
    find_blindspots,
    opposite_retrieval,
    positive_retrieval,
)
from app.lib.web_search import format_results as _format_web_results
from app.lib.web_search import web_search as _web_search


# ---------------------------------------------------------------------------
# Persona-lens prompt (used by get_persona_lens tool)
# ---------------------------------------------------------------------------


def _active_frameworks_lines() -> tuple[list[str], list[str]]:
    framework_lines: list[str] = []
    cite_examples: list[str] = []
    for d in DIMENSIONS:
        if not d.get("enabled", True):
            continue
        name = d.get("name") or d.get("key")
        key = d.get("key")
        subs = d.get("sub_dimensions") or []
        if subs:
            sub_keys = " / ".join(s.get("key", "") for s in subs if s.get("key"))
            framework_lines.append(f"- {name} ({key}): {sub_keys}")
            if d.get("summary_format") == "scores":
                first = subs[0].get("key")
                if first:
                    cite_examples.append(f"'{first}=…'")
        else:
            framework_lines.append(f"- {name} ({key})")
    return framework_lines, cite_examples


def _q2_system(profile_summary: str, mood_stats: str = "", raw_block: str = "") -> str:
    mood_section = f"\n\n## Mood and journaling patterns\n{mood_stats}" if mood_stats else ""
    raw_section = f"\n\n{raw_block}" if raw_block else ""
    framework_lines, cite_examples = _active_frameworks_lines()
    frameworks_block = "\n".join(framework_lines) if framework_lines else "(profile dimensions are injected from user configuration)"

    # Defensive citation guidance: only ask for "<key>=<score>" syntax when at least
    # one active dimension actually has scores in profile_summary. Otherwise the LLM
    # would hallucinate numbers. Also handle the empty-profile case (early users)
    # where there's nothing to cite from.
    has_scored_dims  = bool(cite_examples)
    profile_is_empty = (
        not profile_summary.strip()
        or profile_summary.strip() == "(no historical profile yet)"
    )
    if profile_is_empty:
        cite_line = (
            "The user's profile is still empty (early-stage user). Do NOT cite profile values; "
            "anchor every claim in the raw records below instead."
        )
    elif has_scored_dims:
        cite_hint = ", ".join(cite_examples[:3])
        cite_line = f"Cite specific sub-key scores when making each claim (e.g., {cite_hint})."
    else:
        cite_line = (
            "The active dimensions are non-numeric (key_value or free-form). Cite specific "
            "sub-key values shown in the profile (e.g., 'occupation=engineer'); do NOT invent scores."
        )

    return (
        "You are a personality / values consultant. Interpret the user's profile strictly by the dimensions "
        "and sub-keys provided below — do not assume any framework that is not listed.\n\n"
        "## Active profile dimensions (loaded from configuration)\n"
        f"{frameworks_block}\n\n"
        "Based on the user profile AND the raw records below, identify: the angles this user is most likely to overlook on this question, "
        "the judgments they are most likely to over-lean toward, and the cognitive blind spots related to their profile.\n"
        "Anchor every claim in the raw records: cite a specific phrase the user wrote, not a generic inference. "
        "If the raw records show the question concerns A, do not analyze it as if it concerned B.\n"
        f"{cite_line}\n"
        "Do not give advice — only reveal. Match the user's language. Keep it under ~120 words.\n\n"
        f"## User profile\n{profile_summary}{mood_section}{raw_section}"
    )


# ---------------------------------------------------------------------------
# Evolution-path computation (used by find_evolution_paths tool)
# ---------------------------------------------------------------------------


def _compute_evolution_paths(
    nodes: dict[int, dict],
    edges: list[dict],
    max_paths: int = 3,
    max_hops: int = 3,
) -> list[dict]:
    if not nodes or not edges:
        return []
    adj: dict[int, list[tuple[int, dict]]] = {}
    for e in edges:
        f, t = e.get("from_id"), e.get("to_id")
        if f is None or t is None:
            continue
        adj.setdefault(f, []).append((t, e))
        adj.setdefault(t, []).append((f, e))

    internal_anchors = sorted(
        [n for n in nodes.values()
         if n.get("origin") == "internal" and float(n.get("strength", 0)) >= 0.6],
        key=lambda n: float(n.get("strength", 0)),
        reverse=True,
    )[:6]
    external_targets = {n["id"]: n for n in nodes.values() if n.get("origin") == "external"}
    if not internal_anchors or not external_targets:
        return []

    candidates: list[dict] = []
    for anchor in internal_anchors:
        visited = {anchor["id"]: []}
        frontier = [anchor["id"]]
        for _ in range(max_hops):
            next_frontier = []
            for nid in frontier:
                for (nbr, edge) in adj.get(nid, []):
                    if nbr in visited:
                        continue
                    new_path = visited[nid] + [{
                        "from_id":     nid,
                        "from_label":  nodes.get(nid, {}).get("label", ""),
                        "from_origin": nodes.get(nid, {}).get("origin", ""),
                        "relation":    edge.get("relation_type", ""),
                        "weight":      round(float(edge.get("weight", 0)), 3),
                        "to_id":       nbr,
                        "to_label":    nodes.get(nbr, {}).get("label", ""),
                        "to_origin":   nodes.get(nbr, {}).get("origin", ""),
                    }]
                    visited[nbr] = new_path
                    next_frontier.append(nbr)
                    if nbr in external_targets:
                        weights = [step["weight"] for step in new_path]
                        avg_w = sum(weights) / len(weights) if weights else 0
                        target_s = float(external_targets[nbr].get("strength", 0))
                        score = avg_w * target_s * (0.7 ** (len(new_path) - 1))
                        candidates.append({
                            "anchor_id":       anchor["id"],
                            "anchor_label":    anchor.get("label", ""),
                            "anchor_strength": float(anchor.get("strength", 0)),
                            "target_id":       nbr,
                            "target_label":    external_targets[nbr].get("label", ""),
                            "target_strength": target_s,
                            "hops":            new_path,
                            "score":           round(score, 4),
                        })
            frontier = next_frontier

    best_per_pair: dict[tuple, dict] = {}
    for c in candidates:
        key = (c["anchor_id"], c["target_id"])
        if key not in best_per_pair or c["score"] > best_per_pair[key]["score"]:
            best_per_pair[key] = c
    return sorted(best_per_pair.values(), key=lambda c: c["score"], reverse=True)[:max_paths]


def _format_evolution_paths(paths: list[dict]) -> str:
    if not paths:
        return ""
    lines = ["Real multi-hop paths in the explored subgraph "
             "(use these directly as evolution candidates — do not invent edges):\n"]
    for i, p in enumerate(paths, 1):
        steps_str = " → ".join(
            f"{s['from_label']} --[{s['relation']}, w={s['weight']:.2f}]--> {s['to_label']}"
            for s in p["hops"]
        )
        lines.append(
            f"**Path {i}** (score={p['score']}):\n"
            f"  anchor [{p['anchor_label']}](s={p['anchor_strength']:.2f}, internal) "
            f"→→→ target [{p['target_label']}](s={p['target_strength']:.2f}, external)\n"
            f"  steps: {steps_str}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool schema (OpenAI function-calling format)
# ---------------------------------------------------------------------------

AGENT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "recall_raw",
            "description": (
                "Search the user's raw entries (their own words) by semantic relevance to a query. "
                "Returns up to 8 unique entries, each with date and the cognitive nodes it is linked to. "
                "Call this whenever the question concerns the user's experience, feelings, decisions, or anything they may have written about. "
                "Side effect: caches the resulting raw_pool so get_persona_lens / find_evolution_paths can use it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query — typically a paraphrase of the user's question or a sub-aspect.",
                    },
                    "init_size": {
                        "type": "integer",
                        "description": "How many entries to return up-front (default 8).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_raw_by_node",
            "description": (
                "Given specific node ids, fetch the raw entries that produced or activated those nodes. "
                "Use after search_graph / expand_node when you want to see the actual sentences behind a specific belief node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Node ids to look up.",
                    },
                    "max_entries": {
                        "type": "integer",
                        "description": "Max total entries to return across all nodes (default 8).",
                    },
                },
                "required": ["node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_graph",
            "description": (
                "Semantic search the cognitive graph for nodes most relevant to a query. "
                "Each node has origin=internal (the user's own beliefs/experiences) or external "
                "(concepts they have referenced but may not have internalized). "
                "Use origin filter to narrow scope: 'internal' for what they actually believe, "
                "'external' for frameworks they know but may not use."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "description": "Default 6, max 12."},
                    "origin": {
                        "type": "string",
                        "enum": ["internal", "external"],
                        "description": "Optional: only return nodes of this origin.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "expand_node",
            "description": (
                "Expand a subgraph from given seed nodes along their edges. "
                "Use to deepen exploration after search_graph found interesting entry points. "
                "Optionally filter to specific relation types (opposes / derives / supports / similar) "
                "or to neighbours of a particular origin."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {"type": "array", "items": {"type": "integer"}},
                    "relations": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["opposes", "derives", "supports", "similar"]},
                        "description": "Restrict to these relation types. Omit for all.",
                    },
                    "target_origin": {
                        "type": "string",
                        "enum": ["internal", "external"],
                        "description": "Only keep neighbour nodes of this origin.",
                    },
                },
                "required": ["node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_neighborhood",
            "description": (
                "Zoom in on a single node: returns its full 1-hop neighbourhood "
                "(all edges with weights and all neighbour nodes with origin/strength). "
                "Useful for inspecting a specific belief in detail."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "integer"},
                },
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_opposites",
            "description": (
                "For given seed nodes, walk along 'opposes' edges and return their opposing peers. "
                "Empty result for a high-strength internal node = potential blind spot "
                "(the belief has never been challenged in the user's own writing)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_nodes",
            "description": (
                "Given two node ids, return: shortest paths between them (up to 3 hops), "
                "their common neighbours, and whether they are directly opposed. "
                "Use to interrogate 'how do these two beliefs of mine relate?' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_a_id": {"type": "integer"},
                    "node_b_id": {"type": "integer"},
                },
                "required": ["node_a_id", "node_b_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_blindspots",
            "description": (
                "Globally scan the user's graph for high-strength internal beliefs that have NO opposing edge. "
                "These are convictions never challenged by their own writing — prime suspects for cognitive blind spots. "
                "Returns up to 12 nodes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_strength": {"type": "number", "description": "Default 0.45."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_bridges",
            "description": (
                "List internal↔external bridge edges in the user's graph. These are the concrete locations "
                "where the user's own beliefs touch externally referenced frameworks — the cognitive boundary zone. "
                "Optionally filter by domain."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Optional domain filter (e.g. 'psychology')."},
                    "limit": {"type": "integer", "description": "Default 20, max 50."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_evolution_paths",
            "description": (
                "Find real multi-hop paths from the user's high-strength internal anchors to external concepts. "
                "These paths represent concrete cognitive growth routes that exist in the graph (not invented). "
                "Operates on the subgraph already explored this turn — call search_graph + expand_node first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_paths": {"type": "integer", "description": "Default 3, max 6."},
                    "max_hops": {"type": "integer", "description": "Default 3."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_persona_lens",
            "description": (
                "Run a focused personality / blind-spot analysis using the user's profile + cached raw entries. "
                "Returns a short paragraph identifying the angles this user is most likely to overlook on the question. "
                "Costs an extra LLM call — use once per turn at most. Cached after the first call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "Optional sub-topic to focus the lens on. Omit to use the original question.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_history_answer",
            "description": (
                "Read the full final answer text from a prior turn in this session. "
                "Use when the session brief mentions a turn whose detail you need to "
                "reference verbatim (e.g. user is asking about something you said earlier)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "turn_index": {"type": "integer", "description": "0-based index of the prior turn."},
                },
                "required": ["turn_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_history_tools",
            "description": (
                "List the tool calls a prior turn made, with their arguments and short summaries "
                "(no full payloads). Use to find which specific call's detail is worth pulling next "
                "via recall_history_tool_detail."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "turn_index": {"type": "integer"},
                },
                "required": ["turn_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_history_tool_detail",
            "description": (
                "Return the full result content one specific tool call produced in a prior turn — "
                "exactly the text that was fed back to the model at the time. "
                "By default the response is capped at ~64KB and the actual payload size is annotated "
                "so you can decide whether to re-call with force_full=true to bypass the cap."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "turn_index": {"type": "integer"},
                    "tool_index": {"type": "integer", "description": "0-based index within that turn's tool calls."},
                    "force_full": {"type": "boolean", "description": "If true, bypass the 64KB soft cap. Default false."},
                },
                "required": ["turn_index", "tool_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the public web for external knowledge: research, definitions, expert frameworks, fresh perspectives. "
                "Use sparingly when the answer truly needs information beyond the user's graph and your own knowledge."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "description": "Default 5, max 10."},
                },
                "required": ["query"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution context (per-turn shared state)
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    question: str
    profile_summary: str = ""
    mood_stats: str = ""
    session_id: str | None = None
    visited_node_ids: set[int] = field(default_factory=set)
    all_nodes: dict[int, dict] = field(default_factory=dict)
    all_edges: list[dict] = field(default_factory=list)
    raw_pool: dict | None = None
    persona_lens_cache: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ingest_nodes(ctx: ToolContext, nodes: list[dict]) -> None:
    for n in nodes:
        nid = n.get("id")
        if nid is None:
            continue
        ctx.visited_node_ids.add(nid)
        existing = ctx.all_nodes.get(nid)
        if existing:
            existing.update({k: v for k, v in n.items() if v is not None})
        else:
            ctx.all_nodes[nid] = dict(n)


def _ingest_edges(ctx: ToolContext, edges: list[dict]) -> None:
    seen = {(e.get("from_id"), e.get("to_id"), e.get("relation_type")) for e in ctx.all_edges}
    for e in edges:
        key = (e.get("from_id"), e.get("to_id"), e.get("relation_type"))
        if key in seen:
            continue
        seen.add(key)
        ctx.all_edges.append(e)


def _slim_node(n: dict) -> dict:
    return {
        "id":          n.get("id"),
        "label":       n.get("label", ""),
        "domain":      n.get("domain", ""),
        "node_type":   n.get("node_type", ""),
        "origin":      n.get("origin", ""),
        "strength":    round(float(n.get("strength", 0)), 3),
        "sim":         round(float(n.get("sim", 0)), 3) if n.get("sim") is not None else None,
        "description": (n.get("description") or "")[:200],
    }


def _slim_edge(e: dict) -> dict:
    return {
        "from_id":       e.get("from_id"),
        "to_id":         e.get("to_id"),
        "from_label":    e.get("from_label", ""),
        "to_label":      e.get("to_label", ""),
        "relation_type": e.get("relation_type", ""),
        "weight":        round(float(e.get("weight", 0)), 3),
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def _t_recall_raw(args: dict, ctx: ToolContext) -> dict:
    query = str(args.get("query", "")).strip()
    init_size = int(args.get("init_size", 8))
    if not query:
        return {"summary": "missing query", "detail": {}}
    pool = await build_raw_pool(query, init_size=init_size)
    ctx.raw_pool = pool
    entries = pool.get("entries", [])
    return {
        "summary": f"recall_raw '{query}' → {len(entries)} entries, "
                   f"{pool.get('total_chars', 0)} chars, "
                   f"{len(pool.get('candidates', []))} more available",
        "detail": {
            "entries": [
                {
                    "id":          e["id"],
                    "date":        e.get("date", ""),
                    "linked_nodes": [
                        {"id": l["node_id"], "label": l["label"],
                         "strength": round(float(l["strength"]), 3)}
                        for l in (e.get("linked_nodes") or [])[:5]
                    ],
                    "raw":         e["raw"],
                }
                for e in entries
            ],
            "candidates_remaining": len(pool.get("candidates", [])),
            "total_chars":          pool.get("total_chars", 0),
        },
        "llm_text": render_raw_pool(pool) or "(no relevant raw entries)",
    }


async def _t_recall_raw_by_node(args: dict, ctx: ToolContext) -> dict:
    node_ids = [int(i) for i in args.get("node_ids", []) if isinstance(i, (int, str))]
    max_entries = min(int(args.get("max_entries", 8)), 20)
    if not node_ids:
        return {"summary": "missing node_ids", "detail": {}}

    placeholders = ",".join("?" * len(node_ids))
    entry_links: dict[int, list[dict]] = {}
    with get_conn() as conn:
        node_rows = conn.execute(
            f"SELECT id, label, source_entry_ids, strength FROM backbone_nodes WHERE id IN ({placeholders})",
            node_ids,
        ).fetchall()
        for row in node_rows:
            try:
                src_ids = json.loads(row["source_entry_ids"] or "[]")
            except Exception:
                src_ids = []
            for eid in src_ids:
                entry_links.setdefault(int(eid), []).append({
                    "node_id":  row["id"], "label": row["label"],
                    "strength": float(row["strength"] or 0),
                })
            act_rows = conn.execute(
                "SELECT entry_id FROM backbone_activations WHERE node_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (row["id"], PER_NODE_ACTIVATION_LIMIT),
            ).fetchall()
            for r in act_rows:
                entry_links.setdefault(int(r["entry_id"]), []).append({
                    "node_id":  row["id"], "label": row["label"],
                    "strength": float(row["strength"] or 0),
                })
        if not entry_links:
            return {"summary": "no entries linked to those nodes", "detail": {"entries": []}}
        eid_list = list(entry_links.keys())
        eph = ",".join("?" * len(eid_list))
        ent_rows = conn.execute(
            f"SELECT id, raw, created_at FROM entries WHERE id IN ({eph})",
            eid_list,
        ).fetchall()

    entries = []
    for r in ent_rows:
        raw = (r["raw"] or "").strip()
        if not raw:
            continue
        links = entry_links.get(r["id"], [])
        max_s = max((l["strength"] for l in links), default=0.0)
        entries.append({
            "id":           r["id"],
            "date":         (r["created_at"] or "")[:10],
            "raw":          raw,
            "max_strength": round(max_s, 4),
            "linked_nodes": links,
        })
    entries.sort(key=lambda e: (e["max_strength"], e["date"]), reverse=True)
    entries = entries[:max_entries]

    lines = [f"### Entry #{e['id']} ({e['date']}) — links: "
             + ", ".join(f"{l['label']}(s={l['strength']:.2f})" for l in e["linked_nodes"][:4])
             + f"\n{e['raw']}\n"
             for e in entries]
    return {
        "summary": f"recall_raw_by_node({len(node_ids)} nodes) → {len(entries)} entries",
        "detail": {"entries": entries},
        "llm_text": "\n".join(lines) if lines else "(no entries)",
    }


async def _t_search_graph(args: dict, ctx: ToolContext) -> dict:
    query = str(args.get("query", "")).strip()
    top_k = min(int(args.get("top_k", 6)), 12)
    origin = args.get("origin")
    if not query:
        return {"summary": "missing query", "detail": {}}
    emb = await embed(query)
    if origin in ("internal", "external"):
        # over-fetch then filter, since positive_retrieval has no origin filter
        raw = positive_retrieval(emb, top_k=top_k * 3, exclude_ids=ctx.visited_node_ids)
        nodes = [n for n in raw if n.get("origin") == origin][:top_k]
    else:
        nodes = positive_retrieval(emb, top_k=top_k, exclude_ids=ctx.visited_node_ids)
    _ingest_nodes(ctx, nodes)
    summary = (
        f"search_graph '{query}'"
        + (f" origin={origin}" if origin else "")
        + f" → {len(nodes)} nodes"
    )
    return {
        "summary": summary,
        "detail": {"nodes": [_slim_node(n) for n in nodes]},
        "llm_text": _format_nodes(nodes),
    }


async def _t_expand_node(args: dict, ctx: ToolContext) -> dict:
    node_ids = [int(i) for i in args.get("node_ids", []) if isinstance(i, (int, str))]
    relations = args.get("relations")
    target_origin = args.get("target_origin")
    seeds = [ctx.all_nodes[i] for i in node_ids if i in ctx.all_nodes]
    if not seeds:
        return {"summary": "no known seed nodes — call search_graph first",
                "detail": {"nodes": [], "edges": []}}
    hops = ({r: 2 for r in relations}
            if relations
            else {"opposes": 2, "derives": 2, "supports": 2, "similar": 1})
    sub = expand_subgraph(seeds, hop_per_relation=hops)
    nodes_out = sub.get("nodes", [])
    edges_out = sub.get("edges", [])
    if target_origin in ("internal", "external"):
        keep_ids = {n["id"] for n in nodes_out if n.get("origin") == target_origin}
        keep_ids.update(s["id"] for s in seeds)
        nodes_out = [n for n in nodes_out if n["id"] in keep_ids]
        edges_out = [e for e in edges_out
                     if e.get("from_id") in keep_ids and e.get("to_id") in keep_ids]
    _ingest_nodes(ctx, nodes_out)
    _ingest_edges(ctx, edges_out)
    summary = (
        f"expand_node({len(seeds)} seeds"
        + (f", relations={relations}" if relations else "")
        + (f", target_origin={target_origin}" if target_origin else "")
        + f") → {len(nodes_out)} nodes, {len(edges_out)} edges"
    )
    return {
        "summary": summary,
        "detail": {
            "nodes": [_slim_node(n) for n in nodes_out[:60]],
            "edges": [_slim_edge(e) for e in edges_out[:80]],
        },
        "llm_text": _format_subgraph(nodes_out, edges_out),
    }


async def _t_get_node_neighborhood(args: dict, ctx: ToolContext) -> dict:
    nid = int(args.get("node_id", 0))
    if not nid:
        return {"summary": "missing node_id", "detail": {}}
    with get_conn() as conn:
        node_row = conn.execute(
            "SELECT id, domain, node_type, label, description, origin, strength "
            "FROM backbone_nodes WHERE id=?", (nid,)
        ).fetchone()
        if not node_row:
            return {"summary": f"node {nid} not found", "detail": {}}
        edge_rows = conn.execute(
            """SELECT e.from_node_id, e.to_node_id, e.relation_type, e.weight,
                      n1.label AS from_label, n1.origin AS from_origin,
                      n1.strength AS from_strength, n1.domain AS from_domain,
                      n2.label AS to_label, n2.origin AS to_origin,
                      n2.strength AS to_strength, n2.domain AS to_domain
               FROM backbone_edges e
               JOIN backbone_nodes n1 ON n1.id = e.from_node_id
               JOIN backbone_nodes n2 ON n2.id = e.to_node_id
               WHERE e.from_node_id = ? OR e.to_node_id = ?
               ORDER BY e.weight DESC LIMIT 60""",
            (nid, nid),
        ).fetchall()
    node = dict(node_row)
    _ingest_nodes(ctx, [node])
    edges = []
    for r in edge_rows:
        e = {
            "from_id": r["from_node_id"], "to_id": r["to_node_id"],
            "from_label": r["from_label"], "to_label": r["to_label"],
            "relation_type": r["relation_type"],
            "weight": round(float(r["weight"]), 3),
        }
        edges.append(e)
        # ingest the neighbour node too
        is_from = r["from_node_id"] == nid
        nbr_id = r["to_node_id"] if is_from else r["from_node_id"]
        nbr = {
            "id":       nbr_id,
            "label":    r["to_label" if is_from else "from_label"],
            "origin":   r["to_origin" if is_from else "from_origin"],
            "strength": float(r["to_strength" if is_from else "from_strength"]),
            "domain":   r["to_domain" if is_from else "from_domain"],
        }
        _ingest_nodes(ctx, [nbr])
    _ingest_edges(ctx, edges)
    return {
        "summary": f"get_node_neighborhood({nid} '{node['label']}') → {len(edges)} edges",
        "detail": {"node": _slim_node(node), "edges": [_slim_edge(e) for e in edges]},
        "llm_text": _format_subgraph([node], edges),
    }


async def _t_get_opposites(args: dict, ctx: ToolContext) -> dict:
    node_ids = [int(i) for i in args.get("node_ids", []) if isinstance(i, (int, str))]
    seeds = [ctx.all_nodes[i] for i in node_ids if i in ctx.all_nodes]
    if not seeds:
        # fall back: load from DB so the tool isn't fragile
        if not node_ids:
            return {"summary": "missing node_ids", "detail": {}}
        ph = ",".join("?" * len(node_ids))
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT id, label, domain, origin, strength FROM backbone_nodes WHERE id IN ({ph})",
                node_ids,
            ).fetchall()
        seeds = [dict(r) for r in rows]
        _ingest_nodes(ctx, seeds)
    opposites = opposite_retrieval(seeds)
    _ingest_nodes(ctx, opposites)
    seed_labels = ", ".join(s.get("label", "") for s in seeds[:5])
    if not opposites:
        return {
            "summary": f"get_opposites([{seed_labels}]) → 0 opposites — possible blind spot",
            "detail": {"opposites": [], "seed_labels": seed_labels},
            "llm_text": f"No opposing edges found for: {seed_labels}. "
                        "If any of these are high-strength internal beliefs, they are likely blind spots.",
        }
    return {
        "summary": f"get_opposites([{seed_labels}]) → {len(opposites)} opposing nodes",
        "detail": {"opposites": [_slim_node(n) for n in opposites]},
        "llm_text": _format_nodes(opposites),
    }


async def _t_compare_nodes(args: dict, ctx: ToolContext) -> dict:
    a = int(args.get("node_a_id", 0))
    b = int(args.get("node_b_id", 0))
    if not a or not b:
        return {"summary": "missing node ids", "detail": {}}
    with get_conn() as conn:
        nrows = conn.execute(
            "SELECT id, label, domain, origin, strength FROM backbone_nodes WHERE id IN (?,?)",
            (a, b),
        ).fetchall()
        nmap = {r["id"]: dict(r) for r in nrows}
        if a not in nmap or b not in nmap:
            return {"summary": "one or both nodes not found", "detail": {}}
        # build adjacency for nodes within 3 hops via BFS
        adj: dict[int, list[tuple[int, dict]]] = {}
        visited = {a}
        frontier = {a}
        all_edges: list[dict] = []
        for _ in range(3):
            if not frontier:
                break
            ph = ",".join("?" * len(frontier))
            erows = conn.execute(
                f"""SELECT e.from_node_id, e.to_node_id, e.relation_type, e.weight,
                          n1.label AS from_label, n2.label AS to_label
                   FROM backbone_edges e
                   JOIN backbone_nodes n1 ON n1.id = e.from_node_id
                   JOIN backbone_nodes n2 ON n2.id = e.to_node_id
                   WHERE e.from_node_id IN ({ph}) OR e.to_node_id IN ({ph})""",
                (*frontier, *frontier),
            ).fetchall()
            next_front = set()
            for er in erows:
                e = {
                    "from_id": er["from_node_id"], "to_id": er["to_node_id"],
                    "from_label": er["from_label"], "to_label": er["to_label"],
                    "relation_type": er["relation_type"],
                    "weight": round(float(er["weight"]), 3),
                }
                all_edges.append(e)
                adj.setdefault(e["from_id"], []).append((e["to_id"], e))
                adj.setdefault(e["to_id"], []).append((e["from_id"], e))
                for nid in (e["from_id"], e["to_id"]):
                    if nid not in visited:
                        next_front.add(nid)
                        visited.add(nid)
            frontier = next_front
    # BFS path from a to b
    paths: list[list[dict]] = []
    queue: list[tuple[int, list[dict]]] = [(a, [])]
    visited_paths = {a}
    while queue and not paths:
        next_q: list[tuple[int, list[dict]]] = []
        for nid, path in queue:
            for nbr, edge in adj.get(nid, []):
                if nbr == b:
                    paths.append(path + [edge])
                elif nbr not in visited_paths and len(path) < 2:
                    visited_paths.add(nbr)
                    next_q.append((nbr, path + [edge]))
        queue = next_q
    a_neighbors = {nbr for nbr, _ in adj.get(a, [])}
    b_neighbors = {nbr for nbr, _ in adj.get(b, [])}
    common = sorted(a_neighbors & b_neighbors)
    direct_opposed = any(
        e["relation_type"] == "opposes"
        and {e["from_id"], e["to_id"]} == {a, b}
        for e in all_edges
    )
    return {
        "summary": f"compare_nodes({a},{b}) → {len(paths)} short paths, "
                   f"{len(common)} common neighbours, opposes={direct_opposed}",
        "detail": {
            "node_a":          _slim_node(nmap[a]),
            "node_b":          _slim_node(nmap[b]),
            "paths":           [[_slim_edge(e) for e in p] for p in paths[:5]],
            "common_neighbors": common[:20],
            "direct_opposed":  direct_opposed,
        },
        "llm_text": (
            f"{nmap[a]['label']} ↔ {nmap[b]['label']}: "
            f"direct opposes={direct_opposed}, common neighbours={len(common)}, "
            f"shortest paths shown={len(paths[:5])}"
        ),
    }


async def _t_list_blindspots(args: dict, ctx: ToolContext) -> dict:
    min_s = float(args.get("min_strength", 0.45))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, label, domain, node_type, origin, strength, description "
            "FROM backbone_nodes WHERE origin='internal' AND strength >= ? "
            "ORDER BY strength DESC LIMIT 60",
            (min_s,),
        ).fetchall()
    candidates = [dict(r) for r in rows]
    blind = find_blindspots(candidates, min_strength=min_s)[:12]
    _ingest_nodes(ctx, blind)
    return {
        "summary": f"list_blindspots(min_strength={min_s}) → {len(blind)} unchecked beliefs",
        "detail": {"blindspots": [_slim_node(n) for n in blind]},
        "llm_text": _format_nodes(blind),
    }


async def _t_list_bridges(args: dict, ctx: ToolContext) -> dict:
    domain = args.get("domain")
    limit = min(int(args.get("limit", 20)), 50)
    sql = (
        "SELECT e.from_node_id, e.to_node_id, e.relation_type, e.weight, "
        "       n1.label AS from_label, n1.origin AS from_origin, n1.domain AS from_domain, "
        "       n2.label AS to_label, n2.origin AS to_origin, n2.domain AS to_domain "
        "FROM backbone_edges e "
        "JOIN backbone_nodes n1 ON n1.id = e.from_node_id "
        "JOIN backbone_nodes n2 ON n2.id = e.to_node_id "
        "WHERE n1.origin != n2.origin "
    )
    params: list = []
    if domain:
        sql += "AND (n1.domain = ? OR n2.domain = ?) "
        params.extend([domain, domain])
    sql += "ORDER BY e.weight DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    bridges = [
        {
            "from_id":       r["from_node_id"],
            "to_id":         r["to_node_id"],
            "from_label":    r["from_label"],
            "from_origin":   r["from_origin"],
            "from_domain":   r["from_domain"],
            "to_label":      r["to_label"],
            "to_origin":     r["to_origin"],
            "to_domain":     r["to_domain"],
            "relation_type": r["relation_type"],
            "weight":        round(float(r["weight"]), 3),
        }
        for r in rows
    ]
    lines = [
        f"- [{b['from_origin']}]{b['from_label']} --[{b['relation_type']}, w={b['weight']:.2f}]--> "
        f"[{b['to_origin']}]{b['to_label']}"
        for b in bridges
    ]
    return {
        "summary": f"list_bridges(domain={domain}) → {len(bridges)} internal↔external edges",
        "detail": {"bridges": bridges},
        "llm_text": "\n".join(lines) if lines else "(no internal↔external bridges)",
    }


async def _t_find_evolution_paths(args: dict, ctx: ToolContext) -> dict:
    max_paths = min(int(args.get("max_paths", 3)), 6)
    max_hops = int(args.get("max_hops", 3))
    if not ctx.all_nodes or not ctx.all_edges:
        return {
            "summary": "no explored subgraph yet — call search_graph + expand_node first",
            "detail": {"paths": []},
            "llm_text": "(empty subgraph — explore first)",
        }
    paths = _compute_evolution_paths(
        ctx.all_nodes, ctx.all_edges, max_paths=max_paths, max_hops=max_hops,
    )
    return {
        "summary": f"find_evolution_paths → {len(paths)} candidate paths",
        "detail": {"paths": paths},
        "llm_text": _format_evolution_paths(paths) or "(no internal→external paths reachable)",
    }


async def _t_get_persona_lens(args: dict, ctx: ToolContext) -> dict:
    from shared.llm import chat_text_stream

    focus = (args.get("focus") or "").strip()
    cache_key = focus or "__default__"
    if cache_key in ctx.persona_lens_cache:
        return {
            "summary": f"get_persona_lens(focus='{focus}') → cached",
            "detail": {"text": ctx.persona_lens_cache[cache_key]},
            "llm_text": ctx.persona_lens_cache[cache_key],
        }
    raw_block = render_raw_pool(ctx.raw_pool) if ctx.raw_pool else ""
    sys_prompt = _q2_system(ctx.profile_summary, ctx.mood_stats, raw_block=raw_block)
    user_prompt = focus or ctx.question
    buf: list[str] = []
    async for delta in chat_text_stream(
        system_prompt=sys_prompt, user_prompt=user_prompt,
        stage="agent:persona_lens",
    ):
        buf.append(delta)
    text = "".join(buf).strip()
    ctx.persona_lens_cache[cache_key] = text
    return {
        "summary": f"get_persona_lens(focus='{focus}') → {len(text)} chars",
        "detail": {"text": text},
        "llm_text": text or "(persona lens returned empty)",
    }


_HISTORY_PAYLOAD_SOFT_CAP = 64 * 1024  # bytes; bypassed via force_full=true


def _load_session_turns(session_id: str | None) -> list[dict]:
    if not session_id:
        return []
    with get_conn() as conn:
        row = conn.execute(
            "SELECT turns_json FROM query_logs WHERE session_id=?", (session_id,)
        ).fetchone()
    if not row:
        return []
    try:
        return json.loads(row["turns_json"] or "[]")
    except Exception:
        return []


def _proceed_turn_at(session_id: str | None, turn_index: int) -> dict | None:
    """Return the turn_index-th 'proceed' turn (matches what's surfaced in the brief)."""
    turns = _load_session_turns(session_id)
    proceed = [t for t in turns if t.get("intent") == "proceed"]
    if 0 <= turn_index < len(proceed):
        return proceed[turn_index]
    return None


async def _t_recall_history_answer(args: dict, ctx: ToolContext) -> dict:
    idx = int(args.get("turn_index", -1))
    turn = _proceed_turn_at(ctx.session_id, idx)
    if not turn:
        return {
            "summary": f"recall_history_answer({idx}) → turn not found",
            "detail":  {"turn_index": idx},
            "llm_text": f"(no turn at index {idx})",
        }
    answer = turn.get("response") or ""
    return {
        "summary":  f"recall_history_answer({idx}) → {len(answer)} chars",
        "detail":   {"turn_index": idx, "question": turn.get("question", ""), "answer": answer},
        "llm_text": answer or "(empty answer)",
    }


async def _t_recall_history_tools(args: dict, ctx: ToolContext) -> dict:
    idx = int(args.get("turn_index", -1))
    turn = _proceed_turn_at(ctx.session_id, idx)
    if not turn:
        return {
            "summary": f"recall_history_tools({idx}) → turn not found",
            "detail":  {"turn_index": idx},
            "llm_text": f"(no turn at index {idx})",
        }
    calls = turn.get("tool_calls") or []
    rows = [
        {
            "tool_index": i,
            "round":      c.get("round"),
            "tool":       c.get("tool"),
            "args":       c.get("args", {}),
            "summary":    c.get("summary", ""),
            "latency_ms": c.get("latency_ms"),
        }
        for i, c in enumerate(calls)
    ]
    lines = [
        f"[{r['tool_index']}] R{r['round']} {r['tool']}({json.dumps(r['args'], ensure_ascii=False)}) "
        f"→ {r['summary']}"
        for r in rows
    ]
    return {
        "summary":  f"recall_history_tools({idx}) → {len(rows)} tool calls",
        "detail":   {"turn_index": idx, "calls": rows},
        "llm_text": "\n".join(lines) if lines else "(no tool calls in that turn)",
    }


async def _t_recall_history_tool_detail(args: dict, ctx: ToolContext) -> dict:
    turn_idx = int(args.get("turn_index", -1))
    tool_idx = int(args.get("tool_index", -1))
    force_full = bool(args.get("force_full", False))
    if not ctx.session_id:
        return {"summary": "no session_id in context", "detail": {}, "llm_text": ""}
    # Pull from query_traces — that's where full request/response payloads live.
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT seq, tool_name, request_json, response_json, latency_ms, error
               FROM query_traces
               WHERE session_id=? AND turn_index=? AND event_type='tool_call'
               ORDER BY seq""",
            (ctx.session_id, turn_idx),
        ).fetchall()
    if tool_idx < 0 or tool_idx >= len(rows):
        return {
            "summary":  f"recall_history_tool_detail({turn_idx},{tool_idx}) → not found",
            "detail":   {"available": len(rows)},
            "llm_text": f"(no tool call at turn={turn_idx} index={tool_idx}; that turn has {len(rows)} calls)",
        }
    row = rows[tool_idx]
    try:
        resp = json.loads(row["response_json"] or "null")
    except Exception:
        resp = None
    raw_text = ""
    if isinstance(resp, dict):
        raw_text = resp.get("llm_text") or resp.get("summary") or ""
        if not raw_text:
            raw_text = json.dumps(resp.get("detail") or {}, ensure_ascii=False)
    elif resp is not None:
        raw_text = str(resp)

    payload_bytes = len(raw_text.encode("utf-8"))
    truncated = False
    body = raw_text
    if not force_full and payload_bytes > _HISTORY_PAYLOAD_SOFT_CAP:
        # cut to roughly the cap on a UTF-8 boundary
        body = raw_text.encode("utf-8")[:_HISTORY_PAYLOAD_SOFT_CAP].decode("utf-8", errors="ignore")
        truncated = True

    note = (
        f"\n\n---\n(payload_size={payload_bytes} bytes; "
        + ("truncated to ~64KB — call again with force_full=true for the rest"
           if truncated
           else "delivered in full")
        + ")"
    )
    return {
        "summary": (
            f"recall_history_tool_detail(turn={turn_idx},tool={tool_idx},tool_name={row['tool_name']}) "
            f"→ {payload_bytes} bytes"
            + (" [truncated]" if truncated else "")
        ),
        "detail": {
            "turn_index":     turn_idx,
            "tool_index":     tool_idx,
            "tool_name":      row["tool_name"],
            "payload_bytes":  payload_bytes,
            "truncated":      truncated,
            "latency_ms":     row["latency_ms"],
            "error":          row["error"],
        },
        "llm_text": body + note,
    }


async def _t_web_search(args: dict, ctx: ToolContext) -> dict:
    query = str(args.get("query", "")).strip()
    max_results = min(int(args.get("max_results", 5)), 10)
    if not query:
        return {"summary": "missing query", "detail": {}}
    ws = await _web_search(query, max_results=max_results)
    if ws.get("error"):
        return {
            "summary": f"web_search error: {ws['error']}",
            "detail": {"error": ws["error"]},
            "llm_text": ws.get("summary", ""),
        }
    results = ws.get("results", [])
    return {
        "summary": f"web_search '{query}' → {len(results)} results",
        "detail": {"results": results, "summary": ws.get("summary", "")},
        "llm_text": _format_web_results(results, ws.get("summary", "")),
    }


# ---------------------------------------------------------------------------
# Dispatch + formatters
# ---------------------------------------------------------------------------


_DISPATCH = {
    "recall_raw":            _t_recall_raw,
    "recall_raw_by_node":    _t_recall_raw_by_node,
    "search_graph":          _t_search_graph,
    "expand_node":           _t_expand_node,
    "get_node_neighborhood": _t_get_node_neighborhood,
    "get_opposites":         _t_get_opposites,
    "compare_nodes":         _t_compare_nodes,
    "list_blindspots":       _t_list_blindspots,
    "list_bridges":          _t_list_bridges,
    "find_evolution_paths":  _t_find_evolution_paths,
    "get_persona_lens":      _t_get_persona_lens,
    "recall_history_answer":      _t_recall_history_answer,
    "recall_history_tools":       _t_recall_history_tools,
    "recall_history_tool_detail": _t_recall_history_tool_detail,
    "web_search":            _t_web_search,
}


async def execute_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    fn = _DISPATCH.get(name)
    if not fn:
        return {
            "summary": f"unknown tool: {name}",
            "detail": {},
            "llm_text": f"(unknown tool '{name}' — agent should not call this)",
        }
    return await fn(args or {}, ctx)


# ---------------------------------------------------------------------------
# Plain-text formatters (the strings sent back to the LLM as tool output)
# ---------------------------------------------------------------------------


def _format_nodes(nodes: list[dict]) -> str:
    if not nodes:
        return "(none)"
    return "\n".join(
        f"- [id={n.get('id')}][{n.get('origin','')}][{n.get('domain','')}][{n.get('node_type','')}] "
        f"{n.get('label','')} (strength={float(n.get('strength',0)):.3f})"
        + (f": {n.get('description','')}" if n.get("description") else "")
        for n in nodes
    )


def _format_subgraph(nodes: list[dict], edges: list[dict]) -> str:
    if not nodes and not edges:
        return "(empty subgraph)"
    lines: list[str] = []
    if nodes:
        lines.append("Nodes:")
        for n in nodes[:40]:
            lines.append(
                f"  [id={n.get('id')}][{n.get('origin','')}][{n.get('domain','')}] "
                f"{n.get('label','')} (s={float(n.get('strength',0)):.3f})"
            )
    if edges:
        lines.append("Edges:")
        for e in edges[:60]:
            lines.append(
                f"  {e.get('from_label','')} --[{e.get('relation_type','')}, w={float(e.get('weight',0)):.2f}]--> "
                f"{e.get('to_label','')}"
            )
    return "\n".join(lines)
