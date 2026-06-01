from __future__ import annotations

import pytest

from agent.build import GODOT_ERROR_RE
from agent import assets as assets_module
from agent.clients.tripo import _url_of
from agent import llm as llm_module
from agent.schema import GameDesign
from agent.synthesize import EditPlan, FileEdit, _apply_repair_plan, sanity_check


def _valid_design(**overrides):
    data = {
        "dimension": "2D",
        "template": "platformer_2d",
        "title": "Test",
        "pitch": "A small platformer test.",
        "narrative_framing": "A tiny test world with a clear goal.",
        "scope": "micro",
        "controls": {"move": "A/D or left/right arrows", "jump": "Space, W, or up arrow"},
        "core_verb": "jump",
        "mechanics": ["jump over gaps"],
        "win_condition": "reach the goal",
        "lose_condition": None,
        "camera": {"kind": "follow", "params": {}},
        "scene_flow": [{"id": "gameplay", "kind": "gameplay", "transitions": []}],
        "signals": [],
        "art_style": "Crisp pixel art with a small warm palette and hard edges.",
        "palette": ["#111111", "#333333", "#777777", "#eeeeee"],
        "juice": ["pickup flash", "screen shake on win", "jump particles"],
        "assets": [
            {
                "id": "player",
                "role": "player",
                "kind": "sprite",
                "prompt": "small hero",
                "size": [32, 32],
                "expected_bbox": None,
                "fallback_role": "player_sprite_platformer",
            }
        ],
        "shaders": [{"target": "Player/Sprite2D", "kind": "outline", "params": {}}],
        "sfx_map": {},
    }
    data.update(overrides)
    return data


def test_build_stderr_error_patterns_are_fatal():
    stderr = (
        "SCRIPT ERROR: Parse Error: Cannot infer the type of \"dist\" variable\n"
        "ERROR: Failed loading resource: res://scenes/main.tscn.\n"
        "SHADER ERROR: Using 'return' in the 'fragment' processor function is incorrect.\n"
    )
    assert GODOT_ERROR_RE.search(stderr)


def test_schema_rejects_unavailable_templates_and_post_process():
    with pytest.raises(Exception):
        GameDesign.model_validate(_valid_design(template="puzzle_2d"))

    bad_shader = _valid_design(
        shaders=[{"target": "post_process", "kind": "outline", "params": {}}]
    )
    with pytest.raises(Exception):
        GameDesign.model_validate(bad_shader)


def test_schema_rejects_design_without_canonical_controls():
    bad_controls = _valid_design(controls={"move": "A/D", "jump": "space"})

    with pytest.raises(Exception, match="arrow keys"):
        GameDesign.model_validate(bad_controls)


def test_sanity_catches_autoload_and_web_shader_invariants(tmp_path):
    (tmp_path / "autoload").mkdir()
    (tmp_path / "scenes").mkdir()
    (tmp_path / "shaders").mkdir()
    (tmp_path / "autoload" / "ready_signal.gd").write_text("extends Node\n")
    (tmp_path / "autoload" / "screen_shake.gd").write_text("extends Node\n")
    (tmp_path / "scenes" / "main.tscn").write_text("[gd_scene format=3]\n[node name=\"Main\" type=\"Node2D\"]\n")
    (tmp_path / "project.godot").write_text(
        'config_version=5\n\n[application]\nrun/main_scene="res://scenes/main.tscn"\n\n'
        '[autoload]\nReadySignal="*res://autoload/ready_signal.gd"\n'
    )
    (tmp_path / "shaders" / "bad.gdshader").write_text(
        "shader_type canvas_item;\nvoid fragment(){ COLOR = texture(SCREEN_TEXTURE, SCREEN_UV); }\n"
    )

    errs = sanity_check(tmp_path)

    assert any("ScreenShake" in e for e in errs)
    assert any("SCREEN_TEXTURE" in e for e in errs)


def test_sanity_parses_autoload_section_only(tmp_path):
    _write_minimal_project(tmp_path)
    project = tmp_path / "project.godot"
    project.write_text(
        project.read_text()
        + '\n[other]\nReadySignal="wrong.gd"\nScreenShake="wrong.gd"\n'
    )

    assert sanity_check(tmp_path) == []


def test_repair_plan_rolls_back_when_sanity_fails(tmp_path):
    _write_minimal_project(tmp_path)
    project = tmp_path / "project.godot"
    original_project = project.read_text()
    plan = EditPlan(
        files=[
            FileEdit(
                path="project.godot",
                content=original_project.replace(
                    'ScreenShake="*res://autoload/screen_shake.gd"\n', ""
                ),
            )
        ]
    )

    with pytest.raises(ValueError, match="repair produced sanity errors"):
        _apply_repair_plan(tmp_path, plan)

    assert project.read_text() == original_project
    assert not list(tmp_path.parent.glob("._repair_backup_*"))


