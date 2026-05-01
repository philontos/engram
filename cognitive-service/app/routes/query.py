"""POST /query — 四阶段个性化消费，NDJSON 流式响应。

请求体: {"question": str, "mode": "full" | "fast"}
响应: application/x-ndjson，每行一个 JSON 事件
"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.lib.db import get_conn
from app.lib.query_pipeline import run_query
from pydantic import BaseModel

router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    mode: str = "full"
    session_id: str | None = None


@router.post("/query")
async def query(req: QueryRequest):
    async def stream():
        try:
            async for event in run_query(req.question, req.mode, session_id=req.session_id):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.get("/query/latest-session")
async def latest_session():
    """返回最近一条 query_logs 的 session_id 和 turns 摘要，供 plugin 续接多轮对话。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT session_id, turns_json FROM query_logs ORDER BY updated_at DESC LIMIT 1"
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
