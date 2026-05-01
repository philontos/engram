#!/usr/bin/env python3
"""Reset cognitive-service data during testing."""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_DIR = SCRIPT_DIR.parent


def resolve_default_db_path() -> Path:
    candidates = [
        SERVICE_DIR / "data" / "cognitive.db",
        SERVICE_DIR.parent / "data" / "cognitive" / "cognitive.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_default_vector_path() -> Path:
    candidates = [
        SERVICE_DIR / "data" / "vectors",
        SERVICE_DIR.parent / "data" / "cognitive" / "vectors",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


DB_PATH = Path(os.getenv("DB_PATH", str(resolve_default_db_path())))
VECTOR_INDEX_PATH = Path(os.getenv("VECTOR_INDEX_PATH", str(resolve_default_vector_path())))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def clear_sqlite_sequence(conn: sqlite3.Connection, tables: list[str]) -> None:
    for table in tables:
        conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))


def reset_all(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM backbone_activations")
    conn.execute("DELETE FROM backbone_edges")
    conn.execute("DELETE FROM backbone_nodes")
    conn.execute("DELETE FROM pipeline_traces")
    conn.execute("DELETE FROM profile_snapshots")
    conn.execute("DELETE FROM slice_features")
    conn.execute("DELETE FROM slices")
    conn.execute("DELETE FROM profile_dimensions")
    conn.execute("DELETE FROM entries")
    clear_sqlite_sequence(conn, [
        "backbone_activations", "backbone_edges", "backbone_nodes",
        "pipeline_traces", "profile_snapshots", "slice_features", "slices",
        "profile_dimensions", "entries",
    ])


def reset_derived(conn: sqlite3.Connection) -> None:
    """保留 entries，清除所有衍生数据（slice/profile/backbone）。"""
    conn.execute("DELETE FROM backbone_activations")
    conn.execute("DELETE FROM backbone_edges")
    conn.execute("DELETE FROM backbone_nodes")
    conn.execute("DELETE FROM pipeline_traces")
    conn.execute("DELETE FROM profile_snapshots")
    conn.execute("DELETE FROM slice_features")
    conn.execute("DELETE FROM slices")
    conn.execute("DELETE FROM profile_dimensions")
    clear_sqlite_sequence(conn, [
        "backbone_activations", "backbone_edges", "backbone_nodes",
        "pipeline_traces", "profile_snapshots", "slice_features", "slices",
        "profile_dimensions",
    ])


def reset_vectors() -> None:
    if VECTOR_INDEX_PATH.exists():
        shutil.rmtree(VECTOR_INDEX_PATH)
    VECTOR_INDEX_PATH.mkdir(parents=True, exist_ok=True)


def confirm(scope: str) -> None:
    print(f"About to reset scope: {scope}")
    print(f"DB: {DB_PATH}")
    reply = input("Type 'yes' to confirm: ").strip()
    if reply != "yes":
        raise SystemExit("Aborted.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset cognitive-service data by scope")
    parser.add_argument(
        "--scope",
        choices=["all", "derived", "vectors"],
        default="all",
        help="all=entries+derived+vectors, derived=facts+lens data only, vectors=vector index only",
    )
    parser.add_argument("--yes", action="store_true", help="Required safety flag.")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("Refusing to reset without --yes.")
    confirm(args.scope)

    if args.scope == "vectors":
        reset_vectors()
        print("Vectors reset.")
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        if args.scope == "all":
            reset_all(conn)
            reset_vectors()
        elif args.scope == "derived":
            reset_derived(conn)

    print(f"Reset complete for scope: {args.scope}")


if __name__ == "__main__":
    main()
