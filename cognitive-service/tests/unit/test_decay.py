"""时间衰减公式测试（NODE_STRENGTH 与 EDGE_DECAY 共享 exp(-λ × days) 的形态）。

注意：profile_merge 已切到贝叶斯递推（见 test_profile_merge.py），node_strength
已切到 DWAS（见 test_node_strength.py），不再共用旧的 freq_bonus / alpha 公式。
本文件只保留两组核心 exp 衰减性质的回归测试。
"""

import math
import pytest
from app.config.graph_rules import NODE_STRENGTH, EDGE_DECAY


def _time_decay(days: int, lam: float) -> float:
    return math.exp(-lam * days)


# ── 节点 strength 时间衰减 ──────────────────────────────────────────────────

class TestNodeTimeDecay:
    lam = NODE_STRENGTH["lambda"]  # 0.01

    def test_no_time_passed(self):
        assert _time_decay(0, self.lam) == pytest.approx(1.0)

    def test_half_life_69_days(self):
        # λ=0.01 时半衰期约 69 天 (ln2/0.01 ≈ 69.3)
        result = _time_decay(69, self.lam)
        assert 0.49 < result < 0.51

    def test_one_year_decay(self):
        # 365 天后约剩 2.6%
        result = _time_decay(365, self.lam)
        assert result == pytest.approx(math.exp(-0.01 * 365), rel=1e-6)
        assert result < 0.03


# ── Edge 消费时衰减 ──────────────────────────────────────────────────────────

class TestEdgeDecay:
    lam = EDGE_DECAY["lambda"]   # 0.002
    floor = EDGE_DECAY["floor"]  # 0.3

    def _decay(self, weight: float, days: int) -> float:
        return max(self.floor, weight * math.exp(-self.lam * days))

    def test_no_decay_at_zero_days(self):
        assert self._decay(0.8, 0) == pytest.approx(0.8)

    def test_floor_enforced(self):
        # 无论时间多久，不低于 floor
        assert self._decay(1.0, 99999) == pytest.approx(self.floor)
        assert self._decay(0.1, 0) == pytest.approx(self.floor)  # 初始值已低于 floor

    def test_500_days_approx_37_percent(self):
        # λ=0.002, t=500 → exp(-1) ≈ 0.368
        result = self._decay(1.0, 500)
        assert result == pytest.approx(math.exp(-0.002 * 500), rel=1e-4)

    def test_floor_lambda_combo_makes_sense(self):
        # floor=0.3 意味着边永不消失到 0，确保图谱连通性
        assert self.floor > 0.0
        assert self.lam < NODE_STRENGTH["lambda"]  # edge decay 比 node decay 慢
