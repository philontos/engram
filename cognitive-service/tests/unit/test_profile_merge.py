"""profile_merge 贝叶斯递推融合的测试。

公式（见 app/lib/profile_merge.py 模块 docstring）：
    τ_obs = c²
    τ_new = γ × τ_old + τ_obs
    α     = τ_obs / τ_new
    μ_new = μ_old + α × (x − μ_old)

测试覆盖三层：
1. 纯公式：_bayes_update 在已知输入下的数值正确性
2. 收敛性质：稳态精度上限、α 衰减、对漂移的响应
3. 端到端：merge_dimension 通过 DB 一整轮，覆盖首次写入 / null 信号 /
   facts key_value / min_conf 兜底等分支
"""

import json

import pytest

from app.config.graph_rules import PROFILE_MERGE
from app.lib.db import get_conn
from app.lib.profile_merge import _bayes_update, _confidence_display, merge_dimension


# ── 纯公式 ──────────────────────────────────────────────────────────────────

class TestBayesUpdate:
    def test_high_confidence_pulls_score(self):
        # 起点 50 / τ=1，强信号 (x=80, c=0.9) 一次拉得动
        new_score, new_tau = _bayes_update(50.0, 1.0, 80.0, 0.9)
        # τ_obs=0.81, τ_new = 0.98×1 + 0.81 = 1.79; α = 0.81/1.79 ≈ 0.452
        assert new_tau == pytest.approx(0.98 * 1.0 + 0.81, rel=1e-4)
        assert new_score == pytest.approx(50.0 + 0.452 * 30.0, rel=2e-2)

    def test_low_confidence_barely_moves(self):
        new_score, new_tau = _bayes_update(50.0, 1.0, 80.0, 0.2)
        # τ_obs=0.04, τ_new = 0.98 + 0.04 = 1.02; α ≈ 0.039
        assert new_score == pytest.approx(50.0 + 0.039 * 30.0, rel=5e-2)
        assert new_score < 52.0

    def test_alpha_decays_with_accumulated_tau(self):
        # τ 越大，同样观测的 α 越小（系统越"沉重"）
        _, tau_after_obs_1 = _bayes_update(50.0, 1.0, 80.0, 0.7)
        score_low, _ = _bayes_update(50.0, 1.0, 80.0, 0.7)
        score_high, _ = _bayes_update(50.0, 50.0, 80.0, 0.7)
        # 同样 (x=80, c=0.7)，τ=50 时 score 移动远小于 τ=1
        assert (score_low - 50) > 5 * (score_high - 50)


# ── 收敛性质 ────────────────────────────────────────────────────────────────

class TestConvergence:
    def test_steady_state_tau_bounded_by_gamma(self):
        # 反复用 c=0.5 喂入，τ 应该收敛到 c² / (1−γ) = 0.25 / 0.02 = 12.5
        gamma = PROFILE_MERGE["gamma"]
        expected_tau_inf = 0.25 / (1 - gamma)
        score, tau = 50.0, 1.0
        for _ in range(2000):
            score, tau = _bayes_update(score, tau, 70.0, 0.5)
        assert tau == pytest.approx(expected_tau_inf, rel=0.05)

    def test_score_converges_to_observation_mean(self):
        # 反复用 (x=70, c=0.7)，μ 应当收敛到 70（在 ~1 分误差内）
        score, tau = 50.0, 1.0
        for _ in range(500):
            score, tau = _bayes_update(score, tau, 70.0, 0.7)
        assert abs(score - 70.0) < 1.0

    def test_drift_response_under_forgetting(self):
        # 先用 200 条 x=40 让系统稳定，再切换到 x=60 跑 300 条，应当追上来
        score, tau = 50.0, 1.0
        for _ in range(200):
            score, tau = _bayes_update(score, tau, 40.0, 0.7)
        assert abs(score - 40.0) < 1.0  # 稳态在 40
        for _ in range(300):
            score, tau = _bayes_update(score, tau, 60.0, 0.7)
        # γ=0.98 下，300 条足以追到目标的 95%+
        assert score > 58.0

    def test_pure_bayes_gamma_one_locks_in(self):
        # γ=1 是病理对照：τ 无上限，越积累越死，对漂移响应迟钝
        # 这里手动用 γ=1 模拟
        score, tau = 50.0, 1.0
        for _ in range(1000):
            tau_obs = 0.49  # c=0.7
            tau_new = 1.0 * tau + tau_obs  # γ=1
            alpha = tau_obs / tau_new
            score = score + alpha * (40.0 - score)
            tau = tau_new
        # 1000 条之后 τ 已 ≈ 491，新 c=0.7 观测 α ≈ 0.001
        # 切到 60 跑 100 条只能挪一点点
        for _ in range(100):
            tau_obs = 0.49
            tau_new = 1.0 * tau + tau_obs
            alpha = tau_obs / tau_new
            score = score + alpha * (60.0 - score)
            tau = tau_new
        # 远没追到 60，验证"越用越死"
        assert score < 50.0


# ── confidence 展示值映射 ────────────────────────────────────────────────────

class TestConfidenceDisplay:
    def test_zero_tau_zero_confidence(self):
        assert _confidence_display(0.0) == 0.0

    def test_tau_equals_ref_confidence_half(self):
        ref = PROFILE_MERGE["tau_ref"]
        assert _confidence_display(ref) == pytest.approx(0.5)

    def test_large_tau_approaches_one(self):
        assert _confidence_display(1000.0) > 0.99

    def test_monotonic(self):
        prev = -1.0
        for tau in [0.5, 1.0, 2.0, 5.0, 10.0, 50.0, 200.0]:
            cur = _confidence_display(tau)
            assert cur > prev
            prev = cur


