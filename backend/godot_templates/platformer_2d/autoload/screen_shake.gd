extends Node
# Global screen-shake bus. Any script calls `ScreenShake.kick(amount, dur)`
# and the active Camera2D jitters by +/- amount for dur seconds, decaying
# to zero. Works without coupling the caller to the camera node.

var _amount: float = 0.0
var _duration: float = 0.0
var _elapsed: float = 0.0
var _rng := RandomNumberGenerator.new()

func kick(amount: float = 6.0, duration: float = 0.18) -> void:
	# Take the stronger of the in-flight shake and the new kick so rapid
	# successive hits don't clip each other short.
	if amount > _amount:
		_amount = amount
	_duration = max(_duration, duration)
	_elapsed = 0.0

func _process(delta: float) -> void:
	var cam := _active_camera()
	if cam == null:
		return
	if _duration <= 0.0 or _elapsed >= _duration:
		cam.offset = Vector2.ZERO
		return
	_elapsed += delta
	var t := 1.0 - (_elapsed / _duration)
	var mag := _amount * t * t
	cam.offset = Vector2(_rng.randf_range(-mag, mag), _rng.randf_range(-mag, mag))
	if _elapsed >= _duration:
		cam.offset = Vector2.ZERO
		_amount = 0.0
		_duration = 0.0

func _active_camera() -> Camera2D:
	var tree := get_tree()
	if tree == null:
		return null
	var vp := tree.root.get_viewport()
	return vp.get_camera_2d() if vp else null
