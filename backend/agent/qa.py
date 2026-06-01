"""Phase 5 — Visual QA.

Playwright (chromium headless) loads the exported web build, polls
`window.__GODOT_READY__` (set by the per-template `autoload/ready_signal.gd`
via JavaScriptBridge), then captures a short interaction sequence. The PNGs
go to Gemini 3 Flash which flags critical rendering and gameplay failures
(blank canvas, pink missing-texture squares, error overlays, broken scale,
or controls that visibly do nothing).

QA is strictly a floor: aesthetic issues are NOT its job. We only trigger
a repair when the game is visibly broken, because any repair spends from
the shared global budget (cap=3) that synthesize + build already drew on.

The web build is served by the same FastAPI that runs this module — we hit
it over HTTP so Godot's fetch()-based loader works normally (file:// would
fail cross-origin for .pck/.wasm).
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from .events import Event
from .llm import extract_json, gemini_vision_json
from .paths import session_log_dir
from .prompts import load_prompt

QA_BASE_URL = os.environ.get("QA_BASE_URL", "http://127.0.0.1:8000")
READY_TIMEOUT_S = 30.0
VIEWPORT = {"width": 1280, "height": 720}
INTERACTION_STEPS = (
    ("ready", None),
    ("after holding ArrowRight", "ArrowRight"),
    ("after holding ArrowUp", "ArrowUp"),
    ("after pressing Space", "Space"),
)


@dataclass
class QAResult:
    ok: bool
    severity: str  # "none" | "critical"
    issue_kind: str | None
    description: str
    screenshots_rel: list[str] = field(default_factory=list)
    browser_diagnostics: list[str] = field(default_factory=list)


async def _capture(
    session_id: str, web_url: str, web_dir: Path
) -> tuple[list[bytes], list[str], list[str], list[str]]:
    """Return screenshots, relative paths, labels, and browser diagnostics."""
    from playwright.async_api import async_playwright

    qa_dir = web_dir.parent / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    images: list[bytes] = []
    rel_paths: list[str] = []
    labels: list[str] = []
    diagnostics: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(viewport=VIEWPORT)
            page = await ctx.new_page()
            def _on_console(msg) -> None:
                if msg.type in {"error", "warning"}:
                    diagnostics.append(f"console.{msg.type}: {msg.text}")

            page.on("console", _on_console)
            page.on("pageerror", lambda exc: diagnostics.append(f"pageerror: {exc}"))
            resp = await page.goto(web_url, wait_until="load")
            status = resp.status if resp else None
            if status is None or status >= 400:
                raise RuntimeError(f"web build URL returned HTTP {status}: {web_url}")
            await page.wait_for_function(
                "window.__GODOT_READY__ === true",
                timeout=READY_TIMEOUT_S * 1000,
            )
            await page.mouse.click(VIEWPORT["width"] / 2, VIEWPORT["height"] / 2)
            for i, (label, key) in enumerate(INTERACTION_STEPS):
                if key == "Space":
                    await page.keyboard.press(key)
                    await asyncio.sleep(0.5)
                elif key:
                    await page.keyboard.down(key)
                    await asyncio.sleep(0.8)
                    await page.keyboard.up(key)
                    await asyncio.sleep(0.2)
                png = await page.screenshot(type="png", full_page=False)
                images.append(png)
                labels.append(label)
                fname = f"qa_{i}_{label.lower().replace(' ', '_')}.png"
                (qa_dir / fname).write_bytes(png)
                rel_paths.append(f"workspaces/{session_id}/qa/{fname}")
        finally:
            await browser.close()

    return images, rel_paths, labels, diagnostics


async def _review(images: list[bytes], labels: list[str], diagnostics: list[str]) -> QAResult:
    system = load_prompt("qa")
    diag_text = "\n".join(f"- {d}" for d in diagnostics[-20:]) or "- none"
    user = (
        "Screenshots attached in this order:\n"
        + "\n".join(f"{i + 1}. {label}" for i, label in enumerate(labels))
        + "\n\nBrowser/runtime diagnostics captured during the sequence:\n"
        + diag_text
        + "\n\n"
        "Return the single JSON object defined in the system prompt."
    )
    text = await gemini_vision_json(
        system=system, user=user, images_png=images, temperature=0.1
    )
    raw = extract_json(text)
    ok = bool(raw.get("ok"))
    severity = str(raw.get("severity") or ("none" if ok else "critical"))
    return QAResult(
        ok=ok,
        severity=severity,
        issue_kind=raw.get("issue_kind") or None,
        description=str(raw.get("description") or ""),
        browser_diagnostics=diagnostics,
    )


def _log(session_id: str, entries: list[dict]) -> None:
    (session_log_dir(session_id) / "qa.json").write_text(json.dumps(entries, indent=2))


async def run_qa(
    session_id: str,
    project_dir: Path,
) -> AsyncIterator[tuple[Event, QAResult | None]]:
    """Async generator: (Event, result-on-final-yield).

    Never raises — Playwright/WebGL/headless failures on CI etc. are
    surfaced as an error event and a None result, and the pipeline's
    caller treats that the same as 'QA inconclusive, ship what we have'.
    """
    web_dir = project_dir.parent / "web"
    if not (web_dir / "index.html").exists():
        yield (
            Event(
                phase="qa",
                step="capture",
                status="error",
                detail="web/index.html missing; nothing to QA",
            ),
            None,
        )
        return

    web_url = f"{QA_BASE_URL}/workspaces/{session_id}/web/index.html"
    yield (
        Event(
            phase="qa",
            step="capture",
            status="start",
            detail=f"polling __GODOT_READY__ at {web_url}",
        ),
        None,
    )

    try:
        images, shot_rels, labels, diagnostics = await _capture(session_id, web_url, web_dir)
    except Exception as e:
        _log(session_id, [{"stage": "capture", "error": f"{type(e).__name__}: {e}"}])
        yield (
            Event(
                phase="qa",
                step="capture",
                status="error",
                detail=f"{type(e).__name__}: {e}",
            ),
            None,
        )
        return

    yield (
        Event(
            phase="qa",
            step="capture",
            status="done",
            detail=f"{len(images)} screenshots",
            payload={"screenshots": shot_rels, "labels": labels},
        ),
        None,
    )

    try:
        result = await _review(images, labels, diagnostics)
    except Exception as e:
        _log(
            session_id,
            [{"stage": "review", "error": f"{type(e).__name__}: {e}", "shots": shot_rels}],
        )
        yield (
            Event(
                phase="qa",
                step="review",
                status="error",
                detail=f"gemini review failed: {type(e).__name__}: {e}",
            ),
            None,
        )
        return

    result.screenshots_rel = shot_rels
    _log(
        session_id,
        [
            {
                "stage": "review",
                "ok": result.ok,
                "severity": result.severity,
                "issue_kind": result.issue_kind,
                "description": result.description,
                "shots": shot_rels,
                "labels": labels,
                "browser_diagnostics": diagnostics[-20:],
            }
        ],
    )

    yield (
        Event(
            phase="qa",
            step="review",
            status="done" if result.ok else "progress",
            detail=(
                "pass"
                if result.ok
                else f"{result.issue_kind or 'issue'}: {result.description}"
            ),
            payload={
                "ok": result.ok,
                "severity": result.severity,
                "issue_kind": result.issue_kind,
                "screenshots": shot_rels,
                "browser_diagnostics": result.browser_diagnostics[-20:],
            },
        ),
        result,
    )
