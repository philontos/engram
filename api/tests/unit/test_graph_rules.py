"""graph_rules 常量完整性检查。

这些测试不验证业务逻辑，只确保配置文件结构完整、数值在合理范围内。
当你修改参数时，如果某个值超出预期范围，这里会告诉你。
"""

import pytest
from app.config.graph_rules import (
    NODE_TYPES, RELATION_TYPES, NODE_ORIGINS, EDGE_SOURCES,
    NODE_STRENGTH, EDGE_WEIGHT, EDGE_DECAY, ALGO_EDGE,
    OPPOSITION_PROPAGATION, PROFILE_MERGE, RETRIEVAL,
    DEDUP_THRESHOLD, CROSS_DOMAIN_SIM_THRESHOLD, SOURCE_ENTRIES_MAX,
)


def test_node_types_non_empty():
    assert len(NODE_TYPES) > 0
    assert all(isinstance(t, str) for t in NODE_TYPES)


def test_relation_types_non_empty():
    assert len(RELATION_TYPES) > 0


def test_origins_and_sources():
    assert "internal" in NODE_ORIGINS
    assert "external" in NODE_ORIGINS
    assert "llm" in EDGE_SOURCES
    assert "algo" in EDGE_SOURCES


def test_node_strength_lambda_range():
    lam = NODE_STRENGTH["lambda"]
    # 合理范围：半衰期在 10~1000 天之间 (ln2/lam)
    assert 0.0007 < lam < 0.07


def test_edge_decay_lambda_slower_than_node():
    # 边的衰减应比节点慢（边持久性更高）
    assert EDGE_DECAY["lambda"] < NODE_STRENGTH["lambda"]


def test_edge_decay_floor_range():
    floor = EDGE_DECAY["floor"]
    assert 0.0 < floor < 1.0


def test_edge_weight_deltas_ordered():
    assert 0 < EDGE_WEIGHT["min_delta"] < EDGE_WEIGHT["base_delta"] <= 1.0


def test_dedup_threshold_high():
    # 去重阈值应足够高，避免误合并不同节点
    assert DEDUP_THRESHOLD > 0.85


def test_cross_domain_threshold_higher_than_intra():
    assert CROSS_DOMAIN_SIM_THRESHOLD > ALGO_EDGE["intra_domain_sim_threshold"]


def test_source_entries_max_positive():
    assert SOURCE_ENTRIES_MAX > 0


def test_retrieval_params_positive():
    assert RETRIEVAL["rough_top_k"] > 0
    assert RETRIEVAL["max_edges_per_node"] > 0


def test_opposition_propagation_weight_cap_low():
    # 传染推出的对立边权重应低于关联边累加上限，避免传染边压制显式边
    assert OPPOSITION_PROPAGATION["weight_cap"] < ALGO_EDGE["association_weight_cap_max"]
    assert 0.0 < OPPOSITION_PROPAGATION["weight_cap"] < 1.0
