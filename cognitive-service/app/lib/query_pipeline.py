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
from app.lib.config_loader import DIMENSIONS
from app.lib.db import get_conn
from app.lib.embed import embed
from app.lib.retrieval import (
    expand_subgraph,
    find_blindspots,
    opposite_retrieval,
    positive_retrieval,
)
from app.lib.raw_recall import build_raw_pool, render_raw_pool
from app.lib.slice_pipeline import get_mood_stats, get_profile_summary
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
            "description": "Semantic search in the graph to find nodes most relevant to a query — use as an exploration entry point. Can be called multiple times for different angles of the question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query text — a sub-angle or concept of the question.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of nodes to return (default 6).",
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
            "description": "Expand a subgraph from given nodes along their edges. Use to deepen exploration after finding nodes of interest.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Node IDs to expand (from graph_search or get_opposites results).",
                    },
                    "relations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Relation types to expand. Allowed: opposes, derives, supports, similar. Omit to expand all types.",
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
            "description": "Get opposing / contradictory nodes for given seeds. Use to surface cognitive tension and overlooked opposites.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Seed node IDs.",
                    },
                },
                "required": ["node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for external knowledge, research, definitions, alternative perspectives. "
                "Use for (a) factual questions needing authoritative data/research; "
                "(b) concepts missing from the user's graph that need external reference; "
                "(c) verifying whether a high-strength user belief conflicts with established knowledge; "
                "(d) fresh perspectives that could illuminate blind spots. "
                "Do not search overly generic content — keep queries tightly tied to the user's question or a specific node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query — a complete question or core phrase. Any language is fine.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 5, max 10).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_INTENT_SYSTEM = """\
You are an intent classifier for a personal cognitive analysis system.
Classify the user's input. Output strict JSON only, no other text:
{"intent": "proceed" | "clarify" | "off_topic", "mode": "factual" | "reflective" | "exploratory", "message": "..."}

## intent
proceed: Input has clear self-exploration / cognition / decision-making intent, specific enough to analyze.
  Special case: if the conversation history contains a concept/framework/methodology the system mentioned,
  and the user asks "what is X" or "explain X" — this is cognitive exploration, always classify as proceed.
  message: leave empty.
clarify: Has analytical potential but too vague to analyze. message: one concise follow-up question, matching the user's input language.
off_topic: Greetings / small talk / test input / meaningless / unrelated to personal cognition.
  Even if conversation history exists, judge by the current input itself.
  message: brief friendly note, matching the user's input language.

## mode (only meaningful when intent=proceed; default to "reflective" for other intents)
factual: Asks about how the world works — facts, definitions, mechanisms, possibility.
  Wants: a real answer grounded in knowledge, with personalized lens as secondary.
  Examples:
    - "什么是依恋类型？" → factual
    - "What's the difference between CBT and psychoanalysis?" → factual

reflective: Asks for self-diagnosis / advice / decisions about themselves.
  Wants: cognitive diagnosis grounded in their own profile + records.
  Examples:
    - "我为什么总是回避冲突？" → reflective
    - "Should I leave this job? I keep going back and forth." → reflective

exploratory: Records a thought, observation, or musing — not really asking but inviting connection.
  Statement form, often without a question mark, idea-sharing tone.
  Wants: gentle expansion — surface related beliefs, suggest tensions, propose directions.
  Examples:
    - "最近一直在想自由意志这件事" → exploratory
    - "I keep noticing how anchoring theory shows up in relationships too" → exploratory

## Mode disambiguation rule
When a question mixes factual + reflective (e.g. "Should I switch into psychology?" mixes
a career decision with field knowledge), prefer reflective — the personal stake dominates.
Pure knowledge questions go to factual. When unsure between any two, default to reflective.\
"""

_Q1_SYSTEM = "You are a knowledgeable generalist advisor. Given the user's question, provide an objective, balanced analysis covering the main angles. Be direct, avoid flattery or exaggeration. Match the user's language. Keep it under ~120 words."


def _active_frameworks_lines() -> tuple[list[str], list[str]]:
    """根据配置动态构建当前画像所含框架的描述行 + 引用示例。

    返回 (framework_lines, cite_examples)：
    - framework_lines: 每个 enabled dimension 一行 "Name (key): sub1 / sub2 / ..."
    - cite_examples:   每个 score 类 sub-key 取一个示例 "subkey=…"
    """
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
    cite_hint = ", ".join(cite_examples[:3]) if cite_examples else "'<sub_key>=<score> → ...'"
    return (
        "You are a personality / values consultant. Interpret the user's profile strictly by the dimensions "
        "and sub-keys provided below — do not assume any framework that is not listed.\n\n"
        "## Active profile dimensions (loaded from configuration)\n"
        f"{frameworks_block}\n\n"
        "Based on the user profile AND the raw records below, identify: the angles this user is most likely to overlook on this question, "
        "the judgments they are most likely to over-lean toward, and the cognitive blind spots related to their profile.\n"
        "Anchor every claim in the raw records: cite a specific phrase the user wrote, not a generic inference. "
        "If the raw records show the question concerns A, do not analyze it as if it concerned B.\n"
        f"Cite specific sub-key scores when making each claim (e.g., {cite_hint}).\n"
        "Do not give advice — only reveal. Match the user's language. Keep it under ~120 words.\n\n"
        f"## User profile\n{profile_summary}{mood_section}{raw_section}"
    )


def _explore_system(profile_summary: str, mood_stats: str = "", raw_block: str = "") -> str:
    mood_section = f"\n\n## Mood and journaling patterns\n{mood_stats}" if mood_stats else ""
    raw_section = f"\n\n{raw_block}" if raw_block else ""
    return (
        "You are a cognitive graph exploration expert. Use multi-round tool calls to deeply explore the user's personal knowledge graph.\n\n"
        "Use the raw records below as your starting evidence — they are the most relevant entries for this question. "
        "Search the graph from the nodes already linked to these records, then expand outward. "
        "Do NOT re-search for what's already shown in the raw records.\n\n"
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
        "5. web_search when needed: factual questions, missing external concepts, verifying user's belief against research,\n"
        "   or finding fresh perspectives that could illuminate blind spots. Use sparingly (1-3 calls) — each call costs.\n"
        "6. Stop when sufficient depth is reached\n\n"
        f"## User profile\n{profile_summary}{mood_section}{raw_section}"
    )


_SYNTHESIS_BASE = """\
You are a cognitive map advisor speaking directly to the user.

Match the user's language. Translate the bracketed section titles given below (e.g. [Cognitive Anchor]) into that language naturally while preserving their meaning.

You will receive:
- The user's deeply held belief nodes, with raw record excerpts (the user's own words — the most direct evidence)
- Blind spot candidates (high strength but no opposing tension)
- External knowledge nodes and internal↔external bridge edges
- Cross-domain connections
- The Q2 personality lens (a prior pass that already identified the user's blind spots from their profile + raw)

## Pre-output reasoning (complete silently, do not output)
Before writing, reason through:
1. What is the SPECIFIC subject the user is asking about? Extract the literal action / object / decision they named (e.g. "addressing one's parents" not "family relationships", "choose job A vs. B" not "career anxiety"). Every section you write must directly serve THIS subject.
2. What did Q2 already establish? Build on it — do not restart the diagnosis from scratch.
3. From raw record excerpts, what does the user truly say? What recurs? What carries emotional intensity?
4. What internal contradictions exist, even without explicit opposing edges?
5. What do the external nodes mean — supporting beliefs, or challenging them?

## Universal output requirements (HARD CONSTRAINTS — do not violate)

**[On-topic constraint]** Every paragraph must visibly anchor to the user's literal question.
- If the user asks about X, the word X (or its direct synonym) MUST appear in every section, not just the opening.
- Do NOT drift to a meta-topic that merely contains X (e.g. drifting from "addressing one's parents" to "emotional expression difficulties in general").
- The Evolution Directions / action-recommendation section must be a concrete answer to "how to handle X", not "how to fix the user's larger psychological pattern".

**[Edge consumption constraint]** You MUST reference at least 3 edges from the graph and explain what each one reveals about the user's cognition.
- You may write them in any natural way that fits the paragraph (e.g. "the tension between your <authority pressure> ↔opposes↔ <non-violent communication> tells us …").
- Do NOT invent edges that are not in the graph. If the graph is thin in some area, say so honestly rather than fabricate.
- The provided "Evolution path candidates" section gives you ready-made multi-hop paths — when describing Evolution Directions, prefer one of those paths over stitching edges together yourself.

**[Opposite-pair constraint]** You MUST identify at least 1 internal↔external opposite pair from the graph
(e.g. user's high-strength internal "X" vs. external "Y" they have not internalized) and tell the user:
"You are anchored at X; the closest evolution path is to practice Y in the specific context of [their question subject]."

**[Q2 continuation constraint]** If the Q2 personality lens identified a specific blind spot, you build ON it (deepen, ground in graph evidence, give it a concrete handhold against the user's question). Do NOT propose a parallel diagnosis that ignores or contradicts Q2.

**[Citation constraint]** Every claim must cite specific node labels or the user's own words; never vaguely say "the user tends toward X".

**[Tone constraint]** Direct, as if speaking to the user in person, not writing a report.
"""

_SYNTHESIS_FACTUAL = _SYNTHESIS_BASE + """
## Mode: FACTUAL — answer the question, then add personal lens

The user asked a knowledge / mechanism / possibility question. They want a real answer first.

## Output structure (three sections — translate the bracket titles into the user's language)

**[Direct Answer]** (~180-300 words)
Give a clear, balanced answer to the question itself. Use general knowledge appropriately.
Cover: what the current understanding is, key conditions / nuances, common misconceptions.
Be direct. No "this is a complex topic that depends on many factors" hedging — say what is known.

**[Your Lens]** (~120-180 words)
Now bring in their cognitive map. Cite specific node labels and raw-record words.
Address: how does the user already think about this? Which of their beliefs align with the answer, which conflict?
What does their personality / values lean to that affects how they receive this answer?
This is NOT a personality diagnosis — it's a contextual lens for the factual answer above.

**[Possible Blind Spots]** (~90-150 words)
Optional but recommended. From the graph: which of their high-strength beliefs (if any) might prevent them from
genuinely accepting the factual answer? What would they need to question for the answer to land?
Skip this section if the question genuinely has nothing to do with their existing beliefs.

Total length: roughly 420-540 words."""

_SYNTHESIS_REFLECTIVE = _SYNTHESIS_BASE + """
## Mode: REFLECTIVE — diagnostic four-part analysis

The user asked for self-diagnosis / advice / a decision about themselves.
Deliver a precise diagnosis of their current cognitive state — anchored to the SPECIFIC subject they named.

## Output structure (four sections — translate the bracket titles into the user's language)

**[Cognitive Anchor]**
Starting from raw records, identify what the user truly believes ABOUT THE SPECIFIC SUBJECT THEY ASKED.
Analyze relationships between these beliefs — what worldview or action logic drives the SPECIFIC behavior they're stuck on?
Quote the user's own words. Do not drift to general patterns; tie every belief back to the question's literal subject.

**[Conviction Blind Spot]**
Which high-strength nodes around THIS subject have no opposing tension? Using raw records, why has this belief never been challenged in the specific context they raised?
State directly: if wrong, what are the consequences for the specific situation they're asking about?
Name a specific risk scenario tied to the question subject, no "may need attention" hedging.

**[Cognitive Boundary]**
What boundaries do external nodes and bridge edges reveal AROUND THIS SUBJECT?
Cite at least 1 internal↔external opposite pair: where is the user anchored, where is the unused external concept, and how does the gap relate to their question?
Has the user truly understood these external frameworks, or merely learned the label?

**[Evolution Directions]**
1-2 high-penetration cognitive upgrade directions, each ANSWERING THE LITERAL QUESTION the user asked.
- The action verb in each direction must be the same kind of action the user named in their question (e.g. if they asked about "addressing one's parents", the handhold must involve actually saying / addressing / naming, not "having a deeper conversation about emotions").
- Each direction MUST be grounded in one of the pre-computed "Evolution path candidates" or one of the "internal↔external opposite pairs". If neither is suitable for a direction you want to give, drop the direction — do not invent edges.
- Cite the path or pair you're using (e.g. "Along path 1: from your <guilt in family relationships> to <self-forgiveness>"). No graph anchor → no recommendation.
- No motivational advice — give cognitive pathways with concrete handholds.

Total length: roughly 420-600 words; depth over breadth.
Before submitting, self-check: does each section contain the literal subject of the user's question? If not, rewrite that section."""

_SYNTHESIS_EXPLORATORY = _SYNTHESIS_BASE + """
## Mode: EXPLORATORY — gentle expansion of an idea

The user shared a thought / observation / musing — not really asking, but inviting deeper connection.
Reflect their idea back with sharper edges, then surface related territory in their map.

## Output structure (three sections — translate the bracket titles into the user's language)

**[The Core of This Idea]** (~120-180 words)
Restate their idea more precisely than they did. What's the actual claim or insight buried in their words?
What's the implicit assumption? Quote their own words and sharpen them.

**[Resonance With Existing Beliefs]** (~180-240 words)
Walk through which existing high-strength belief nodes resonate with this idea.
Cite specific node labels and raw-record fragments. Are there nodes this idea naturally extends, or contradicts?
This is mapping, not judging — you're showing them how this new idea sits in their existing cognitive map.

**[Three Directions to Push Further]** (~120-180 words)
Three concrete directions where this idea could go next:
- A direction that connects to their EXTERNAL nodes (bringing in unused knowledge)
- A direction that probes a contradiction with another belief
- A direction that has actionable / testable hypothesis form
Each direction in 1-2 sentences with specific node references. Skip empty motivation.

Total length: roughly 420-600 words."""

# Map mode → synthesis system prompt
_SYNTHESIS_BY_MODE = {
    "factual":     _SYNTHESIS_FACTUAL,
    "reflective":  _SYNTHESIS_REFLECTIVE,
    "exploratory": _SYNTHESIS_EXPLORATORY,
}

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
        summary = f"Found {len(nodes)} nodes: {', '.join(n['label'] for n in nodes)}"
        content = _format_nodes(nodes)
        return {"nodes": nodes, "edges": [], "summary": summary,
                "content": content, "node_count": len(nodes)}

    if name == "expand_node":
        node_ids = [int(i) for i in args.get("node_ids", [])]
        seed_nodes = [all_nodes[nid] for nid in node_ids if nid in all_nodes]
        if not seed_nodes:
            return {"nodes": [], "edges": [], "summary": "Specified nodes not found",
                    "content": "(nodes are not in the known scope; use graph_search first to locate them)", "node_count": 0}
        relations = args.get("relations")
        hop_config = (
            {r: 2 for r in relations}
            if relations
            else {"opposes": 2, "derives": 2, "supports": 2, "similar": 1}
        )
        result = expand_subgraph(seed_nodes, hop_per_relation=hop_config)
        new_count = sum(1 for n in result["nodes"] if n["id"] not in visited_ids)
        visited_ids.update(n["id"] for n in result["nodes"])
        summary = f"Expanded to {len(result['nodes'])} nodes ({new_count} new) and {len(result['edges'])} edges"
        content = _format_subgraph(result)
        return {"nodes": result["nodes"], "edges": result["edges"],
                "summary": summary, "content": content, "node_count": new_count}

    if name == "web_search":
        from app.lib.web_search import web_search as do_web_search, format_results
        query = str(args.get("query", ""))
        max_results = int(args.get("max_results", 5))
        if not query.strip():
            return {"nodes": [], "edges": [], "summary": "web_search missing query parameter",
                    "content": "(please provide a query)", "node_count": 0}
        ws = await do_web_search(query, max_results=max_results)
        if ws.get("error"):
            return {"nodes": [], "edges": [], "summary": ws["error"],
                    "content": ws.get("summary", ""), "node_count": 0}
        results = ws.get("results", [])
        summary = f"web_search \"{query}\" → {len(results)} results"
        content = format_results(results, ws.get("summary", ""))
        return {"nodes": [], "edges": [], "summary": summary,
                "content": content, "node_count": 0}

    if name == "get_opposites":
        node_ids = [int(i) for i in args.get("node_ids", [])]
        seed_nodes = [all_nodes[nid] for nid in node_ids if nid in all_nodes]
        if not seed_nodes:
            return {"nodes": [], "edges": [], "summary": "Specified nodes not found",
                    "content": "(nodes are not in the known scope)", "node_count": 0}
        opposites = opposite_retrieval(seed_nodes)
        new_count = sum(1 for n in opposites if n["id"] not in visited_ids)
        visited_ids.update(n["id"] for n in opposites)
        labels = [n["label"] for n in opposites[:6]]
        summary = f"Found {len(opposites)} opposing nodes: {', '.join(labels)}"
        content = _format_nodes(opposites)
        return {"nodes": opposites, "edges": [], "summary": summary,
                "content": content, "node_count": new_count}

    return {"nodes": [], "edges": [], "summary": f"Unknown tool: {name}",
            "content": "", "node_count": 0}


# ---------------------------------------------------------------------------
# 文本格式化（给 LLM 看的）
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


def _format_subgraph(subgraph: dict) -> str:
    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])
    if not nodes and not edges:
        return "(subgraph is empty)"
    lines = []
    if nodes:
        lines.append("Nodes:")
        for n in nodes[:40]:
            lines.append(
                f"  [id={n.get('id')}][{n.get('origin','')}][{n.get('domain','')}] "
                f"{n.get('label','')} (strength={float(n.get('strength',0)):.3f})"
            )
    if edges:
        lines.append("Edges:")
        for e in edges[:60]:
            lines.append(
                f"  {e.get('from_label','')} --[{e.get('relation_type','')}]--> "
                f"{e.get('to_label','')} ({_wfmt(float(e.get('weight',0)))})"
            )
    return "\n".join(lines)


def _analyze_cognitive_structure(
    nodes: dict[int, dict], edges: list[dict]
) -> dict:
    """从累积节点/边中预计算认知结构特征。"""
    node_list = list(nodes.values())

    # 在子图中有对立边的节点 ID
    nodes_with_opposites: set[int] = set()
    for e in edges:
        if e.get("relation_type") == "opposes":
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


def _compute_evolution_paths(
    nodes: dict[int, dict],
    edges: list[dict],
    max_paths: int = 3,
    max_hops: int = 3,
) -> list[dict]:
    """从 internal 高 strength 锚点 BFS 到 external 节点，找真实存在的演化路径。

    返回路径列表（按 score 降序）。每条路径含：
      - hops: [{from_id, from_label, relation, weight, to_id, to_label, to_origin}]
      - score: 路径打分（平均边权 × 终点 strength × 短路径偏好）
    """
    if not nodes or not edges:
        return []

    # 邻接表：from_id -> [(to_id, edge)]
    adj: dict[int, list[tuple[int, dict]]] = {}
    for e in edges:
        f, t = e.get("from_id"), e.get("to_id")
        if f is None or t is None:
            continue
        adj.setdefault(f, []).append((t, e))
        # 边视为无向（推导/支撑等也允许逆向追溯，符合"路径"的认知含义）
        adj.setdefault(t, []).append((f, e))

    internal_anchors = sorted(
        [n for n in nodes.values()
         if n.get("origin") == "internal" and float(n.get("strength", 0)) >= 0.6],
        key=lambda n: float(n.get("strength", 0)),
        reverse=True,
    )[:6]

    external_targets = {
        n["id"]: n for n in nodes.values() if n.get("origin") == "external"
    }
    if not internal_anchors or not external_targets:
        return []

    candidates: list[dict] = []
    for anchor in internal_anchors:
        # BFS 限定跳数
        visited = {anchor["id"]: []}  # node_id -> path_of_edges
        frontier = [anchor["id"]]
        for hop in range(max_hops):
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
                        # 跳数惩罚：每跳乘以 0.7
                        score = avg_w * target_s * (0.7 ** (len(new_path) - 1))
                        candidates.append({
                            "anchor_id":      anchor["id"],
                            "anchor_label":   anchor.get("label", ""),
                            "anchor_strength": float(anchor.get("strength", 0)),
                            "target_id":      nbr,
                            "target_label":   external_targets[nbr].get("label", ""),
                            "target_strength": target_s,
                            "hops":           new_path,
                            "score":          round(score, 4),
                        })
            frontier = next_frontier

    # 同 anchor→target 的多条路径只保留得分最高
    best_per_pair: dict[tuple, dict] = {}
    for c in candidates:
        key = (c["anchor_id"], c["target_id"])
        if key not in best_per_pair or c["score"] > best_per_pair[key]["score"]:
            best_per_pair[key] = c

    return sorted(best_per_pair.values(), key=lambda c: c["score"], reverse=True)[:max_paths]


def _format_evolution_paths(paths: list[dict]) -> str:
    if not paths:
        return ""
    lines = ["\n## Evolution path candidates (real multi-hop paths in the graph; Evolution Directions MUST be grounded in at least one of these)"]
    lines.append(
        "Each path starts from a high-strength internal anchor and reaches an external target via real edges. "
        "Use these paths directly when narrating — do NOT invent edges that are not in the graph.\n"
    )
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


def _synthesis_prompt(
    question: str,
    nodes: dict[int, dict],
    edges: list[dict],
    raw_pool: dict | None = None,
    hist_ctx: str = "",
    q2_text: str = "",
) -> str:
    struct = _analyze_cognitive_structure(nodes, edges)
    lines = []
    if hist_ctx:
        lines.append(hist_ctx + "\n")
    lines.append(f"## Current question (your answer must directly serve this question; do not drift to meta-level)\n{question}\n")
    if q2_text:
        lines.append(
            "## Prior Q2 personality lens (an existing diagnosis — build on it, do not start over)\n"
            f"{q2_text}\n"
        )

    # raw pool — user's most direct evidence; place first, never truncate.
    if raw_pool and raw_pool.get("entries"):
        lines.append(render_raw_pool(raw_pool))

    top_internal = struct["high_strength_internal"][:18]
    lines.append("\n## Deeply held beliefs (internal, strength ≥ 0.45)")
    if top_internal:
        for n in top_internal:
            line = (
                f"- [{n.get('domain')}][{n.get('node_type')}] **{n.get('label')}** "
                f"(strength={float(n.get('strength',0)):.3f})"
            )
            if n.get("description"):
                line += f"\n  description: {n['description']}"
            lines.append(line)
    else:
        lines.append("(none)")

    lines.append("\n## Conviction blind-spot candidates (internal, high strength, no opposing edge in subgraph)")
    if struct["blindspot_candidates"]:
        for n in struct["blindspot_candidates"][:10]:
            line = f"- [{n.get('domain')}] {n.get('label')} (strength={float(n.get('strength',0)):.3f})"
            if n.get("description"):
                line += f": {n['description']}"
            lines.append(line)
    else:
        lines.append("(every high-strength internal node has at least one opposing edge — blind spots are hidden)")

    lines.append("\n## External knowledge nodes (origin=external — encountered but not internalized)")
    if struct["external_nodes"]:
        for n in struct["external_nodes"][:12]:
            lines.append(f"- [{n.get('domain')}][{n.get('node_type')}] {n.get('label')}"
                         + (f": {n.get('description','')}" if n.get("description") else ""))
    else:
        lines.append("(no external nodes touched in this exploration)")

    lines.append("\n## Internal↔external bridge edges (concrete locations of the cognitive boundary)")
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
        lines.append("(no internal↔external bridge edges)")

    lines.append("\n## Cross-domain edges (connections across domains — implicit cross-domain insight)")
    if struct["cross_domain_edges"]:
        sorted_cross = sorted(struct["cross_domain_edges"], key=lambda e: float(e.get("weight", 0)), reverse=True)
        for e in sorted_cross[:15]:
            lines.append(
                f"- [{e['from_domain']}]{e.get('from_label','')} "
                f"--[{e.get('relation_type','')}]--> "
                f"[{e['to_domain']}]{e.get('to_label','')} ({_wfmt(float(e.get('weight',0)))})"
            )
    else:
        lines.append("(no cross-domain edges)")

    opposite_edges = [e for e in edges if e.get("relation_type") == "opposes"]
    if opposite_edges:
        lines.append(f"\n## Opposition panorama ({len(opposite_edges)} edges total)")
        for e in sorted(opposite_edges, key=lambda e: float(e.get("weight", 0)), reverse=True)[:20]:
            lines.append(
                f"  {e.get('from_label','')} ←opposes→ {e.get('to_label','')} ({_wfmt(float(e.get('weight',0)))})"
            )

    evo_paths = _compute_evolution_paths(nodes, edges)
    if evo_paths:
        lines.append(_format_evolution_paths(evo_paths))

    in_ex_pairs: list[tuple[dict, dict, dict]] = []  # (internal_node, external_node, edge)
    for e in edges:
        if e.get("relation_type") != "opposes":
            continue
        f_node = nodes.get(e.get("from_id"), {})
        t_node = nodes.get(e.get("to_id"), {})
        if not f_node or not t_node:
            continue
        f_origin, t_origin = f_node.get("origin"), t_node.get("origin")
        if f_origin == "internal" and t_origin == "external":
            in_ex_pairs.append((f_node, t_node, e))
        elif f_origin == "external" and t_origin == "internal":
            in_ex_pairs.append((t_node, f_node, e))
    if in_ex_pairs:
        in_ex_pairs.sort(key=lambda p: float(p[0].get("strength", 0)), reverse=True)
        lines.append("\n## Internal↔external opposite pairs (Evolution Directions MUST pick at least one of these)")
        lines.append("The user is currently anchored on the left (internal). The growth direction is to practice the right (external) concept, grounded in the user's specific question context.")
        for in_n, ex_n, e in in_ex_pairs[:10]:
            lines.append(
                f"- anchor [{in_n.get('domain')}] **{in_n.get('label')}** (s={float(in_n.get('strength',0)):.2f}) "
                f"↔ evolve to [{ex_n.get('domain')}] **{ex_n.get('label')}** (s={float(ex_n.get('strength',0)):.2f}) "
                f"edge weight {_wfmt(float(e.get('weight',0)))}"
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
    parts = ["## Prior conversation turns (build on these — do not repeat conclusions)"]
    for i, h in enumerate(history, 1):
        turn_parts = [f"**Turn {i}**\nUser asked: {h['question']}\nAnswer summary: {h['answer'][:1000]}"]
        if h.get("q2_distilled"):
            turn_parts.append(f"Personality lens summary: {h['q2_distilled']}")
        elif h.get("q2_text"):
            turn_parts.append(f"Personality lens summary: {h['q2_text'][:400]}")
        parts.append("\n".join(turn_parts))
    return "\n\n".join(parts)


def _with_history(question: str, history_ctx: str) -> str:
    if not history_ctx:
        return question
    return f"{history_ctx}\n\n## Current follow-up question\n{question}"


async def run_query(question: str, mode: str = "full", session_id: str | None = None) -> AsyncIterator[dict]:
    """多轮图谱探索消费链路。mode='fast' 跳过 Q1/Q2。"""
    if not is_structured_llm_configured():
        yield {"type": "error", "message": "LLM is not configured"}
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
        intent_user_prompt = f"{hist_ctx}\n\n## Current input\n{question}"
    try:
        intent_result = await chat_json(
            system_prompt=_INTENT_SYSTEM,
            user_prompt=intent_user_prompt,
            stage="query:intent_check",
        )
    except Exception:
        intent_result = {"intent": "proceed", "message": ""}
    intent = intent_result.get("intent", "proceed")
    mode = intent_result.get("mode", "reflective")
    if mode not in _SYNTHESIS_BY_MODE:
        mode = "reflective"
    message = (intent_result.get("message") or "").strip()
    yield {"type": "stage", "stage": "intent_check", "status": "done",
           "intent": intent, "mode": mode, "message": message}
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
            yield {"type": "error", "message": f"persistence failed: {exc}"}
            log_id = None
        yield {"type": "done", "session_id": session_id, "log_id": log_id}
        return

    q1_text = ""
    q2_text = ""
    raw_pool: dict = {"entries": [], "candidates": [], "total_chars": 0,
                      "budget": 0, "exhausted": True}
    raw_block = ""

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

        # --- Raw 召回（核心步骤）：基于问题向量检索，给后续阶段提供原汁原味证据 ---
        yield {"type": "stage", "stage": "raw_recall", "status": "start"}
        try:
            raw_pool = await build_raw_pool(question)
        except Exception as exc:
            yield {"type": "error", "message": f"raw recall failed: {exc}"}
            raw_pool = {"entries": [], "candidates": [], "total_chars": 0,
                        "budget": 0, "exhausted": True}
        raw_block = render_raw_pool(raw_pool)
        yield {
            "type": "stage", "stage": "raw_recall", "status": "done",
            "entry_count": len(raw_pool.get("entries", [])),
            "total_chars": raw_pool.get("total_chars", 0),
            "candidates_remaining": len(raw_pool.get("candidates", [])),
            "entries": [
                {"id": e["id"], "date": e["date"],
                 "linked_nodes": [
                    {"id": l["node_id"], "label": l["label"], "strength": l["strength"]}
                    for l in (e.get("linked_nodes") or [])[:5]
                 ],
                 "raw": e["raw"]}
                for e in raw_pool.get("entries", [])
            ],
        }

        # --- Q2 人格穿刺（基于 raw 池消歧 + 画像）---
        yield {"type": "stage", "stage": "persona_blindspot", "status": "start"}
        buf = []
        async for delta in chat_text_stream(
            system_prompt=_q2_system(profile_summary, mood_stats, raw_block=raw_block),
            user_prompt=user_prompt_with_history,
            stage="query:persona_blindspot",
        ):
            buf.append(delta)
            yield {"type": "delta", "stage": "persona_blindspot", "delta": delta}
        q2_text = "".join(buf)
        yield {"type": "stage", "stage": "persona_blindspot", "status": "done", "text": q2_text}

    # --- Q3 图谱迭代探索（raw 池作为种子证据注入）---
    yield {"type": "stage", "stage": "graph_explore", "status": "start"}

    explore_system = _explore_system(profile_summary, mood_stats, raw_block=raw_block)
    if hist_ctx:
        explore_system = explore_system + f"\n\n{hist_ctx}"

    messages: list[dict] = [
        {"role": "system", "content": explore_system},
        {"role": "user", "content": user_prompt_with_history},
    ]
    visited_ids: set[int] = set()
    all_nodes: dict[int, dict] = {}
    all_edges: list[dict] = []
    # Trace log: every tool call + result, persisted with the turn for later inspection
    tool_trace: list[dict] = []

    for round_num in range(1, MAX_EXPLORE_ROUNDS + 1):
        try:
            result = await chat_with_tools(
                messages=messages,
                tools=EXPLORE_TOOLS,
                stage=f"query:explore:r{round_num}",
            )
        except Exception as exc:
            yield {"type": "error", "message": f"exploration round {round_num} failed: {exc}"}
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
            # Record for persistence
            tool_trace.append({
                "round": round_num,
                "tool": tool_name,
                "args": args,
                "summary": "",  # filled in after execution
                "node_count": 0,
                "preview": "",  # short content preview for web_search/graph_search
            })

            try:
                tool_result = await _execute_tool(tool_name, args, visited_ids, all_nodes)
            except Exception as exc:
                tool_result = {"nodes": [], "edges": [], "summary": f"execution failed: {exc}",
                               "content": "", "node_count": 0}

            # Update last trace entry with result info
            if tool_trace:
                tool_trace[-1]["summary"] = tool_result.get("summary", "")
                tool_trace[-1]["node_count"] = tool_result.get("node_count", 0)
                preview = (tool_result.get("content") or "")
                tool_trace[-1]["preview"] = preview[:600] if preview else ""

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

    # --- 综合诊断（流式，最终结果）---
    yield {"type": "stage", "stage": "graph_insight", "status": "start"}
    q3_text = ""
    if all_nodes or raw_pool.get("entries"):
        synth_prompt = _synthesis_prompt(
            question, all_nodes, all_edges,
            raw_pool=raw_pool, hist_ctx=hist_ctx, q2_text=q2_text,
        )
        synthesis_system = _SYNTHESIS_BY_MODE[mode]
        if hist_ctx:
            synthesis_system = (
                synthesis_system
                + "\n\n## Follow-up guidance\n"
                "This is a follow-up turn in a multi-turn conversation. Prior conversation history is included in the user prompt.\n"
                "Deepen on top of the prior conclusions — do not repeat earlier analysis.\n"
                "Surface the connection or tension between this follow-up and the prior cognition, and reveal a new layer."
            )
        buf = []
        async for delta in chat_text_stream(
            system_prompt=synthesis_system,
            user_prompt=synth_prompt,
            stage="query:graph_insight",
            context={
                "nodes": len(all_nodes),
                "edges": len(all_edges),
                "raw_entries": len(raw_pool.get("entries", [])),
            },
        ):
            buf.append(delta)
            yield {"type": "delta", "stage": "graph_insight", "delta": delta}
        q3_text = "".join(buf)
    else:
        yield {"type": "delta", "stage": "graph_insight", "delta": "(no relevant content in the graph yet)"}
        q3_text = "(no relevant content in the graph yet)"

    yield {"type": "stage", "stage": "graph_insight", "status": "done", "text": q3_text}

    seeds_list = sorted(all_nodes.values(), key=lambda n: float(n.get("strength", 0)), reverse=True)
    raw_pool_persisted = {
        "total_chars":           raw_pool.get("total_chars", 0),
        "budget":                raw_pool.get("budget", 0),
        "candidates_remaining":  len(raw_pool.get("candidates", [])),
        "entries": [
            {
                "id":           e.get("id"),
                "date":         e.get("date"),
                "raw":          e.get("raw", ""),  # 不截断
                "max_strength": e.get("max_strength", 0),
                "linked_nodes": [
                    {"id": l["node_id"], "label": l["label"], "strength": l["strength"]}
                    for l in (e.get("linked_nodes") or [])[:5]
                ],
            }
            for e in raw_pool.get("entries", [])
        ],
    }
    try:
        log_id = _persist_turn(
            session_id, question, mode,
            {
                "question": question,
                "intent": "proceed",
                "mode": mode,
                "response": q3_text,
                "q1_text": q1_text,
                "q2_text": q2_text,
                "history_context": hist_ctx,
                "tool_calls": tool_trace,
                "raw_pool": raw_pool_persisted,
            },
            is_new=is_new_session,
            seeds_list=seeds_list,
            q1_text=q1_text, q2_text=q2_text, q3_text=q3_text, q4_text="",
        )
    except Exception as exc:
        yield {"type": "error", "message": f"持久化失败：{exc}"}
        log_id = None

    yield {"type": "done", "session_id": session_id, "log_id": log_id}
