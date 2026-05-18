"""POST /capture — write a single thought / reflection.

Engram is a cognitive capture system. Inputs that are pure event logs or
reminders are rejected by the intent gate; only reflections become entries.
The slice + backbone pipeline is triggered automatically in the background
once an entry is created.
"""

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.lib import process_events
from app.lib.db import get_conn
from app.lib.embed import embed
from app.lib.intent_gate import classify
from app.lib.vector_store import get_store

router = APIRouter()


class CaptureRequest(BaseModel):
    type: str = "text"
    content: str
    source: str = "api"
    memory_type: str | None = None
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    mood: str | None = None
    tags: list[str] | None = None


class CaptureResponse(BaseModel):
    track: str          # "entry" | "reject"
    id: int | None      # entry_id when track == "entry"
    reason: str = ""


def _build_metadata(req: CaptureRequest) -> dict[str, Any]:
    now = datetime.now().astimezone()
    metadata: dict[str, Any] = {
        "captured_at": now.isoformat(),
        "timezone": str(now.tzinfo) if now.tzinfo else None,
        "date": now.date().isoformat(),
        "weekday": now.strftime("%A").lower(),
        "time_of_day": (
            "morning"   if 5  <= now.hour < 12 else
            "afternoon" if 12 <= now.hour < 18 else
            "evening"   if 18 <= now.hour < 23 else
            "night"
        ),
        "channel": req.source,
        "source_type": req.type,
    }
    if req.metadata:
        metadata.update(req.metadata)
    return metadata


async def _create_entry(raw: str, req: CaptureRequest, metadata: dict | None = None) -> int:
    memory_type = (req.memory_type or "thought").strip().lower()
    context_json = json.dumps(req.context or {}, ensure_ascii=False)
    metadata_json = json.dumps(metadata or _build_metadata(req), ensure_ascii=False)
    tags_json = json.dumps(req.tags or [], ensure_ascii=False)
    embedding = await embed(raw)

    with get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO entries
               (type, raw, summary, tags, mood, vector_id, source, memory_type,
                importance, context_json, metadata_json, processing_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (req.type, raw, raw[:100], tags_json, req.mood, None,
             req.source, memory_type, None, context_json, metadata_json, "captured"),
        )
        entry_id = cursor.lastrowid

    get_store().add(entry_id, embedding)
    with get_conn() as conn:
        conn.execute("UPDATE entries SET vector_id=? WHERE id=?", (entry_id, entry_id))
    return entry_id


async def _trigger_process(entry_id: int) -> None:
    from app.routes.process_entry import run_pipeline_bg
    await run_pipeline_bg(entry_id)


@router.post("/capture", response_model=CaptureResponse)
async def capture(req: CaptureRequest):
    if req.type != "text":
        raise HTTPException(status_code=400, detail="Engram API is text-only.")

    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is empty.")

    intent = await classify(content)
    track = intent["track"]
    reason = intent.get("reason", "")

    if track == "reject":
        return CaptureResponse(track="reject", id=None, reason=reason)

    metadata = _build_metadata(req)
    entry_id = await _create_entry(content, req, metadata=metadata)
    process_events.init(entry_id)
    asyncio.create_task(_trigger_process(entry_id))
    return CaptureResponse(track="entry", id=entry_id, reason=reason)
