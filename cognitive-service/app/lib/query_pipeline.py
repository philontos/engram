"""消费层：多轮图谱探索 + 个性化深度推理。

链路：
  Q1  通用解答（baseline，full 模式）
  Q2  人格穿刺（画像注入，full 模式）
  Q3  图谱迭代探索（agent loop，工具调用，最多 MAX_EXPLORE_ROUNDS 轮）
      └─ graph_search   语义搜索入口节点
      └─ expand_node    沿关系边展开子图
      └─ get_opposites  获取对立/矛盾节点
  综合输出  基于探索结果流式输出洞察
"""

import json
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator


def _wtag(weight: float) -> str:
    """Return a human-readable strength tag for an edge weight.
    Computed at query time — weight values in DB are never modified.
    Scale: single-pass max increment is 0.15; >0.5 requires 4+ reinforcements.
    """
    if weight >= 0.5:
        return "strong"
    if weight >= 0.25:
        return "moderate"
    return "weak"


def _wfmt(weight: float) -> str:
    return f"w={weight:.2f}[{_wtag(weight)}]"

from app.lib.config_loader import load_shared_backbone_prompt
from app.lib.db import get_conn
from app.lib.embed import embed
from app.lib.retrieval import (
    expand_subgraph,
    find_blindspots,
    opposite_retrieval,
    positive_retrieval,
)
from app.lib.slice_pipeline import get_mood_stats, get_profile_summary
from app.lib.theme_analysis import run_theme_analysis
from shared.llm import chat_json, chat_text_stream, chat_with_tools, is_structured_llm_configured

MAX_EXPLORE_ROUNDS = 3
MAX_HISTORY_TURNS = 20

# ---------------------------------------------------------------------------
# 工具 Schema（OpenAI function calling 格式）
# ---------------------------------------------------------------------------

