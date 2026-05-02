from dotenv import load_dotenv
load_dotenv()

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.lib.db import init_db
from app.lib.config_loader import detect_orphan_domains
from app.routes import capture, import_entries, process_entry, query, revert_entry, ui_api

app = FastAPI(title="Cognitive Service")
logger = logging.getLogger("cognitive")


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


app.include_router(capture.router)
app.include_router(import_entries.router)
app.include_router(process_entry.router)
app.include_router(revert_entry.router)
app.include_router(query.router)
app.include_router(ui_api.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
