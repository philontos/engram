"""Manage backbone / dimension configurations from the CLI.

Usage examples:

  python -m scripts.manage_config backbone list
  python -m scripts.manage_config backbone add economics --name "Economics"
  python -m scripts.manage_config backbone disable history
  python -m scripts.manage_config backbone enable history
  python -m scripts.manage_config backbone remove history

  python -m scripts.manage_config dimension list
  python -m scripts.manage_config dimension add curiosity --name "Curiosity"
  python -m scripts.manage_config dimension disable curiosity
  python -m scripts.manage_config dimension remove curiosity

Notes:
  - `add`  : copies _template/ to <key>/ and patches the key + name fields in
             config.py. Other fields (color / focus_hints / extract.spt
             content / rubric.md) are left as template placeholders for you
             to edit before the next service restart.
  - `remove`: prompts for confirmation; deletes the entire directory.
             DB rows referencing the removed key are kept (orphan domain).
  - `disable / enable`: edits the `enabled` field in config.py — soft toggle
             without touching DB or files.
  - All operations are filesystem-only; restart the service to pick changes up.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "app" / "config"

KIND_DIRS = {
    "backbone":  ROOT / "backbones",
    "dimension": ROOT / "dimensions",
}

KIND_VARS = {
    "backbone":  "BACKBONE",
    "dimension": "DIMENSION",
}


# ── helpers ────────────────────────────────────────────────────────────────

def _root(kind: str) -> Path:
    if kind not in KIND_DIRS:
        sys.exit(f"unknown kind '{kind}', expected one of {sorted(KIND_DIRS)}")
    return KIND_DIRS[kind]


def _cfg_path(kind: str, key: str) -> Path:
    return _root(kind) / key / "config.py"


def _list_dirs(kind: str) -> list[Path]:
    base = _root(kind)
    if not base.exists():
        return []
    return sorted(
        d for d in base.iterdir()
        if d.is_dir() and not d.name.startswith("_") and not d.name.startswith(".")
    )


def _read_field(text: str, field: str) -> str | None:
    """Naive single-line string-literal field reader: matches `\"field\": \"value\"`."""
    m = re.search(rf'"{re.escape(field)}"\s*:\s*"([^"]*)"', text)
    return m.group(1) if m else None


def _read_bool_field(text: str, field: str) -> bool | None:
    m = re.search(rf'"{re.escape(field)}"\s*:\s*(True|False)\b', text)
    if not m:
        return None
    return m.group(1) == "True"


def _confirm(prompt: str) -> bool:
    try:
        ans = input(f"{prompt} [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans in ("y", "yes")


# ── subcommands ────────────────────────────────────────────────────────────

def cmd_list(kind: str) -> int:
    base = _root(kind)
    if not base.exists():
        print(f"(no {kind} directory: {base})")
        return 0
    rows: list[tuple[str, str, str]] = []  # (key, name, status)
    for d in _list_dirs(kind):
        cfg = d / "config.py"
        if not cfg.exists():
            rows.append((d.name, "—", "no config.py"))
            continue
        text = cfg.read_text(encoding="utf-8")
        name = _read_field(text, "name") or "—"
        enabled = _read_bool_field(text, "enabled")
        status = "disabled" if enabled is False else "enabled"
        rows.append((d.name, name, status))
    if not rows:
        print(f"(no {kind}s defined under {base})")
        return 0
    width_key = max(len("KEY"), max(len(r[0]) for r in rows))
    width_name = max(len("NAME"), max(len(r[1]) for r in rows))
    print(f"{'KEY':<{width_key}}  {'NAME':<{width_name}}  STATUS")
    print(f"{'-' * width_key}  {'-' * width_name}  {'-' * 8}")
    for k, n, s in rows:
        print(f"{k:<{width_key}}  {n:<{width_name}}  {s}")
    return 0


def cmd_add(kind: str, key: str, name: str | None) -> int:
    base = _root(kind)
    template = base / "_template"
    target = base / key
    if not template.exists():
        sys.exit(f"template missing: {template}")
    if target.exists():
        sys.exit(f"already exists: {target}")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
        sys.exit(f"key must be snake_case ASCII (got '{key}')")
    display_name = name or key.replace("_", " ").title()

    shutil.copytree(template, target)
    cfg_file = target / "config.py"
    text = cfg_file.read_text(encoding="utf-8")

    # Replace the `"key": "..."` line.
    text = re.sub(r'("key"\s*:\s*)"[^"]*"', rf'\1"{key}"', text, count=1)

    # Replace or insert the `"name": "..."` line.
    if re.search(r'"name"\s*:\s*"[^"]*"', text):
        text = re.sub(r'("name"\s*:\s*)"[^"]*"', rf'\1"{display_name}"', text, count=1)
    else:
        # Insert a name line right after the key line.
        text = re.sub(
            r'("key"\s*:\s*"[^"]*",?\s*\n)',
            rf'\1    "name":        "{display_name}",\n',
            text,
            count=1,
        )

    cfg_file.write_text(text, encoding="utf-8")

    print(f"created {target}")
    print(f"  key  = {key}")
    print(f"  name = {display_name}")
    print()
    print("Next steps:")
    print(f"  1. Edit  {cfg_file}")
    if kind == "backbone":
        print(f"  2. Edit  {target / 'node_extract.spt'}  (replace [DOMAIN NAME] placeholders)")
    else:
        print(f"  2. Edit  {target / 'extract.spt'}  and  {target / 'rubric.md'}")
    print("  3. Restart the cognitive-service for the new config to take effect.")
    return 0


def cmd_remove(kind: str, key: str, force: bool) -> int:
    target = _root(kind) / key
    if not target.exists():
        sys.exit(f"not found: {target}")
    if key.startswith("_"):
        sys.exit(f"refusing to remove reserved directory '{key}'")
    print(f"About to delete: {target}")
    if not force:
        if not _confirm(f"Permanently delete {kind} '{key}'?"):
            print("aborted.")
            return 1
        if not _confirm(f"Are you absolutely sure? Type 'y' again to confirm"):
            print("aborted.")
            return 1
    shutil.rmtree(target)
    print(f"removed {target}")
    if kind == "backbone":
        print("Note: existing nodes in DB with this domain are kept (orphan).")
        print("      Restart the service; orphan_domains will surface in /ui/api/backbones.")
    else:
        print("Note: profile_dimensions / slice_features rows for this dimension are kept.")
        print("      Restart the service for the loader to drop it from the active list.")
    return 0


def _set_enabled(cfg_file: Path, value: bool) -> bool:
    """Write `"enabled": True|False` into config.py. Returns True if changed."""
    text = cfg_file.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'("enabled"\s*:\s*)(True|False)\b',
        rf'\1{value}',
        text,
        count=1,
    )
    if n == 0:
        # No enabled field — insert one after the key line.
        new_text, n = re.subn(
            r'("key"\s*:\s*"[^"]*",?\s*\n)',
            rf'\1    "enabled":     {value},\n',
            text,
            count=1,
        )
    if n == 0:
        return False
    if new_text == text:
        return False
    cfg_file.write_text(new_text, encoding="utf-8")
    return True


def cmd_toggle(kind: str, key: str, enable: bool) -> int:
    cfg_file = _cfg_path(kind, key)
    if not cfg_file.exists():
        sys.exit(f"not found: {cfg_file}")
    changed = _set_enabled(cfg_file, enable)
    state = "enabled" if enable else "disabled"
    if changed:
        print(f"{kind} '{key}' {state}.")
        print("Restart the cognitive-service for the change to take effect.")
        return 0
    print(f"{kind} '{key}' is already {state} (no change).")
    return 0


# ── arg parsing ────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="manage_config",
                                description="Manage backbone / dimension config directories.")
    sub = p.add_subparsers(dest="kind", required=True)

    for kind in ("backbone", "dimension"):
        kp = sub.add_parser(kind, help=f"manage {kind}s")
        ksub = kp.add_subparsers(dest="action", required=True)

        ksub.add_parser("list", help=f"list all {kind}s and their status")

        a = ksub.add_parser("add", help=f"create a new {kind} from template")
        a.add_argument("key", help="snake_case key (also used as DB enum value)")
        a.add_argument("--name", help="human-readable display name (defaults to key)")

        r = ksub.add_parser("remove", help=f"delete a {kind} directory (with confirmation)")
        r.add_argument("key")
        r.add_argument("--force", action="store_true", help="skip confirmation prompts")

        ksub.add_parser("enable",  help=f"set enabled=True for a {kind}").add_argument("key")
        ksub.add_parser("disable", help=f"set enabled=False for a {kind}").add_argument("key")

    args = p.parse_args(argv)

    if args.action == "list":
        return cmd_list(args.kind)
    if args.action == "add":
        return cmd_add(args.kind, args.key, args.name)
    if args.action == "remove":
        return cmd_remove(args.kind, args.key, args.force)
    if args.action == "enable":
        return cmd_toggle(args.kind, args.key, True)
    if args.action == "disable":
        return cmd_toggle(args.kind, args.key, False)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