# ── 端到端（带 DB）────────────────────────────────────────────────────────

class TestMergeDimensionEndToEnd:
    def test_first_write_uses_prior(self, db):
        # 首次写入，先验起步
        merge_dimension("ocean", {"O": {"score": 80, "confidence": 0.9, "evidence": "loves new ideas"}})

        with get_conn() as conn:
            row = conn.execute("SELECT content_json, sample_count FROM profile_dimensions").fetchone()

        assert row is not None
        content = json.loads(row["content_json"])
        # 起点 μ=50, τ=1; (x=80, c=0.9) → τ_new = 0.98+0.81 = 1.79; α = 0.452; μ ≈ 63.55
        assert content["O"]["score"] == pytest.approx(63.55, abs=0.5)
        assert "tau" in content["O"]
        assert "confidence" in content["O"]
        assert content["O"]["evidence"] == "loves new ideas"
        assert row["sample_count"] == 1

    def test_null_subdim_first_write_skipped(self, db):
        # LLM 返回 None 的子维度在首次写入时直接跳过
        merge_dimension("ocean", {"O": None})
        with get_conn() as conn:
            row = conn.execute("SELECT content_json FROM profile_dimensions").fetchone()
        assert row is not None
        content = json.loads(row["content_json"])
        assert "O" not in content  # null 不写入

    def test_null_subdim_preserves_old_value(self, db):
        # 老画像有 O，新观测对 O 显式 null → 保留老画像不变
        merge_dimension("ocean", {"O": {"score": 80, "confidence": 0.9, "evidence": "x"}})
        with get_conn() as conn:
            old = json.loads(conn.execute("SELECT content_json FROM profile_dimensions").fetchone()["content_json"])

        merge_dimension("ocean", {"O": None})
        with get_conn() as conn:
            new = json.loads(conn.execute("SELECT content_json FROM profile_dimensions").fetchone()["content_json"])
        # O 子维度应当原样保留（同 score / 同 tau）
        assert new["O"]["score"] == old["O"]["score"]
        assert new["O"]["tau"] == old["O"]["tau"]

    def test_min_conf_safety_net(self, db):
        # LLM 不守 null 约定，仍输出 (score=50, conf=0.05) → 被 min_conf 兜底过滤
        merge_dimension("ocean", {"O": {"score": 50, "confidence": 0.05}})
        with get_conn() as conn:
            row = conn.execute("SELECT content_json FROM profile_dimensions").fetchone()
        content = json.loads(row["content_json"])
        assert "O" not in content  # 被 min_conf 过滤

    def test_multiple_entries_converge(self, db):
        # 喂 200 条 (x=70, c=0.6)，最终 score 应在 70 附近
        for _ in range(200):
            merge_dimension("ocean", {"E": {"score": 70, "confidence": 0.6, "evidence": "social"}})

        with get_conn() as conn:
            row = conn.execute("SELECT content_json, sample_count FROM profile_dimensions").fetchone()
        content = json.loads(row["content_json"])
        assert content["E"]["score"] == pytest.approx(70.0, abs=1.0)
        assert row["sample_count"] == 200

    def test_facts_key_value_overwrite_unchanged(self, db):
        # facts 维度（无 score 字段）走旧覆盖逻辑，不受贝叶斯影响
        merge_dimension("facts", {"occupation": {"value": "engineer", "evidence": "engineering work"}}, entry_id=1)
        merge_dimension("facts", {"occupation": {"value": "designer", "evidence": "design work"}}, entry_id=2)

        with get_conn() as conn:
            row = conn.execute("SELECT content_json FROM profile_dimensions WHERE dimension='facts'").fetchone()
        content = json.loads(row["content_json"])
        assert content["occupation"]["value"] == "designer"  # 后者覆盖
        assert content["occupation"]["source_entry_id"] == 2

    def test_new_subkey_added_to_existing_dim(self, db):
        # 已有 OCEAN.O，再喂入 C 子维度（首次出现）→ 走先验起步
        merge_dimension("ocean", {"O": {"score": 70, "confidence": 0.7}})
        merge_dimension("ocean", {"C": {"score": 80, "confidence": 0.8}})

        with get_conn() as conn:
            row = conn.execute("SELECT content_json FROM profile_dimensions").fetchone()
        content = json.loads(row["content_json"])
        # O 应保留（第一轮写入），C 应作为新子维度出现
        assert "O" in content
        assert "C" in content
        # C 应基于先验 μ=50, τ=1 起步
        assert content["C"]["score"] > 50  # 被 80 拉高
        assert content["C"]["score"] < 80  # 但被先验拽住

    def test_score_range_zero_to_one_uses_midpoint_prior(self, db, monkeypatch):
        # 模拟一个 0-1 范围维度：先验 μ_0 应为 0.5
        from app.lib import profile_merge as pm
        # 覆盖 DIMENSION_MAP 临时插一个测试维度配置
        fake_dim = {"key": "test_likert", "score_range": [0.0, 1.0]}
        monkeypatch.setitem(pm.DIMENSION_MAP, "test_likert", fake_dim)

        merge_dimension("test_likert", {"a": {"score": 0.9, "confidence": 0.8}})
        with get_conn() as conn:
            row = conn.execute(
                "SELECT content_json FROM profile_dimensions WHERE dimension='test_likert'"
            ).fetchone()
        content = json.loads(row["content_json"])
        # 起点 μ=0.5, τ=1; (x=0.9, c=0.8) → τ_obs=0.64, τ_new=1.62, α=0.395
        # μ_new = 0.5 + 0.395 × 0.4 ≈ 0.658
        assert content["a"]["score"] == pytest.approx(0.66, abs=0.02)
