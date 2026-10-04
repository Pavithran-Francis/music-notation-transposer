"""FastAPI application entry point.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import REPO_DIR, get_settings
from app.db import init_db
from app.services import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    jobs.recover_interrupted()
    jobs.start_cleanup_thread()
    yield


app = FastAPI(
    title="Sheet Music Transposer API",
    version="1.0.0",
    description="Upload sheet music (PDF, image, MusicXML), recognize it, transpose it for another "
                "instrument and export engraved PDF, MusicXML and MIDI.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):  # never leak stack traces to the client
    logging.getLogger("smt").exception("unhandled error")
    return JSONResponse({"detail": "An unexpected error occurred. Please try again."}, status_code=500)


# Serve the built frontend (production) from the same origin when available.
_dist = REPO_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (_dist / path).resolve()
        if path and f.is_file() and _dist.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
