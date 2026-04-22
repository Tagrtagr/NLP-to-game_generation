"""Garbage detection for generated assets.

Per the plan:
- 2D images: PNG < 1KB, stddev < 3 across all channels, or fully transparent.
- Tripo meshes (step 7): GLB < 10KB, vertex count < 24, bbox near-zero, or
  scale mis-match vs expected_bbox. Those live in clients/tripo.py.
"""
from __future__ import annotations

import io

from PIL import Image, ImageStat


class GarbageOutput(Exception):
    """Raised when a generated asset fails sanity checks."""


MIN_PNG_BYTES = 1024
MIN_STDDEV = 3.0


def check_2d_image(data: bytes) -> None:
    """Raises GarbageOutput if the image is trivially bad."""
    if len(data) < MIN_PNG_BYTES:
        raise GarbageOutput(f"image too small: {len(data)} bytes")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise GarbageOutput(f"cannot decode image: {e}") from e

    if img.mode == "RGBA":
        alpha = img.getchannel("A")
        if ImageStat.Stat(alpha).extrema[0] == (0, 0):
            raise GarbageOutput("image fully transparent")
        rgb = img.convert("RGB")
    else:
        rgb = img.convert("RGB")

    stddev = ImageStat.Stat(rgb).stddev
    if all(s < MIN_STDDEV for s in stddev):
        raise GarbageOutput(f"image near-uniform (stddev={stddev})")
