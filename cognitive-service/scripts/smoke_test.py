#!/usr/bin/env python3
"""Smoke test for cognitive-service endpoints.

Usage:
  python3 scripts/smoke_test.py
  python3 scripts/smoke_test.py --service-url http://127.0.0.1:18080
  python3 scripts/smoke_test.py --full   # also triggers process pipeline
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib import error, request


def http_get(url: str) -> tuple[int, Any]:
    try:
        with request.urlopen(request.Request(url), timeout=10) as r:
            return r.status, json.loads(r.read())
    except error.HTTPError as e:
        return e.code, e.read().decode()


def http_post(url: str, payload: dict) -> tuple[int, Any]:
    data = json.dumps(payload).encode()
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except error.HTTPError as e:
        return e.code, e.read().decode()


def check(name: str, ok: bool, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-url", default="http://127.0.0.1:18080")
    parser.add_argument("--full", action="store_true", help="Also trigger process pipeline (requires LLM)")
    args = parser.parse_args()
    base = args.service_url.rstrip("/")
    ok = True

    # health
    s, b = http_get(f"{base}/health")
    ok &= check("health", s == 200, f"status={s}")

    # stats
    s, b = http_get(f"{base}/ui/api/stats")
    ok &= check("ui/api/stats", s == 200 and "entries" in b, f"status={s} keys={list(b) if isinstance(b, dict) else b}")

    # capture
    s, b = http_post(f"{base}/capture", {"type": "text", "content": "smoke test entry: thinking about product decisions", "memory_type": "thought"})
    capture_ok = s == 200 and isinstance(b, dict) and "id" in b
    entry_id = b.get("id") if capture_ok else None
    ok &= check("capture", capture_ok, f"status={s} id={entry_id}")

    # entries list
    s, b = http_get(f"{base}/ui/api/entries?limit=5")
    ok &= check("ui/api/entries", s == 200 and "entries" in b, f"status={s}")

    # entry detail
    if entry_id:
        s, b = http_get(f"{base}/ui/api/entry/{entry_id}")
        ok &= check("ui/api/entry/{id}", s == 200 and "entry" in b, f"status={s}")

    # graph
    s, b = http_get(f"{base}/ui/api/graph")
    ok &= check("ui/api/graph", s == 200 and "nodes" in b, f"status={s} nodes={len(b.get('nodes', []))}")

    # profile
    s, b = http_get(f"{base}/ui/api/profile")
    ok &= check("ui/api/profile", s == 200, f"status={s}")

    # process pipeline (optional, requires LLM config)
    if args.full and entry_id:
        s, b = http_post(f"{base}/entries/{entry_id}/process", {})
        ok &= check("process pipeline", s == 200 and b.get("status") in ("done", "slice_failed"),
                    f"status={s} result={b.get('status')} nodes={b.get('nodes_upserted')} edges={b.get('edges_upserted')}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
