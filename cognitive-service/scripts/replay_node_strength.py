"""Algorithm-only replay: rebuild backbone_nodes.strength from backbone_activations,
without invoking any LLM.

Use when you change `_update_node_strength` (e.g. switching to DWAS) or
`NODE_STRENGTH` config and want to see the new strength distribution on existing
data without paying LLM cost. Each activation row carries the original
`profile_match_score` (= new_conf at activation time), so we can replay the
formula in time order.

CLI:
    python -m scripts.replay_node_strength
    python -m scripts.replay_node_strength --domain psychology
    python -m scripts.replay_node_strength --histogram

Library use:
    from scripts.replay_node_strength import replay
    stats = replay(domain=None)
"""

import argparse
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config.graph_rules import NODE_STRENGTH
from app.lib.db import get_conn


@dataclass
class ReplayStats:
    nodes_touched:        int
    activations_replayed: int
    hist_buckets:         dict   # {"0-0.5": n, "0.5-1": n, ...}
    max_strength:         float
    median_strength:      float


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _histogram(values: list[float]) -> dict:
    """Coarse bucketing for "what does the new distribution look like" verification."""
    edges = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]
    labels = ["<0.5", "0.5-1", "1-1.5", "1.5-2", "2-3", "3-5", ">=5"]
    buckets = {l: 0 for l in labels}
    for v in values:
        placed = False
        for i, edge in enumerate(edges):
            if v < edge:
                buckets[labels[i]] += 1
                placed = True
                break
        if not placed:
            buckets[labels[-1]] += 1
    return buckets


def replay(domain: str | None = None) -> ReplayStats:
    """Wipe strength + hit_count + last_hit_at on (optionally domain-scoped) nodes,
    then replay all activations in chronological order under the current formula.

    Args:
        domain: if set, only replay nodes within this domain.

    Returns: stats summary.
    """
    lam = NODE_STRENGTH["lambda"]
    cap = NODE_STRENGTH.get("cap")

    # 1. Pull node ids in scope
    with get_conn() as conn:
        if domain:
            node_rows = conn.execute(
                "SELECT id FROM backbone_nodes WHERE domain = ?",
                (domain,),
            ).fetchall()
        else:
            node_rows = conn.execute("SELECT id FROM backbone_nodes").fetchall()
    node_ids = [r["id"] for r in node_rows]
    if not node_ids:
        return ReplayStats(0, 0, {}, 0.0, 0.0)

    placeholders = ",".join(["?"] * len(node_ids))

    # 2. Reset strength / hit_count / last_hit_at on those nodes
    with get_conn() as conn:
        conn.execute(
            f"UPDATE backbone_nodes SET strength = 0.0, hit_count = 0, last_hit_at = NULL "
            f"WHERE id IN ({placeholders})",
            node_ids,
        )

    # 3. Pull all activations for these nodes in chronological order
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT node_id, profile_match_score AS new_conf, created_at
                FROM backbone_activations
                WHERE node_id IN ({placeholders})
                ORDER BY created_at ASC, id ASC""",
            node_ids,
        ).fetchall()

    # 4. Walk activations: for each, decay the in-memory state then add new_conf
    state: dict[int, dict] = {nid: {"strength": 0.0, "hits": 0, "last_dt": None} for nid in node_ids}
    n_acts = 0
    for r in rows:
        nid = r["node_id"]
        st = state.get(nid)
        if st is None:
            continue
        new_conf = float(r["new_conf"] or 0.0)
        dt = _parse_dt(r["created_at"])
        if st["last_dt"] is not None and dt is not None:
            days = max(0, (dt - st["last_dt"]).days)
            decayed = st["strength"] * math.exp(-lam * days)
        else:
            decayed = st["strength"]
        new_strength = decayed + new_conf
        if cap is not None:
            new_strength = min(new_strength, float(cap))
        st["strength"] = new_strength
        st["hits"] += 1
        st["last_dt"] = dt
        n_acts += 1

    # 5. Persist back
    with get_conn() as conn:
        for nid, st in state.items():
            if st["hits"] == 0:
                continue
            last_str = st["last_dt"].isoformat() if st["last_dt"] else None
            conn.execute(
                "UPDATE backbone_nodes SET strength = ?, hit_count = ?, last_hit_at = ? WHERE id = ?",
                (round(st["strength"], 4), st["hits"], last_str, nid),
            )

    # 6. Build distribution stats from updated rows
    final_strengths = sorted([st["strength"] for st in state.values() if st["hits"] > 0])
    if final_strengths:
        median = final_strengths[len(final_strengths) // 2]
        max_v = final_strengths[-1]
    else:
        median = 0.0
        max_v = 0.0

    return ReplayStats(
        nodes_touched=len([s for s in state.values() if s["hits"] > 0]),
        activations_replayed=n_acts,
        hist_buckets=_histogram(final_strengths),
        max_strength=round(max_v, 3),
        median_strength=round(median, 3),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0] if __doc__ else "")
    ap.add_argument("--domain", help="Only replay nodes in this domain (e.g. psychology)")
    ap.add_argument("--histogram", action="store_true", help="Print strength distribution buckets")
    args = ap.parse_args()

    stats = replay(domain=args.domain)
    print(f"nodes_touched        : {stats.nodes_touched}")
    print(f"activations_replayed : {stats.activations_replayed}")
    print(f"max_strength         : {stats.max_strength}")
    print(f"median_strength      : {stats.median_strength}")
    if args.histogram and stats.hist_buckets:
        print("\ndistribution:")
        for bucket, n in stats.hist_buckets.items():
            print(f"  {bucket:>8s}  {n}")


if __name__ == "__main__":
    main()
