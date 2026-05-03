"""Legacy session-lookup endpoint kept for the MCP server.

The actual query path is now /query/agent (see app/routes/agent.py). This file
exists only to expose /query/latest-session, which the MCP server uses to let
clients continue the most recent conversation.
"""

import json

from fastapi import APIRouter

from app.lib.db import get_conn

router = APIRouter()


@router.get("/query/latest-session")
async def latest_session():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT session_id, turns_json FROM query_logs "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    if not row or not row["session_id"]:
        return {"session_id": None, "history": []}
    try:
        turns = json.loads(row["turns_json"] or "[]")
    except Exception:
        turns = []
    history = [
        {"question": t["question"], "answer": t.get("response", "")}
        for t in turns
        if t.get("intent") == "proceed"
    ]
    return {"session_id": row["session_id"], "history": history}
