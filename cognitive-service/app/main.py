from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.lib.db import init_db
from app.routes import capture, import_entries, process_entry, query, revert_entry, ui_api

app = FastAPI(title="Cognitive Service")


@app.on_event("startup")
async def startup():
    init_db()


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
