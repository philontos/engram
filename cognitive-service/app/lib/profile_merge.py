"""算法：将单次切片特征融合进持久化画像 profile_dimensions。"""

import json
import math
from datetime import datetime, timezone

from app.lib.db import get_conn
from app.config.graph_rules import PROFILE_MERGE


def _days_since(updated_at_str: str) -> int:
    try:
        dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return 0


def merge_dimension(dimension: str, new_content: dict, entry_id: int | None = None) -> None:
    """将单次切片的 new_content 融合进 profile_dimensions[dimension]。

    核心思路：历史画像是"惯性"，新切片是"信号"，两者加权平均。
    历史惯性越强（样本多、更新近），新信号需要更高 confidence 才能扳动。

    逐子维度独立融合，互不干扰（例如 OCEAN 的 O 和 C 各自独立计算）。

    entry_id：本次切片所属 entry，用于在 evidence 上附带溯源锚点。
    """
    lam = PROFILE_MERGE["lambda"]

    with get_conn() as conn:
        row = conn.execute(
            "SELECT content_json, sample_count, updated_at FROM profile_dimensions WHERE dimension = ?",
            (dimension,),
        ).fetchone()

    # 首次写入：直接存入，无需融合
    if row is None:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO profile_dimensions (dimension, content_json, sample_count, updated_at) VALUES (?, ?, 1, CURRENT_TIMESTAMP)",
                (dimension, json.dumps(new_content, ensure_ascii=False)),
            )
        return

    old_content = json.loads(row["content_json"])
    sample_count = row["sample_count"] or 0
    days = _days_since(row["updated_at"])

    # time_decay = exp(-λ × days)：时间衰减因子，范围 (0, 1]
    #   λ=0.01 时，半衰期约 69 天；1 年后衰减至 ~0.026
    #   代表"历史多久没被新信号强化"，越久越过时
    time_decay = math.exp(-lam * days)

    # freq_bonus = 1 + log(1 + n)：频次加成，范围 [1, ∞)，增长越来越慢
    #   1 条:1.69 / 10 条:3.40 / 50 条:4.91 / 100 条:5.61
    #   代表"这个画像被多少次信号强化过"，越多越稳固
    freq_bonus = 1.0 + math.log(1.0 + sample_count)

    # hist_weight = time_decay × freq_bonus：历史画像的综合惯性权重，无上界
    #   新近且样本多 → 惯性大（如 10 条+0 天 ≈ 3.4）
    #   久远且样本少 → 惯性小（如 1 条+365 天 ≈ 0.04）
    hist_weight = time_decay * freq_bonus

    merged = {}
    all_keys = set(old_content) | set(new_content)

    for key in all_keys:
        new_val = new_content.get(key)
        old_val = old_content.get(key)

        # facts 等非评分字段（无 score 字段）：直接取新值覆盖，不做加权
        if not isinstance(new_val, dict) or "score" not in (new_val or {}):
            chosen = new_val if new_val is not None else old_val
            # facts 新值带 evidence 时，附加 source_entry_id 作为溯源锚点
            if isinstance(chosen, dict) and "evidence" in chosen and entry_id is not None and chosen is new_val:
                chosen = {**chosen, "source_entry_id": entry_id}
            merged[key] = chosen
            continue

        new_score = float(new_val.get("score", 50))
        new_conf = float(new_val.get("confidence", 0.5))

        # 无信号维度（confidence 极低）直接跳过，保留历史画像不受污染
        if new_conf < 0.15:
            if old_val is not None:
                merged[key] = old_val
            continue

        if isinstance(old_val, dict) and "score" in old_val:
            old_score = float(old_val.get("score", 50))
            old_conf = float(old_val.get("confidence", 0.5))

            # hist_effective = hist_weight × old_conf：历史侧有效权重
            #   同时考虑"历史有多稳固"和"历史有多可信"
            #   old_conf 高（历史置信度高）→ 历史更抗扰动
            #   old_conf 低（历史本身不确定）→ 历史更容易被新信号覆盖
            hist_effective = hist_weight * old_conf

            # alpha = new_conf / (hist_effective + new_conf)：新信号的混合系数，范围 (0, 1)
            #   new_conf 高且 hist_effective 小 → alpha 大，新信号主导
            #   new_conf 低或 hist_effective 大 → alpha 小，新信号影响微弱
            #   示例（old_conf=0.8，10 条样本）：
            #     new_conf=0.9 → alpha≈0.25（新信号占 25%）
            #     new_conf=0.3 → alpha≈0.12（新信号占 12%）
            #     new_conf=0.05 → alpha≈0.02（新信号几乎无影响）
            denom = hist_effective + new_conf
            alpha = new_conf / denom if denom else 0.0

            # score 和 confidence 共用同一个 alpha，行为一致：
            # - alpha 小时，两者都几乎不动（低质量信号被天然过滤）
            # - alpha 大时，两者都向新信号方向移动
            # - confidence 有涨有跌，真实反映近期信号质量
            m_score = (1 - alpha) * old_score + alpha * new_score
            m_conf = min(0.99, (1 - alpha) * old_conf + alpha * new_conf)
        else:
            # 老画像里没有此 key（新增维度）：直接用新值
            m_score = new_score
            m_conf = new_conf

        item = {"score": round(m_score, 2), "confidence": round(m_conf, 3)}
        if "evidence" in new_val:
            item["evidence"] = new_val["evidence"]
            if entry_id is not None:
                item["source_entry_id"] = entry_id
        merged[key] = item

    with get_conn() as conn:
        conn.execute(
            "UPDATE profile_dimensions SET content_json = ?, sample_count = ?, updated_at = CURRENT_TIMESTAMP WHERE dimension = ?",
            (json.dumps(merged, ensure_ascii=False), sample_count + 1, dimension),
        )
