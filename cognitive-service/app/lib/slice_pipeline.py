"""Call 1: 从 raw entry 提取人格切片，并融合进持久化画像。"""

import json
from string import Template

from app.lib.config_loader import DIMENSION_MAP, DIMENSIONS, ENTRY_ANALYZER_MAP
from app.lib.db import get_conn
from app.lib.profile_merge import merge_dimension
from shared.llm import StructuredLLMError, chat_json, is_structured_llm_configured


def get_mood_stats() -> str:
    """近期情绪分布 + 时段分布，供消费链路使用。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT mood, metadata_json FROM entries WHERE mood IS NOT NULL AND mood != ''"
        ).fetchall()
    if not rows:
        return ""
    mood_dist: dict[str, int] = {}
    tod_dist: dict[str, int] = {}
    for r in rows:
        mood_dist[r["mood"]] = mood_dist.get(r["mood"], 0) + 1
        try:
            meta = json.loads(r["metadata_json"] or "{}")
            tod = meta.get("time_of_day")
            if tod:
                tod_dist[tod] = tod_dist.get(tod, 0) + 1
        except Exception:
            pass
    total = sum(mood_dist.values())
    mood_parts = ", ".join(
        f"{m}({c})" for m, c in sorted(mood_dist.items(), key=lambda x: -x[1])[:8]
    )
    tod_parts = ", ".join(
        f"{t}({c})" for t, c in sorted(tod_dist.items(), key=lambda x: -x[1])
    )
    lines = [f"Mood distribution ({total} entries): {mood_parts}"]
    if tod_parts:
        lines.append(f"Recording times: {tod_parts}")
    return "\n".join(lines)


def _render_dim(dim_key: str, content: dict) -> str | None:
    """Render a dimension's content to a summary line using its config's summary_format."""
    cfg = DIMENSION_MAP.get(dim_key)
    if not cfg:
        return None

    fmt = cfg.get("summary_format", "free")
    if fmt == "skip":
        return None

    label = cfg.get("summary_label", cfg.get("name", dim_key))

    if fmt == "scores":
        items = [(k, v) for k, v in content.items() if isinstance(v, dict)]
        if cfg.get("sort_by_score", False):
            items.sort(key=lambda x: -x[1].get("score", 50))
        s = ", ".join(
            f"{k}={v.get('score', 50):.0f}(conf={v.get('confidence', 0):.2f})"
            for k, v in items
        )
        return f"{label}: {s}" if s else None

    if fmt == "key_value":
        items = {}
        for k, v in content.items():
            if not v or v == "null":
                continue
            items[k] = v["value"] if isinstance(v, dict) and "value" in v else v
        if not items:
            return None
        return f"{label}: " + "; ".join(f"{k}={v}" for k, v in items.items())

    # free fallback — any unknown dimension gets json-dumped
    s = json.dumps(content, ensure_ascii=False)
    return f"{label}: {s}"


def get_profile_summary() -> str:
    """读取 profile_dimensions 表，将持久化画像压缩成单段文本供 LLM 使用。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dimension, content_json FROM profile_dimensions ORDER BY dimension"
        ).fetchall()

    if not rows:
        return "(no historical profile yet)"

    parts = []
    for row in rows:
        line = _render_dim(row["dimension"], json.loads(row["content_json"]))
        if line:
            parts.append(line)

    return "\n".join(parts) if parts else "(no historical profile yet)"



async def _extract_dimension(dim: dict, raw: str, profile_summary: str) -> dict | None:
    """单个维度的 LLM 提取，失败返回 None。"""
    prompt_tmpl = dim.get("_prompt", "")
    if not prompt_tmpl:
        return None

    system_prompt = Template(prompt_tmpl).safe_substitute(
        rubric=dim.get("_rubric", ""),
        profile_summary=profile_summary,
        raw_entry=raw,
    )

    try:
        return await chat_json(
            system_prompt=system_prompt, user_prompt="",
            stage=f"slice:{dim['key']}",
            context={"raw_chars": len(raw)},
        )
    except StructuredLLMError:
        return None


