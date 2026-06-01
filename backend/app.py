from __future__ import annotations

import json
import uuid
import os
from datetime import datetime, timezone
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
SAVED_GAMES_DIR = BACKEND_DIR / "saved_games"
SAVED_GAMES_INDEX = SAVED_GAMES_DIR / "index.json"
WORKSPACES_DIR.mkdir(exist_ok=True)
SAVED_GAMES_DIR.mkdir(exist_ok=True)

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


class AssetThumb(BaseModel):
    asset_id: str = ""
    role: str = ""
    kind: str = ""
    source: str = "generated"
    rel_path: str = ""
    url: str | None = None
    error: str | None = None


class SaveGameRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=2000)
    template: str | None = Field(default=None, max_length=64)
    controls: dict[str, str] = Field(default_factory=dict)
    assets: list[AssetThumb] = Field(default_factory=list)


class SavedGame(BaseModel):
    session_id: str
    title: str
    prompt: str | None = None
    template: str | None = None
    controls: dict[str, str] = Field(default_factory=dict)
    assets: list[AssetThumb] = Field(default_factory=list)
    web_rel: str
    saved_at: str


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.2.0"}


def _safe_session_id(sid: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if not sid or any(c not in allowed for c in sid):
        raise HTTPException(400, "invalid session id")
    return sid


def _read_saved_games() -> dict[str, dict]:
    if not SAVED_GAMES_INDEX.exists():
        return {}
    try:
        data = json.loads(SAVED_GAMES_INDEX.read_text())
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def _write_saved_games(data: dict[str, dict]) -> None:
    tmp = SAVED_GAMES_INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(SAVED_GAMES_INDEX)


def _saved_web_rel(sid: str) -> str:
    web_index = WORKSPACES_DIR / sid / "web" / "index.html"
    if not web_index.exists():
        raise HTTPException(404, f"generated web build for session {sid} was not found")
    return f"workspaces/{sid}/web/index.html"


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


@app.get("/api/saves")
async def list_saves() -> dict[str, list[SavedGame]]:
    saves = [SavedGame.model_validate(v) for v in _read_saved_games().values()]
    saves.sort(key=lambda item: item.saved_at, reverse=True)
    return {"saves": saves}


@app.post("/api/saves")
async def save_game(req: SaveGameRequest) -> SavedGame:
    sid = _safe_session_id(req.session_id)
    web_rel = _saved_web_rel(sid)
    saved = SavedGame(
        session_id=sid,
        title=(req.title or req.prompt or f"Game {sid}").strip()[:120],
        prompt=req.prompt.strip() if req.prompt else None,
        template=req.template,
        controls=req.controls,
        assets=req.assets,
        web_rel=web_rel,
        saved_at=datetime.now(timezone.utc).isoformat(),
    )
    data = _read_saved_games()
    data[sid] = saved.model_dump()
    _write_saved_games(data)
    return saved


@app.delete("/api/saves/{sid}")
async def delete_save(sid: str) -> dict[str, bool]:
    sid = _safe_session_id(sid)
    data = _read_saved_games()
    existed = sid in data
    data.pop(sid, None)
    _write_saved_games(data)
    return {"deleted": existed}


app.mount(
    "/workspaces",
    StaticFiles(directory=str(WORKSPACES_DIR), html=True),
    name="workspaces",
)
