"""节点强度 & 画像融合的时间衰减公式测试。

这些公式散落在 backbone_pipeline._update_node_strength 和 profile_merge.merge_dimension，
逻辑完全一致，统一在这里验证。改动任一参数时测试会挂，提醒你后果。
"""

import math
import pytest
from app.config.graph_rules import NODE_STRENGTH, PROFILE_MERGE, EDGE_DECAY


# ── 共用的纯公式（与生产代码保持一致）─────────────────────────────────────────

def _time_decay(days: int, lam: float) -> float:
    return math.exp(-lam * days)

def _freq_bonus(hit_count: int) -> float:
    return 1.0 + math.log(1.0 + hit_count)

def _alpha(old_strength: float, new_conf: float, hist_weight: float) -> float:
    hist_effective = hist_weight * old_strength
    denom = hist_effective + new_conf
    return new_conf / denom if denom > 0 else 1.0

def _new_strength(old: float, alpha: float, new_conf: float) -> float:
    return (1 - alpha) * old + alpha * new_conf


# ── 时间衰减 ────────────────────────────────────────────────────────────────

class TestTimeDecay:
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

    def test_profile_lambda_same_value(self):
        # profile_merge 与 node_strength 使用相同衰减系数
        assert PROFILE_MERGE["lambda"] == NODE_STRENGTH["lambda"]


# ── 频次加成 ────────────────────────────────────────────────────────────────

class TestFreqBonus:
    def test_zero_hits(self):
        # 0 次：log(1) = 0，freq_bonus = 1.0
        assert _freq_bonus(0) == pytest.approx(1.0)

    def test_one_hit(self):
        assert _freq_bonus(1) == pytest.approx(1.0 + math.log(2))

    def test_growth_slows_down(self):
        # 增长越来越慢：等宽区间内的增量递减
        d1 = _freq_bonus(10) - _freq_bonus(0)   # 区间宽度 10
        d2 = _freq_bonus(20) - _freq_bonus(10)  # 区间宽度 10
        d3 = _freq_bonus(50) - _freq_bonus(40)  # 区间宽度 10
        assert d1 > d2 > d3

    def test_known_values(self):
        # 文档注释中的参考值
        assert _freq_bonus(10) == pytest.approx(1 + math.log(11), rel=1e-4)
        assert _freq_bonus(50) == pytest.approx(1 + math.log(51), rel=1e-4)


# ── Alpha 混合系数 ──────────────────────────────────────────────────────────

class TestAlpha:
    def test_no_history(self):
        # 历史 strength=0：alpha 应为 1（全用新信号）
        hw = _time_decay(0, 0.01) * _freq_bonus(0)
        a = _alpha(old_strength=0.0, new_conf=0.8, hist_weight=hw)
        assert a == pytest.approx(1.0)

    def test_high_new_conf_dominates_weak_history(self):
        # 新信号强 + 历史弱（1 条 + 365 天）→ alpha 大
        hw = _time_decay(365, 0.01) * _freq_bonus(1)
        a = _alpha(old_strength=0.7, new_conf=0.9, hist_weight=hw)
        assert a > 0.8

    def test_low_new_conf_loses_to_strong_history(self):
        # 新信号弱 + 历史强（10 条 + 0 天）→ alpha 小
        hw = _time_decay(0, 0.01) * _freq_bonus(10)
        a = _alpha(old_strength=0.8, new_conf=0.3, hist_weight=hw)
        assert a < 0.15

    def test_alpha_range(self):
        # alpha 始终在 (0, 1]
        for hit_count in [0, 5, 50]:
            for days in [0, 30, 180]:
                hw = _time_decay(days, 0.01) * _freq_bonus(hit_count)
                a = _alpha(0.7, 0.5, hw)
                assert 0.0 < a <= 1.0


# ── 强度更新 ─────────────────────────────────────────────────────────────────

class TestStrengthUpdate:
    def test_first_hit_equals_new_conf(self):
        # 首次命中（old=0, hit_count=0, days=0）→ strength = new_conf
        hw = _time_decay(0, 0.01) * _freq_bonus(0)
        a = _alpha(0.0, 0.8, hw)
        assert _new_strength(0.0, a, 0.8) == pytest.approx(0.8)

    def test_strength_moves_toward_new(self):
        # 有历史时，新 strength 介于 old 和 new_conf 之间
        old = 0.6
        new_conf = 0.9
        hw = _time_decay(30, 0.01) * _freq_bonus(5)
        a = _alpha(old, new_conf, hw)
        result = _new_strength(old, a, new_conf)
        assert old < result < new_conf

    def test_very_stale_history_overridden(self):
        # 历史很久远（500 天）+ 新信号高置信 → 应明显向新信号靠拢
        old = 0.3
        new_conf = 0.9
        hw = _time_decay(500, 0.01) * _freq_bonus(3)
        a = _alpha(old, new_conf, hw)
        result = _new_strength(old, a, new_conf)
        assert result > 0.7


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