def _normalize_extraction(dim_cfg: dict, content: dict) -> dict:
    """对 LLM 抽取结果做 schema 兜底归一化。

    新 prompt 约定：每个子维度要么是 {score, confidence, evidence}，要么是 None。
    LLM 偶尔不守约定时（缺字段、错类型、`{"abstain": true}` 之类），统一兜底为 None。
    facts 等非评分维度（无 score 字段）保留原值。
    """
    if not isinstance(content, dict):
        return {}

    sub_dims = dim_cfg.get("sub_dimensions") or []
    summary_format = dim_cfg.get("summary_format", "free")

    if summary_format != "scores" or not sub_dims:
        # 非 score 形态（facts / situation 等）→ 不动
        return content

    out: dict = {}
    for sd in sub_dims:
        key = sd.get("key")
        if not key:
            continue
        v = content.get(key)
        if v is None:
            out[key] = None
        elif isinstance(v, dict) and "score" in v and "confidence" in v:
            out[key] = v
        else:
            # 异常 schema（缺字段 / 非字典 / {"abstain":true} 等）→ 兜底为 None
            out[key] = None
    return out


def _extraction_health(dim_cfg: dict, content: dict) -> dict:
    """统计单次抽取的健康指标，供观测用。

    返回三个计数：
    - null_count        : LLM 显式返回 None 的子维度数（新 prompt 期望的形态）
    - low_conf_count    : confidence < 0.15 的占位（旧 prompt 行为，应该接近 0）
    - midpoint_hedge_count: score 在 [45,55] 且 conf ∈ [0.15, 0.5) 的中点 hedge
                           （anchoring 残留，越低越好）
    + total: 子维度总数（分母）
    """
    sub_dims = dim_cfg.get("sub_dimensions") or []
    if dim_cfg.get("summary_format") != "scores" or not sub_dims:
        return {}

    null_count = 0
    low_conf_count = 0
    hedge_count = 0
    total = 0
    for sd in sub_dims:
        key = sd.get("key")
        if not key:
            continue
        total += 1
        v = content.get(key)
        if v is None:
            null_count += 1
            continue
        if not isinstance(v, dict):
            continue
        c = float(v.get("confidence", 0))
        s = float(v.get("score", 50))
        if c < 0.15:
            low_conf_count += 1
        elif c < 0.5 and 45 <= s <= 55:
            hedge_count += 1
    return {
        "total": total,
        "null_count": null_count,
        "low_conf_count": low_conf_count,
        "midpoint_hedge_count": hedge_count,
    }


