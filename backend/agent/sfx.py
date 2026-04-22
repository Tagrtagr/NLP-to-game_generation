"""Deterministic SFX resolution.

No generation path — every sfx_map value is schema-validated against
sfx_manifest.json, so we just copy the corresponding .wav from backend/sfx/
into the session workspace and return a (event, key, rel_path) list that
the synthesize phase references by concrete filename.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .manifests import sfx_manifest
from .paths import SFX_DIR, session_dir
from .schema import GameDesign


@dataclass
class ResolvedSfx:
    event: str
    key: str
    rel_path: str


def resolve_sfx(design: GameDesign, session_id: str) -> list[ResolvedSfx]:
    out_dir: Path = session_dir(session_id) / "sfx"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = sfx_manifest()
    resolved: list[ResolvedSfx] = []
    for event, key in design.sfx_map.items():
        entry = manifest[key]  # schema validator guarantees this exists
        src = SFX_DIR / entry["file"]
        dst = out_dir / Path(entry["file"]).name
        if src.exists():
            shutil.copyfile(src, dst)
        resolved.append(
            ResolvedSfx(event=event, key=key, rel_path=f"sfx/{dst.name}")
        )
    return resolved
