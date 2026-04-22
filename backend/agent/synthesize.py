"""Phase 3 — Synthesize.

Claude Opus 4.7 turns (GameDesign + resolved assets/SFX + template file tree +
Godot context) into a strict JSON edit plan. We copy the chosen template into
the session workspace, apply the plan (path-scoped writes only), then run
structural sanity checks:

- every .gd starts with `extends` (optionally preceded by `class_name`)
- balanced parens / braces / brackets in each .gd
- every `res://` reference points to a file that actually exists on disk
- every `Input.is_action_*("name")` uses an action declared in project.godot

On sanity failure, we feed the specific violations back and ask for a fix,
spending from the shared `RepairBudget` (cap=3 across synthesize + build +
QA for the whole session).
"""
from __future__ import annotations

import json
import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator

from .assets import ResolvedAsset
from .budget import RepairBudget
from .events import Event
from .llm import CLAUDE_SONNET_MODEL, claude_json, extract_json
from .paths import CONTEXT_DIR, TEMPLATES_DIR, session_dir, session_log_dir
from .prompts import load_prompt
from .schema import GameDesign
from .sfx import ResolvedSfx

MAX_CONTEXT_FILE_BYTES = 40_000
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".ttf", ".otf", ".ogg", ".wav", ".mp3", ".glb", ".gltf", ".bin"}


class FileEdit(BaseModel):
    path: str
    content: str

    @field_validator("path")
    @classmethod
    def _safe_path(cls, v: str) -> str:
        if not v or v.startswith("/") or ".." in Path(v).parts:
            raise ValueError(f"path '{v}' must be project-relative with no '..'")
        return v


class EditPlan(BaseModel):
    files: list[FileEdit]


# --------------------------------------------------------------------------- #
# Template copy + context building                                            #
# --------------------------------------------------------------------------- #


def _copy_template(design: GameDesign, session_id: str) -> Path:
    src = TEMPLATES_DIR / design.template
    sess = session_dir(session_id)
    dst = sess / "project"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    # Mirror resolved assets + SFX into the project so `res://assets/...` and
    # `res://sfx/...` paths that synthesize emits actually resolve.
    for sub in ("assets", "sfx"):
        src_sub = sess / sub
        if src_sub.exists():
            shutil.copytree(src_sub, dst / sub, dirs_exist_ok=True)
    return dst


def _tree_summary(root: Path) -> str:
    out: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() in SKIP_SUFFIXES:
            continue
        rel = p.relative_to(root)
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        if len(text) > MAX_CONTEXT_FILE_BYTES:
            text = text[:MAX_CONTEXT_FILE_BYTES] + "\n# ...[truncated]"
        out.append(f"=== {rel} ===\n{text}")
    return "\n\n".join(out)


def _context_snippets() -> str:
    parts: list[str] = []
    for name in ("api_cheatsheet.md", "shader_snippets.md", "per_template_notes.md"):
        p = CONTEXT_DIR / name
        if p.exists():
            parts.append(f"=== {name} ===\n{p.read_text()}")
    return "\n\n".join(parts)


def _build_user_prompt(
    design: GameDesign,
    resolved_assets: list[ResolvedAsset],
    resolved_sfx: list[ResolvedSfx],
    template_tree: str,
    ctx: str,
) -> str:
    assets_manifest = [
        {
            "asset_id": r.asset_id,
            "role": r.role,
            "kind": r.kind,
            "res_path": f"res://{r.rel_path}",
            "source": r.source,
        }
        for r in resolved_assets
    ]
    sfx_entries = [
        {"event": s.event, "key": s.key, "res_path": f"res://{s.rel_path}"}
        for s in resolved_sfx
    ]
    return (
        f"GAME DESIGN:\n{design.model_dump_json(indent=2)}\n\n"
        f"RESOLVED ASSETS (every res_path below already exists on disk):\n"
        f"{json.dumps(assets_manifest, indent=2)}\n\n"
        f"RESOLVED SFX:\n{json.dumps(sfx_entries, indent=2)}\n\n"
        f"TEMPLATE FILE TREE (current contents):\n{template_tree}\n\n"
        f"GODOT CONTEXT:\n{ctx}\n\n"
        'Emit a single JSON object: {"files":[{"path":"...","content":"..."}]}.'
        " Only include files you're creating or changing."
    )


