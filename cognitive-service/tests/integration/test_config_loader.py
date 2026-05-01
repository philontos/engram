"""dimension / backbone 热插拔（冷插拔）发现逻辑测试。

核心问题：新增一个符合约定的目录，_load_* 函数能否正确发现它？
不符合约定的目录（无 config.py、_ 前缀）能否被正确跳过？

注意：DIMENSIONS / BACKBONES 是模块级缓存，测试直接调用 _load_* 函数
并 monkeypatch 根目录，而不依赖模块缓存。
"""

import pytest
from pathlib import Path
import app.lib.config_loader as cl


# ── 当前配置完整性 ─────────────────────────────────────────────────────────────

def test_dimensions_loaded():
    assert len(cl.DIMENSIONS) > 0
    assert "situation" not in cl.DIMENSION_MAP  # situation is an entry analyzer, not a dimension


def test_backbones_loaded():
    assert len(cl.BACKBONES) > 0


def test_entry_analyzers_loaded():
    assert "situation" in cl.ENTRY_ANALYZER_MAP
    sit = cl.ENTRY_ANALYZER_MAP["situation"]
    assert sit["_prompt"]  # prompt template must be loaded
    assert sit.get("target_field") == "situation_json"


def test_dimension_map_keyed_by_key():
    for key, dim in cl.DIMENSION_MAP.items():
        assert dim["key"] == key


def test_backbone_map_keyed_by_key():
    for key, bb in cl.BACKBONE_MAP.items():
        assert bb["key"] == key


def test_all_dimensions_have_required_fields():
    for dim in cl.DIMENSIONS:
        assert "key" in dim, f"dimension missing 'key': {dim}"
        assert "name" in dim, f"dimension missing 'name': {dim.get('key')}"
        assert "enabled" in dim


def test_all_backbones_have_required_fields():
    for bb in cl.BACKBONES:
        assert "key" in bb, f"backbone missing 'key': {bb}"
        assert "description" in bb


def test_template_dirs_not_loaded():
    # _template 目录应被跳过
    assert "_template" not in cl.DIMENSION_MAP
    assert "_template" not in cl.BACKBONE_MAP


# ── 动态发现：新增 backbone ───────────────────────────────────────────────────

def test_new_valid_backbone_discovered(tmp_path, monkeypatch):
    bb_dir = tmp_path / "my_new_domain"
    bb_dir.mkdir()
    (bb_dir / "config.py").write_text(
        'BACKBONE = {"key": "my_new_domain", "description": "Test domain", "focus_hints": []}\n'
    )
    monkeypatch.setattr(cl, "_BACKBONES_ROOT", tmp_path)

    result = cl._load_backbones()
    keys = [b["key"] for b in result]
    assert "my_new_domain" in keys


def test_new_valid_dimension_discovered(tmp_path, monkeypatch):
    dim_dir = tmp_path / "my_dim"
    dim_dir.mkdir()
    (dim_dir / "config.py").write_text(
        'DIMENSION = {"key": "my_dim", "name": "My Dim", "enabled": True, '
        '"merge": True, "prompt_template": "extract.spt", '
        '"summary_format": "scores", "summary_label": "MyDim", "sort_by_score": True}\n'
    )
    monkeypatch.setattr(cl, "_DIMENSIONS_ROOT", tmp_path)

    pipeline_dims, all_map = cl._load_dimensions()
    assert "my_dim" in [d["key"] for d in pipeline_dims]
    assert "my_dim" in all_map



# ── 约定违反：应被静默跳过 ──────────────────────────────────────────────────────

def test_dir_without_config_py_skipped(tmp_path, monkeypatch):
    (tmp_path / "no_config").mkdir()
    monkeypatch.setattr(cl, "_BACKBONES_ROOT", tmp_path)

    result = cl._load_backbones()
    assert result == []


def test_underscore_prefix_dir_skipped(tmp_path, monkeypatch):
    bb_dir = tmp_path / "_internal"
    bb_dir.mkdir()
    (bb_dir / "config.py").write_text(
        'BACKBONE = {"key": "_internal", "description": "should skip"}\n'
    )
    monkeypatch.setattr(cl, "_BACKBONES_ROOT", tmp_path)

    result = cl._load_backbones()
    assert result == []


def test_dot_prefix_dir_skipped(tmp_path, monkeypatch):
    bb_dir = tmp_path / ".hidden"
    bb_dir.mkdir()
    (bb_dir / "config.py").write_text(
        'BACKBONE = {"key": "hidden", "description": "should skip"}\n'
    )
    monkeypatch.setattr(cl, "_BACKBONES_ROOT", tmp_path)

    result = cl._load_backbones()
    assert result == []


def test_multiple_backbones_sorted_by_name(tmp_path, monkeypatch):
    for name in ["zzz_domain", "aaa_domain", "mmm_domain"]:
        d = tmp_path / name
        d.mkdir()
        (d / "config.py").write_text(
            f'BACKBONE = {{"key": "{name}", "description": "test"}}\n'
        )
    monkeypatch.setattr(cl, "_BACKBONES_ROOT", tmp_path)

    result = cl._load_backbones()
    keys = [b["key"] for b in result]
    assert keys == sorted(keys)  # _load_backbones 使用 sorted() 遍历


# ── prompt 模板加载 ────────────────────────────────────────────────────────────

def test_backbone_node_prompt_loaded_if_exists(tmp_path, monkeypatch):
    bb_dir = tmp_path / "with_prompt"
    bb_dir.mkdir()
    (bb_dir / "config.py").write_text(
        'BACKBONE = {"key": "with_prompt", "description": "test"}\n'
    )
    (bb_dir / "node_extract.spt").write_text("你是一个节点提取助手")
    monkeypatch.setattr(cl, "_BACKBONES_ROOT", tmp_path)

    result = cl._load_backbones()
    assert result[0]["_internal_node_prompt"] == "你是一个节点提取助手"


def test_backbone_empty_prompt_if_spt_missing(tmp_path, monkeypatch):
    bb_dir = tmp_path / "no_prompt"
    bb_dir.mkdir()
    (bb_dir / "config.py").write_text(
        'BACKBONE = {"key": "no_prompt", "description": "test"}\n'
    )
    monkeypatch.setattr(cl, "_BACKBONES_ROOT", tmp_path)

    result = cl._load_backbones()
    assert result[0]["_internal_node_prompt"] == ""
