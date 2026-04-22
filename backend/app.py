from __future__ import annotations

import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agent.pipeline import run_pipeline

BACKEND_DIR = Path(__file__).resolve().parent
WORKSPACES_DIR = BACKEND_DIR / "workspaces"
WORKSPACES_DIR.mkdir(exist_ok=True)

load_dotenv(BACKEND_DIR / ".env")

app = FastAPI(title="Godot Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    sid = req.session_id or uuid.uuid4().hex[:12]

    async def stream():
        # First event carries the session id so the frontend knows which
        # workspace path to point the iframe at.
        yield {"event": "session", "data": sid}
        try:
            async for ev in run_pipeline(sid, req.prompt):
                yield {"event": "phase", "data": ev.model_dump_json(exclude_none=True)}
        except Exception as e:
            yield {
                "event": "phase",
                "data": f'{{"phase":"design","step":"pipeline","status":"error","detail":"unhandled: {type(e).__name__}: {e}"}}',
            }
        yield {"event": "done", "data": sid}

    return EventSourceResponse(stream())


app.mount(
    "/workspaces",
    StaticFiles(directory=str(WORKSPACES_DIR), html=True),
    name="workspaces",
)
