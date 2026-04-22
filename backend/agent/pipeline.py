"""Pipeline orchestrator.

Chains the five phases and emits a single SSE stream. Owns the shared
RepairBudget (cap=3) so synthesize and build spend from the same counter,
preventing the worst-case 2+2+2 = 6-repair stacking the plan warned about.

Phase 5 (visual QA) is a stub in this commit — it lands in step 12.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from .assets import ResolvedAsset, resolve_all
from .breaker import CircuitBreaker
from .budget import RepairBudget
from .build import run_build
from .design import run_design
from .events import Event
from .schema import GameDesign
from .sfx import resolve_sfx
from .synthesize import repair_from_build_error, run_synthesize


async def run_pipeline(session_id: str, user_prompt: str) -> AsyncIterator[Event]:
    budget = RepairBudget(cap=3)

    yield Event(
        phase="design",
        step="pipeline",
        status="start",
        detail=f"session {session_id}",
        payload={"budget_cap": budget.cap},
    )

    # ---------- Phase 1: Design ---------- #
    design: GameDesign | None = None
    async for ev, d in run_design(session_id, user_prompt):
        yield ev
        if d is not None:
            design = d
    if design is None:
        yield Event(
            phase="design",
            step="pipeline",
            status="error",
            detail="design phase produced no valid candidate; aborting",
        )
        return

    # ---------- Phase 2: Assets ---------- #
    breaker = CircuitBreaker()
    resolved_assets: list[ResolvedAsset] = []
    async for ev, ra in resolve_all(design, session_id, breaker):
        yield ev
        if ra is not None:
            resolved_assets.append(ra)

    resolved_sfx = resolve_sfx(design, session_id)
    yield Event(
        phase="assets",
        step="sfx",
        status="done",
        detail=f"{len(resolved_sfx)} sfx resolved",
        payload={"sfx": [s.rel_path for s in resolved_sfx]},
    )

    # ---------- Phase 3: Synthesize ---------- #
    project_dir: Path | None = None
    async for ev, pd in run_synthesize(
        session_id, design, resolved_assets, resolved_sfx, budget=budget
    ):
        yield ev
        if pd is not None:
            project_dir = pd
    if project_dir is None:
        yield Event(
            phase="synthesize",
            step="pipeline",
            status="error",
            detail="synthesize produced no project dir; aborting",
        )
        return

    # ---------- Phase 4: Build ---------- #
    async def _repair(stderr: str) -> None:
        await repair_from_build_error(
            session_id, design, resolved_assets, resolved_sfx, project_dir, stderr
        )

    web_ready = False
    async for ev, wd in run_build(
        session_id, project_dir, budget=budget, repair_fn=_repair
    ):
        yield ev
        if wd is not None:
            web_ready = True

    # ---------- Phase 5: QA ---------- #
    # Visual QA lands in step 12. For now, if the build succeeded we report
    # ready; otherwise we surface the partial state so the iframe can still
    # attempt to load whatever's there.
    if web_ready:
        yield Event(
            phase="qa",
            step="ready",
            status="done",
            detail="web build ready",
            payload={
                "web_rel": f"workspaces/{session_id}/web/index.html",
                "budget_used": budget.used,
                "budget_trace": budget.trace,
            },
        )
    else:
        yield Event(
            phase="qa",
            step="ready",
            status="error",
            detail="build failed; nothing to QA",
            payload={"budget_used": budget.used, "budget_trace": budget.trace},
        )