EXPLORE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "graph_search",
            "description": "在图谱中语义搜索，找到与查询最相关的节点作为探索入口。可以针对问题的不同角度多次调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询文本，可以是问题的某个子角度或概念",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回节点数量，默认 6",
                        "default": 6,
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
            "description": "从指定节点沿关系边展开子图，探索关联知识结构。用于在找到感兴趣的节点后深入探索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "要展开的节点 ID 列表（来自 graph_search 或 get_opposites 的结果）",
                    },
                    "relations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "指定展开的关系类型，可选值：对立、推导、支撑、相似。不填则展开全部类型。",
                    },
                },
                "required": ["node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_opposites",
            "description": "获取节点的对立/矛盾节点，用于发现认知张力和被忽视的对立面。",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "种子节点 ID 列表",
                    },
                },
                "required": ["node_ids"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_INTENT_SYSTEM = """\
You are an intent classifier for a personal cognitive analysis system.
Classify the user's input into exactly one intent. Output strict JSON only, no other text:
{"intent": "proceed" | "clarify" | "off_topic", "message": "..."}

proceed: Input has clear self-exploration / cognition / decision-making intent, specific enough to analyze.
  Special case: if the conversation history contains a concept/framework/methodology the system mentioned,
  and the user asks "what is X" or "explain X" — this is cognitive exploration, always classify as proceed.
  message: leave empty.
clarify: Has analytical potential but too vague to analyze. message: one specific follow-up question (in Chinese, concise).
off_topic: Greetings / small talk / test input / meaningless / unrelated to personal cognition.
  Even if conversation history exists, judge by the current input itself.
  message: brief friendly note in Chinese.\
"""

_Q1_SYSTEM = "You are a knowledgeable generalist advisor. Given the user's question, provide an objective, balanced analysis covering the main angles. Be direct, avoid flattery or exaggeration. Keep it under 200 Chinese characters."


def _q2_system(profile_summary: str, mood_stats: str = "") -> str:
    mood_section = f"\n\n## 情绪与记录习惯\n{mood_stats}" if mood_stats else ""
    return (
        "You are a personality psychology consultant, well-versed in Big Five and Schwartz values theory.\n"
        "Based on the user profile below, identify: the angles this user is most likely to overlook on this question, "
        "the judgments they are most likely to over-lean toward, and the cognitive blind spots related to their personality.\n"
        "Do not give advice — only reveal. Keep it under 200 Chinese characters.\n\n"
        f"## 用户画像\n{profile_summary}{mood_section}"
    )


def _explore_system(profile_summary: str, mood_stats: str = "") -> str:
    mood_section = f"\n\n## 情绪与记录习惯\n{mood_stats}" if mood_stats else ""
    return (
        "You are a cognitive graph exploration expert. Use multi-round tool calls to deeply explore the user's personal knowledge graph.\n\n"
        "## Node semantics (must understand)\n"
        "- origin=internal: nodes from the user's own experiences/thinking — what the user truly knows or believes\n"
        "  → high strength internal = deeply held beliefs; may be cognitive anchors or blind spots\n"
        "  → low strength internal = touched but not deepened; has evolution potential\n"
        "- origin=external: referenced external concepts/frameworks/figures — things the user knows exist but hasn't internalized\n"
        "  → internal↔external edges = cognitive boundary zones, often the best breakthrough points\n"
        "  → external nodes with no internal connections = cognitive blind spots / gaps\n\n"
        "## Edge weight semantics (do NOT treat low weight as unreliable)\n"
        "- Weight is a cumulative reinforcement score. Single-pass max increment is 0.15; reaching 0.5 requires 4+ separate entries.\n"
        "- weak (<0.25): observed once or twice — nascent connection, not yet confirmed\n"
        "- moderate (0.25–0.5): repeatedly reinforced — meaningful pattern\n"
        "- strong (≥0.5): deeply established — high-confidence structural link\n"
        "- A weak edge is still a real observed connection; do not dismiss it.\n\n"
        "## Exploration strategy (follow in order)\n"
        "1. graph_search: find entry nodes around the question; note origin and strength\n"
        "2. Prioritize get_opposites on high-strength internal nodes: no opposites = potential blind spot\n"
        "3. Use expand_node on internal↔external connection points: cognitive boundary, highest evolution value\n"
        "4. graph_search again from different angles, covering the opposite side or neglected dimensions\n"
        "5. Stop when sufficient depth is reached\n\n"
        f"## 用户画像\n{profile_summary}{mood_section}"
    )


_SYNTHESIS_SYSTEM = """\
You are a cognitive map diagnostician. Your task is not to summarize — it is to deliver a precise diagnosis of the user's current cognitive state.

You will receive:
- The user's deeply held belief nodes, with raw record excerpts (the user's own words — the most direct evidence)
- Blind spot candidates (high strength but no opposing tension)
- External knowledge nodes and internal↔external bridge edges
- Cross-domain connections

## Pre-output reasoning (complete silently, do not output)
Before writing, reason through:
1. From the raw record excerpts, what is the user actually saying? What recurs? What carries emotional intensity?
2. What internal contradictions exist between these beliefs, even without explicit opposing edges?
3. What do the external nodes represent? Is the user using them to support beliefs, or do they challenge the user?
4. What does the user truly not understand? (Not "never encountered" — but "encountered yet not genuinely grasped")

## Output structure (four sections, each must contain substantive analysis — never just list node names)

**【认知锚点】**
Starting from the raw records, identify what the user truly and deeply believes.
Analyze the relationships between these beliefs — what worldview or action logic do they collectively form?
Quote the user's own words (from raw record excerpts) as evidence.

**【确信盲区】**
Which high-strength nodes have no opposing tension? Using the raw records, why has this belief never been challenged?
State directly: if this belief is wrong, what are the consequences? In what situations will the user hit a wall?
Do not say "may need attention" — name the specific risk scenario.

**【认知边界】**
What boundaries do the external nodes and bridge edges reveal?
Has the user truly understood these external frameworks/concepts, or merely learned the label?
Which external node, if genuinely internalized, would most disrupt the user's core beliefs? Why?

**【演化方向】**
Based on the above three sections, give 1-2 high-penetration cognitive upgrade directions.
Must be specific: starting from which current belief, extending in which direction, and what decision or behavior pattern would change as a result.
No motivational advice — give cognitive pathways with concrete handholds.

## Output requirements
- Every argument must cite specific node labels or the user's own words; never just say "the user tends toward X"
- Tone: direct, as if speaking to the user in person, not writing a report
- Total length: 700-1000 Chinese characters; depth over breadth
- Strictly based on graph content; do not introduce concepts outside the graph\
"""

# ---------------------------------------------------------------------------
# 工具执行
# ---------------------------------------------------------------------------

async def _execute_tool(
    name: str,
    args: dict,
    visited_ids: set[int],
    all_nodes: dict[int, dict],
) -> dict:
    """执行单次工具调用，返回 {nodes, edges, summary, content, node_count}。"""

    if name == "graph_search":
        query = str(args.get("query", ""))
        top_k = min(int(args.get("top_k", 6)), 12)
        emb = await embed(query)
        nodes = positive_retrieval(emb, top_k=top_k, exclude_ids=visited_ids)
        visited_ids.update(n["id"] for n in nodes)
        summary = f"找到 {len(nodes)} 个节点：{', '.join(n['label'] for n in nodes)}"
        content = _format_nodes(nodes)
        return {"nodes": nodes, "edges": [], "summary": summary,
                "content": content, "node_count": len(nodes)}

    if name == "expand_node":
        node_ids = [int(i) for i in args.get("node_ids", [])]
        seed_nodes = [all_nodes[nid] for nid in node_ids if nid in all_nodes]
        if not seed_nodes:
            return {"nodes": [], "edges": [], "summary": "未找到指定节点",
                    "content": "（节点不在已知范围内，请先用 graph_search 找到节点）", "node_count": 0}
        relations = args.get("relations")
        hop_config = (
            {r: 2 for r in relations}
            if relations
            else {"对立": 2, "推导": 2, "支撑": 2, "相似": 1}
        )
        result = expand_subgraph(seed_nodes, hop_per_relation=hop_config)
        new_count = sum(1 for n in result["nodes"] if n["id"] not in visited_ids)
        visited_ids.update(n["id"] for n in result["nodes"])
        summary = f"展开得到 {len(result['nodes'])} 个节点（新增 {new_count} 个）、{len(result['edges'])} 条边"
        content = _format_subgraph(result)
        return {"nodes": result["nodes"], "edges": result["edges"],
                "summary": summary, "content": content, "node_count": new_count}

    if name == "get_opposites":
        node_ids = [int(i) for i in args.get("node_ids", [])]
        seed_nodes = [all_nodes[nid] for nid in node_ids if nid in all_nodes]
        if not seed_nodes:
            return {"nodes": [], "edges": [], "summary": "未找到指定节点",
                    "content": "（节点不在已知范围内）", "node_count": 0}
        opposites = opposite_retrieval(seed_nodes)
        new_count = sum(1 for n in opposites if n["id"] not in visited_ids)
        visited_ids.update(n["id"] for n in opposites)
        labels = [n["label"] for n in opposites[:6]]
        summary = f"找到 {len(opposites)} 个对立节点：{', '.join(labels)}"
        content = _format_nodes(opposites)
        return {"nodes": opposites, "edges": [], "summary": summary,
                "content": content, "node_count": new_count}

    return {"nodes": [], "edges": [], "summary": f"未知工具: {name}",
            "content": "", "node_count": 0}


# ---------------------------------------------------------------------------
# 文本格式化（给 LLM 看的）
# ---------------------------------------------------------------------------

def _format_nodes(nodes: list[dict]) -> str:
    if not nodes:
        return "（无）"
    return "\n".join(
        f"- [id={n.get('id')}][{n.get('origin','')}][{n.get('domain','')}][{n.get('node_type','')}] "
        f"{n.get('label','')}（strength={float(n.get('strength',0)):.3f}）"
        + (f"：{n.get('description','')}" if n.get("description") else "")
        for n in nodes
    )


def _format_subgraph(subgraph: dict) -> str:
    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])
    if not nodes and not edges:
        return "（子图为空）"
    lines = []
    if nodes:
        lines.append("节点：")
        for n in nodes[:40]:
            lines.append(
                f"  [id={n.get('id')}][{n.get('origin','')}][{n.get('domain','')}] "
                f"{n.get('label','')}（strength={float(n.get('strength',0)):.3f}）"
            )
    if edges:
        lines.append("边：")
        for e in edges[:60]:
            lines.append(
                f"  {e.get('from_label','')} --[{e.get('relation_type','')}]--> "
                f"{e.get('to_label','')} ({_wfmt(float(e.get('weight',0)))})"
            )
    return "\n".join(lines)


