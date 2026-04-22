# walker_3d template

Minimal-viable third-person 3D walker. Ships with:

- `CharacterBody3D` player with world-space WASD movement relative to camera yaw, gravity, and jump. Capsule primitive mesh + capsule collision as placeholder — synthesize/asset phase swaps the `MeshPivot/Mesh.mesh` property to a Tripo-generated GLB (or the Kenney humanoid fallback). Collision shape is intentionally decoupled from the visual mesh so swapping art never breaks physics.
- Third-person follow camera (`CameraRig` + `Camera3D`) with exponential smoothing. No mouse-look by default — web iframe pointer-lock is unreliable. Synthesize may swap to orbit/fixed cams per `GameDesign.camera.kind`.
- Flat 60×60 ground, three obstacle cubes, glowing green goal Area3D, fall-through-world restart at y < -20.
- `WorldEnvironment` with procedural sky (top/horizon gradient) — gives every 3D game a decent default sky even before shader customization.
- `ReadySignal` autoload firing `window.__GODOT_READY__ = true` one frame after `_ready`. Phase 5 Playwright polls this flag.
- `export_presets.cfg` Web preset with `thread_support=false` → single-threaded WASM, no COOP/COEP headers required.

## Why primitives, not a Kenney mesh, in this commit

Step 4 wires in bundled Kenney fallback packs. Once that lands, the asset-resolution path that falls back to a real humanoid mesh is plugged in here: synthesize will reference `fallback_assets/meshes_3d/humanoid.glb` and set it as the MeshPivot's mesh. Until then, the capsule lets the template run standalone and exercises the 3D export path end-to-end.

## What synthesize is expected to customize

- Swap `MeshPivot/Mesh.mesh` for a real humanoid/creature GLB (generated via Tripo, or the bundled Kenney fallback).
- Replace ground + obstacle box meshes with generated or bundled environment meshes.
- Add a shader from `shader_snippets.md` — `sky_gradient` applied to the sky material is the cheapest aesthetic lift for 3D.
- Apply `GameDesign.palette` to the sky colors, ground material, and obstacle materials.
- Wire SFX (footsteps, jump, land, pickup, win) through `AudioStreamPlayer3D` on the player or `AudioStreamPlayer` for UI events.
- Expand/rearrange the obstacle layout to match `GameDesign.mechanics`.

## What synthesize must NOT remove

- `autoload/ready_signal.gd` and the `[autoload] ReadySignal=` line in `project.godot`.
- Input actions `move_forward/move_back/move_left/move_right/jump`.
- `thread_support=false` in `export_presets.cfg`.
- The `CameraRig` node — the player script reads its yaw for camera-relative movement.
