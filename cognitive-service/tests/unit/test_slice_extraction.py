"""Slice 抽取的 schema 兜底与观测指标测试。

被测函数（app/lib/slice_pipeline.py）：
- _normalize_extraction(dim_cfg, content)：异常 schema → null 兜底
- _extraction_health(dim_cfg, content)：null / low_conf / midpoint_hedge 计数
"""

from app.lib.slice_pipeline import _extraction_health, _normalize_extraction


# Mock dimension config (mirrors OCEAN structure but smaller)
SCORE_DIM = {
    "key": "test_score",
    "summary_format": "scores",
    "sub_dimensions": [
        {"key": "A"},
        {"key": "B"},
        {"key": "C"},
    ],
}

KEY_VALUE_DIM = {
    "key": "test_facts",
    "summary_format": "key_value",
}


# ── _normalize_extraction ──────────────────────────────────────────────────

class TestNormalizeExtraction:
    def test_well_formed_passthrough(self):
        content = {
            "A": {"score": 70, "confidence": 0.8, "evidence": "x"},
            "B": None,
            "C": {"score": 30, "confidence": 0.6, "evidence": "y"},
        }
        out = _normalize_extraction(SCORE_DIM, content)
        assert out["A"] == content["A"]
        assert out["B"] is None
        assert out["C"] == content["C"]

    def test_missing_subdim_filled_with_none(self):
        # LLM 漏返回某个 key → 兜底为 None
        content = {"A": {"score": 70, "confidence": 0.8, "evidence": "x"}}
        out = _normalize_extraction(SCORE_DIM, content)
        assert out["A"] == content["A"]
        assert out["B"] is None
        assert out["C"] is None

    def test_abstain_object_coerced_to_none(self):
        # LLM 输出 {"abstain": true} 之类的非标准结构 → None
        content = {
            "A": {"abstain": True},
            "B": {"score": 50},  # 缺 confidence 字段
            "C": {"score": 60, "confidence": 0.7},
        }
        out = _normalize_extraction(SCORE_DIM, content)
        assert out["A"] is None
        assert out["B"] is None
        assert out["C"] == content["C"]

    def test_non_dict_value_coerced_to_none(self):
        # LLM 输出标量 / 字符串 → None
        content = {"A": 50, "B": "no signal", "C": [1, 2]}
        out = _normalize_extraction(SCORE_DIM, content)
        assert out["A"] is None
        assert out["B"] is None
        assert out["C"] is None

    def test_key_value_dim_passthrough(self):
        # facts 等 key_value 维度不走归一化（结构形态不同）
        content = {"occupation": {"value": "engineer", "evidence": "x"}}
        out = _normalize_extraction(KEY_VALUE_DIM, content)
        assert out == content


# ── _extraction_health ─────────────────────────────────────────────────────

class TestExtractionHealth:
    def test_all_null_counts_correctly(self):
        content = {"A": None, "B": None, "C": None}
        h = _extraction_health(SCORE_DIM, content)
        assert h["total"] == 3
        assert h["null_count"] == 3
        assert h["low_conf_count"] == 0
        assert h["midpoint_hedge_count"] == 0

    def test_low_conf_counted_separately(self):
        # conf < 0.15 = low_conf 占位（旧 prompt 行为）
        content = {
            "A": {"score": 50, "confidence": 0.05},
            "B": {"score": 70, "confidence": 0.8},
            "C": None,
        }
        h = _extraction_health(SCORE_DIM, content)
        assert h["low_conf_count"] == 1
        assert h["null_count"] == 1

    def test_midpoint_hedge_detected(self):
        # score ∈ [45, 55] 且 conf ∈ [0.15, 0.5) = anchoring hedge
        content = {
            "A": {"score": 52, "confidence": 0.3},   # hedge
            "B": {"score": 48, "confidence": 0.4},   # hedge
            "C": {"score": 70, "confidence": 0.4},   # 真信号，不 hedge
        }
        h = _extraction_health(SCORE_DIM, content)
        assert h["midpoint_hedge_count"] == 2
        assert h["low_conf_count"] == 0
        assert h["null_count"] == 0

    def test_high_conf_midpoint_not_hedge(self):
        # 高 confidence 的中点是真"用户在该维度均衡"，不算 hedge
        content = {"A": {"score": 50, "confidence": 0.7}}
        h = _extraction_health({**SCORE_DIM, "sub_dimensions": [{"key": "A"}]}, content)
        assert h["midpoint_hedge_count"] == 0

    def test_key_value_dim_returns_empty(self):
        # 非 score 形态 → 不计算健康指标
        h = _extraction_health(KEY_VALUE_DIM, {"x": 1})
        assert h == {}
