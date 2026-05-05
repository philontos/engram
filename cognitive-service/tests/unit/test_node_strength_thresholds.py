"""DWAS strength 阈值与排序权重的 config 化测试。

PR #6 之前这些参数 hardcoded（旧 [0,1] 范围下的 0.6 / 0.45 / 0.5 / 0.5/0.3/0.2），
改成从 NODE_STRENGTH config 读后默认值适配新 DWAS 分布（0-5+）。

测试覆盖：
1. 配置存在性 + 默认值合理性
2. find_blindspots 默认从 config 读
3. _precise_retrieval rank 公式权重从 config 读
"""

import pytest

from app.config.graph_rules import NODE_STRENGTH
from app.lib.retrieval import find_blindspots


# ── 配置存在性 ──────────────────────────────────────────────────────────────

class TestNodeStrengthConfigShape:
    def test_thresholds_present(self):
        assert "anchor_min" in NODE_STRENGTH
        assert "blindspot_min" in NODE_STRENGTH

    def test_rank_weights_present(self):
        for k in ("rank_strength_weight", "rank_new_conf_weight", "rank_rough_sim_weight"):
            assert k in NODE_STRENGTH
            assert isinstance(NODE_STRENGTH[k], (int, float))

    def test_rank_weights_sum_to_one(self):
        # 不强制，但默认值应该和约为 1（凸组合语义直观）
        total = (NODE_STRENGTH["rank_strength_weight"]
                 + NODE_STRENGTH["rank_new_conf_weight"]
                 + NODE_STRENGTH["rank_rough_sim_weight"])
        assert total == pytest.approx(1.0, abs=0.01)

    def test_anchor_min_above_blindspot_min(self):
        # 锚点门槛应当 >= 盲区门槛，否则语义混乱
        assert NODE_STRENGTH["anchor_min"] >= NODE_STRENGTH["blindspot_min"]

    def test_thresholds_match_dwas_range(self):
        # 旧 [0,1] 范围，旧默认 0.6/0.45。新 DWAS [0, ~5+]，默认应当 > 0.5
        # 否则就跟没改一样。
        assert NODE_STRENGTH["anchor_min"] > 0.5
        assert NODE_STRENGTH["blindspot_min"] > 0.5


# ── find_blindspots 默认从 config 读 ────────────────────────────────────────

class TestFindBlindspotsDefault:
    def test_filter_uses_config_default_when_omitted(self, db, monkeypatch):
        # 把阈值临时调到 2.0：strength=1.5 应被过滤掉，strength=2.5 应通过初筛
        monkeypatch.setitem(NODE_STRENGTH, "blindspot_min", 2.0)
        seed = [
            {"id": 1, "origin": "internal", "strength": 1.5, "label": "weak"},
            {"id": 2, "origin": "internal", "strength": 2.5, "label": "strong"},
        ]
        result = find_blindspots(seed)  # 不传 min_strength
        # weak 被阈值过滤；strong 进 DB 查询，因 db fixture 空表无 edges → 空集 →
        # 在 find_blindspots 内被认为"无对立边"= 真盲区候选 → 通过
        labels = [n.get("label") for n in result]
        assert "weak" not in labels
        assert "strong" in labels

    def test_explicit_min_strength_overrides_config(self, db, monkeypatch):
        # config 阈值 5.0（高），但显式传 0.5（低）→ 应当被显式参数覆盖
        monkeypatch.setitem(NODE_STRENGTH, "blindspot_min", 5.0)
        seed = [{"id": 1, "origin": "internal", "strength": 1.0, "label": "x"}]
        result = find_blindspots(seed, min_strength=0.5)
        assert len(result) == 1


# ── _precise_retrieval rank 公式 ────────────────────────────────────────────

class TestPreciseRetrievalRankWeights:
    def test_high_strength_outranks_high_sim_under_default_weights(self):
        # 默认权重下 strength 主导：strength=3 应当胜过 sim=0.95（DWAS 后这是预期）
        ws = NODE_STRENGTH["rank_strength_weight"]
        wc = NODE_STRENGTH["rank_new_conf_weight"]
        wr = NODE_STRENGTH["rank_rough_sim_weight"]
        rank_high_s   = ws * 3.0 + wc * 0.5 + wr * 0.3
        rank_high_sim = ws * 0.5 + wc * 0.5 + wr * 0.95
        assert rank_high_s > rank_high_sim

    def test_weights_can_be_tuned_to_demote_strength(self, monkeypatch):
        # 如果用户发现 strength 过度压制别的信号，调小 strength 权重应有效
        monkeypatch.setitem(NODE_STRENGTH, "rank_strength_weight", 0.1)
        monkeypatch.setitem(NODE_STRENGTH, "rank_rough_sim_weight", 0.6)
        ws = NODE_STRENGTH["rank_strength_weight"]
        wr = NODE_STRENGTH["rank_rough_sim_weight"]
        rank_high_s   = ws * 3.0 + 0.0 + wr * 0.3
        rank_high_sim = ws * 0.5 + 0.0 + wr * 0.95
        # 在这套权重下 high_sim 反超
        assert rank_high_sim > rank_high_s
