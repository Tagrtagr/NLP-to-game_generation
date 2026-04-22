"""Thin LLM client wrappers.

Deliberately small: `design`, `synthesize`, `qa` each build their own prompts and
pass them here. No prompt-building logic lives in this module.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from typing import Any

# Lazy-imported to keep `import agent` cheap at app startup.
_anthropic_client = None
_gemini_client = None


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai

        _gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _gemini_client


CLAUDE_OPUS_MODEL = "claude-opus-4-7"
CLAUDE_SONNET_MODEL = "claude-sonnet-4-6"
GEMINI_FLASH_MODEL = "gemini-3-flash-preview"


async def claude_json(
    *,
    system: str,
    user: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    model: str = CLAUDE_OPUS_MODEL,
) -> str:
    """Single Claude call returning raw text. Caller parses JSON."""
    client = _anthropic()
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    # Opus 4.7 deprecated `temperature`; Sonnet still accepts it.
    if model != CLAUDE_OPUS_MODEL:
        kwargs["temperature"] = temperature
    # Retry on 429 rate-limit: honor retry-after, else exponential backoff.
    import anthropic
    delay = 2.0
    for attempt in range(4):
        try:
            resp = await client.messages.create(**kwargs)
            break
        except anthropic.RateLimitError as e:
            retry_after = None
            hdrs = getattr(getattr(e, "response", None), "headers", None)
            if hdrs:
                try:
                    retry_after = float(hdrs.get("retry-after") or hdrs.get("x-ratelimit-reset") or 0)
                except ValueError:
                    retry_after = None
            wait = retry_after if retry_after and retry_after > 0 else delay + random.uniform(0, 1)
            if attempt == 3:
                raise
            await asyncio.sleep(min(wait, 60.0))
            delay *= 2
    # Concatenate any text blocks.
    chunks: list[str] = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            chunks.append(block.text)
    return "".join(chunks).strip()


async def gemini_json(
    *,
    system: str,
    user: str,
    temperature: float = 0.2,
) -> str:
    client = _gemini()
    resp = client.models.generate_content(
        model=GEMINI_FLASH_MODEL,
        contents=[{"role": "user", "parts": [{"text": user}]}],
        config={
            "system_instruction": system,
            "temperature": temperature,
            "response_mime_type": "application/json",
        },
    )
    return resp.text.strip()


async def gemini_vision_json(
    *,
    system: str,
    user: str,
    images_png: list[bytes],
    temperature: float = 0.1,
) -> str:
    """Multimodal Gemini call: system + user text + N inline PNGs, JSON response."""
    client = _gemini()
    parts: list[dict] = [{"text": user}]
    for data in images_png:
        import base64

        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(data).decode("ascii"),
                }
            }
        )
    resp = client.models.generate_content(
        model=GEMINI_FLASH_MODEL,
        contents=[{"role": "user", "parts": parts}],
        config={
            "system_instruction": system,
            "temperature": temperature,
            "response_mime_type": "application/json",
        },
    )
    return resp.text.strip()


def extract_json(text: str) -> dict[str, Any]:
    """Tolerant JSON extraction: strips ```json fences, trims to first {...} block."""
    t = text.strip()
    if t.startswith("```"):
        # Strip leading ```json or ``` and trailing ```
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
        t = t.strip()
    # Find outermost braces if there's extra prose.
    if not t.startswith("{"):
        start = t.find("{")
        end = t.rfind("}")
        if start != -1 and end != -1 and end > start:
            t = t[start : end + 1]
    return json.loads(t)
