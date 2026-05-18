#!/usr/bin/env python3
"""Inspect Engram API SQLite data.

Examples:
  python3 scripts/inspect_memory.py overview
  python3 scripts/inspect_memory.py entries --limit 20
  python3 scripts/inspect_memory.py entries --entry-id 5
  python3 scripts/inspect_memory.py slice --entry-id 5
  python3 scripts/inspect_memory.py profile
  python3 scripts/inspect_memory.py nodes --domain psychology --limit 20
  python3 scripts/inspect_memory.py edges --limit 20
  python3 scripts/inspect_memory.py graph --domain business
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


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


def pj(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def kv(data: dict) -> None:
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            print(f"{k}: {json.dumps(v, ensure_ascii=False, indent=2)}")
        else:
            print(f"{k}: {v}")


# ---------------------------------------------------------------------------

def cmd_overview(_args: argparse.Namespace) -> None:
    with get_conn() as conn:
        tables = ["entries", "slices", "slice_features", "profile_dimensions",
                  "backbone_nodes", "backbone_edges", "backbone_activations"]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

        status_rows = conn.execute(
            "SELECT IFNULL(processing_status,'captured') AS s, COUNT(*) AS n FROM entries GROUP BY s ORDER BY n DESC"
        ).fetchall()

        domain_rows = conn.execute(
            "SELECT domain, COUNT(*) AS n FROM backbone_nodes GROUP BY domain ORDER BY n DESC"
        ).fetchall()

    section("Table Counts")
    kv(counts)
    section("Entry Processing Status")
    for r in status_rows:
        print(f"  {r['s']}: {r['n']}")
    section("Backbone Nodes by Domain")
    for r in domain_rows:
        print(f"  {r['domain']}: {r['n']}")


def cmd_entries(args: argparse.Namespace) -> None:
    params: list[Any] = []
    clauses: list[str] = []
    if args.entry_id is not None:
        clauses.append("id = ?"); params.append(args.entry_id)
    if args.processing_status:
        clauses.append("IFNULL(processing_status,'captured') = ?"); params.append(args.processing_status)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"SELECT id, created_at, source, memory_type, processing_status, raw FROM entries{where} ORDER BY created_at DESC LIMIT ?"
    params.append(args.limit)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        print("No entries found.")
        return
    for r in rows:
        section(f"Entry #{r['id']}")
        kv({"created_at": r["created_at"], "source": r["source"],
            "memory_type": r["memory_type"], "status": r["processing_status"],
            "raw": r["raw"]})


def cmd_slice(args: argparse.Namespace) -> None:
    if args.entry_id is None:
        raise SystemExit("--entry-id required")

    with get_conn() as conn:
        sl = conn.execute(
            "SELECT id, created_at FROM slices WHERE entry_id=? ORDER BY created_at DESC LIMIT 1",
            (args.entry_id,)
        ).fetchone()
        if not sl:
            print(f"No slice for entry #{args.entry_id}")
            return
        features = conn.execute(
            "SELECT dimension, content_json, confidence FROM slice_features WHERE slice_id=? ORDER BY dimension",
            (sl["id"],)
        ).fetchall()

    section(f"Slice for Entry #{args.entry_id} (slice_id={sl['id']})")
    for f in features:
        section(f"  {f['dimension']} (confidence={f['confidence']})")
        print(json.dumps(pj(f["content_json"]), ensure_ascii=False, indent=2))


def cmd_profile(_args: argparse.Namespace) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dimension, content_json, sample_count, updated_at FROM profile_dimensions ORDER BY dimension"
        ).fetchall()

    if not rows:
        print("No profile data yet.")
        return
    for r in rows:
        section(f"{r['dimension']}  (samples={r['sample_count']}  updated={r['updated_at']})")
        print(json.dumps(pj(r["content_json"]), ensure_ascii=False, indent=2))


def cmd_nodes(args: argparse.Namespace) -> None:
    params: list[Any] = []
    clauses: list[str] = []
    if args.domain:
        clauses.append("domain = ?"); params.append(args.domain)
    if args.node_type:
        clauses.append("node_type = ?"); params.append(args.node_type)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"""
        SELECT id, domain, node_type, label, description, strength, hit_count, last_hit_at, created_at
        FROM backbone_nodes{where}
        ORDER BY strength DESC LIMIT ?
    """
    params.append(args.limit)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        print("No nodes found.")
        return
    for r in rows:
        print(f"  [{r['id']:4d}] [{r['domain']:12s}] [{r['node_type']:4s}] {r['label']:<35s} "
              f"strength={r['strength']:.3f}  hits={r['hit_count']}  last={r['last_hit_at'] or '-'}")
        if args.verbose and r["description"]:
            print(f"         {r['description']}")


def cmd_edges(args: argparse.Namespace) -> None:
    params: list[Any] = []
    clauses: list[str] = []
    if args.node_id:
        clauses.append("(e.from_node_id=? OR e.to_node_id=?)")
        params.extend([args.node_id, args.node_id])
    if args.relation:
        clauses.append("e.relation_type=?"); params.append(args.relation)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"""
        SELECT e.id, n1.label AS from_label, n1.domain AS from_domain,
               e.relation_type, n2.label AS to_label, n2.domain AS to_domain,
               e.weight, e.confidence, e.edge_source, e.last_reinforced_at
        FROM backbone_edges e
        JOIN backbone_nodes n1 ON n1.id = e.from_node_id
        JOIN backbone_nodes n2 ON n2.id = e.to_node_id
        {where}
        ORDER BY e.weight DESC LIMIT ?
    """
    params.append(args.limit)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        print("No edges found.")
        return
    for r in rows:
        print(f"  {r['from_label']} [{r['from_domain']}]  --[{r['relation_type']}]-->  "
              f"{r['to_label']} [{r['to_domain']}]  "
              f"w={r['weight']:.3f} conf={r['confidence']:.2f} src={r['edge_source']}")


def cmd_graph(args: argparse.Namespace) -> None:
    """Print an ASCII adjacency summary for a domain."""
    with get_conn() as conn:
        params: list[Any] = []
        where = ""
        if args.domain:
            where = " WHERE n.domain=?"
            params.append(args.domain)
        nodes = conn.execute(
            f"SELECT id, label, strength FROM backbone_nodes n{where} ORDER BY strength DESC LIMIT 30",
            params
        ).fetchall()
        if not nodes:
            print("No nodes.")
            return
        node_ids = {r["id"] for r in nodes}
        id_to_label = {r["id"]: r["label"] for r in nodes}

        edges = conn.execute(
            "SELECT from_node_id, to_node_id, relation_type, weight FROM backbone_edges ORDER BY weight DESC"
        ).fetchall()

    section(f"Graph{'  domain=' + args.domain if args.domain else ''}")
    print(f"Nodes ({len(nodes)}):")
    for r in nodes:
        print(f"  [{r['id']:4d}] {r['label']:<35s} strength={r['strength']:.3f}")
    print(f"\nEdges (within shown nodes):")
    for e in edges:
        if e["from_node_id"] in node_ids and e["to_node_id"] in node_ids:
            print(f"  {id_to_label[e['from_node_id']]} --[{e['relation_type']}]--> "
                  f"{id_to_label[e['to_node_id']]}  w={e['weight']:.3f}")


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Inspect Engram API SQLite data")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("overview", help="Table counts + domain breakdown").set_defaults(func=cmd_overview)

    e = sub.add_parser("entries", help="List entries")
    e.add_argument("--limit", type=int, default=20)
    e.add_argument("--entry-id", type=int)
    e.add_argument("--processing-status")
    e.set_defaults(func=cmd_entries)

    s = sub.add_parser("slice", help="Show slice features for one entry")
    s.add_argument("--entry-id", type=int, required=True)
    s.set_defaults(func=cmd_slice)

    sub.add_parser("profile", help="Show merged profile dimensions").set_defaults(func=cmd_profile)

    n = sub.add_parser("nodes", help="List backbone nodes")
    n.add_argument("--limit", type=int, default=30)
    n.add_argument("--domain")
    n.add_argument("--node-type")
    n.add_argument("--verbose", "-v", action="store_true")
    n.set_defaults(func=cmd_nodes)

    ed = sub.add_parser("edges", help="List backbone edges")
    ed.add_argument("--limit", type=int, default=30)
    ed.add_argument("--node-id", type=int)
    ed.add_argument("--relation")
    ed.set_defaults(func=cmd_edges)

    g = sub.add_parser("graph", help="ASCII adjacency summary")
    g.add_argument("--domain")
    g.set_defaults(func=cmd_graph)

    return p


def main() -> None:
    build_parser().parse_args().__dict__["func"](build_parser().parse_args())


if __name__ == "__main__":
    main()
