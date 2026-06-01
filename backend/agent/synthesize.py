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
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator

from .assets import ResolvedAsset
from .budget import RepairBudget
from .events import Event
from .llm import CLAUDE_SONNET_MODEL, claude_json, extract_json
from .paths import CONTEXT_DIR, TEMPLATES_DIR, session_dir, session_log_dir
from .prompts import load_prompt
from .schema import GameDesign, TemplateId
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


def _apply_repair_plan(
    project_dir: Path, plan: EditPlan, template: TemplateId | None = None
) -> list[str]:
    """Apply a repair atomically and require the project to stay structurally sane."""
    backup = project_dir.parent / f"._repair_backup_{uuid.uuid4().hex}"
    shutil.copytree(project_dir, backup)
    try:
        applied = _apply_plan(project_dir, plan)
        errs = sanity_check(project_dir, template=template)
        if errs:
            raise ValueError("repair produced sanity errors:\n" + "\n".join(f"- {e}" for e in errs[:20]))
    except Exception:
        if project_dir.exists():
            shutil.rmtree(project_dir)
        shutil.move(str(backup), str(project_dir))
        raise
    else:
        shutil.rmtree(backup)
        return applied


# --------------------------------------------------------------------------- #
# Sanity checks                                                               #
# --------------------------------------------------------------------------- #


_RES_PATH_RE = re.compile(r"""["'](res://[^"']+)["']""")
_ACTION_RE = re.compile(
    r"""Input\.(?:is_action_(?:pressed|just_pressed|just_released)|get_action_strength)\(\s*["']([^"']+)["']\s*\)"""
)
_GET_AXIS_RE = re.compile(
    r"""Input\.get_axis\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']\s*\)"""
)
_GET_VECTOR_RE = re.compile(
    r"""Input\.get_vector\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']\s*\)"""
)
_ONREADY_DOLLAR_PATH_RE = re.compile(
    r"""@onready\s+var\s+[^=\n]+=\s*\$(?:"([^"\n]+)"|([A-Za-z0-9_./%-]+))"""
)
_PROJECT_MAIN_SCENE_RE = re.compile(r'run/main_scene\s*=\s*"([^"]+)"')
_ARROW_KEY_BY_ACTION = {
    "move_left": 4194319,
    "move_right": 4194321,
    "move_up": 4194320,
    "move_down": 4194322,
    "move_forward": 4194320,
    "move_back": 4194322,
}
_TEMPLATE_REQUIRED_ACTIONS: dict[TemplateId, set[str]] = {
    "platformer_2d": {"move_left", "move_right", "jump"},
    "topdown_2d": {"move_left", "move_right", "move_up", "move_down"},
    "walker_3d": {"move_left", "move_right", "move_forward", "move_back", "jump"},
}
_TEMPLATE_REQUIRED_KEYCODES: dict[TemplateId, dict[str, set[int]]] = {
    "platformer_2d": {
        "move_left": {65, 4194319},
        "move_right": {68, 4194321},
        "jump": {32, 87, 4194320},
    },
    "topdown_2d": {
        "move_left": {65, 4194319},
        "move_right": {68, 4194321},
        "move_up": {87, 4194320},
        "move_down": {83, 4194322},
    },
    "walker_3d": {
        "move_left": {65, 4194319},
        "move_right": {68, 4194321},
        "move_forward": {87, 4194320},
        "move_back": {83, 4194322},
        "jump": {32},
    },
}


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


def _input_actions_in_text(text: str) -> list[str]:
    actions = list(_ACTION_RE.findall(text))
    for negative, positive in _GET_AXIS_RE.findall(text):
        actions.extend([negative, positive])
    for left, right, up, down in _GET_VECTOR_RE.findall(text):
        actions.extend([left, right, up, down])
    return actions


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


def _parse_input_action_keycodes(project_godot_text: str) -> dict[str, set[int]]:
    in_input = False
    current_action: str | None = None
    braces = 0
    keycodes: dict[str, set[int]] = {}
    for line in project_godot_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_input = stripped == "[input]"
            current_action = None
            braces = 0
            continue
        if not in_input:
            continue
        if current_action is None:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if not m:
                continue
            current_action = m.group(1)
            keycodes.setdefault(current_action, set())
            braces = line.count("{") - line.count("}")
        else:
            braces += line.count("{") - line.count("}")
        if current_action is not None:
            for code in re.findall(r'"physical_keycode"\s*:\s*(\d+)', line):
                keycodes[current_action].add(int(code))
            if braces <= 0 and "}" in line:
                current_action = None
                braces = 0
    return keycodes


def _parse_autoloads(project_godot_text: str) -> dict[str, str]:
    in_autoload = False
    autoloads: dict[str, str] = {}
    for line in project_godot_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_autoload = stripped == "[autoload]"
            continue
        if not in_autoload:
            continue
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"\*?([^"]+)"', line)
        if m:
            autoloads[m.group(1)] = m.group(2)
    return autoloads


