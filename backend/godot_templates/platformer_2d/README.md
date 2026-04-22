# platformer_2d template

Minimal-viable side-scrolling platformer. Ships with:

- `CharacterBody2D` player with coyote time + jump buffering (`scripts/player.gd`).
- Three platforms + ground + goal, all `ColorRect`-visualed (no external texture deps). Synthesize phase swaps `ColorRect` visuals for `Sprite2D`/`TileMap` with generated or fallback art.
- `ReadySignal` autoload firing `window.__GODOT_READY__ = true` one frame after `_ready` — required by Phase 5 Playwright polling.
- `export_presets.cfg` Web preset with `thread_support=false` → single-threaded WASM, no COOP/COEP headers needed.

## What synthesize is expected to customize

- Replace `ColorRect` visuals with real sprites (player, tiles, goal) driven by `GameDesign.assets`.
- Add a shader from `shader_snippets.md` (CRT, water, outline, dither, palette-lock). Apply to `Camera2D` or a `CanvasLayer` for post-process, or to specific visuals.
- Expand `scenes/main.tscn` with more platforms / enemies / pickups per `GameDesign.mechanics`.
- Wire SFX via `sfx_map` → `AudioStreamPlayer` nodes on events (jump, land, pickup, win, lose).
- Apply `palette` colors to `Background`, platform `Visual`s, player `Visual`, UI `Banner`.

## What synthesize must NOT remove

- `autoload/ready_signal.gd` and the `[autoload] ReadySignal=` line in `project.godot`.
- Input actions `move_left`, `move_right`, `jump` in `project.godot` (rename only via controls spec).
- `thread_support=false` in `export_presets.cfg`.
