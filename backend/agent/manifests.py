from __future__ import annotations

import json
from functools import lru_cache

from .paths import FALLBACK_DIR, SFX_DIR


@lru_cache(maxsize=1)
def fallback_manifest() -> dict[str, dict]:
    """Semantic-role -> {kind, desc, files, expected_bbox_diagonal_m?} map.
    The `_doc` key is filtered out — only real roles returned.
    """
    raw = json.loads((FALLBACK_DIR / "manifest.json").read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@lru_cache(maxsize=1)
def sfx_manifest() -> dict[str, dict]:
    raw = json.loads((SFX_DIR / "sfx_manifest.json").read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def fallback_roles() -> set[str]:
    return set(fallback_manifest().keys())


def sfx_keys() -> set[str]:
    return set(sfx_manifest().keys())
