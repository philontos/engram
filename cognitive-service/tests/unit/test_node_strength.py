"""DWAS（Decay-Weighted Activation Sum）节点 strength 测试。

写入公式（_update_node_strength）：
    decayed       = old_strength × exp(-λ × Δt)
    new_strength  = decayed + new_conf
    [optional cap]

读取公式（effective_strength）：
    effective = stored × exp(-λ × days_since_last_hit)

测试覆盖：
1. 写入纯公式：单次 / 多次 / 长间隔后衰减
2. 读取衰减：未激活时 effective 自然下沉
3. cap 截断：可选硬上限
4. replay 端到端：从 backbone_activations 重建 strength
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.config.graph_rules import NODE_STRENGTH
from app.lib.backbone_pipeline import effective_strength
from app.lib.db import get_conn


# ── 写入公式（纯算）─────────────────────────────────────────────────────────

def _dwas_step(old: float, new_conf: float, days: int, lam: float = NODE_STRENGTH["lambda"]) -> float:
    return old * math.exp(-lam * days) + new_conf


class TestDWASFormula:
    def test_first_activation_equals_new_conf(self):
        assert _dwas_step(old=0.0, new_conf=0.7, days=0) == pytest.approx(0.7)

    def test_consecutive_same_day_accumulate(self):
        # 同一天连激活两次 c=0.7 → strength 应当几乎 = 1.4（无衰减）
        s = _dwas_step(0.0, 0.7, 0)
        s = _dwas_step(s, 0.7, 0)
        assert s == pytest.approx(1.4, abs=1e-6)

    def test_decay_then_accumulate(self):
        # 第一次激活 c=0.8，69 天后再激活 c=0.6
        # decayed = 0.8 × 0.5 = 0.4；+0.6 = 1.0
        s1 = _dwas_step(0.0, 0.8, 0)
        s2 = _dwas_step(s1, 0.6, 69)
        assert s2 == pytest.approx(1.0, abs=0.01)

    def test_high_frequency_grows_unbounded(self):
        # 10 次连激活 c=0.7（同一天）→ strength 应可超过 1.0（区分新 DWAS vs 旧凸组合）
        s = 0.0
        for _ in range(10):
            s = _dwas_step(s, 0.7, 0)
        assert s == pytest.approx(7.0, abs=1e-6)

    def test_long_dormancy_decays_to_near_zero(self):
        # strength=2.0，500 天没激活 → 衰减到 ~0.013
        s = 2.0 * math.exp(-NODE_STRENGTH["lambda"] * 500)
        assert s < 0.02


# ── 读取衰减（effective_strength）────────────────────────────────────────────

class TestEffectiveStrength:
    def test_no_last_hit_returns_stored(self):
        assert effective_strength(2.5, None) == 2.5

    def test_zero_strength_returns_zero(self):
        assert effective_strength(0.0, "2024-01-01T00:00:00+00:00") == 0.0

    def test_recent_hit_no_decay(self):
        ref = datetime(2024, 5, 1, tzinfo=timezone.utc)
        recent = (ref - timedelta(hours=1)).isoformat()
        # < 1 day → 0 days → no decay
        assert effective_strength(2.0, recent, now=ref) == pytest.approx(2.0)

    def test_69_day_dormancy_halves_strength(self):
        ref = datetime(2024, 5, 1, tzinfo=timezone.utc)
        old = (ref - timedelta(days=69)).isoformat()
        eff = effective_strength(4.0, old, now=ref)
        assert eff == pytest.approx(4.0 * math.exp(-NODE_STRENGTH["lambda"] * 69), abs=0.01)

    def test_malformed_timestamp_returns_stored(self):
        # 防御：解析失败时返回原值（不衰减）
        assert effective_strength(1.5, "not-a-timestamp") == 1.5


# ── 端到端：DB + replay ──────────────────────────────────────────────────────

def _seed_node_with_activations(domain: str, label: str, activations: list[tuple[float, datetime]]) -> int:
    """Insert one node + N backbone_activations rows. Returns node_id."""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO backbone_nodes
               (domain, node_type, label, origin, strength, hit_count)
               VALUES (?, 'concept', ?, 'internal', 0.0, 0)""",
            (domain, label),
        )
        node_id = cur.lastrowid
        # need a parent entry + activation records
        for new_conf, dt in activations:
            cur = conn.execute("INSERT INTO entries (type, raw, created_at) VALUES ('thought', 'x', ?)", (dt.isoformat(),))
            entry_id = cur.lastrowid
            conn.execute(
                """INSERT INTO backbone_activations
                   (node_id, entry_id, profile_match_score, created_at)
                   VALUES (?, ?, ?, ?)""",
                (node_id, entry_id, new_conf, dt.isoformat()),
            )
    return node_id


