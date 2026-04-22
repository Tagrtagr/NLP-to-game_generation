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
from .clients import gpt_image, pixellab, tripo
from .events import Event
from .garbage import GarbageOutput, check_2d_image
from .manifests import fallback_manifest
from .paths import FALLBACK_DIR, session_dir
from .schema import Asset, AssetKind, GameDesign

Source = Literal["generated", "fallback"]

TIMEOUTS: dict[AssetKind, float] = {
    "sprite": 35.0,
    "tileset": 35.0,
    "bg": 35.0,
    "ui": 30.0,
    "mesh": 150.0,
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


def _write_placeholder(asset: Asset, dst: Path) -> None:
    """Synthesize a placeholder file when the bundled Kenney asset is missing.

    2D: solid-color PNG (magenta = obviously a placeholder).
    3D: tiny valid GLB with a single cube.
    """
    if asset.kind == "mesh":
        dst.write_bytes(_cube_glb())
        return
    w, h = asset.size or (64, 64)
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (w, h), (255, 64, 200, 255))
    draw = ImageDraw.Draw(img)
    label = asset.id[:10]
    draw.text((2, 2), label, fill=(0, 0, 0, 255))
    img.save(dst, format="PNG")


def _cube_glb() -> bytes:
    """Minimal valid GLB containing a unit cube. Used as 3D placeholder."""
    import json as _json
    import struct

    # 8 vertices of a unit cube, 12 triangles.
    verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    ]
    idxs = [
        0, 1, 2, 0, 2, 3,  4, 6, 5, 4, 7, 6,
        0, 4, 5, 0, 5, 1,  1, 5, 6, 1, 6, 2,
        2, 6, 7, 2, 7, 3,  3, 7, 4, 3, 4, 0,
    ]
    vbuf = b"".join(struct.pack("<fff", *v) for v in verts)
    ibuf = b"".join(struct.pack("<H", i) for i in idxs)
    # pad index buffer to 4 bytes
    while len(ibuf) % 4:
        ibuf += b"\x00"
    bin_data = vbuf + ibuf
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "buffers": [{"byteLength": len(bin_data)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vbuf), "target": 34962},
            {"buffer": 0, "byteOffset": len(vbuf), "byteLength": len(idxs) * 2, "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(verts), "type": "VEC3",
             "min": [-0.5, -0.5, -0.5], "max": [0.5, 0.5, 0.5]},
            {"bufferView": 1, "componentType": 5123, "count": len(idxs), "type": "SCALAR"},
        ],
    }
    gjson = _json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(gjson) % 4:
        gjson += b" "
    json_chunk = struct.pack("<II", len(gjson), 0x4E4F534A) + gjson
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data
    total = 12 + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, total)
    return header + json_chunk + bin_chunk


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
    if src.exists():
        shutil.copyfile(src, dst)
    else:
        # Bootstrap leaves Kenney packs as a manual step. If they're missing,
        # synthesize a placeholder so the pipeline still ships.
        _write_placeholder(asset, dst)
        reason = f"{reason}; bundled fallback missing, using placeholder"
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
    """Sprites + tilesets → PixelLab (pixel-art, native small sizes).
    Backgrounds + UI → gpt-image-1 (illustrated, large canvas).
    """
    if asset.kind in ("sprite", "tileset"):
        w, h = asset.size or (64, 64)
        return await asyncio.wait_for(
            pixellab.generate_sprite(
                prompt=asset.prompt, width=w, height=h, style=style
            ),
            timeout=TIMEOUTS[asset.kind],
        )
    if asset.kind == "bg":
        w, h = asset.size or (1536, 1024)
        transparent = False
    else:
        w, h = asset.size or (512, 256)
        transparent = True
    return await asyncio.wait_for(
        gpt_image.generate_image(
            prompt=asset.prompt,
            width=w,
            height=h,
            style=style,
            transparent=transparent,
        ),
        timeout=TIMEOUTS[asset.kind],
    )


async def _generate_mesh(asset: Asset, style: str) -> bytes:
    """Tripo text-to-model + scale-sanity + min-size garbage check.

    Raises TripoError / ScaleMismatch on failure — caller converts both into
    a fallback. 3D gets an aggressive fallback posture: any of these failure
    modes means we ship the bundled Kenney mesh instead of a mis-scaled
    black-screen.
    """
    data = await asyncio.wait_for(
        tripo.generate_mesh(prompt=asset.prompt, style=style),
        timeout=TIMEOUTS["mesh"],
    )
    tripo.check_glb(data, asset.expected_bbox)
    return data


def _service_for(kind: AssetKind) -> str:
    if kind == "mesh":
        return tripo.SERVICE_NAME
    if kind in ("sprite", "tileset"):
        return pixellab.SERVICE_NAME
    return gpt_image.SERVICE_NAME


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

    is_mesh = asset.kind == "mesh"
    try:
        if is_mesh:
            data = await _generate_mesh(asset, style)
        else:
            data = await _generate_2d(asset, style)
            check_2d_image(data)
    except (TimeoutError, asyncio.TimeoutError) as e:
        breaker.record_failure(service)
        return _load_fallback(asset, session_id, f"timeout: {e}")
    except GarbageOutput as e:
        breaker.record_failure(service)
        return _load_fallback(asset, session_id, f"garbage: {e}")
    except tripo.ScaleMismatch as e:
        # Not a service-health failure; don't trip the breaker — future meshes
        # may still scale correctly. Just swap in the bundled fallback mesh.
        return _load_fallback(asset, session_id, f"scale-mismatch: {e}")
    except tripo.TripoError as e:
        breaker.record_failure(service)
        return _load_fallback(asset, session_id, f"tripo: {e}")
    except NotImplementedError as e:
        return _load_fallback(asset, session_id, str(e))
    except Exception as e:
        breaker.record_failure(service)
        return _load_fallback(asset, session_id, f"{type(e).__name__}: {e}")

    breaker.record_success(service)
    dst_dir = _assets_dir(session_id)
    suffix = ".glb" if is_mesh else ".png"
    dst = dst_dir / f"{asset.id}{suffix}"
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
