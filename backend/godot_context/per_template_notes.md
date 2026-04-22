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

## topdown_2d / shooter_2d / puzzle_2d / adventure_3d

- Use the patterns from platformer_2d (2D) or walker_3d (3D) as reference. Keep the ready_signal autoload untouched in all templates.

## Shared invariants (every template)

- `autoload/ready_signal.gd` must remain registered in `project.godot`'s `[autoload]` section. It fires `window.__GODOT_READY__ = true` on first frame; Playwright QA polls for it.
- Single-threaded web export: `export_presets.cfg` already sets `thread_support=false`. Don't flip it.
- Input actions must exist in `project.godot` `[input]` before scripts reference them.