def _parse_scene_nodes(scene_text: str) -> tuple[dict[str, str], dict[str, str]]:
    ext_scripts: dict[str, str] = {}
    nodes: dict[str, str] = {}
    node_scripts: dict[str, str] = {}
    current_node_path: str | None = None
    root_path: str | None = None

    for line in scene_text.splitlines():
        ext = re.match(r'^\[ext_resource\s+([^\]]+)\]', line)
        if ext:
            attrs = dict(re.findall(r'(\w+)=("[^"]*"|[^\s]+)', ext.group(1)))
            if attrs.get("type", "").strip('"') == "Script":
                path = attrs.get("path", "").strip('"')
                ext_id = attrs.get("id", "").strip('"')
                if path and ext_id:
                    ext_scripts[ext_id] = path
            continue

        node = re.match(r'^\[node\s+([^\]]+)\]', line)
        if node:
            attrs = dict(re.findall(r'(\w+)=("[^"]*"|[^\s]+)', node.group(1)))
            raw_name = attrs.get("name", "").strip('"')
            raw_parent = attrs.get("parent", "").strip('"')
            if not raw_name:
                current_node_path = None
                continue
            if not raw_parent:
                current_node_path = raw_name
                root_path = raw_name
            elif raw_parent == ".":
                current_node_path = f"{root_path}/{raw_name}" if root_path else raw_name
            else:
                current_node_path = (
                    f"{root_path}/{raw_parent}/{raw_name}" if root_path else f"{raw_parent}/{raw_name}"
                )
            nodes[current_node_path] = raw_name
            continue

        if current_node_path is not None:
            script = re.match(r'^\s*script\s*=\s*ExtResource\("([^"]+)"\)', line)
            if script and script.group(1) in ext_scripts:
                node_scripts[current_node_path] = ext_scripts[script.group(1)]

    return nodes, node_scripts


def _resolve_relative_node_path(nodes: dict[str, str], owner_path: str, ref_path: str) -> bool:
    if (
        not ref_path
        or ref_path.startswith("/")
        or ref_path.startswith("%")
        or ":" in ref_path
    ):
        return True
    parts = owner_path.split("/") if owner_path else []
    for part in ref_path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts) in nodes


def _scene_script_owners(project_dir: Path) -> tuple[dict[str, list[tuple[Path, str, dict[str, str]]]], list[str]]:
    owners: dict[str, list[tuple[Path, str, dict[str, str]]]] = {}
    errs: list[str] = []
    for scene in project_dir.rglob("*.tscn"):
        try:
            text = scene.read_text()
        except UnicodeDecodeError:
            continue
        nodes, node_scripts = _parse_scene_nodes(text)
        for owner_path, script_res_path in node_scripts.items():
            if not script_res_path.startswith("res://"):
                continue
            script_path = project_dir / script_res_path[len("res://") :]
            if not script_path.exists():
                rel = scene.relative_to(project_dir)
                errs.append(f"{rel}: script ExtResource references missing '{script_res_path}'")
                continue
            owners.setdefault(str(script_path.resolve()), []).append((scene, owner_path, nodes))
    return owners, errs