def test_sanity_catches_missing_onready_node_path(tmp_path):
    _write_minimal_project(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "main.gd").write_text(
        "extends Node2D\n\n"
        "@onready var player: Node2D = $Player\n"
        "@onready var missing: Label = $UI/MissingLabel\n"
    )
    (tmp_path / "scenes" / "main.tscn").write_text(
        '[gd_scene format=3]\n'
        '[ext_resource type="Script" path="res://scripts/main.gd" id="1_main"]\n\n'
        '[node name="Main" type="Node2D"]\n'
        'script = ExtResource("1_main")\n\n'
        '[node name="Player" type="Node2D" parent="."]\n\n'
        '[node name="UI" type="CanvasLayer" parent="."]\n'
    )

    errs = sanity_check(tmp_path)

    assert any("$UI/MissingLabel" in e for e in errs)
    assert not any("$Player" in e for e in errs)


def test_sanity_catches_dropped_arrow_key_bindings_for_movement(tmp_path):
    _write_minimal_project(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "player.gd").write_text(
        "extends CharacterBody2D\n\n"
        "func _physics_process(delta: float) -> void:\n"
        '\tvar dir := Input.get_axis("move_left", "move_right")\n'
    )
    project = tmp_path / "project.godot"
    project.write_text(
        project.read_text()
        + '\n[input]\n'
        + 'move_left={\n'
        + '"deadzone": 0.5,\n'
        + '"events": [Object(InputEventKey,"physical_keycode":65)]\n'
        + '}\n'
        + 'move_right={\n'
        + '"deadzone": 0.5,\n'
        + '"events": [Object(InputEventKey,"physical_keycode":4194321)]\n'
        + '}\n'
    )

    errs = sanity_check(tmp_path)

    assert any("move_left" in e and "4194319" in e for e in errs)
    assert not any("move_right" in e and "4194321" in e for e in errs)


def test_sanity_enforces_topdown_get_vector_controls(tmp_path):
    _write_minimal_project(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "player.gd").write_text(
        "extends CharacterBody2D\n\n"
        "func _physics_process(delta: float) -> void:\n"
        '\tvar dir := Input.get_axis("move_left", "move_right")\n'
    )
    project = tmp_path / "project.godot"
    project.write_text(
        project.read_text()
        + '\n[input]\n'
        + _action_block("move_left", [65, 4194319])
        + _action_block("move_right", [68, 4194321])
        + _action_block("move_up", [87, 4194320])
        + _action_block("move_down", [83, 4194322])
    )

    errs = sanity_check(tmp_path, template="topdown_2d")

    assert any("must read input action 'move_up'" in e for e in errs)
    assert any("must read input action 'move_down'" in e for e in errs)


