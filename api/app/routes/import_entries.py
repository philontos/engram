"""POST /import/entries — 批量导入历史 entries，保留原始时间戳和元数据。"""

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.lib.db import get_conn
from app.lib.embed import embed
from app.lib.vector_store import get_store

router = APIRouter()


class ImportEntry(BaseModel):
    created_at: str
    type: str = "text"
    raw: str
    source: str = "api"
    memory_type: str | None = None
    mood: str | None = None
    tags: list[str] | None = None
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class ImportRequest(BaseModel):
    entries: list[ImportEntry]


class ImportResult(BaseModel):
    imported: int
    skipped: int
    ids: list[int]


@router.post("/import/entries", response_model=ImportResult)
async def import_entries(req: ImportRequest):
    imported_ids: list[int] = []
    skipped = 0

    for entry in req.entries:
        if not entry.raw or not entry.raw.strip():
            skipped += 1
            continue

        raw = entry.raw.strip()
        memory_type = (entry.memory_type or "thought").strip().lower()
        context_json = json.dumps(entry.context or {}, ensure_ascii=False)
        metadata_json = json.dumps(entry.metadata or {}, ensure_ascii=False)
        tags_json = json.dumps(entry.tags or [], ensure_ascii=False)

        embedding = await embed(raw)

        with get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO entries (
                    created_at, type, raw, summary, tags, mood, vector_id,
                    source, memory_type, importance, context_json, metadata_json, processing_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.created_at, entry.type, raw, raw[:100],
                    tags_json, entry.mood, None,
                    entry.source, memory_type, None,
                    context_json, metadata_json, "captured",
                ),
            )
            entry_id = cursor.lastrowid

        get_store().add(entry_id, embedding)

        with get_conn() as conn:
            conn.execute("UPDATE entries SET vector_id = ? WHERE id = ?", (entry_id, entry_id))

        imported_ids.append(entry_id)

    return ImportResult(imported=len(imported_ids), skipped=skipped, ids=imported_ids)