def _with_feedback(user: str, errs: list[str]) -> str:
    joined = "\n".join(f"- {e}" for e in errs)
    return (
        user
        + "\n\nYour previous edit plan failed with:\n"
        + joined
        + "\n\nEmit a corrected plan. Same JSON format."
    )


# --------------------------------------------------------------------------- #
# Plan application                                                            #
# --------------------------------------------------------------------------- #


def _apply_plan(project_dir: Path, plan: EditPlan) -> list[str]:
    applied: list[str] = []
    for fe in plan.files:
        dst = (project_dir / fe.path).resolve()
        # Guard against any resolve-based escape even though field_validator caught '..'.
        if not str(dst).startswith(str(project_dir.resolve())):
            raise ValueError(f"path '{fe.path}' escaped project dir")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(fe.content)
        applied.append(fe.path)
    return applied


# --------------------------------------------------------------------------- #
# Sanity checks                                                               #
# --------------------------------------------------------------------------- #


_RES_PATH_RE = re.compile(r"""["'](res://[^"']+)["']""")
_ACTION_RE = re.compile(
    r"""is_action_(?:pressed|just_pressed|just_released)\(\s*["']([^"']+)["']\s*\)"""
)


def _gd_has_extends(text: str) -> bool:
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("class_name "):
            continue  # allow class_name then extends
        return s.startswith("extends ")
    return False


def _balanced(text: str, pairs: list[tuple[str, str]]) -> list[str]:
    errs = []
    for o, c in pairs:
        if text.count(o) != text.count(c):
            errs.append(f"unbalanced '{o}{c}' ({text.count(o)}/{text.count(c)})")
    return errs


def _parse_input_actions(project_godot_text: str) -> set[str]:
    in_input = False
    actions: set[str] = set()
    for line in project_godot_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_input = stripped == "[input]"
            continue
        if in_input:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if m:
                actions.add(m.group(1))
    return actions


def sanity_check(project_dir: Path) -> list[str]:
    errs: list[str] = []

    proj_godot = project_dir / "project.godot"
    actions: set[str] = set()
    if proj_godot.exists():
        actions = _parse_input_actions(proj_godot.read_text())
    else:
        errs.append("project.godot is missing")

    for p in project_dir.rglob("*.gd"):
        rel = p.relative_to(project_dir)
        text = p.read_text()
        if not _gd_has_extends(text):
            errs.append(f"{rel}: missing `extends` on first non-comment line")
        for e in _balanced(text, [("(", ")"), ("{", "}"), ("[", "]")]):
            errs.append(f"{rel}: {e}")
        for act in _ACTION_RE.findall(text):
            if act not in actions:
                errs.append(
                    f"{rel}: Input action '{act}' not declared in project.godot [input]"
                )

    for p in (
        list(project_dir.rglob("*.gd"))
        + list(project_dir.rglob("*.tscn"))
        + list(project_dir.rglob("*.tres"))
        + ([proj_godot] if proj_godot.exists() else [])
    ):
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        rel = p.relative_to(project_dir)
        for ref in _RES_PATH_RE.findall(text):
            target = project_dir / ref[len("res://") :]
            if not target.exists():
                errs.append(f"{rel}: references missing '{ref}'")

    # Scene/resource files must declare resources as [ext_resource] and
    # reference them via ExtResource("id") / SubResource("id"). GDScript's
    # load()/preload() calls parse silently in the editor but fail at
    # runtime with "Parse error" on line N, producing a blank canvas that
    # neither export nor asset-path checks catch.
    for p in list(project_dir.rglob("*.tscn")) + list(project_dir.rglob("*.tres")):
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        rel = p.relative_to(project_dir)
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith("[") or s.startswith("#") or not s:
                continue
            if re.search(r"\b(?:pre)?load\s*\(", s):
                errs.append(
                    f"{rel}:{i}: '{s[:60]}' — .tscn/.tres cannot use load()/preload(); "
                    f"declare as [ext_resource] at top of file and reference via ExtResource(\"id\")"
                )

    return errs


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #


