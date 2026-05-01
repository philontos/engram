#!/usr/bin/env python3
"""Export raw entries and metadata as a durable backup snapshot."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def resolve_default_output_path() -> Path:
    db_path = Path(os.getenv("DB_PATH", str(resolve_default_db_path())))
    return db_path.parent / "exports" / "raw_entries.json"


DB_PATH = Path(os.getenv("DB_PATH", str(resolve_default_db_path())))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def parse_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Export raw entries and metadata as a JSON snapshot")
    parser.add_argument(
        "--output",
        default=str(resolve_default_output_path()),
        help="Output JSON file. Existing file will be overwritten.",
    )
    parser.add_argument(
        "--entry-id",
        type=int,
        action="append",
        help="Export only specific entry ids. Repeat for multiple entries.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Export only the most recent N entries.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    query = """
        SELECT
            id,
            created_at,
            type,
            raw,
            source,
            memory_type,
            mood,
            tags,
            context_json,
            metadata_json,
            processing_status,
            vector_id
        FROM entries
    """
    params: list[Any] = []
    clauses: list[str] = []
    if args.entry_id:
        entry_ids = sorted(set(args.entry_id))
        clauses.append(f"id IN ({','.join('?' for _ in entry_ids)})")
        params.extend(entry_ids)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at ASC"
    if args.limit is not None:
        query += " LIMIT ?"
        params.append(args.limit)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    entries = []
    for row in rows:
        entries.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "type": row["type"],
                "raw": row["raw"],
                "source": row["source"],
                "memory_type": row["memory_type"],
                "mood": row["mood"],
                "tags": parse_json(row["tags"]) or [],
                "context": parse_json(row["context_json"]) or {},
                "metadata": parse_json(row["metadata_json"]) or {},
                "processing_status": row["processing_status"],
                "vector_id": row["vector_id"],
            }
        )

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(DB_PATH),
        "entry_count": len(entries),
        "entries": entries,
    }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Export complete: {output_path}")
    print(f"entries: {len(entries)}")


if __name__ == "__main__":
    main()
