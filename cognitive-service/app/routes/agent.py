"""Agent-mode query endpoints.

POST /query/agent          — stream NDJSON of agent run events
GET  /query/trace/{sid}    — full trace dump for a session (all turns or one turn)
"""

import json

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.lib.agent_runtime import run_agent
from app.lib.db import get_conn

router = APIRouter()


class AgentQueryRequest(BaseModel):
    question: str
    session_id: str | None = None


@router.post("/query/agent")
async def query_agent(req: AgentQueryRequest):
    async def stream():
        try:
            async for event in run_agent(req.question, session_id=req.session_id):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps(
                {"type": "error", "message": str(exc), "where": "stream"},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.get("/query/trace/{session_id}")
async def get_trace(session_id: str, turn: int | None = Query(None)):
    """Return the raw event sequence for a session (or a specific turn).

    Each event row carries the full LLM request/response or full tool args/result.
    Intended for human inspection during debugging — not a stable API.
    """
    sql = (
        "SELECT id, session_id, turn_index, round_num, seq, event_type, tool_name, "
        "       request_json, response_json, latency_ms, error, created_at "
        "FROM query_traces WHERE session_id=? "
    )
    params: list = [session_id]
    if turn is not None:
        sql += "AND turn_index=? "
        params.append(turn)
    sql += "ORDER BY turn_index, seq"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    def _decode(s: str | None):
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return s

    events = [
        {
            "id":          r["id"],
            "session_id":  r["session_id"],
            "turn_index":  r["turn_index"],
            "round_num":   r["round_num"],
            "seq":         r["seq"],
            "event_type":  r["event_type"],
            "tool_name":   r["tool_name"],
            "request":     _decode(r["request_json"]),
            "response":    _decode(r["response_json"]),
            "latency_ms":  r["latency_ms"],
            "error":       r["error"],
            "created_at":  r["created_at"],
        }
        for r in rows
    ]
    return JSONResponse({"session_id": session_id, "count": len(events), "events": events})
