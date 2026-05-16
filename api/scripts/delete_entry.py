#!/usr/bin/env python3
"""Delete one or more entries and all their derived data.

Examples:
  python3 scripts/delete_entry.py --entry-id 12 --yes
  python3 scripts/delete_entry.py --entry-id 12 --entry-id 13 --yes
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_DIR = SCRIPT_DIR.parent


def resolve_default_db_path() -> Path:
    candidates = [
        SERVICE_DIR / "data" / "cognitive.db",
        SERVICE_DIR.parent / "data" / "cognitive" / "cognitive.db",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


DB_PATH = Path(os.getenv("DB_PATH", str(resolve_default_db_path())))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def mark_vector_deleted(entry_id: int) -> None:
    try:
        import sys
        sys.path.insert(0, str(SERVICE_DIR))
        from app.lib.vector_store import get_store
        store = get_store()
        if store.index:
            store.index.mark_deleted(entry_id)
            store.index.save_index(store.index_path)
    except Exception as exc:
        print(f"[warn] vector mark_deleted failed for {entry_id}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry-id", type=int, action="append", required=True)
    parser.add_argument("--yes", action="store_true", help="Required safety flag")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("Pass --yes to confirm.")

    entry_ids = sorted(set(args.entry_id))
    print(f"DB: {DB_PATH}")
    print(f"Deleting entry IDs: {entry_ids}")
    reply = input("Type 'yes' to confirm: ").strip()
    if reply != "yes":
        raise SystemExit("Aborted.")

    placeholders = ",".join("?" for _ in entry_ids)

    with get_conn() as conn:
        existing = {r["id"] for r in conn.execute(f"SELECT id FROM entries WHERE id IN ({placeholders})", entry_ids).fetchall()}
        if not existing:
            raise SystemExit("No matching entries found.")

        ep = list(existing)
        ph = ",".join("?" for _ in ep)

        # backbone activations for these entries
        n_act = conn.execute(f"DELETE FROM backbone_activations WHERE entry_id IN ({ph})", ep).rowcount

        # slices + slice features
        slice_ids = [r["id"] for r in conn.execute(f"SELECT id FROM slices WHERE entry_id IN ({ph})", ep).fetchall()]
        n_sf = 0
        if slice_ids:
            sph = ",".join("?" for _ in slice_ids)
            n_sf = conn.execute(f"DELETE FROM slice_features WHERE slice_id IN ({sph})", slice_ids).rowcount
        n_sl = conn.execute(f"DELETE FROM slices WHERE entry_id IN ({ph})", ep).rowcount

        # profile snapshots + pipeline traces
        n_snap = conn.execute(f"DELETE FROM profile_snapshots WHERE entry_id IN ({ph})", ep).rowcount
        n_trace = conn.execute(f"DELETE FROM pipeline_traces WHERE entry_id IN ({ph})", ep).rowcount

        n_ent = conn.execute(f"DELETE FROM entries WHERE id IN ({ph})", ep).rowcount

    for eid in existing:
        mark_vector_deleted(eid)

    print(f"Done. entries={n_ent} slices={n_sl} slice_features={n_sf} activations={n_act} snapshots={n_snap} traces={n_trace}")
    print("Note: backbone nodes/edges are NOT deleted (they may be shared across entries).")


if __name__ == "__main__":
    main()
