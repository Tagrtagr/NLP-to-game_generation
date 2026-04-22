"""Pipeline orchestrator.

Chains the five phases and emits a single SSE stream. Owns the shared
RepairBudget (cap=3) so synthesize, build, and QA all spend from the same
counter, preventing the worst-case 2+2+2 = 6-repair stacking the plan
warned about.
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
from .qa import QAResult, run_qa
from .schema import GameDesign
from .sfx import resolve_sfx
from .synthesize import (
    repair_from_build_error,
    repair_from_qa_issue,
    run_synthesize,
)

MAX_QA_ROUNDS = 2  # initial + one budget-gated repair attempt


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
    async def _build_repair(stderr: str) -> None:
        await repair_from_build_error(
            session_id, design, resolved_assets, resolved_sfx, project_dir, stderr
        )

    web_ready = False
    async for ev, wd in run_build(
        session_id, project_dir, budget=budget, repair_fn=_build_repair
    ):
        yield ev
        if wd is not None:
            web_ready = True

    # ---------- Phase 5: Visual QA ---------- #
    qa_result: QAResult | None = None
    if web_ready:
        for qa_round in range(MAX_QA_ROUNDS):
            qa_result = None
            async for ev, r in run_qa(session_id, project_dir):
                yield ev
                if r is not None:
                    qa_result = r

            # Accept: QA inconclusive (None) OR passed OR non-critical.
            # We only spend budget on critical failures.
            if (
                qa_result is None
                or qa_result.ok
                or qa_result.severity != "critical"
            ):
                break
            if qa_round + 1 >= MAX_QA_ROUNDS:
                break
            if not budget.try_consume(f"qa_repair:{qa_round + 1}"):
                yield Event(
                    phase="qa",
                    step="repair",
                    status="error",
                    detail="critical issue but repair budget exhausted",
                )
                break

            yield Event(
                phase="qa",
                step="repair",
                status="start",
                detail=f"patching for {qa_result.issue_kind}: {qa_result.description}",
            )
            try:
                await repair_from_qa_issue(
                    session_id,
                    design,
                    resolved_assets,
                    resolved_sfx,
                    project_dir,
                    qa_result.issue_kind or "unknown",
                    qa_result.description,
                )
            except Exception as e:
                yield Event(
                    phase="qa",
                    step="repair",
                    status="error",
                    detail=f"synthesize repair raised: {type(e).__name__}: {e}",
                )
                break

            # Re-export with no further repairs (budget already spent above).
            # Pass repair_fn=None so run_build won't try to spend again.
            rebuild_ok = False
            async for ev, wd in run_build(
                session_id, project_dir, budget=budget, repair_fn=None
            ):
                yield ev
                if wd is not None:
                    rebuild_ok = True
            if not rebuild_ok:
                break
            # Loop back to re-QA.

    # ---------- Terminal ready event ---------- #
    if web_ready:
        qa_ok = qa_result.ok if qa_result is not None else True
        yield Event(
            phase="qa",
            step="ready",
            status="done" if qa_ok else "progress",
            detail="web build ready" + ("" if qa_ok else " (QA flagged; shipping anyway)"),
            payload={
                "web_rel": f"workspaces/{session_id}/web/index.html",
                "budget_used": budget.used,
                "budget_trace": budget.trace,
                "qa_ok": qa_ok,
                "qa_screenshots": qa_result.screenshots_rel if qa_result else [],
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
