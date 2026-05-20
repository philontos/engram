"""数据库 schema 完整性与迁移测试。

使用临时文件数据库（via conftest.db fixture），不触碰生产数据。
目标：schema 改动或新增迁移后，这里能第一时间发现遗漏。
"""

import json
import pytest


def _tables(db) -> set[str]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {r["name"] for r in rows}


def _columns(db, table: str) -> set[str]:
    with db.get_conn() as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _indexes(db, table: str) -> set[str]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        ).fetchall()
    return {r["name"] for r in rows}


# ── 表存在性 ─────────────────────────────────────────────────────────────────

def test_all_core_tables_exist(db):
    expected = {
        "entries", "slices", "slice_features", "profile_dimensions",
        "backbone_nodes", "backbone_edges", "backbone_activations",
        "profile_snapshots", "pipeline_traces", "query_logs",
        "memos", "capture_buffer",
    }
    assert expected <= _tables(db)


# ── 迁移列存在性（存量迁移）────────────────────────────────────────────────────

def test_pipeline_traces_has_rollback_json(db):
    assert "rollback_json" in _columns(db, "pipeline_traces")


def test_query_logs_migration_columns(db):
    cols = _columns(db, "query_logs")
    assert "session_id" in cols
    assert "turns_json" in cols
    assert "updated_at" in cols


# ── 关键列结构 ────────────────────────────────────────────────────────────────

def test_backbone_nodes_columns(db):
    cols = _columns(db, "backbone_nodes")
    for c in ["id", "domain", "label", "node_type", "origin", "strength",
              "hit_count", "source_entry_ids", "embedding_json"]:
        assert c in cols, f"missing column: {c}"


def test_backbone_edges_columns(db):
    cols = _columns(db, "backbone_edges")
    for c in ["id", "from_node_id", "to_node_id", "relation_type",
              "edge_source", "weight", "confidence", "source_entry_ids"]:
        assert c in cols, f"missing column: {c}"


# ── CHECK 约束 ────────────────────────────────────────────────────────────────

def test_backbone_nodes_origin_check(db):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO entries (type, raw) VALUES ('test', 'x')"
        )
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO backbone_nodes (domain, node_type, label, origin, strength) "
                "VALUES ('d', 't', 'l', 'invalid_origin', 0.5)"
            )


def test_backbone_edges_source_check(db):
    with db.get_conn() as conn:
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO backbone_edges "
                "(from_node_id, to_node_id, relation_type, edge_source, weight, confidence) "
                "VALUES (1, 2, '支撑', 'invalid_source', 0.5, 0.5)"
            )


# ── UNIQUE 约束 ───────────────────────────────────────────────────────────────

def test_backbone_nodes_domain_label_unique(db):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO backbone_nodes (domain, node_type, label, origin, strength) "
            "VALUES ('tech', '概念', '机器学习', 'internal', 0.5)"
        )
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO backbone_nodes (domain, node_type, label, origin, strength) "
                "VALUES ('tech', '方法', '机器学习', 'internal', 0.3)"
            )


def test_profile_dimensions_dimension_unique(db):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO profile_dimensions (dimension, content_json, sample_count) "
            "VALUES ('ocean', '{}', 1)"
        )
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO profile_dimensions (dimension, content_json, sample_count) "
                "VALUES ('ocean', '{}', 2)"
            )


# ── 基础 CRUD ─────────────────────────────────────────────────────────────────

def test_entry_insert_and_read(db):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO entries (type, raw, processing_status) VALUES (?, ?, ?)",
            ("thought", "今天学了点新东西", "captured"),
        )
        row = conn.execute(
            "SELECT * FROM entries WHERE type='thought'"
        ).fetchone()
    assert row["raw"] == "今天学了点新东西"
    assert row["processing_status"] == "captured"
    assert row["importance"] == 3  # DEFAULT 值


def test_source_entry_ids_default_empty_array(db):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO backbone_nodes (domain, node_type, label, origin, strength) "
            "VALUES ('tech', '概念', '测试节点', 'internal', 0.5)"
        )
        row = conn.execute(
            "SELECT source_entry_ids FROM backbone_nodes WHERE label='测试节点'"
        ).fetchone()
    assert json.loads(row["source_entry_ids"]) == []


# ── 索引存在性（关键查询路径）────────────────────────────────────────────────────

def test_key_indexes_exist(db):
    assert "idx_backbone_nodes_domain" in _indexes(db, "backbone_nodes")
    assert "idx_backbone_nodes_strength" in _indexes(db, "backbone_nodes")
    assert "idx_backbone_edges_from" in _indexes(db, "backbone_edges")
    assert "idx_slice_features_dimension" in _indexes(db, "slice_features")


def test_contacts_schema(db):
    with db.get_conn() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(contacts)")}
        assert cols == {
            "id", "display_name", "aliases_json",
            "status", "merged_into_id",
            "relationship_kind", "kind_locked", "field_locks_json",
            "active_status", "intimacy_score",
            "first_seen_entry_id", "last_seen_entry_id", "last_interaction_at",
            "context_summary", "metadata_json",
            "created_at", "updated_at",
        }
        ev_cols = {row[1] for row in conn.execute("PRAGMA table_info(contact_evidence)")}
        assert ev_cols == {
            "id", "contact_id", "entry_id",
            "mention_text", "excerpt", "confidence",
            "suggested_kind", "ambiguous_candidate_ids_json",
            "interaction_observed", "created_at",
        }
        # 索引存在
        idx = {row[1] for row in conn.execute("PRAGMA index_list(contacts)")}
        assert {"idx_contacts_status", "idx_contacts_display_name",
                "idx_contacts_last_interaction", "idx_contacts_first_seen_entry"} <= idx
        ev_idx = {row[1] for row in conn.execute("PRAGMA index_list(contact_evidence)")}
        assert {"idx_contact_evidence_contact", "idx_contact_evidence_entry"} <= ev_idx