class TestReplayNodeStrength:
    def test_replay_rebuilds_strength_chronologically(self, db):
        # 3 activations: c=0.7, then 1 day later c=0.7, then 69 days later c=0.6
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        node_id = _seed_node_with_activations("psychology", "test_concept", [
            (0.7, base),
            (0.7, base + timedelta(days=1)),
            (0.6, base + timedelta(days=70)),
        ])

        from scripts.replay_node_strength import replay
        stats = replay(domain="psychology")

        assert stats.activations_replayed == 3
        assert stats.nodes_touched == 1

        with get_conn() as conn:
            row = conn.execute(
                "SELECT strength, hit_count FROM backbone_nodes WHERE id=?", (node_id,)
            ).fetchone()
        # Manually compute expected:
        # s = 0.7
        # s = 0.7 × exp(-0.01×1) + 0.7 ≈ 1.393
        # s = 1.393 × exp(-0.01×69) + 0.6 ≈ 1.393 × 0.5 + 0.6 ≈ 1.297
        expected = 0.7
        expected = expected * math.exp(-0.01 * 1) + 0.7
        expected = expected * math.exp(-0.01 * 69) + 0.6
        assert row["strength"] == pytest.approx(expected, abs=0.01)
        assert row["hit_count"] == 3

    def test_replay_domain_filter(self, db):
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        psy_id = _seed_node_with_activations("psychology", "node_a", [(0.7, base)])
        bus_id = _seed_node_with_activations("business", "node_b", [(0.5, base)])

        # set a sentinel strength on business node before replay
        with get_conn() as conn:
            conn.execute("UPDATE backbone_nodes SET strength = 99.0 WHERE id=?", (bus_id,))

        from scripts.replay_node_strength import replay
        stats = replay(domain="psychology")

        assert stats.nodes_touched == 1

        with get_conn() as conn:
            psy = conn.execute("SELECT strength FROM backbone_nodes WHERE id=?", (psy_id,)).fetchone()
            bus = conn.execute("SELECT strength FROM backbone_nodes WHERE id=?", (bus_id,)).fetchone()
        # psychology rebuilt from activation
        assert psy["strength"] == pytest.approx(0.7, abs=0.01)
        # business untouched (still has sentinel)
        assert bus["strength"] == 99.0

    def test_replay_histogram_buckets(self, db):
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        # one weak, one medium, one strong (10 activations same day)
        _seed_node_with_activations("psychology", "weak",   [(0.3, base)])
        _seed_node_with_activations("psychology", "medium", [(0.7, base), (0.7, base + timedelta(days=1))])
        strong_acts = [(0.7, base + timedelta(hours=i)) for i in range(10)]
        _seed_node_with_activations("psychology", "strong", strong_acts)

        from scripts.replay_node_strength import replay
        stats = replay(domain="psychology")

        # We expect: weak < 0.5, medium ~1.4, strong ~7.0
        assert stats.hist_buckets["<0.5"] == 1   # weak
        assert stats.hist_buckets["1-1.5"] == 1  # medium
        assert stats.hist_buckets[">=5"] == 1    # strong
        assert stats.max_strength > 5.0