async def generate_slice(entry_id: int, raw: str, trace: dict | None = None) -> int | None:
    """生成并持久化一条 entry 的完整切片。返回 slice_id，失败返回 None。

    trace（可选）：传入则在 trace["slice_extraction_health"] 写入每维度的
    null/low_conf/midpoint_hedge 计数，供后续观测和 prompt 调优。
    """
    if not is_structured_llm_configured():
        return None

    profile_summary = get_profile_summary()

    # 读取 entry 的 mood / memory_type / time_of_day，拼成上下文头部注入 LLM
    with get_conn() as conn:
        erow = conn.execute(
            "SELECT mood, memory_type, metadata_json FROM entries WHERE id=?", (entry_id,)
        ).fetchone()

    enriched_raw = raw
    if erow:
        ctx_parts = []
        if erow["memory_type"]:
            ctx_parts.append(f"type: {erow['memory_type']}")
        if erow["mood"]:
            ctx_parts.append(f"mood: {erow['mood']}")
        try:
            meta = json.loads(erow["metadata_json"] or "{}")
            wd = meta.get("weekday", "")
            tod = meta.get("time_of_day", "")
            if wd or tod:
                ctx_parts.append(f"time: {(wd + ' ' + tod).strip()}")
        except Exception:
            pass
        if ctx_parts:
            enriched_raw = f"[{' / '.join(ctx_parts)}]\n{raw}"

    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO slices (entry_id, created_at) VALUES (?, CURRENT_TIMESTAMP)",
            (entry_id,),
        )
        slice_id = cursor.lastrowid

    # entry analyzers：per-entry 标注，写入 entries 对应字段，不进维度系统
    situation_dim = ENTRY_ANALYZER_MAP.get("situation")
    situation_content: dict | None = None
    if situation_dim and situation_dim.get("enabled", True):
        situation_content = await _extract_dimension(situation_dim, enriched_raw, profile_summary)
        if situation_content:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE entries SET situation_json=? WHERE id=?",
                    (json.dumps(situation_content, ensure_ascii=False), entry_id),
                )

    # 根据 situation 决定是否跳过画像融合
    # retrospective + recounting_past = 复述过去的自己，不应污染当前画像
    skip_profile_merge = False
    if situation_content:
        if (situation_content.get("temporal_frame") == "retrospective"
                and situation_content.get("narrator_stance") == "recounting_past"):
            skip_profile_merge = True

    # 提取人格维度，先收集结果再决定是否 merge
    extracted: dict[str, tuple[dict, dict]] = {}  # key -> (dim_cfg, content)
    health: dict[str, dict] = {}  # key -> {null_count, low_conf_count, midpoint_hedge_count}
    for dim in DIMENSIONS:
        if dim["key"] == "situation":
            continue  # situation 已单独处理
        if not dim.get("enabled", True):
            continue
        raw_content = await _extract_dimension(dim, enriched_raw, profile_summary)
        if not raw_content:
            continue
        # schema 兜底：异常子维度（缺字段 / 错类型）统一归一化为 None
        content = _normalize_extraction(dim, raw_content)
        # 观测埋点：记录每维度的 null / low_conf / midpoint_hedge 计数
        h = _extraction_health(dim, content)
        if h:
            health[dim["key"]] = h
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO slice_features (slice_id, dimension, content_json, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (slice_id, dim["key"], json.dumps(content, ensure_ascii=False)),
            )
        extracted[dim["key"]] = (dim, content)

    if trace is not None and health:
        trace["slice_extraction_health"] = health

    for key, (dim, content) in extracted.items():
        if skip_profile_merge:
            continue  # 复述过去，跳过所有画像融合
        merge_dimension(key, content, entry_id=entry_id)

    return slice_id


def get_situation_context(entry_id: int) -> str:
    """返回该 entry 的情境描述字符串，供 backbone pipeline 注入 LLM 提示词。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT situation_json FROM entries WHERE id=?",
            (entry_id,),
        ).fetchone()
    if not row or not row["situation_json"]:
        return ""

    s = json.loads(row["situation_json"])
    parts = []

    tf = s.get("temporal_frame")
    ns = s.get("narrator_stance")
    lp = s.get("life_phase_ref")
    em = s.get("emotional_state")
    pr = s.get("pressure_level")
    en = s.get("energy_level")

    if tf == "retrospective":
        ref = f" (life phase: {lp})" if lp else ""
        parts.append(f"retrospective entry{ref}")
        if ns == "recounting_past":
            parts.append("user is recounting past self, not current beliefs")
        elif ns == "mixed":
            parts.append("contains both past recounting and current reflection")
    elif tf == "hypothetical":
        parts.append("hypothetical/speculative thinking")

    if em:
        parts.append(f"emotional state: {em}")
    if pr and pr != "medium":
        parts.append(f"pressure: {pr}")
    if en and en != "medium":
        parts.append(f"energy: {en}")

    return "; ".join(parts) if parts else ""


def get_slice_summary(slice_id: int) -> str:
    """返回切片的紧凑摘要，供 backbone pipeline 作上下文。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dimension, content_json FROM slice_features WHERE slice_id = ?",
            (slice_id,),
        ).fetchall()

    parts = []
    for row in rows:
        line = _render_dim(row["dimension"], json.loads(row["content_json"]))
        if line:
            parts.append(line)

    return "\n".join(parts) if parts else "(slice is empty)"
