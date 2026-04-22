"""Phase 4 — Build.

Runs `godot --headless --path <project> --export-release "Web" ../web/index.html`
and streams stdout/stderr back as SSE events.

The preset (template `export_presets.cfg`) pins `variant/thread_support=false` so
the WASM export is single-threaded — no SharedArrayBuffer, no COOP/COEP, works
in every iframe.

On non-zero exit we feed stderr + touched files back to Claude via synthesize's
repair path and rebuild — bounded here by `max_repairs` (the pipeline orchestrator
in step 10 passes whatever's left of the global session budget).
"""
from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from .events import Event
from .paths import BACKEND_DIR, session_dir, session_log_dir

PRESET_NAME = "Web"
EXPORT_RELATIVE = "../web/index.html"
DEFAULT_TIMEOUT = 90.0

# Priority: GODOT_BIN env var (CI), then repo-local ./bin/godot from bootstrap.sh,
# then PATH lookup. Pipeline should error loudly if none resolves.
def godot_bin() -> str:
    env = os.environ.get("GODOT_BIN")
    if env:
        return env
    repo_local = BACKEND_DIR.parent / "bin" / "godot"
    if repo_local.exists():
        return str(repo_local)
    which = shutil.which("godot") or shutil.which("godot4")
    if which:
        return which
    raise RuntimeError(
        "No Godot binary found. Set GODOT_BIN or run scripts/bootstrap.sh to install ./bin/godot."
    )


@dataclass
class BuildResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    web_dir: Path | None  # path to dir containing index.html when ok


async def _run_export(project_dir: Path, web_dir: Path, timeout: float) -> BuildResult:
    web_dir.mkdir(parents=True, exist_ok=True)
    # The export preset's export_path is `../web/index.html` relative to project_dir;
    # we passed web_dir = project_dir.parent / "web" when calling so paths match.
    cmd = [
        godot_bin(),
        "--headless",
        "--path",
        str(project_dir),
        "--export-release",
        PRESET_NAME,
        EXPORT_RELATIVE,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return BuildResult(
            ok=False,
            returncode=-1,
            stdout="",
            stderr=f"godot export timed out after {timeout}s",
            web_dir=None,
        )

    stdout = out_b.decode("utf-8", errors="replace")
    stderr = err_b.decode("utf-8", errors="replace")
    index = web_dir / "index.html"
    ok = proc.returncode == 0 and index.exists()
    return BuildResult(
        ok=ok,
        returncode=proc.returncode or 0,
        stdout=stdout,
        stderr=stderr,
        web_dir=web_dir if ok else None,
    )


def _log_build(session_id: str, attempts: list[dict]) -> None:
    (session_log_dir(session_id) / "build.json").write_text(
        __import__("json").dumps(attempts, indent=2)
    )


async def run_build(
    session_id: str,
    project_dir: Path,
    *,
    max_repairs: int = 1,
    timeout: float = DEFAULT_TIMEOUT,
    repair_fn=None,
) -> AsyncIterator[tuple[Event, Path | None]]:
    """Export the project to web. On failure, call repair_fn(stderr) if provided,
    which should mutate project_dir in place, then retry.

    Final yield's path is the web dir (containing index.html) on success, else None.
    """
    web_dir = project_dir.parent / "web"
    attempts: list[dict] = []

    for attempt in range(max_repairs + 1):
        yield (
            Event(
                phase="build",
                step="export",
                status="start",
                detail=f"godot export ({'first' if attempt == 0 else f'repair {attempt}'})",
            ),
            None,
        )

        try:
            result = await _run_export(project_dir, web_dir, timeout=timeout)
        except RuntimeError as e:
            # Missing godot binary — terminal.
            yield (
                Event(phase="build", step="export", status="error", detail=str(e)),
                None,
            )
            _log_build(session_id, attempts)
            return

        attempts.append(
            {
                "attempt": attempt,
                "returncode": result.returncode,
                "stderr_tail": result.stderr[-2000:],
                "ok": result.ok,
            }
        )

        if result.ok:
            _log_build(session_id, attempts)
            yield (
                Event(
                    phase="build",
                    step="export",
                    status="done",
                    detail="web export succeeded",
                    payload={"web_rel": "web/index.html"},
                ),
                result.web_dir,
            )
            return

        yield (
            Event(
                phase="build",
                step="export",
                status="progress" if attempt < max_repairs else "error",
                detail=(
                    f"rc={result.returncode}; "
                    + ("repairing" if attempt < max_repairs and repair_fn else "no repair")
                ),
                payload={"stderr_tail": result.stderr[-1200:]},
            ),
            None,
        )

        if attempt >= max_repairs or repair_fn is None:
            break

        try:
            await repair_fn(result.stderr)
        except Exception as e:
            yield (
                Event(
                    phase="build",
                    step="repair",
                    status="error",
                    detail=f"repair_fn raised: {type(e).__name__}: {e}",
                ),
                None,
            )
            break

    _log_build(session_id, attempts)
    yield (
        Event(
            phase="build",
            step="export",
            status="error",
            detail=f"build failed after {len(attempts)} attempt(s)",
        ),
        None,
    )
