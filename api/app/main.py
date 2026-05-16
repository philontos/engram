from dotenv import load_dotenv
load_dotenv()

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.lib.db import init_db
from app.lib.config_loader import detect_orphan_domains
from app.routes import agent, capture, import_entries, process_entry, query, revert_entry, ui_api

app = FastAPI(title="Cognitive Service")
logger = logging.getLogger("cognitive")


# Local dev only: enable CORS for the Vite dev server on :5173.
# In production, Caddy keeps web + api same-origin, so CORS is unnecessary.
if os.getenv("ENGRAM_DEV") == "1":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def startup():
    init_db()
    orphans = detect_orphan_domains()
    if orphans:
        logger.warning(
            "Orphan backbone domains in DB (no matching config dir): %s. "
            "Existing nodes are kept and still consumed by query pipelines, "
            "but new entries will not write to these domains.",
            ", ".join(orphans),
        )

    # Crash recovery: any entry left in 'processing' from a previous run had
    # its pipeline interrupted (process killed, OOM, container restart). Roll
    # them back to 'captured' so process_pending picks them up again.
    from app.lib.db import get_conn
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE entries SET processing_status='captured' WHERE processing_status='processing'"
        )
        if cur.rowcount:
            logger.warning("Reset %d stuck 'processing' entries to 'captured' on startup", cur.rowcount)


app.include_router(capture.router)
app.include_router(import_entries.router)
app.include_router(process_entry.router)
app.include_router(revert_entry.router)
app.include_router(query.router)
app.include_router(agent.router)
app.include_router(ui_api.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
