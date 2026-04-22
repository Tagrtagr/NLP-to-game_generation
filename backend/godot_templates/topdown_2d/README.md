# topdown_2d (tier-1 template)

Minimal-viable top-down 2D with pickup-based win condition.

## Scene
- `Main` (`scripts/main.gd`) — top-level `Node2D` with Camera2D, bordered
  play area, four pickups laid out in a cross, UI layer with a "collected
  N / M" counter + banner.
- `Player` (`scripts/player.gd`) — `CharacterBody2D` with 8-way input and
  diagonal-normalized velocity, accel/friction smoothing. Signals:
  `picked_up`, `died`, `won`.

## Autoloads
- `ReadySignal` — sets `window.__GODOT_READY__ = true` one frame after
  scene load (Playwright polls this in Phase 5).
- `ScreenShake` — `ScreenShake.kick(amount, duration)` jitters the
  active `Camera2D.offset`. Already wired into pickup (3 px) and win
  (8 px) moments.

## Inputs
`move_left` / `move_right` / `move_up` / `move_down` — WASD or arrow keys.

## Customization by synthesize
- Swap `ColorRect` visuals for sprites (player, pickups, walls).
- Replace border walls with a tileset or hand-placed obstacles.
- Add a second mechanic (enemy patrols, timer, etc.) via new scene nodes.
- Add a shader to `Main/Background` for atmosphere (see
  `godot_context/shader_snippets.md`).

## Invariants (DO NOT remove)
- `autoload/ready_signal.gd` registration in `[autoload]`.
- `[input]` actions `move_left/right/up/down` exist (scripts reference
  them via `Input.get_axis`).
- The 4 pickup `Area2D` nodes under `Pickups` are the win counter; if
  you add more, update nothing — the counter is auto-derived from
  child count.
