"""主题深析层：对每个核心信念节点，基于原始记录做 focused LLM 分析。

并行执行，每个节点一次独立 LLM 调用。
输入：all_nodes + all_edges（来自图谱探索阶段）
输出：[{"node": ..., "entries": [...], "analysis": str}]
"""

import asyncio

from app.lib.entry_aggregation import aggregate_entries
from shared.llm import chat_text_stream

MAX_THEMES = 4

_SYSTEM = """\
You are a cognitive analyst. Your task is to deeply analyze the user's cognitive state around a specific belief node.
Base your analysis strictly on the provided raw records — do not introduce concepts from outside them.
Output 150-200 Chinese characters. Tone: direct, as if speaking to the user in person, not writing a report.\
"""


def _build_prompt(theme: dict, question: str, opposites: list[str]) -> str:
    node = theme["node"]
    entries = theme["entries"]

    lines = [
        "## Belief node",
        f"「{node['label']}」（{node['domain']} / {node['node_type']}，strength={node['strength']:.3f}）",
    ]
    if node.get("description"):
        lines.append(f"Description: {node['description']}")

    if opposites:
        lines.append("\n## Opposing nodes")
        lines.append("、".join(f"「{l}」" for l in opposites[:4]))

    lines.append(f"\n## User's raw records ({len(entries)} entries, chronological)")
    for e in entries:
        rel_note = f"\n  [Node relevance: {e['relevance']}]" if e.get("relevance") else ""
        lines.append(f"[{e['date']}] {e['raw']}{rel_note}")

    lines.append(f"\n## Analysis question\nUser asked: 「{question}」")
    lines.append(
        "\nAnalyze:\n"
        "1. What is the true state of this belief in these records? (Not the label — what the user actually expressed)\n"
        "2. Are there internal contradictions or an evolution trajectory across the records?\n"
        "3. In the context of the question, how will this belief influence the user's judgment or action?"
    )

    return "\n".join(lines)


async def _analyze_one(
    theme: dict, question: str, opposites: list[str], idx: int
) -> tuple[int, str]:
    prompt = _build_prompt(theme, question, opposites)
    buf: list[str] = []
    async for delta in chat_text_stream(
        system_prompt=_SYSTEM,
        user_prompt=prompt,
        temperature=0.6,
        stage=f"query:theme_analysis:{idx}",
    ):
        buf.append(delta)
    return idx, "".join(buf)


async def run_theme_analysis(
    question: str,
    all_nodes: dict[int, dict],
    all_edges: list[dict],
) -> list[dict]:
    """
    返回 [{"node": {...}, "entries": [...], "analysis": str}]
    最多 MAX_THEMES 个主题，asyncio.gather 并行分析。
    """
    themes = aggregate_entries(all_nodes)[:MAX_THEMES]
    if not themes:
        return []

    # 为每个主题收集对立节点 label
    theme_ids = {t["node"]["id"] for t in themes}
    opposite_map: dict[int, list[str]] = {nid: [] for nid in theme_ids}
    for e in all_edges:
        if e.get("relation_type") == "对立":
            fid, tid = e.get("from_id"), e.get("to_id")
            if fid in opposite_map:
                opposite_map[fid].append(e.get("to_label", ""))
            if tid in opposite_map:
                opposite_map[tid].append(e.get("from_label", ""))

    tasks = [
        _analyze_one(theme, question, opposite_map[theme["node"]["id"]], i)
        for i, theme in enumerate(themes)
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    idx_to_text: dict[int, str] = {}
    for r in raw_results:
        if isinstance(r, Exception):
            continue
        i, text = r
        idx_to_text[i] = text

    for i, theme in enumerate(themes):
        theme["analysis"] = idx_to_text.get(i, "（分析失败）")

    return themes
