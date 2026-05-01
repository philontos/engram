"""动态加载 dimensions 和 backbones 的配置与 prompt 模板。"""

import importlib.util
from pathlib import Path
from typing import Any

_CONFIG_ROOT = Path(__file__).resolve().parent.parent / "config"
_DIMENSIONS_ROOT = _CONFIG_ROOT / "dimensions"
_BACKBONES_ROOT = _CONFIG_ROOT / "backbones"
_ENTRY_ANALYZERS_ROOT = _CONFIG_ROOT / "entry_analyzers"


def _load_py(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("_cfg", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _load_dimensions() -> tuple[list[dict], dict[str, dict]]:
    """Returns (pipeline_dims, dim_map).

    pipeline_dims: dimensions that participate in the slice pipeline.
    dim_map: all dimensions keyed by 'key'.
    """
    dims = []
    for d in sorted(_DIMENSIONS_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        cfg_file = d / "config.py"
        if not cfg_file.exists():
            continue
        mod = _load_py(cfg_file)
        cfg = dict(mod.DIMENSION)
        cfg["_dir"] = d
        cfg["_prompt"] = _read(d / cfg.get("prompt_template", "extract.spt"))
        cfg["_rubric"] = _read(d / "rubric.md")
        dims.append(cfg)
    return dims, {d["key"]: d for d in dims}


def _load_entry_analyzers() -> tuple[list[dict], dict[str, dict]]:
    """Returns (analyzers, analyzer_map).

    Entry analyzers annotate individual entries (e.g. situation context).
    They do not accumulate into the user profile.
    """
    analyzers = []
    for d in sorted(_ENTRY_ANALYZERS_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        cfg_file = d / "config.py"
        if not cfg_file.exists():
            continue
        mod = _load_py(cfg_file)
        cfg = dict(mod.ANALYZER)
        cfg["_dir"] = d
        cfg["_prompt"] = _read(d / cfg.get("prompt_template", "extract.spt"))
        analyzers.append(cfg)
    return analyzers, {a["key"]: a for a in analyzers}


def _load_backbones() -> list[dict]:
    bbs = []
    for d in sorted(_BACKBONES_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        cfg_file = d / "config.py"
        if not cfg_file.exists():
            continue
        mod = _load_py(cfg_file)
        cfg = dict(mod.BACKBONE)
        cfg["_dir"] = d
        # 内源 prompt：每域独立（承载域视角与节点类型说明）
        cfg["_internal_node_prompt"] = _read(d / "node_extract.spt")
        # focus_hints 拼成字符串供外源 prompt 注入
        hints = cfg.get("focus_hints") or []
        cfg["_focus_hints_text"] = "\n".join(f"- {h}" for h in hints) if hints else "（无额外指引）"
        bbs.append(cfg)
    return bbs


def load_shared_backbone_prompt(name: str) -> str:
    return _read(_BACKBONES_ROOT / "_shared" / name)


# Module-level cache — loaded once at import time
DIMENSIONS, DIMENSION_MAP           = _load_dimensions()
BACKBONES:  list[dict]              = _load_backbones()
BACKBONE_MAP:  dict[str, dict]      = {b["key"]: b for b in BACKBONES}
ENTRY_ANALYZERS, ENTRY_ANALYZER_MAP = _load_entry_analyzers()
