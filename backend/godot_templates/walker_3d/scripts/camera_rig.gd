extends Node3D
# Lazy third-person follow. Tracks player position with exponential smoothing.
# No mouse-look: web iframe pointer-lock is unreliable. Synthesize may
# replace this with orbit/fixed cams per GameDesign.camera.kind.

@export var target_path: NodePath = ^"../Player"
@export var follow_height: float = 3.0
@export var follow_distance: float = 6.0
@export var smoothing: float = 6.0

@onready var _target: Node3D = get_node_or_null(target_path)

func _process(delta: float) -> void:
	if _target == null:
		return
	var desired := _target.global_position
	global_position = global_position.lerp(desired, clamp(delta * smoothing, 0.0, 1.0))
