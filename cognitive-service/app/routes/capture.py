import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.lib.db import get_conn
from app.lib.embed import embed
from app.lib.intent_gate import classify
from app.lib.vector_store import get_store

router = APIRouter()

BUFFER_TIMEOUT_MINUTES = 60
BUFFER_MAX_CHARS = 2000


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
    track: str          # "entry" | "memo" | "buffer" | "buffer_flushed"
    id: int | None      # entry_id 或 memo_id（buffer 时为 None）
    buffer_session_id: str | None = None
    flushed_entry_id: int | None = None  # buffer flush 后合并生成的 entry_id
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


# ---------------------------------------------------------------------------
# Buffer helpers
# ---------------------------------------------------------------------------

def _get_active_buffer(source: str) -> list[dict] | None:
    """返回该 source 当前未 flush 的 buffer 条目（按时间排序），超时则返回 None。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM capture_buffer WHERE source=? AND flushed=0 ORDER BY created_at ASC",
            (source,),
        ).fetchall()
    if not rows:
        return None
    last_time = datetime.fromisoformat(rows[-1]["created_at"].replace(" ", "T"))
    if datetime.utcnow() - last_time > timedelta(minutes=BUFFER_TIMEOUT_MINUTES):
        return None  # 超时，调用方负责 flush
    return [dict(r) for r in rows]


_CONNECTOR_RE = re.compile(
    r"(^(接上[一上面]?条[，,。\s]*|接着说[，,。\s]*|续上[，,。\s]*))"
    r"|(我还没说完[，,。\s]*$"
    r"|未完待续[，,。\s]*$"
    r"|接下来说[，,。\s]*$"
    r"|下一条接着[，,。\s]*$"
    r"|接着说[，,。\s]*$)"
)


def _strip_connectors(text: str) -> str:
    return _CONNECTOR_RE.sub("", text).strip()


def _flush_buffer(rows: list[dict]) -> tuple[str, dict]:
    """把 buffer 条目合并成一条 raw，裁剪首尾连接词后返回。"""
    segments = [_strip_connectors(r["raw"]) for r in rows]
    merged_raw = "\n".join(s for s in segments if s)
    first_meta = json.loads(rows[0]["metadata_json"] or "{}")
    return merged_raw, first_meta


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


def _mark_buffer_flushed(rows: list[dict], entry_id: int) -> None:
    ids = [r["id"] for r in rows]
    ph = ",".join("?" * len(ids))
    with get_conn() as conn:
        conn.execute(
            f"UPDATE capture_buffer SET flushed=1, entry_id=? WHERE id IN ({ph})",
            [entry_id, *ids],
        )


def _check_buffer_timeout(source: str) -> list[dict] | None:
    """检查是否有超时未 flush 的 buffer，有则返回，否则 None。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM capture_buffer WHERE source=? AND flushed=0 ORDER BY created_at ASC",
            (source,),
        ).fetchall()
    if not rows:
        return None
    last_time = datetime.fromisoformat(rows[-1]["created_at"].replace(" ", "T"))
    if datetime.utcnow() - last_time > timedelta(minutes=BUFFER_TIMEOUT_MINUTES):
        return [dict(r) for r in rows]
    return None


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/capture", response_model=CaptureResponse)
async def capture(req: CaptureRequest):
    if req.type != "text":
        raise HTTPException(status_code=400, detail="cognitive-service is text-only.")

    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is empty.")

    metadata = _build_metadata(req)

    # 1. 意图识别
    intent = await classify(content)
    track = intent["track"]
    reason = intent.get("reason", "")

    # 2. 检查是否有超时 buffer 需要先 flush（无论本次 track 是什么）
    timed_out = _check_buffer_timeout(req.source)
    if timed_out:
        merged_raw, first_meta = _flush_buffer(timed_out)
        flushed_entry_id = await _create_entry(merged_raw, req, metadata=first_meta)
        _mark_buffer_flushed(timed_out, flushed_entry_id)
        asyncio.create_task(_trigger_process(flushed_entry_id))

    # 3. 按 track 处理当前输入
    if track == "memo":
        # 有活跃 buffer + 本次是 memo → 先 flush buffer
        active = _get_active_buffer(req.source)
        flushed_entry_id_from_active = None
        if active:
            merged_raw, first_meta = _flush_buffer(active)
            flushed_entry_id_from_active = await _create_entry(merged_raw, req, metadata=first_meta)
            _mark_buffer_flushed(active, flushed_entry_id_from_active)
            asyncio.create_task(_trigger_process(flushed_entry_id_from_active))

        memo_id = _save_memo(content, req.source, metadata)
        return CaptureResponse(
            track="memo",
            id=memo_id,
            flushed_entry_id=flushed_entry_id_from_active,
            reason=reason,
        )

    if track == "entry":
        # 有活跃 buffer + 本次是 entry → 先 flush buffer
        active = _get_active_buffer(req.source)
        flushed_entry_id_from_active = None
        if active:
            merged_raw, first_meta = _flush_buffer(active)
            flushed_entry_id_from_active = await _create_entry(merged_raw, req, metadata=first_meta)
            _mark_buffer_flushed(active, flushed_entry_id_from_active)
            asyncio.create_task(_trigger_process(flushed_entry_id_from_active))

        entry_id = await _create_entry(content, req, metadata=metadata)
        asyncio.create_task(_trigger_process(entry_id))
        return CaptureResponse(
            track="entry",
            id=entry_id,
            flushed_entry_id=flushed_entry_id_from_active,
            reason=reason,
        )

    # track == "buffer"
    active = _get_active_buffer(req.source)
    if active:
        session_id = active[0]["buffer_session_id"]
        # buffer 积累过长 → 强制 flush，当前输入开新 session
        total_chars = sum(len(r["raw"]) for r in active) + len(content)
        if total_chars > BUFFER_MAX_CHARS:
            merged_raw, first_meta = _flush_buffer(active)
            flushed_entry_id = await _create_entry(merged_raw, req, metadata=first_meta)
            _mark_buffer_flushed(active, flushed_entry_id)
            asyncio.create_task(_trigger_process(flushed_entry_id))
            session_id = str(uuid.uuid4())
    else:
        session_id = str(uuid.uuid4())

    _append_buffer(session_id, content, req.source, metadata)
    return CaptureResponse(
        track="buffer",
        id=None,
        buffer_session_id=session_id,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_memo(raw: str, source: str, metadata: dict) -> int:
    import re
    words = re.findall(r'[\w一-鿿]+', raw)
    keywords = list(dict.fromkeys(words))[:10]
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO memos (raw, source, keywords_json, metadata_json) VALUES (?, ?, ?, ?)",
            (raw, source,
             json.dumps(keywords, ensure_ascii=False),
             json.dumps(metadata, ensure_ascii=False)),
        )
        return cur.lastrowid


def _append_buffer(session_id: str, raw: str, source: str, metadata: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO capture_buffer (buffer_session_id, raw, source, metadata_json) VALUES (?, ?, ?, ?)",
            (session_id, raw, source, json.dumps(metadata, ensure_ascii=False)),
        )


async def _trigger_process(entry_id: int) -> None:
    from app.routes.process_entry import run_pipeline_bg
    await run_pipeline_bg(entry_id)
