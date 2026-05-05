"""Algorithm-only replay: rebuild profile_dimensions and profile_snapshots
from existing slice_features, without invoking any LLM.

Use when you change the merge formula (`profile_merge.py`) or its parameters
(`graph_rules.PROFILE_MERGE`) and want to see the new curves on existing data
without paying LLM cost. Typical run: <1s for hundreds of entries.

CLI:
    python -m scripts.replay_profile_merge
    python -m scripts.replay_profile_merge --dimension ocean
    python -m scripts.replay_profile_merge --limit 50

Library use (e.g. from a REST endpoint):
    from scripts.replay_profile_merge import replay
    stats = replay(dimension=None, limit=None)
"""

import argparse
import json
from dataclasses import dataclass

from app.lib.db import get_conn
from app.lib.profile_merge import merge_dimension


@dataclass
class ReplayStats:
    entries_processed: int
    slice_features_replayed: int
    dimensions_touched: int
    snapshots_written: int


def _save_snapshot(entry_id: int) -> None:
    """Same as routes/process_entry._save_profile_snapshot, copied here to keep
    this script importable without web-stack dependencies."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dimension, content_json FROM profile_dimensions"
        ).fetchall()
    snapshot = {r["dimension"]: json.loads(r["content_json"]) for r in rows}
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO profile_snapshots (entry_id, snapshot_json, created_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (entry_id, json.dumps(snapshot, ensure_ascii=False)),
        )


def replay(dimension: str | None = None, limit: int | None = None) -> ReplayStats:
    """Wipe profile_dimensions + profile_snapshots, then re-merge from slice_features.

    Args:
        dimension: if given, only replay this dimension (others unchanged in DB).
        limit: if given, only replay the first N entries (oldest first).

    Returns: stats summary.
    """
    # 1. Snapshot the entries we'll process (chronological, optionally limited)
    with get_conn() as conn:
        if limit is not None:
            entry_rows = conn.execute(
                "SELECT id FROM entries ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            entry_rows = conn.execute(
                "SELECT id FROM entries ORDER BY created_at ASC"
            ).fetchall()
    entry_ids = [r["id"] for r in entry_rows]

    # 2. Wipe derived state (only the dimensions we'll touch, to be safe)
    with get_conn() as conn:
        if dimension:
            conn.execute("DELETE FROM profile_dimensions WHERE dimension = ?", (dimension,))
        else:
            conn.execute("DELETE FROM profile_dimensions")
        # Snapshots are entry-scoped, always wipe what we'll replay
        if entry_ids:
            placeholders = ",".join(["?"] * len(entry_ids))
            conn.execute(
                f"DELETE FROM profile_snapshots WHERE entry_id IN ({placeholders})",
                entry_ids,
            )

    # 3. Walk entries in chronological order, replay each entry's slice_features
    sf_count = 0
    dims_touched: set[str] = set()
    snaps = 0
    for entry_id in entry_ids:
        with get_conn() as conn:
            if dimension:
                feats = conn.execute(
                    """SELECT sf.dimension, sf.content_json
                       FROM slice_features sf
                       JOIN slices s ON s.id = sf.slice_id
                       WHERE s.entry_id = ? AND sf.dimension = ?""",
                    (entry_id, dimension),
                ).fetchall()
            else:
                feats = conn.execute(
                    """SELECT sf.dimension, sf.content_json
                       FROM slice_features sf
                       JOIN slices s ON s.id = sf.slice_id
                       WHERE s.entry_id = ?""",
                    (entry_id,),
                ).fetchall()

        for f in feats:
            try:
                content = json.loads(f["content_json"])
            except Exception:
                continue
            merge_dimension(f["dimension"], content, entry_id=entry_id)
            sf_count += 1
            dims_touched.add(f["dimension"])

        if feats:
            _save_snapshot(entry_id)
            snaps += 1

    return ReplayStats(
        entries_processed=len(entry_ids),
        slice_features_replayed=sf_count,
        dimensions_touched=len(dims_touched),
        snapshots_written=snaps,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0] if __doc__ else "")
    ap.add_argument("--dimension", help="Only replay this dimension (e.g. ocean)")
    ap.add_argument("--limit", type=int, help="Only replay the first N entries (oldest first)")
    args = ap.parse_args()

    stats = replay(dimension=args.dimension, limit=args.limit)
    print(f"entries_processed       : {stats.entries_processed}")
    print(f"slice_features_replayed : {stats.slice_features_replayed}")
    print(f"dimensions_touched      : {stats.dimensions_touched}")
    print(f"snapshots_written       : {stats.snapshots_written}")


if __name__ == "__main__":
    main()
