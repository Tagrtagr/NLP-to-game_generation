"""Tripo v2.5 client — text-to-3D-model (GLB output, fast mode).

Tripo is an async generation API: submit a task, poll for completion, then
download the GLB. We treat 3D as flaky — short effective timeout, strict
scale-sanity check, aggressive fallback posture (enforced by the caller).

API:
  POST https://api.tripo3d.ai/v2/openapi/task        {type, prompt, model_version}
  GET  https://api.tripo3d.ai/v2/openapi/task/{id}   {status, output: {model}}
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
from typing import Any

import httpx

SERVICE_NAME = "tripo"
TRIPO_BASE = "https://api.tripo3d.ai/v2/openapi"
MODEL_VERSION = "v2.5-20250123"  # fast mode
POLL_INTERVAL = 2.0


class TripoError(Exception):
    pass


class ScaleMismatch(Exception):
    """Generated mesh's bbox diagonal is wildly off from the declared expected_bbox.

    Common Tripo failure mode that otherwise black-screens the camera.
    """


async def _submit(client: httpx.AsyncClient, headers: dict[str, str], prompt: str) -> str:
    body = {"type": "text_to_model", "prompt": prompt, "model_version": MODEL_VERSION}
    resp = await client.post(f"{TRIPO_BASE}/task", json=body, headers=headers)
    if resp.status_code >= 400:
        raise TripoError(f"submit {resp.status_code}: {resp.text[:200]}")
    data = resp.json().get("data", {})
    task_id = data.get("task_id")
    if not task_id:
        raise TripoError(f"no task_id: {data}")
    return task_id


async def _poll(
    client: httpx.AsyncClient, headers: dict[str, str], task_id: str, deadline: float
) -> str:
    loop = asyncio.get_event_loop()
    while loop.time() < deadline:
        resp = await client.get(f"{TRIPO_BASE}/task/{task_id}", headers=headers)
        if resp.status_code >= 400:
            raise TripoError(f"poll {resp.status_code}: {resp.text[:200]}")
        data = resp.json().get("data", {})
        status = data.get("status")
        if status == "success":
            model_url = (data.get("output") or {}).get("model") or (
                data.get("result") or {}
            ).get("model")
            if not model_url:
                raise TripoError(f"no model url: {data}")
            return model_url
        if status in ("failed", "cancelled", "expired"):
            raise TripoError(f"task {status}: {data.get('error') or data}")
        await asyncio.sleep(POLL_INTERVAL)
    raise asyncio.TimeoutError(f"tripo task {task_id} did not finish before deadline")


async def generate_mesh(
    *,
    prompt: str,
    style: str | None = None,
    timeout: float = 150.0,
) -> bytes:
    """Submit text-to-model, poll to completion, download GLB. Returns raw bytes."""
    api_key = os.environ.get("TRIPO_API_KEY")
    if not api_key:
        raise TripoError("TRIPO_API_KEY not set")

    full_prompt = f"{prompt}. {style}" if style else prompt
    headers = {"Authorization": f"Bearer {api_key}"}

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout

    async with httpx.AsyncClient(timeout=30.0) as client:
        task_id = await _submit(client, headers, full_prompt)
        model_url = await _poll(client, headers, task_id, deadline)
        resp = await client.get(model_url)
        if resp.status_code >= 400:
            raise TripoError(f"download {resp.status_code}")
        return resp.content


# --------------------------------------------------------------------------- #
# Garbage / scale sanity — imported by assets.py                              #
# --------------------------------------------------------------------------- #

MIN_GLB_BYTES = 10 * 1024
SCALE_MISMATCH_FACTOR = 10.0


def glb_bbox_diagonal(data: bytes) -> float:
    """Largest VEC3 accessor bbox diagonal in the GLB.

    POSITION accessors in glTF must declare min/max. We scan all VEC3
    accessors with min+max and take the largest diagonal — in practice the
    mesh's position accessor. Returns 0.0 if none found.
    """
    if len(data) < 20 or data[:4] != b"glTF":
        return 0.0
    json_len = struct.unpack_from("<I", data, 12)[0]
    try:
        doc = json.loads(data[20 : 20 + json_len])
    except Exception:
        return 0.0
    best = 0.0
    for acc in doc.get("accessors", []):
        if acc.get("type") != "VEC3":
            continue
        mn, mx = acc.get("min"), acc.get("max")
        if not (mn and mx and len(mn) == 3 and len(mx) == 3):
            continue
        diag = sum((mx[i] - mn[i]) ** 2 for i in range(3)) ** 0.5
        if diag > best:
            best = diag
    return best


def check_glb(data: bytes, expected_bbox: float | None) -> None:
    """Raises TripoError (too small / unparseable) or ScaleMismatch."""
    if len(data) < MIN_GLB_BYTES:
        raise TripoError(f"glb too small: {len(data)} bytes")
    diag = glb_bbox_diagonal(data)
    if diag == 0.0:
        raise TripoError("glb has no position bbox")
    if expected_bbox is not None and expected_bbox > 0:
        ratio = diag / expected_bbox
        if ratio > SCALE_MISMATCH_FACTOR or ratio < 1.0 / SCALE_MISMATCH_FACTOR:
            raise ScaleMismatch(
                f"bbox diagonal {diag:.2f}m vs expected {expected_bbox:.2f}m "
                f"(ratio={ratio:.2f})"
            )


def get_mesh_summary(data: bytes) -> dict[str, Any]:
    """Small debug info dict logged to session."""
    return {"bytes": len(data), "bbox_diagonal": round(glb_bbox_diagonal(data), 3)}