def sanity_check(project_dir: Path, template: TemplateId | None = None) -> list[str]:
    errs: list[str] = []

    proj_godot = project_dir / "project.godot"
    actions: set[str] = set()
    action_keycodes: dict[str, set[int]] = {}
    project_text = ""
    if proj_godot.exists():
        project_text = proj_godot.read_text()
        actions = _parse_input_actions(project_text)
        action_keycodes = _parse_input_action_keycodes(project_text)
        autoloads = _parse_autoloads(project_text)
        for name, path in {
            "ReadySignal": "res://autoload/ready_signal.gd",
            "ScreenShake": "res://autoload/screen_shake.gd",
        }.items():
            if autoloads.get(name) != path:
                errs.append(f"project.godot: missing [autoload] registration for {name}={path}")
        m = _PROJECT_MAIN_SCENE_RE.search(project_text)
        if not m:
            errs.append('project.godot: missing application run/main_scene="res://..."')
        elif m.group(1).startswith("res://"):
            main_scene = project_dir / m.group(1)[len("res://") :]
            if not main_scene.exists():
                errs.append(f"project.godot: run/main_scene references missing '{m.group(1)}'")
    else:
        errs.append("project.godot is missing")

    script_owners, scene_owner_errs = _scene_script_owners(project_dir)
    errs.extend(scene_owner_errs)

    used_actions: set[str] = set()
    for p in project_dir.rglob("*.gd"):
        rel = p.relative_to(project_dir)
        text = p.read_text()
        if not _gd_has_extends(text):
            errs.append(f"{rel}: missing `extends` on first non-comment line")
        for e in _balanced(text, [("(", ")"), ("{", "}"), ("[", "]")]):
            errs.append(f"{rel}: {e}")
        file_actions = _input_actions_in_text(text)
        used_actions.update(file_actions)
        for act in file_actions:
            if act not in actions:
                errs.append(
                    f"{rel}: Input action '{act}' not declared in project.godot [input]"
                )
            required_key = _ARROW_KEY_BY_ACTION.get(act)
            if required_key and required_key not in action_keycodes.get(act, set()):
                errs.append(
                    f"project.godot: movement action '{act}' must keep arrow key physical_keycode {required_key}"
                )
        for quoted, bare in _ONREADY_DOLLAR_PATH_RE.findall(text):
            ref_path = quoted or bare
            owners = script_owners.get(str(p.resolve()), [])
            if not owners:
                continue
            for scene, owner_path, nodes in owners:
                if not _resolve_relative_node_path(nodes, owner_path, ref_path):
                    errs.append(
                        f"{rel}: @onready path '${ref_path}' does not resolve from "
                        f"node '{owner_path}' in {scene.relative_to(project_dir)}"
                    )
        if (
            "extends Area2D" in text
            and re.search(r"\bsignal\s+\w*collected\b", text)
            and re.search(r"\bfunc\s+collect\s*\(", text)
            and not re.search(r"\b(?:body|area)(?:_shape)?_entered\b", text)
        ):
            errs.append(
                f"{rel}: collectible Area2D defines collect() but never connects "
                "body_entered/area_entered to call it"
            )

    if template is not None:
        for action in sorted(_TEMPLATE_REQUIRED_ACTIONS[template]):
            if action not in actions:
                errs.append(f"project.godot: template '{template}' requires input action '{action}'")
            if action not in used_actions:
                errs.append(f"scripts: template '{template}' must read input action '{action}'")
        for action, required_codes in _TEMPLATE_REQUIRED_KEYCODES[template].items():
            actual_codes = action_keycodes.get(action, set())
            missing_codes = sorted(required_codes - actual_codes)
            if missing_codes:
                errs.append(
                    f"project.godot: action '{action}' missing required physical_keycode(s) {missing_codes}"
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

    for p in project_dir.rglob("*.gdshader"):
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        rel = p.relative_to(project_dir)
        if "SCREEN_TEXTURE" in text or "screen_texture" in text:
            errs.append(f"{rel}: web build forbids SCREEN_TEXTURE/screen_texture post-process sampling")
        if re.search(r"\bvoid\s+fragment\s*\([^)]*\)\s*\{[\s\S]*?\breturn\s*;", text):
            errs.append(f"{rel}: fragment() contains bare return; Godot shaders reject this")

    for p in list(project_dir.rglob("*.tscn")) + list(project_dir.rglob("*.tres")):
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        rel = p.relative_to(project_dir)
        if "BackBufferCopy" in text:
            errs.append(f"{rel}: web build forbids BackBufferCopy post-process nodes")

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
    base_user = _build_user_prompt(design, resolved_assets, resolved_sfx, tree, ctx)
    user = base_user

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
            user = _with_feedback(base_user, last_errs)
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
            user = _with_feedback(base_user, last_errs)
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

        errs = sanity_check(project_dir, template=design.template)
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
        user = _with_feedback(base_user, errs)
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
    applied = _apply_repair_plan(project_dir, plan, template=design.template)
    # Append to the same log file for traceability.
    log_path = session_log_dir(session_id) / "synthesize.json"
    existing = json.loads(log_path.read_text()) if log_path.exists() else []
    existing.append(
        {
            "stage": "build_repair",
            "stderr_tail": stderr[-1000:],
            "files_applied": applied,
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
        + "- runtime_error: fix the missing node, nil dereference, or invalid"
        " method call described by QA diagnostics.\n"
        + "- unresponsive_controls: verify input actions, movement code,"
        " collision layers, camera following, and visible HUD feedback.\n\n"
        + "Emit a corrective edit plan in the same JSON format."
    )
    text = await claude_json(system=system, user=user, temperature=0.3, max_tokens=16000, model=CLAUDE_SONNET_MODEL)
    raw = extract_json(text)
    plan = EditPlan.model_validate(raw)
    applied = _apply_repair_plan(project_dir, plan, template=design.template)
    log_path = session_log_dir(session_id) / "synthesize.json"
    existing = json.loads(log_path.read_text()) if log_path.exists() else []
    existing.append(
        {
            "stage": "qa_repair",
            "issue_kind": issue_kind,
            "description": description,
            "files_applied": applied,
        }
    )
    log_path.write_text(json.dumps(existing, indent=2))
