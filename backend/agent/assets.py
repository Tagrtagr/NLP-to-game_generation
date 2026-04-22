"""Phase 2 — Asset resolution.

Every `Asset` resolves to a `ResolvedAsset` on disk. Generation is best-effort
and guarded by timeout + garbage detection + per-service circuit breaker; the
bundled fallback role is always loadable as a deterministic file copy.

This module exposes `resolve_all(design, session_id, breaker)` as an async
generator of `(Event, ResolvedAsset | None)` pairs so the pipeline can stream
per-asset progress to the UI. The resolver stores files under
`workspaces/<sid>/assets/` and returns paths relative to that dir.
"""
from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .breaker import CircuitBreaker
from .clients import pixellab
from .events import Event
from .garbage import GarbageOutput, check_2d_image
from .manifests import fallback_manifest
from .paths import FALLBACK_DIR, session_dir
from .schema import Asset, AssetKind, GameDesign

Source = Literal["generated", "fallback"]

TIMEOUTS: dict[AssetKind, float] = {
    "sprite": 20.0,
    "tileset": 25.0,
    "bg": 25.0,
    "ui": 20.0,
    "mesh": 60.0,  # wired up in step 7 (Tripo)
}


@dataclass
class ResolvedAsset:
    asset_id: str
    role: str
    kind: AssetKind
    path: Path  # absolute path to file in session assets dir
    rel_path: str  # path relative to session_dir, for the iframe / SSE
    source: Source
    error: str | None = None  # populated when source == "fallback"


def _assets_dir(session_id: str) -> Path:
    d = session_dir(session_id) / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_fallback(asset: Asset, session_id: str, reason: str) -> ResolvedAsset:
    """Deterministic file copy from fallback_assets/<role file> -> session dir.

    Cannot fail in normal operation — the schema validator guarantees
    fallback_role exists in the manifest before we get here.
    """
    entry = fallback_manifest()[asset.fallback_role]
    files: list[str] = entry.get("files", [])
    if not files:
        raise RuntimeError(f"fallback role '{asset.fallback_role}' has no files")
    # Stable pick across retries: hash-free, just index 0 for now.
    src = FALLBACK_DIR / files[0]
    dst_dir = _assets_dir(session_id)
    dst = dst_dir / f"{asset.id}{src.suffix}"
    shutil.copyfile(src, dst)
    return ResolvedAsset(
        asset_id=asset.id,
        role=asset.role,
        kind=asset.kind,
        path=dst,
        rel_path=f"assets/{dst.name}",
        source="fallback",
        error=reason,
    )


async def _generate_2d(asset: Asset, style: str) -> bytes:
    """Dispatch 2D generation by kind. Raises on failure."""
    if asset.kind in ("sprite", "tileset", "ui"):
        w, h = asset.size or (64, 64)
        return await asyncio.wait_for(
            pixellab.generate_sprite(
                prompt=asset.prompt, width=w, height=h, style=style
            ),
            timeout=TIMEOUTS[asset.kind],
        )
    if asset.kind == "bg":
        # gpt-image-1 wiring in step 7. For now, short-circuit to fallback.
        raise NotImplementedError("bg generation lands in step 7")
    raise NotImplementedError(f"no 2D generator for kind={asset.kind}")


def _service_for(kind: AssetKind) -> str:
    if kind in ("sprite", "tileset", "ui"):
        return pixellab.SERVICE_NAME
    if kind == "bg":
        return "gpt_image"
    return "tripo"


async def resolve_asset(
    asset: Asset,
    *,
    session_id: str,
    style: str,
    breaker: CircuitBreaker,
) -> ResolvedAsset:
    service = _service_for(asset.kind)

    if breaker.is_open(service):
        return _load_fallback(asset, session_id, f"{service} circuit open")

    if asset.kind == "mesh":
        # Tripo lands in step 7; use fallback mesh for now.
        return _load_fallback(asset, session_id, "mesh gen not yet wired")

    try:
        data = await _generate_2d(asset, style)
        check_2d_image(data)
    except (TimeoutError, asyncio.TimeoutError) as e:
        breaker.record_failure(service)
        return _load_fallback(asset, session_id, f"timeout: {e}")
    except GarbageOutput as e:
        breaker.record_failure(service)
        return _load_fallback(asset, session_id, f"garbage: {e}")
    except NotImplementedError as e:
        return _load_fallback(asset, session_id, str(e))
    except Exception as e:
        breaker.record_failure(service)
        return _load_fallback(asset, session_id, f"{type(e).__name__}: {e}")

    breaker.record_success(service)
    dst_dir = _assets_dir(session_id)
    dst = dst_dir / f"{asset.id}.png"
    dst.write_bytes(data)
    return ResolvedAsset(
        asset_id=asset.id,
        role=asset.role,
        kind=asset.kind,
        path=dst,
        rel_path=f"assets/{dst.name}",
        source="generated",
    )


async def resolve_all(
    design: GameDesign,
    session_id: str,
    breaker: CircuitBreaker,
) -> AsyncIterator[tuple[Event, ResolvedAsset | None]]:
    yield (
        Event(
            phase="assets",
            step="fanout",
            status="start",
            detail=f"{len(design.assets)} assets",
        ),
        None,
    )

    tasks = [
        asyncio.create_task(
            resolve_asset(a, session_id=session_id, style=design.art_style, breaker=breaker)
        )
        for a in design.assets
    ]

    for coro in asyncio.as_completed(tasks):
        resolved = await coro
        yield (
            Event(
                phase="assets",
                step="asset_ready",
                status="progress" if resolved.source == "generated" else "done",
                detail=f"{resolved.asset_id} [{resolved.source}]"
                + (f": {resolved.error}" if resolved.error else ""),
                payload={
                    "asset_id": resolved.asset_id,
                    "role": resolved.role,
                    "kind": resolved.kind,
                    "source": resolved.source,
                    "rel_path": resolved.rel_path,
                },
            ),
            resolved,
        )

    yield (
        Event(phase="assets", step="fanout", status="done", detail="all resolved"),
        None,
    )
