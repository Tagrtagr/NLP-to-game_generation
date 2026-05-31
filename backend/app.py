from __future__ import annotations

import uuid
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agent.session_manager import MANAGER

BACKEND_DIR = Path(__file__).resolve().parent
WORKSPACES_DIR = BACKEND_DIR / "workspaces"
WORKSPACES_DIR.mkdir(exist_ok=True)

load_dotenv(BACKEND_DIR / ".env")


def _cors_origins() -> list[str]:
    configured = os.environ.get("CORS_ALLOW_ORIGINS", "")
    origins = [o.strip() for o in configured.split(",") if o.strip()]
    if origins:
        return origins
    return ["http://localhost:5173", "http://127.0.0.1:5173"]

app = FastAPI(title="Godot Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.2.0"}


async def _drain(q):
    while True:
        item = await q.get()
        if item is None:  # terminal sentinel from stream()
            break
        event, data = item
        yield {"event": event, "data": data}
        if event == "done":
            break


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """Start a pipeline and return an SSE stream.

    The pipeline runs as a background task owned by the session manager,
    so disconnecting the SSE does NOT cancel the job. Reconnect via
    /api/stream/{session_id} to resume with full history replay.
    """
    sid = req.session_id or uuid.uuid4().hex[:12]
    MANAGER.start(sid, req.prompt)
    q = await MANAGER.stream(sid)
    return EventSourceResponse(_drain(q))


@app.get("/api/stream/{sid}")
async def resume(sid: str):
    q = await MANAGER.stream(sid)
    if q is None:
        raise HTTPException(404, f"no session {sid}")
    return EventSourceResponse(_drain(q))


@app.post("/api/cancel/{sid}")
async def cancel(sid: str) -> dict[str, bool]:
    return {"cancelled": MANAGER.cancel(sid)}


app.mount(
    "/workspaces",
    StaticFiles(directory=str(WORKSPACES_DIR), html=True),
    name="workspaces",
)
