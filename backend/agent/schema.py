from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .manifests import fallback_manifest, sfx_keys

Dimension = Literal["2D", "3D"]
TemplateId = Literal[
    "platformer_2d",
    "topdown_2d",
    "walker_3d",
]
Scope = Literal["micro", "short", "medium"]
CameraKind = Literal["fixed", "follow", "topdown", "third_person", "orbit"]
AssetKind = Literal["sprite", "tileset", "bg", "mesh", "ui"]
ShaderKind = Literal["water", "outline", "dither", "sky"]
SceneKind = Literal["title", "gameplay", "win", "lose"]

TEMPLATES_2D: set[TemplateId] = {"platformer_2d", "topdown_2d"}
TEMPLATES_3D: set[TemplateId] = {"walker_3d"}
CANONICAL_CONTROLS: dict[TemplateId, dict[str, str]] = {
    "platformer_2d": {
        "move": "A/D or left/right arrows",
        "jump": "Space, W, or up arrow",
    },
    "topdown_2d": {
        "move": "WASD or arrow keys",
        "dash": "Space",
    },
    "walker_3d": {
        "move": "WASD or arrow keys",
        "jump": "Space",
    },
}


class CameraSpec(BaseModel):
    kind: CameraKind
    params: dict[str, float] = Field(default_factory=dict)


class SceneNode(BaseModel):
    id: str
    kind: SceneKind
    transitions: list[str] = Field(default_factory=list)


class SignalSpec(BaseModel):
    name: str
    emitter: str
    listeners: list[str]
    payload_schema: dict[str, str] = Field(default_factory=dict)


class Asset(BaseModel):
    id: str
    role: str
    kind: AssetKind
    prompt: str
    size: tuple[int, int] | None = None
    expected_bbox: float | None = Field(
        default=None,
        description="For 3D meshes: expected bounding-box diagonal in meters. "
        "Used for Tripo scale-sanity check.",
    )
    fallback_role: str = Field(
        description="Key into fallback_assets/manifest.json. Resolved if generation fails."
    )

    @field_validator("fallback_role")
    @classmethod
    def _fallback_role_exists(cls, v: str) -> str:
        roles = set(fallback_manifest().keys())
        if v not in roles:
            raise ValueError(
                f"fallback_role '{v}' is not in fallback_assets/manifest.json. "
                f"Valid roles: {sorted(roles)}"
            )
        return v

    @model_validator(mode="after")
    def _kind_matches_fallback(self) -> "Asset":
        fb = fallback_manifest().get(self.fallback_role, {})
        fb_kind = fb.get("kind")
        if fb_kind and fb_kind != self.kind:
            raise ValueError(
                f"Asset '{self.id}' kind={self.kind} doesn't match "
                f"fallback_role '{self.fallback_role}' kind={fb_kind}"
            )
        return self


class Shader(BaseModel):
    target: str = Field(description="Node path for a specific sprite, mesh, tile, or sky material")
    kind: ShaderKind
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target")
    @classmethod
    def _no_post_process_target(cls, v: str) -> str:
        if v == "post_process":
            raise ValueError("post_process shaders are banned for web export; target a concrete node")
        return v


class GameDesign(BaseModel):
    dimension: Dimension
    template: TemplateId
    title: str = Field(min_length=1, max_length=60)
    pitch: str = Field(min_length=1, max_length=240)
    narrative_framing: str = Field(
        min_length=1,
        description="1-2 sentences giving the game a voice (world/tone).",
    )
    scope: Scope
    controls: dict[str, str]
    core_verb: str = Field(
        min_length=1,
        description="The ONE verb that defines this game (climb, dash, trade, bounce).",
    )
    mechanics: list[str] = Field(min_length=1, max_length=5)
    win_condition: str
    lose_condition: str | None = None
    camera: CameraSpec
    scene_flow: list[SceneNode] = Field(min_length=1)
    signals: list[SignalSpec] = Field(default_factory=list)
    art_style: str = Field(
        min_length=20,
        description="Single committed-to sentence applied to every asset prompt.",
    )
    palette: list[str] = Field(min_length=4, max_length=6)
    juice: list[str] = Field(min_length=3)
    assets: list[Asset] = Field(min_length=1)
    shaders: list[Shader] = Field(min_length=1)
    sfx_map: dict[str, str] = Field(default_factory=dict)

    @field_validator("palette")
    @classmethod
    def _palette_hex(cls, v: list[str]) -> list[str]:
        for c in v:
            if not (c.startswith("#") and len(c) in (4, 7)):
                raise ValueError(f"palette entry '{c}' must be #RGB or #RRGGBB")
        return v

    @field_validator("sfx_map")
    @classmethod
    def _sfx_keys(cls, v: dict[str, str]) -> dict[str, str]:
        keys = sfx_keys()
        bad = {sfx for sfx in v.values() if sfx not in keys}
        if bad:
            raise ValueError(
                f"sfx_map references keys not in sfx_manifest.json: {sorted(bad)}. "
                f"Valid keys: {sorted(keys)}"
            )
        return v

    @model_validator(mode="after")
    def _cross_field_checks(self) -> "GameDesign":
        errs: list[str] = []
        if self.dimension == "2D" and self.template not in TEMPLATES_2D:
            errs.append(f"dimension=2D but template '{self.template}' is not a 2D template")
        if self.dimension == "3D" and self.template not in TEMPLATES_3D:
            errs.append(f"dimension=3D but template '{self.template}' is not a 3D template")
        canonical = CANONICAL_CONTROLS[self.template]
        missing_controls = [key for key in canonical if key not in self.controls]
        if missing_controls:
            errs.append(
                f"template '{self.template}' controls must include canonical action(s): "
                f"{missing_controls}; use {canonical}"
            )
        if "move" in self.controls and "arrow" not in self.controls["move"].lower():
            errs.append("controls.move must explicitly include arrow keys")
        if "jump" in canonical and "space" not in self.controls.get("jump", "").lower():
            errs.append("controls.jump must explicitly include Space")
        if "dash" in canonical and "space" not in self.controls.get("dash", "").lower():
            errs.append("controls.dash must explicitly include Space")
        kinds = {s.kind for s in self.scene_flow}
        if "gameplay" not in kinds:
            errs.append("scene_flow must contain at least one 'gameplay' scene")
        if errs:
            raise ValueError("; ".join(errs))
        return self