@pytest.mark.asyncio
async def test_claude_json_uses_streaming_for_large_outputs(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    class FakeStream:
        async def until_done(self):
            return None

        async def get_final_text(self):
            return ' {"files": []} '

    class FakeStreamManager:
        async def __aenter__(self):
            return FakeStream()

        async def __aexit__(self, exc_type, exc, exc_tb):
            return None

    class FakeMessages:
        def __init__(self):
            self.stream_kwargs = None

        def stream(self, **kwargs):
            self.stream_kwargs = kwargs
            return FakeStreamManager()

        async def create(self, **kwargs):
            raise AssertionError("create() should not be used for large outputs")

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    fake_client = FakeClient()
    monkeypatch.setattr(llm_module, "_anthropic", lambda: fake_client)

    text = await llm_module.claude_json(
        system="system",
        user="user",
        max_tokens=16000,
        model=llm_module.CLAUDE_SONNET_MODEL,
    )

    assert text == '{"files": []}'
    assert fake_client.messages.stream_kwargs is not None


@pytest.mark.asyncio
async def test_openrouter_api_key_routes_claude_json(monkeypatch):
    class FakeCompletions:
        def __init__(self):
            self.kwargs = None

        async def create(self, **kwargs):
            self.kwargs = kwargs

            class Message:
                content = '{"ok": true}'

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

    fake_client = FakeClient()
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_test")
    monkeypatch.setenv("OPENROUTER_TEXT_MODEL", "anthropic/claude-sonnet-4.5")
    monkeypatch.setattr(llm_module, "_openrouter", lambda: fake_client)
    monkeypatch.setattr(
        llm_module,
        "_anthropic",
        lambda: (_ for _ in ()).throw(AssertionError("anthropic should not be used")),
    )

    text = await llm_module.claude_json(system="system", user="user")

    kwargs = fake_client.chat.completions.kwargs
    assert text == '{"ok": true}'
    assert kwargs["model"] == "anthropic/claude-sonnet-4.5"
    assert kwargs["messages"][0] == {"role": "system", "content": "system"}
    assert kwargs["messages"][1] == {"role": "user", "content": "user"}
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_openrouter_vision_uses_data_urls(monkeypatch):
    class FakeCompletions:
        def __init__(self):
            self.kwargs = None

        async def create(self, **kwargs):
            self.kwargs = kwargs

            class Message:
                content = '{"ok": true}'

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

    fake_client = FakeClient()
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_test")
    monkeypatch.setattr(llm_module, "_openrouter", lambda: fake_client)
    monkeypatch.setattr(
        llm_module,
        "_gemini",
        lambda: (_ for _ in ()).throw(AssertionError("gemini should not be used")),
    )

    text = await llm_module.gemini_vision_json(
        system="system",
        user="inspect",
        images_png=[b"png-bytes"],
    )

    kwargs = fake_client.chat.completions.kwargs
    content = kwargs["messages"][1]["content"]
    assert text == '{"ok": true}'
    assert kwargs["model"] == llm_module.OPENROUTER_VISION_MODEL
    assert content[0] == {"type": "text", "text": "inspect"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_tripo_url_extraction_handles_dicts():
    assert _url_of({"type": "model/gltf-binary", "url": "https://example.com/a.glb"}) == (
        "https://example.com/a.glb"
    )


def test_missing_bundled_fallback_raises_without_placeholder_opt_in(tmp_path, monkeypatch):
    design = GameDesign.model_validate(_valid_design())
    asset = design.assets[0]
    fallback_root = tmp_path / "fallback_assets"
    fallback_root.mkdir()

    monkeypatch.delenv("ALLOW_PLACEHOLDER_FALLBACKS", raising=False)
    monkeypatch.setattr(assets_module, "FALLBACK_DIR", fallback_root)
    monkeypatch.setattr(assets_module, "session_dir", lambda sid: tmp_path / sid)
    monkeypatch.setattr(
        assets_module,
        "fallback_manifest",
        lambda: {asset.fallback_role: {"files": ["missing/player.png"]}},
    )

    with pytest.raises(assets_module.AssetResolutionError, match="bundled fallback"):
        assets_module._load_fallback(asset, "strict-session", "timeout")


def test_missing_bundled_fallback_can_write_placeholder_when_enabled(tmp_path, monkeypatch):
    design = GameDesign.model_validate(_valid_design())
    asset = design.assets[0]
    fallback_root = tmp_path / "fallback_assets"
    fallback_root.mkdir()

    monkeypatch.setenv("ALLOW_PLACEHOLDER_FALLBACKS", "true")
    monkeypatch.setattr(assets_module, "FALLBACK_DIR", fallback_root)
    monkeypatch.setattr(assets_module, "session_dir", lambda sid: tmp_path / sid)
    monkeypatch.setattr(
        assets_module,
        "fallback_manifest",
        lambda: {asset.fallback_role: {"files": ["missing/player.png"]}},
    )

    resolved = assets_module._load_fallback(asset, "placeholder-session", "timeout")

    assert resolved.source == "fallback"
    assert resolved.path.exists()
    assert "bundled fallback missing" in (resolved.error or "")


def test_asset_timeout_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("ASSET_TIMEOUT_SPRITE", "180")

    assert assets_module._asset_timeout("sprite") == 180


@pytest.mark.asyncio
async def test_2d_background_uses_pixellab_when_openai_key_missing(monkeypatch):
    called = {}

    async def fake_pixellab_generate_sprite(**kwargs):
        called["pixellab"] = kwargs
        return b"png"

    async def fake_gpt_generate_image(**kwargs):
        raise AssertionError("gpt image should not be used without OPENAI_API_KEY")

    asset = GameDesign.model_validate(
        _valid_design(
            assets=[
                {
                    "id": "bg",
                    "role": "background",
                    "kind": "bg",
                    "prompt": "pixel bakery background",
                    "size": [320, 180],
                    "expected_bbox": None,
                    "fallback_role": "bg_sky_2d",
                }
            ]
        )
    ).assets[0]

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(assets_module.pixellab, "generate_sprite", fake_pixellab_generate_sprite)
    monkeypatch.setattr(assets_module.gpt_image, "generate_image", fake_gpt_generate_image)
    monkeypatch.setattr(assets_module, "check_2d_image", lambda data: None)

    data = await assets_module._generate_2d(asset, "pixel art")

    assert data == b"png"
    assert called["pixellab"]["width"] == 320
    assert called["pixellab"]["height"] == 180


def _write_minimal_project(root):
    (root / "autoload").mkdir()
    (root / "scenes").mkdir()
    (root / "autoload" / "ready_signal.gd").write_text("extends Node\n")
    (root / "autoload" / "screen_shake.gd").write_text("extends Node\n")
    (root / "scenes" / "main.tscn").write_text(
        '[gd_scene format=3]\n[node name="Main" type="Node2D"]\n'
    )
    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\nrun/main_scene="res://scenes/main.tscn"\n\n'
        '[autoload]\nReadySignal="*res://autoload/ready_signal.gd"\n'
        'ScreenShake="*res://autoload/screen_shake.gd"\n'
    )


def _action_block(name, physical_keycodes):
    events = "\n, ".join(
        f'Object(InputEventKey,"physical_keycode":{code})' for code in physical_keycodes
    )
    return f'{name}={{\n"deadzone": 0.5,\n"events": [{events}]\n}}\n'
