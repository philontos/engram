"""边权重增量公式测试。

来源：backbone_pipeline._upsert_edges，公式：
    increment = min_delta + (base_delta - min_delta) * confidence
"""

import pytest
from app.config.graph_rules import EDGE_WEIGHT, ALGO_EDGE


def _increment(confidence: float) -> float:
    base = EDGE_WEIGHT["base_delta"]   # 0.15
    min_d = EDGE_WEIGHT["min_delta"]   # 0.02
    return round(min_d + (base - min_d) * confidence, 4)


class TestEdgeWeightIncrement:
    def test_zero_confidence_gives_min_delta(self):
        assert _increment(0.0) == pytest.approx(EDGE_WEIGHT["min_delta"])

    def test_full_confidence_gives_base_delta(self):
        assert _increment(1.0) == pytest.approx(EDGE_WEIGHT["base_delta"])

    def test_half_confidence_is_midpoint(self):
        base = EDGE_WEIGHT["base_delta"]
        min_d = EDGE_WEIGHT["min_delta"]
        expected = min_d + (base - min_d) * 0.5
        assert _increment(0.5) == pytest.approx(expected, rel=1e-4)

    def test_increment_monotonic(self):
        # 置信度越高，增量越大
        assert _increment(0.3) < _increment(0.6) < _increment(0.9)

    def test_increment_always_positive(self):
        for conf in [0.0, 0.1, 0.5, 0.99, 1.0]:
            assert _increment(conf) > 0

    def test_min_less_than_base(self):
        assert EDGE_WEIGHT["min_delta"] < EDGE_WEIGHT["base_delta"]


class TestAlgoEdgeParams:
    def test_sim_threshold_sane(self):
        # 相似边阈值应 < 跨域合并阈值（否则相似边永远不会建立）
        from app.config.graph_rules import CROSS_DOMAIN_SIM_THRESHOLD
        assert ALGO_EDGE["intra_domain_sim_threshold"] < CROSS_DOMAIN_SIM_THRESHOLD

    def test_association_caps_ordered(self):
        # 首次 cap 应 <= 多次累加上限
        assert ALGO_EDGE["association_initial_cap"] <= ALGO_EDGE["association_weight_cap_max"]

    def test_algo_edge_weight_cap_reasonable(self):
        # 相似算法边上限 < 关联边累加上限（相似边比关联边更受限）
        assert ALGO_EDGE["weight_cap"] < ALGO_EDGE["association_weight_cap_max"]
        # 算法边上限应在合理范围内（不能无上界，也不能为 0）
        assert 0.0 < ALGO_EDGE["weight_cap"] < 1.0
