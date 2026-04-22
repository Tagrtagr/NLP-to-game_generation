from __future__ import annotations

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BACKEND_DIR / "godot_templates"
FALLBACK_DIR = BACKEND_DIR / "fallback_assets"
SFX_DIR = BACKEND_DIR / "sfx"
PROMPTS_DIR = BACKEND_DIR / "prompts"
WORKSPACES_DIR = BACKEND_DIR / "workspaces"
CONTEXT_DIR = BACKEND_DIR / "godot_context"


def session_dir(session_id: str) -> Path:
    d = WORKSPACES_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_log_dir(session_id: str) -> Path:
    d = session_dir(session_id) / "_log"
    d.mkdir(parents=True, exist_ok=True)
    return d
