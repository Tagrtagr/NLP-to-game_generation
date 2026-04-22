# Per-template customization notes

## platformer_2d

- Player script at `scripts/player.gd` (CharacterBody2D) exposes `SPEED`, `JUMP`, `GRAVITY`, coyote time + jump buffer. Tune constants rather than rewriting the loop.
- Swap the player sprite by replacing the `Sprite2D.texture` in `scenes/player.tscn`.
- Tiles live under `scenes/main.tscn`'s TileMap. For new art, point the TileSet source at a sprite under `res://assets/`.
- Add enemies as new `scenes/enemy_*.tscn` scenes and spawn via `scripts/main.gd._ready()`.

## walker_3d

- **Critical: do not touch the collision shape. Swap only `MeshPivot/Mesh.mesh`.** The MeshPivot pattern decouples visual from collision — writing the collision shape from Tripo output commonly breaks physics.
- Camera is a simple follow rig (no mouse-look) — iframe pointer-lock is unreliable; don't add first-person.
- Sky is procedural `ProceduralSkyMaterial`. Replace with a custom sky shader by attaching a ShaderMaterial to the WorldEnvironment's `sky.sky_material`.
- Fall-restart fires at `y < -20`. Keep that guard when customizing level geometry.

## topdown_2d

- 8-way movement with accel/friction smoothing (`scripts/player.gd`). Tune `speed`, `accel`, `friction` on the player node rather than rewriting the loop.
- Win condition is "collect all pickups under `Pickups`". The counter auto-derives from child count — just add/remove `Area2D` children with a `CollisionShape2D` and a visual child; `main.gd` wires them up on `_ready()`.
- Border walls are plain `StaticBody2D`s with `ColorRect` visuals. Swap for a tileset or replace wholesale for custom level geometry.

## shooter_2d / puzzle_2d / adventure_3d

- Tier-2 / stretch. Use platformer_2d (2D) or walker_3d (3D) as reference; every template must keep the `ready_signal` autoload registered.

## Shared invariants (every template)

- `autoload/ready_signal.gd` must remain registered in `project.godot`'s `[autoload]` section. It fires `window.__GODOT_READY__ = true` on first frame; Playwright QA polls for it.
- `autoload/screen_shake.gd` is also registered (as `ScreenShake`) in every tier-1 template. Call `ScreenShake.kick(amount, duration)` anywhere for camera-jitter juice — the autoload finds the active Camera2D / Camera3D via the viewport, so it works without plumbing the camera into the caller. 2D uses pixel amounts (~4-12 px); 3D uses world units (~0.05-0.25). Prefer wiring shake into impact / pickup / win moments over leaving `juice` inert.
- Single-threaded web export: `export_presets.cfg` already sets `thread_support=false`. Don't flip it.
- Input actions must exist in `project.godot` `[input]` before scripts reference them.
