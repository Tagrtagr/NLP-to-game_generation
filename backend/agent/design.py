"""Phase 1 — Design.

Best-of-3 Opus 4.7 samples at temperatures [0.6, 0.85, 1.0] + Gemini Flash critic
biased against blandness. Every candidate + the critic reason is logged to the
session log directory for debugging and writeup.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .events import Event
from .llm import claude_json, extract_json, gemini_json
from .manifests import fallback_manifest, sfx_manifest
from .paths import session_log_dir
from .prompts import load_prompt
from .schema import GameDesign

TEMPERATURES: tuple[float, ...] = (0.6, 0.85, 1.0)
MAX_RETRIES_PER_CANDIDATE = 1


def _build_user_prompt(user_prompt: str) -> str:
    fb = json.dumps(fallback_manifest(), indent=2)
    sfx = json.dumps(sfx_manifest(), indent=2)
    return (
        f"USER PROMPT:\n{user_prompt}\n\n"
        f"FALLBACK ASSET MANIFEST (pick fallback_role from keys here):\n{fb}\n\n"
        f"SFX MANIFEST (sfx_map values must be keys here):\n{sfx}\n\n"
        "Emit the single GameDesign JSON object now."
    )


async def _one_candidate(
    system: str, user: str, temperature: float
) -> tuple[GameDesign | None, list[dict[str, Any]], list[str]]:
    """Try once, then on ValidationError retry once with the error as feedback.

    Returns (design_or_none, raw_json_dicts_seen, error_strings).
    """
    raws: list[dict[str, Any]] = []
    errs: list[str] = []
    current_user = user
    for _attempt in range(MAX_RETRIES_PER_CANDIDATE + 1):
        try:
            text = await claude_json(system=system, user=current_user, temperature=temperature)
            raw = extract_json(text)
            raws.append(raw)
            return GameDesign.model_validate(raw), raws, errs
        except ValidationError as ve:
            err = str(ve)
            errs.append(err)
            current_user = (
                user
                + "\n\nYour previous response failed schema validation with:\n"
                + err
                + "\n\nEmit a corrected GameDesign JSON object."
            )
        except Exception as e:  # network, JSON-parse, etc.
            errs.append(f"{type(e).__name__}: {e}")
            break
    return None, raws, errs


async def _critic_pick(
    candidates: list[GameDesign], user_prompt: str
) -> tuple[int, str]:
    """Gemini Flash critic. Falls back to index 0 on error (logged upstream)."""
    system = load_prompt("design_critic")
    payload = {
        "user_prompt": user_prompt,
        "candidates": [c.model_dump() for c in candidates],
    }
    user = json.dumps(payload, indent=2)
    try:
        text = await gemini_json(system=system, user=user, temperature=0.2)
        raw = extract_json(text)
        idx = int(raw.get("winner_index", 0))
        reason = str(raw.get("reason", ""))
        if not 0 <= idx < len(candidates):
            idx = 0
            reason = f"(critic returned out-of-range index; defaulted to 0) {reason}"
        return idx, reason
    except Exception as e:
        return 0, f"(critic errored: {type(e).__name__}: {e}; defaulted to 0)"


def _log_candidates(
    session_id: str,
    user_prompt: str,
    raws: list[list[dict[str, Any]]],
    errs: list[list[str]],
    designs: list[GameDesign | None],
    winner_idx: int,
    reason: str,
) -> None:
    log_dir = session_log_dir(session_id)
    blob = {
        "user_prompt": user_prompt,
        "candidates": [
            {
                "temperature": TEMPERATURES[i],
                "raw_responses": raws[i],
                "errors": errs[i],
                "parsed": designs[i].model_dump() if designs[i] is not None else None,
            }
            for i in range(len(TEMPERATURES))
        ],
        "winner_index": winner_idx,
        "critic_reason": reason,
    }
    (log_dir / "design_candidates.json").write_text(json.dumps(blob, indent=2))


async def run_design(
    session_id: str,
    user_prompt: str,
) -> AsyncIterator[tuple[Event, GameDesign | None]]:
    """Async-generator yielding (Event, maybe-final-design) pairs.

    The final yield's GameDesign is the chosen design. Earlier yields have None.
    """
    yield Event(phase="design", step="fanout", status="start", detail="3 candidates"), None

    system = load_prompt("design")
    user = _build_user_prompt(user_prompt)

    results = await asyncio.gather(
        *(_one_candidate(system, user, t) for t in TEMPERATURES),
        return_exceptions=False,
    )
    designs = [r[0] for r in results]
    raws = [r[1] for r in results]
    errs = [r[2] for r in results]

    valid_idxs = [i for i, d in enumerate(designs) if d is not None]
    if not valid_idxs:
        _log_candidates(session_id, user_prompt, raws, errs, designs, -1, "all candidates failed")
        yield (
            Event(
                phase="design",
                step="fanout",
                status="error",
                detail="all 3 candidates failed validation",
                payload={"errors": [e[-1] if e else "" for e in errs]},
            ),
            None,
        )
        return

    yield Event(
        phase="design",
        step="fanout",
        status="progress",
        detail=f"{len(valid_idxs)}/3 valid; running critic",
    ), None

    valid_designs = [designs[i] for i in valid_idxs]  # type: ignore[list-item]
    picked_within_valid, reason = await _critic_pick(valid_designs, user_prompt)
    winner_idx = valid_idxs[picked_within_valid]
    chosen = designs[winner_idx]
    assert chosen is not None

    _log_candidates(session_id, user_prompt, raws, errs, designs, winner_idx, reason)

    yield (
        Event(
            phase="design",
            step="critic",
            status="done",
            detail=reason,
            payload={
                "winner_index": winner_idx,
                "temperature": TEMPERATURES[winner_idx],
                "design": chosen.model_dump(),
            },
        ),
        chosen,
    )
