"""算法：将单次切片特征融合进持久化画像 profile_dimensions。

核心：贝叶斯共轭递推估计。每个子维度独立维护一个潜在画像值 θ 的后验分布，
新观测 (x, c) 提供精度 τ_obs = c²，与累积精度 τ_old 加权得到新后验均值 μ。

公式（每个子维度独立计算）：
    τ_obs = c²                       # 观测精度
    τ_new = γ × τ_old + τ_obs        # 遗忘因子衰减后累加
    α     = τ_obs / τ_new            # 新观测的混合权重
    μ_new = μ_old + α × (x − μ_old)  # 后验均值递推

数学性质：
- 稳态 τ_∞ = E[c²] / (1−γ)，α 也有界 ⇒ 画像追踪能力不随使用时间衰减
- θ 不变时 μ 收敛到 E[x]（大数定律 + precision-weighted average）
- θ 慢漂移时 μ 在约 1/(1−γ) 条 entry 内追上变化

存储格式（profile_dimensions.content_json 的子维度对象）：
    {"score": μ, "tau": τ, "confidence": τ/(τ+τ_ref), "evidence": "...", ...}

无信号处理（按优先级）：
1. LLM 显式 `null`：保留旧画像，不更新（首选语义）
2. min_conf 兜底：confidence < 0.15 的"低置信占位"也保留旧画像
   （防 LLM 不守 null 约定，仍输出 score=50, conf=0.05 形式）

facts / key_value 等无 score 字段的子维度走覆盖逻辑（直接取新值）。

详细推导、参数物理含义、收敛仿真见 cognitive-service/README.md "Profile Merge"。
"""

import json

from app.config.graph_rules import PROFILE_MERGE
from app.lib.config_loader import DIMENSION_MAP
from app.lib.db import get_conn


def _score_prior(dimension: str) -> float:
    """子维度的先验均值：score_range 的中点（无信息先验）。"""
    cfg = DIMENSION_MAP.get(dimension) or {}
    rng = cfg.get("score_range") or [0, 100]
    return (float(rng[0]) + float(rng[1])) / 2


def _confidence_display(tau: float) -> float:
    """把累积精度 τ 映射成 [0, 1) 的 confidence 展示值。

    confidence = τ / (τ + τ_ref)：τ=τ_ref 时 0.5，τ→∞ 时趋近 1.0。
    供前端展示用，不参与算法。
    """
    tau_ref = PROFILE_MERGE["tau_ref"]
    return tau / (tau + tau_ref) if tau + tau_ref > 0 else 0.0


def _bayes_update(old_score: float, old_tau: float, x: float, c: float) -> tuple[float, float]:
    """贝叶斯递推更新 (μ, τ)。详细公式见模块 docstring。"""
    gamma = PROFILE_MERGE["gamma"]
    tau_obs = c * c
    new_tau = gamma * old_tau + tau_obs
    alpha = tau_obs / new_tau if new_tau > 0 else 0.0
    new_score = old_score + alpha * (x - old_score)
    return new_score, new_tau


def merge_dimension(dimension: str, new_content: dict, entry_id: int | None = None) -> None:
    """将单次切片的 new_content 融合进 profile_dimensions[dimension]。

    每个子维度独立处理：
    - score 字段（OCEAN / MBTI / Schwartz 等数值维度）→ 走 _bayes_update
    - 非 score 字段（facts 等 key_value 形态）→ 直接覆盖，附带 source_entry_id

    entry_id：本次切片所属 entry，用于在 evidence 上附带溯源锚点。
    """
    tau_prior = PROFILE_MERGE["tau_prior"]
    min_conf = PROFILE_MERGE["min_conf"]
    score_prior = _score_prior(dimension)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT content_json, sample_count FROM profile_dimensions WHERE dimension = ?",
            (dimension,),
        ).fetchone()

    is_first = row is None
    old_content = json.loads(row["content_json"]) if row else {}
    sample_count = (row["sample_count"] or 0) if row else 0

    merged: dict = {}
    all_keys = set(old_content) | set(new_content)

    for key in all_keys:
        new_val = new_content.get(key)
        old_val = old_content.get(key)

        # 优先级 1：LLM 显式 null = 该子维度无信号，保留旧画像
        if new_val is None:
            if old_val is not None:
                merged[key] = old_val
            continue

        # 非评分字段（facts 等 key_value 形态，无 score 字段）：直接覆盖
        if not isinstance(new_val, dict) or "score" not in new_val:
            chosen = new_val
            if isinstance(chosen, dict) and "evidence" in chosen and entry_id is not None:
                chosen = {**chosen, "source_entry_id": entry_id}
            merged[key] = chosen
            continue

        new_score = float(new_val.get("score", score_prior))
        new_conf = float(new_val.get("confidence", 0.5))

        # 优先级 2：min_conf 兜底过滤（防 LLM 不守 null 约定，仍输出低置信占位）
        if new_conf < min_conf:
            if old_val is not None:
                merged[key] = old_val
            continue

        # 起点：已有画像或先验
        if isinstance(old_val, dict) and "score" in old_val:
            old_score = float(old_val["score"])
            old_tau = float(old_val["tau"])
        else:
            old_score = score_prior
            old_tau = tau_prior

        m_score, m_tau = _bayes_update(old_score, old_tau, new_score, new_conf)

        item = {
            "score": round(m_score, 2),
            "tau": round(m_tau, 4),
            "confidence": round(_confidence_display(m_tau), 3),
        }
        if "evidence" in new_val:
            item["evidence"] = new_val["evidence"]
            if entry_id is not None:
                item["source_entry_id"] = entry_id
        merged[key] = item

    with get_conn() as conn:
        if is_first:
            conn.execute(
                "INSERT INTO profile_dimensions (dimension, content_json, sample_count, updated_at) "
                "VALUES (?, ?, 1, CURRENT_TIMESTAMP)",
                (dimension, json.dumps(merged, ensure_ascii=False)),
            )
        else:
            conn.execute(
                "UPDATE profile_dimensions SET content_json = ?, sample_count = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE dimension = ?",
                (json.dumps(merged, ensure_ascii=False), sample_count + 1, dimension),
            )
