from __future__ import annotations

from .paths import PROMPTS_DIR


def load_prompt(name: str) -> str:
    """Hot-reloadable: reads from disk every call so prompt edits don't need redeploy."""
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text()