def _get_user_relevance(node_ids: list[int]) -> dict[int, str]:
    """取各节点最近一次有实质内容的 user_relevance。
    过滤掉纯情绪标记（短且只含 emotional state 字样的）。
    """
    if not node_ids:
        return {}
    placeholders = ",".join("?" * len(node_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT node_id, user_relevance FROM backbone_activations "
            f"WHERE node_id IN ({placeholders}) AND user_relevance != '' "
            f"ORDER BY created_at DESC",
            node_ids,
        ).fetchall()
    result: dict[int, str] = {}
    for r in rows:
        if r["node_id"] in result:
            continue
        rel = r["user_relevance"].strip()
        # 过滤掉纯情绪状态标记（短字符串且没有实质内容）
        is_only_tag = rel.startswith("[") and len(rel) < 80 and "→" not in rel and "原文" not in rel
        if not is_only_tag:
            result[r["node_id"]] = rel
    return result


def _get_source_entries(nodes: list[dict]) -> dict[int, list[str]]:
    """取各节点 source_entry_ids 对应的 entry raw 摘录（前 300 字）。
    返回 {node_id: [entry_excerpt, ...]}。
    """
    import json as _json
    node_entry_map: dict[int, list[int]] = {}
    all_entry_ids: set[int] = set()
    for n in nodes:
        try:
            eids = _json.loads(n.get("source_entry_ids") or "[]")
        except Exception:
            eids = []
        node_entry_map[n["id"]] = [int(e) for e in eids[:3]]
        all_entry_ids.update(node_entry_map[n["id"]])

    if not all_entry_ids:
        return {}

    placeholders = ",".join("?" * len(all_entry_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, raw FROM entries WHERE id IN ({placeholders})",
            list(all_entry_ids),
        ).fetchall()
    entry_text: dict[int, str] = {r["id"]: (r["raw"] or "")[:300] for r in rows}

    return {
        nid: [entry_text[eid] for eid in eids if eid in entry_text]
        for nid, eids in node_entry_map.items()
    }


def _analyze_cognitive_structure(
    nodes: dict[int, dict], edges: list[dict]
) -> dict:
    """从累积节点/边中预计算认知结构特征。"""
    node_list = list(nodes.values())

    # 在子图中有对立边的节点 ID
    nodes_with_opposites: set[int] = set()
    for e in edges:
        if e.get("relation_type") == "对立":
            if e.get("from_id") in nodes:
                nodes_with_opposites.add(e["from_id"])
            if e.get("to_id") in nodes:
                nodes_with_opposites.add(e["to_id"])

    internal_ids = {n["id"] for n in node_list if n.get("origin") == "internal"}
    external_ids = {n["id"] for n in node_list if n.get("origin") == "external"}

    high_strength_internal = sorted(
        [n for n in node_list if n.get("origin") == "internal" and float(n.get("strength", 0)) >= 0.45],
        key=lambda n: float(n.get("strength", 0)), reverse=True,
    )
    # 确信盲区：internal 高 strength 但子图中完全没有对立边
    blindspot_candidates = [n for n in high_strength_internal if n["id"] not in nodes_with_opposites]

    external_nodes = sorted(
        [n for n in node_list if n.get("origin") == "external"],
        key=lambda n: float(n.get("strength", 0)), reverse=True,
    )

    # 内外部桥接边（internal↔external）
    bridge_edges = [
        e for e in edges
        if (e.get("from_id") in internal_ids and e.get("to_id") in external_ids)
        or (e.get("from_id") in external_ids and e.get("to_id") in internal_ids)
    ]

    # 跨域边（from_domain ≠ to_domain，从 all_nodes 补字段）
    cross_domain_edges = []
    for e in edges:
        fn = nodes.get(e.get("from_id"))
        tn = nodes.get(e.get("to_id"))
        if fn and tn and fn.get("domain") and tn.get("domain") and fn["domain"] != tn["domain"]:
            cross_domain_edges.append({
                **e,
                "from_domain": fn["domain"], "from_origin": fn.get("origin"),
                "to_domain": tn["domain"],   "to_origin": tn.get("origin"),
            })

    return {
        "high_strength_internal": high_strength_internal,
        "blindspot_candidates": blindspot_candidates,
        "external_nodes": external_nodes,
        "bridge_edges": bridge_edges,
        "cross_domain_edges": cross_domain_edges,
        "nodes_with_opposites": nodes_with_opposites,
    }


def _synthesis_prompt(
    question: str,
    nodes: dict[int, dict],
    edges: list[dict],
    theme_results: list[dict] | None = None,
    hist_ctx: str = "",
) -> str:
    struct = _analyze_cognitive_structure(nodes, edges)
    lines = []
    if hist_ctx:
        lines.append(hist_ctx + "\n")
    lines.append(f"## 当前提问\n{question}\n")

    if theme_results:
        # 主题深析已提供：直接用分析文本，比裸节点 + 摘录丰富得多
        lines.append("## 核心信念深析（基于原始记录的主题分析）")
        for t in theme_results:
            n = t["node"]
            lines.append(
                f"\n### 「{n['label']}」（{n['domain']} / {n['node_type']}，"
                f"strength={float(n['strength']):.3f}）"
            )
            if n.get("description"):
                lines.append(f"节点描述：{n['description']}")
            lines.append(t.get("analysis", "（无分析）"))
    else:
        # fallback：图谱无内源节点或主题深析失败时，退回原始节点列表
        top_internal = struct["high_strength_internal"][:18]
        top_internal_ids = [n["id"] for n in top_internal]
        relevance_map = _get_user_relevance(top_internal_ids)
        source_map = _get_source_entries(top_internal)
        lines.append("## 深度持有信念（internal, strength ≥ 0.45）")
        if top_internal:
            for n in top_internal:
                line = (
                    f"- [{n.get('domain')}][{n.get('node_type')}] **{n.get('label')}** "
                    f"(strength={float(n.get('strength',0)):.3f})"
                )
                if n.get("description"):
                    line += f"\n  描述：{n['description']}"
                rel = relevance_map.get(n["id"], "")
                if rel:
                    if "[" in rel:
                        rel = rel[:rel.rfind("[")].strip() or rel
                    line += f"\n  用户关联：{rel[:250]}"
                entries = source_map.get(n["id"], [])
                if entries:
                    line += f"\n  原始记录：「{entries[0][:250]}」"
                lines.append(line)
        else:
            lines.append("（无）")

    # 2. 确信盲区候选
    lines.append("\n## 确信盲区候选（internal 高 strength + 子图中无对立边）")
    if struct["blindspot_candidates"]:
        for n in struct["blindspot_candidates"][:10]:
            line = f"- [{n.get('domain')}] {n.get('label')} (strength={float(n.get('strength',0)):.3f})"
            if n.get("description"):
                line += f"：{n['description']}"
            lines.append(line)
    else:
        lines.append("（子图中所有高 strength internal 节点均有对立边，盲区隐蔽）")

    # 3. 外部知识节点（知识边界）
    lines.append("\n## 外部知识节点（origin=external，用户接触但未内化）")
    if struct["external_nodes"]:
        for n in struct["external_nodes"][:12]:
            lines.append(f"- [{n.get('domain')}][{n.get('node_type')}] {n.get('label')}"
                         + (f"：{n.get('description','')}" if n.get("description") else ""))
    else:
        lines.append("（本次探索未涉及 external 节点）")

    # 4. 内外部桥接边（认知边界地带）
    lines.append("\n## 内外部桥接边（internal↔external，认知边界的具体位置）")
    if struct["bridge_edges"]:
        for e in struct["bridge_edges"][:15]:
            from_node = nodes.get(e.get("from_id"), {})
            to_node = nodes.get(e.get("to_id"), {})
            lines.append(
                f"- [{from_node.get('origin','?')}]{e.get('from_label','')} "
                f"--[{e.get('relation_type','')}]--> "
                f"[{to_node.get('origin','?')}]{e.get('to_label','')} "
                f"({_wfmt(float(e.get('weight',0)))})"
            )
    else:
        lines.append("（无内外部桥接边）")

    # 5. 跨域连接
    lines.append("\n## 跨域关系边（不同 domain 之间的连接，隐含跨界洞察）")
    if struct["cross_domain_edges"]:
        sorted_cross = sorted(struct["cross_domain_edges"], key=lambda e: float(e.get("weight", 0)), reverse=True)
        for e in sorted_cross[:15]:
            lines.append(
                f"- [{e['from_domain']}]{e.get('from_label','')} "
                f"--[{e.get('relation_type','')}]--> "
                f"[{e['to_domain']}]{e.get('to_label','')} ({_wfmt(float(e.get('weight',0)))})"
            )
    else:
        lines.append("（无跨域边）")

    # 6. 全部对立边（张力全景）
    opposite_edges = [e for e in edges if e.get("relation_type") == "对立"]
    if opposite_edges:
        lines.append(f"\n## 对立关系全景（共 {len(opposite_edges)} 条）")
        for e in sorted(opposite_edges, key=lambda e: float(e.get("weight", 0)), reverse=True)[:20]:
            lines.append(
                f"  {e.get('from_label','')} ←对立→ {e.get('to_label','')} ({_wfmt(float(e.get('weight',0)))})"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _persist_turn(
    session_id: str,
    question: str,
    mode: str,
    turn: dict,
    is_new: bool,
    seeds_list: list | None = None,
    q1_text: str = "",
    q2_text: str = "",
    q3_text: str = "",
    q4_text: str = "",
) -> int | None:
    now = datetime.now(timezone.utc).isoformat()
    turn["created_at"] = now
    with get_conn() as conn:
        if is_new:
            cur = conn.execute(
                """INSERT INTO query_logs
                   (session_id, question, mode, seeds_json, opposites_json,
                    blindspots_json, q1_text, q2_text, q3_text, q4_text,
                    turns_json, updated_at)
                   VALUES (?, ?, ?, ?, '[]', '[]', ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, question, mode,
                    json.dumps(
                        [{"id": n["id"], "label": n.get("label"), "domain": n.get("domain")}
                         for n in (seeds_list or [])[:20]],
                        ensure_ascii=False,
                    ),
                    q1_text, q2_text, q3_text, q4_text,
                    json.dumps([turn], ensure_ascii=False),
                    now,
                ),
            )
            return cur.lastrowid
        else:
            row = conn.execute(
                "SELECT id, turns_json FROM query_logs WHERE session_id=?", (session_id,)
            ).fetchone()
            if row:
                log_id = row["id"]
                try:
                    turns = json.loads(row["turns_json"] or "[]")
                except Exception:
                    turns = []
                turns.append(turn)
                conn.execute(
                    """UPDATE query_logs
                       SET turns_json=?, q3_text=?, q4_text=?, updated_at=?
                       WHERE session_id=?""",
                    (json.dumps(turns, ensure_ascii=False),
                     q3_text, q4_text, now, session_id),
                )
                return log_id
    return None


def _load_history_from_db(session_id: str, max_turns: int = MAX_HISTORY_TURNS) -> list[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT turns_json FROM query_logs WHERE session_id=?", (session_id,)
        ).fetchone()
    if not row:
        return []
    try:
        turns = json.loads(row["turns_json"] or "[]")
    except Exception:
        turns = []
    proceed_turns = [
        {
            "question": t["question"],
            "answer": t.get("response", ""),
            "q2_text": t.get("q2_text", ""),
        }
        for t in turns
        if t.get("intent") == "proceed"
    ]
    return proceed_turns[-max_turns:]


async def _distill_q2(question: str, q2_text: str) -> str:
    """Distill q2_text down to ~400 chars relevant to the current follow-up question."""
    if not q2_text:
        return ""
    system_prompt = load_shared_backbone_prompt("history_distill.spt")
    user_prompt = f"## Prior personality analysis\n{q2_text}\n\n## Current follow-up question\n{question}"
    buf = []
    async for delta in chat_text_stream(system_prompt=system_prompt, user_prompt=user_prompt, stage="query:history_distill"):
        buf.append(delta)
    return "".join(buf)


def _history_context(history: list[dict]) -> str:
    if not history:
        return ""
    parts = ["## 前几轮对话记录（请在此基础上深化，不要重复已有结论）"]
    for i, h in enumerate(history, 1):
        turn_parts = [f"**第{i}轮**\n用户问：{h['question']}\n回答要点：{h['answer'][:1000]}"]
        if h.get("q2_distilled"):
            turn_parts.append(f"人格视角摘要：{h['q2_distilled']}")
        elif h.get("q2_text"):
            turn_parts.append(f"人格视角摘要：{h['q2_text'][:400]}")
        parts.append("\n".join(turn_parts))
    return "\n\n".join(parts)


def _with_history(question: str, history_ctx: str) -> str:
    if not history_ctx:
        return question
    return f"{history_ctx}\n\n## 当前追问\n{question}"


async def run_query(question: str, mode: str = "full", session_id: str | None = None) -> AsyncIterator[dict]:
    """多轮图谱探索消费链路。mode='fast' 跳过 Q1/Q2。"""
    if not is_structured_llm_configured():
        yield {"type": "error", "message": "LLM 未配置"}
        return

    is_new_session = not session_id
    if not session_id:
        session_id = str(uuid.uuid4())

    history = _load_history_from_db(session_id) if not is_new_session else []

    # Distill the most recent turn's q2 against the current question; older turns use raw q2_text
    if history and history[-1].get("q2_text"):
        history[-1]["q2_distilled"] = await _distill_q2(question, history[-1]["q2_text"])

    profile_summary = get_profile_summary()
    mood_stats = get_mood_stats()
    hist_ctx = _history_context(history)
    user_prompt_with_history = _with_history(question, hist_ctx)

    # --- 意图识别 ---
    yield {"type": "stage", "stage": "intent_check", "status": "start"}
    intent_user_prompt = question
    if hist_ctx:
        intent_user_prompt = f"{hist_ctx}\n\n## 当前输入\n{question}"
    try:
        intent_result = await chat_json(
            system_prompt=_INTENT_SYSTEM,
            user_prompt=intent_user_prompt,
            stage="query:intent_check",
        )
    except Exception:
        intent_result = {"intent": "proceed", "message": ""}
    intent = intent_result.get("intent", "proceed")
    message = (intent_result.get("message") or "").strip()
    yield {"type": "stage", "stage": "intent_check", "status": "done",
           "intent": intent, "message": message}
    if intent in ("off_topic", "clarify"):
        yield {"type": "delta", "stage": "intent_check", "delta": message}
        try:
            log_id = _persist_turn(
                session_id, question, mode,
                {"question": question, "intent": intent, "response": message},
                is_new=is_new_session,
                q1_text=message,
            )
        except Exception as exc:
            yield {"type": "error", "message": f"持久化失败：{exc}"}
            log_id = None
        yield {"type": "done", "session_id": session_id, "log_id": log_id}
        return

    q1_text = ""
    q2_text = ""

    # --- Q1 通用解答 ---
    if mode != "fast":
        yield {"type": "stage", "stage": "baseline", "status": "start"}
        buf = []
        async for delta in chat_text_stream(
            system_prompt=_Q1_SYSTEM, user_prompt=user_prompt_with_history, stage="query:baseline"
        ):
            buf.append(delta)
            yield {"type": "delta", "stage": "baseline", "delta": delta}
        q1_text = "".join(buf)
        yield {"type": "stage", "stage": "baseline", "status": "done", "text": q1_text}

        # --- Q2 人格穿刺 ---
        yield {"type": "stage", "stage": "persona_blindspot", "status": "start"}
        buf = []
        async for delta in chat_text_stream(
            system_prompt=_q2_system(profile_summary, mood_stats),
            user_prompt=user_prompt_with_history,
            stage="query:persona_blindspot",
        ):
            buf.append(delta)
            yield {"type": "delta", "stage": "persona_blindspot", "delta": delta}
        q2_text = "".join(buf)
        yield {"type": "stage", "stage": "persona_blindspot", "status": "done", "text": q2_text}

    # --- Q3 图谱迭代探索 ---
    yield {"type": "stage", "stage": "graph_explore", "status": "start"}

    explore_system = _explore_system(profile_summary, mood_stats)
    if hist_ctx:
        explore_system = explore_system + f"\n\n{hist_ctx}"

    messages: list[dict] = [
        {"role": "system", "content": explore_system},
        {"role": "user", "content": user_prompt_with_history},
    ]
    visited_ids: set[int] = set()
    all_nodes: dict[int, dict] = {}
    all_edges: list[dict] = []

    for round_num in range(1, MAX_EXPLORE_ROUNDS + 1):
        try:
            result = await chat_with_tools(
                messages=messages,
                tools=EXPLORE_TOOLS,
                stage=f"query:explore:r{round_num}",
            )
        except Exception as exc:
            yield {"type": "error", "message": f"探索第 {round_num} 轮失败：{exc}"}
            break

        assistant_msg = result["message"]
        finish_reason = result["finish_reason"]

        # 模型不再调用工具，探索结束
        if finish_reason != "tool_calls" or not assistant_msg.get("tool_calls"):
            break

        messages.append(assistant_msg)

        for tc in assistant_msg["tool_calls"]:
            tool_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except Exception:
                args = {}

            yield {
                "type": "tool_call",
                "round": round_num,
                "tool": tool_name,
                "args": args,
            }

            try:
                tool_result = await _execute_tool(tool_name, args, visited_ids, all_nodes)
            except Exception as exc:
                tool_result = {"nodes": [], "edges": [], "summary": f"执行失败：{exc}",
                               "content": "", "node_count": 0}

            # 累积图谱上下文
            for n in tool_result["nodes"]:
                all_nodes[n["id"]] = n
            all_edges.extend(tool_result["edges"])

            yield {
                "type": "tool_result",
                "round": round_num,
                "tool": tool_name,
                "summary": tool_result["summary"],
                "node_count": tool_result["node_count"],
                "detail": {
                    "nodes": [
                        {
                            "id": n.get("id"),
                            "label": n.get("label", ""),
                            "domain": n.get("domain", ""),
                            "origin": n.get("origin", ""),
                            "strength": round(float(n.get("strength", 0)), 3),
                            "sim": round(float(n.get("sim", 0)), 3) if n.get("sim") is not None else None,
                            "description": (n.get("description") or "")[:120],
                        }
                        for n in tool_result["nodes"]
                    ],
                    "edges": [
                        {
                            "from_label": e.get("from_label", ""),
                            "relation_type": e.get("relation_type", ""),
                            "to_label": e.get("to_label", ""),
                            "weight": round(float(e.get("weight", 0)), 3),
                        }
                        for e in tool_result["edges"][:40]
                    ],
                },
            }

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result["content"] or tool_result["summary"],
            })

    yield {"type": "stage", "stage": "graph_explore", "status": "done",
           "node_count": len(all_nodes), "edge_count": len(all_edges)}

    # --- 轮3：主题深析（并行 LLM，每个核心信念 focused 分析）---
    theme_results: list[dict] = []
    q4_text = ""
    if all_nodes:
        yield {"type": "stage", "stage": "theme_analysis", "status": "start"}
        try:
            theme_results = await run_theme_analysis(question, all_nodes, all_edges)
        except Exception as exc:
            yield {"type": "error", "message": f"主题深析失败：{exc}"}

        # 发结构化事件供前端渲染卡片（含 entry 原文）
        theme_buf: list[str] = []
        for t in theme_results:
            n = t["node"]
            yield {
                "type": "theme_result",
                "node": n,
                "entries": [
                    {"id": e["id"], "date": e["date"], "raw": e["raw"][:400]}
                    for e in t.get("entries", [])[:4]
                ],
                "analysis": t.get("analysis", ""),
            }
            theme_buf.append(
                f"**{n['label']}**（{n['domain']}，strength={n['strength']:.3f}）\n\n"
                + t.get("analysis", "")
            )
        q4_text = "\n\n---\n\n".join(theme_buf)
        yield {"type": "stage", "stage": "theme_analysis", "status": "done", "text": q4_text}

    # --- 轮4：综合诊断（流式）---
    yield {"type": "stage", "stage": "graph_insight", "status": "start"}
    q3_text = ""
    if all_nodes:
        synth_prompt = _synthesis_prompt(question, all_nodes, all_edges, theme_results or None, hist_ctx=hist_ctx)
        synthesis_system = _SYNTHESIS_SYSTEM
        if hist_ctx:
            synthesis_system = (
                _SYNTHESIS_SYSTEM
                + "\n\n## 追问指引\n"
                "这是多轮对话中的追问。前几轮对话记录已在用户提问部分提供。\n"
                "请在前几轮结论的基础上深化，不要重复已有分析。\n"
                "明确指出本轮追问与前轮认知的关联或张力，揭示新的层次。"
            )
        buf = []
        async for delta in chat_text_stream(
            system_prompt=synthesis_system,
            user_prompt=synth_prompt,
            stage="query:graph_insight",
            context={
                "nodes": len(all_nodes),
                "edges": len(all_edges),
                "themes": len(theme_results),
            },
        ):
            buf.append(delta)
            yield {"type": "delta", "stage": "graph_insight", "delta": delta}
        q3_text = "".join(buf)
    else:
        yield {"type": "delta", "stage": "graph_insight", "delta": "（图谱暂无相关内容）"}
        q3_text = "（图谱暂无相关内容）"

    yield {"type": "stage", "stage": "graph_insight", "status": "done", "text": q3_text}

    seeds_list = sorted(all_nodes.values(), key=lambda n: float(n.get("strength", 0)), reverse=True)
    try:
        log_id = _persist_turn(
            session_id, question, mode,
            {"question": question, "intent": "proceed", "response": q3_text, "q1_text": q1_text, "q2_text": q2_text, "history_context": hist_ctx},
            is_new=is_new_session,
            seeds_list=seeds_list,
            q1_text=q1_text, q2_text=q2_text, q3_text=q3_text, q4_text=q4_text,
        )
    except Exception as exc:
        yield {"type": "error", "message": f"持久化失败：{exc}"}
        log_id = None

    yield {"type": "done", "session_id": session_id, "log_id": log_id}