async def run_synthesize(
    session_id: str,
    design: GameDesign,
    resolved_assets: list[ResolvedAsset],
    resolved_sfx: list[ResolvedSfx],
    budget: RepairBudget,
) -> AsyncIterator[tuple[Event, Path | None]]:
    """Async generator: (Event, project_dir-if-ready).

    The final yield's path is non-None on success OR on budget-exhausted-but-
    shippable (project_dir exists with template+applied edits). Callers
    decide whether to continue to build or abort.
    """
    project_dir = _copy_template(design, session_id)
    yield (
        Event(
            phase="synthesize",
            step="copy",
            status="done",
            detail=f"copied template '{design.template}' to workspace",
        ),
        None,
    )

    system = load_prompt("synthesize")
    tree = _tree_summary(project_dir)
    ctx = _context_snippets()
    user = _build_user_prompt(design, resolved_assets, resolved_sfx, tree, ctx)

    log: list[dict] = []
    last_errs: list[str] = []
    attempt = 0

    while True:
        # First attempt is free; every subsequent attempt spends one from the
        # shared global budget (cap=3 across synthesize+build+qa).
        if attempt > 0 and not budget.try_consume(f"synthesize_repair:{attempt}"):
            break
        yield (
            Event(
                phase="synthesize",
                step="claude",
                status="start",
                detail="first pass" if attempt == 0 else f"repair {attempt}",
            ),
            None,
        )
        try:
            text = await claude_json(
                system=system, user=user, temperature=0.4, max_tokens=16000, model=CLAUDE_SONNET_MODEL
            )
            raw = extract_json(text)
            plan = EditPlan.model_validate(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            last_errs = [f"edit plan did not parse: {e}"]
            log.append({"attempt": attempt, "stage": "parse", "errors": last_errs})
            user = _with_feedback(user, last_errs)
            attempt += 1
            continue
        except Exception as e:
            yield (
                Event(
                    phase="synthesize",
                    step="claude",
                    status="error",
                    detail=f"{type(e).__name__}: {e}",
                ),
                None,
            )
            _write_log(session_id, log)
            return

        try:
            applied = _apply_plan(project_dir, plan)
        except ValueError as e:
            last_errs = [str(e)]
            log.append({"attempt": attempt, "stage": "apply", "errors": last_errs})
            user = _with_feedback(user, last_errs)
            attempt += 1
            continue

        yield (
            Event(
                phase="synthesize",
                step="apply",
                status="progress",
                detail=f"{len(applied)} files written",
                payload={"files": applied},
            ),
            None,
        )

        errs = sanity_check(project_dir)
        log.append(
            {
                "attempt": attempt,
                "stage": "sanity",
                "files_applied": applied,
                "errors": errs,
            }
        )
        if not errs:
            _write_log(session_id, log)
            yield (
                Event(
                    phase="synthesize",
                    step="sanity",
                    status="done",
                    detail="all checks pass",
                ),
                project_dir,
            )
            return

        last_errs = errs
        user = _with_feedback(user, errs)
        yield (
            Event(
                phase="synthesize",
                step="sanity",
                status="progress",
                detail=f"{len(errs)} issues; repairing",
                payload={"errors": errs[:10]},
            ),
            None,
        )
        attempt += 1

    _write_log(session_id, log)
    yield (
        Event(
            phase="synthesize",
            step="sanity",
            status="error",
            detail=f"sanity failures; budget remaining={budget.remaining}",
            payload={"errors": last_errs[:10]},
        ),
        project_dir,
    )


def _write_log(session_id: str, log: list[dict]) -> None:
    (session_log_dir(session_id) / "synthesize.json").write_text(json.dumps(log, indent=2))


async def repair_from_build_error(
    session_id: str,
    design: GameDesign,
    resolved_assets: list[ResolvedAsset],
    resolved_sfx: list[ResolvedSfx],
    project_dir: Path,
    stderr: str,
) -> None:
    """One-shot patch after a godot export failure.

    Reads the current (post-first-synthesize) project tree, pairs it with
    the export stderr, asks Claude for a corrective edit plan, applies it.
    No sanity loop — the export will re-run and tell us if it's still broken.
    Budget accounting lives in run_build, which calls us at most once per
    retry it spends.
    """
    system = load_prompt("synthesize")
    tree = _tree_summary(project_dir)
    ctx = _context_snippets()
    base = _build_user_prompt(design, resolved_assets, resolved_sfx, tree, ctx)
    user = (
        base
        + "\n\nThe previous export failed. godot --export-release stderr tail:\n"
        + stderr[-2500:]
        + "\n\nEmit a corrective edit plan in the same JSON format."
    )
    text = await claude_json(system=system, user=user, temperature=0.3, max_tokens=16000, model=CLAUDE_SONNET_MODEL)
    raw = extract_json(text)
    plan = EditPlan.model_validate(raw)
    _apply_plan(project_dir, plan)
    # Append to the same log file for traceability.
    log_path = session_log_dir(session_id) / "synthesize.json"
    existing = json.loads(log_path.read_text()) if log_path.exists() else []
    existing.append(
        {
            "stage": "build_repair",
            "stderr_tail": stderr[-1000:],
            "files_applied": [fe.path for fe in plan.files],
        }
    )
    log_path.write_text(json.dumps(existing, indent=2))


async def repair_from_qa_issue(
    session_id: str,
    design: GameDesign,
    resolved_assets: list[ResolvedAsset],
    resolved_sfx: list[ResolvedSfx],
    project_dir: Path,
    issue_kind: str,
    description: str,
) -> None:
    """One-shot patch after visual QA flags a critical rendering issue.

    No sanity loop — the re-export + re-QA will tell us if it stuck.
    Budget accounting happens in the pipeline, which only calls us when
    it has already consumed a qa_repair slot from the shared budget.
    """
    system = load_prompt("synthesize")
    tree = _tree_summary(project_dir)
    ctx = _context_snippets()
    base = _build_user_prompt(design, resolved_assets, resolved_sfx, tree, ctx)
    user = (
        base
        + "\n\nVisual QA on the freshly-built game flagged a CRITICAL rendering issue.\n"
        + f"issue_kind: {issue_kind}\n"
        + f"description: {description}\n\n"
        + "Likely culprits by issue_kind:\n"
        + "- blank: main scene not set in project.godot, or camera looking"
        " the wrong way, or the root node has no visible children.\n"
        + "- missing_texture: a Sprite2D/MeshInstance3D points at a path"
        " that doesn't resolve; check every texture/mesh assignment.\n"
        + "- error_overlay: a runtime error is firing on _ready; fix the"
        " script causing it.\n"
        + "- broken_scale: a node's scale or a camera's zoom/position is"
        " off; do NOT touch collision shapes on the humanoid — only the"
        " mesh scale or camera.\n\n"
        + "Emit a corrective edit plan in the same JSON format."
    )
    text = await claude_json(system=system, user=user, temperature=0.3, max_tokens=16000, model=CLAUDE_SONNET_MODEL)
    raw = extract_json(text)
    plan = EditPlan.model_validate(raw)
    _apply_plan(project_dir, plan)
    log_path = session_log_dir(session_id) / "synthesize.json"
    existing = json.loads(log_path.read_text()) if log_path.exists() else []
    existing.append(
        {
            "stage": "qa_repair",
            "issue_kind": issue_kind,
            "description": description,
            "files_applied": [fe.path for fe in plan.files],
        }
    )
    log_path.write_text(json.dumps(existing, indent=2))
