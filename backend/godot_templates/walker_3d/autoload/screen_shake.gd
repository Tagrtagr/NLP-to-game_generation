extends Node
# Global screen-shake bus for 3D. Any script calls
# `ScreenShake.kick(amount, dur)` and the active Camera3D's `h_offset` /
# `v_offset` jitter by +/- amount for dur seconds, decaying to zero. Works
# without coupling the caller to the camera node.

var _amount: float = 0.0
var _duration: float = 0.0
var _elapsed: float = 0.0
var _rng := RandomNumberGenerator.new()

func kick(amount: float = 0.15, duration: float = 0.2) -> void:
	if amount > _amount:
		_amount = amount
	_duration = max(_duration, duration)
	_elapsed = 0.0

func _process(delta: float) -> void:
	var cam := _active_camera()
	if cam == null:
		return
	if _duration <= 0.0 or _elapsed >= _duration:
		cam.h_offset = 0.0
		cam.v_offset = 0.0
		return
	_elapsed += delta
	var t := 1.0 - (_elapsed / _duration)
	var mag := _amount * t * t
	cam.h_offset = _rng.randf_range(-mag, mag)
	cam.v_offset = _rng.randf_range(-mag, mag)
	if _elapsed >= _duration:
		cam.h_offset = 0.0
		cam.v_offset = 0.0
		_amount = 0.0
		_duration = 0.0

func _active_camera() -> Camera3D:
	var tree := get_tree()
	if tree == null:
		return null
	var vp := tree.root.get_viewport()
	return vp.get_camera_3d() if vp else null
