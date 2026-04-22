"""OpenAI gpt-image-1 client — backgrounds, UI panels, non-pixel 2D.

Returns raw PNG bytes. Higher-level code handles garbage detection + file
placement. Uses the OpenAI async client.
"""
from __future__ import annotations

import base64
import os

SERVICE_NAME = "gpt_image"
MODEL = "gpt-image-1"

# gpt-image-1 only accepts a fixed set of sizes.
VALID_SIZES = {"1024x1024", "1024x1536", "1536x1024", "auto"}


class GptImageError(Exception):
    pass


def _pick_size(width: int | None, height: int | None) -> str:
    if not (width and height):
        return "1024x1024"
    if width > height:
        return "1536x1024"
    if height > width:
        return "1024x1536"
    return "1024x1024"


async def generate_image(
    *,
    prompt: str,
    width: int | None = None,
    height: int | None = None,
    style: str | None = None,
    timeout: float = 25.0,
) -> bytes:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise GptImageError("OPENAI_API_KEY not set")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, timeout=timeout)
    full_prompt = f"{prompt}. {style}" if style else prompt
    size = _pick_size(width, height)
    try:
        resp = await client.images.generate(
            model=MODEL, prompt=full_prompt, size=size, n=1
        )
    except Exception as e:
        raise GptImageError(f"{type(e).__name__}: {e}") from e

    if not resp.data:
        raise GptImageError("empty response")
    b64 = resp.data[0].b64_json
    if not b64:
        raise GptImageError("no b64_json in response")
    return base64.b64decode(b64)
