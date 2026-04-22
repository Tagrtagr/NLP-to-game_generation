"""PixelLab client — pixel-art sprite/tileset generation.

Single-call wrapper around PixelLab's pixflux text-to-pixel endpoint. Returns
raw PNG bytes; higher-level code handles file placement + garbage detection.

API reference: https://api.pixellab.ai/v1/ (pixflux family).
Auth: Bearer token via PIXELLAB_API_KEY env var.
"""
from __future__ import annotations

import base64
import os

import httpx

PIXELLAB_BASE = "https://api.pixellab.ai/v1"
PIXELLAB_ENDPOINT = f"{PIXELLAB_BASE}/generate-image-pixflux"
SERVICE_NAME = "pixellab"


class PixelLabError(Exception):
    pass


async def generate_sprite(
    *,
    prompt: str,
    width: int = 64,
    height: int = 64,
    style: str | None = None,
    timeout: float = 20.0,
) -> bytes:
    """Generate a pixel-art sprite. Returns raw PNG bytes.

    Style suffix (e.g. the `GameDesign.art_style` sentence) is appended to the
    prompt so every sprite in a given session shares a visual lane.
    """
    api_key = os.environ.get("PIXELLAB_API_KEY")
    if not api_key:
        raise PixelLabError("PIXELLAB_API_KEY not set")

    full_prompt = f"{prompt}. {style}" if style else prompt
    body = {
        "description": full_prompt,
        "image_size": {"width": width, "height": height},
        "no_background": True,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(PIXELLAB_ENDPOINT, json=body, headers=headers)
        if resp.status_code >= 400:
            raise PixelLabError(f"pixellab {resp.status_code}: {resp.text[:200]}")
        data = resp.json()

    b64 = data.get("image", {}).get("base64") or data.get("image_base64")
    if not b64:
        raise PixelLabError(f"no image in response: keys={list(data.keys())}")
    return base64.b64decode(b64)
