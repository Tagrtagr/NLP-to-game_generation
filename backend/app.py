from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BACKEND_DIR = Path(__file__).resolve().parent
WORKSPACES_DIR = BACKEND_DIR / "workspaces"
WORKSPACES_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Godot Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


app.mount(
    "/workspaces",
    StaticFiles(directory=str(WORKSPACES_DIR), html=True),
    name="workspaces",
)
