extends CharacterBody2D
# Minimal top-down controller. 8-way movement with diagonal normalization.
# Tunables exposed so synthesize can retune per-game without rewrites.

@export var speed: float = 200.0
@export var accel: float = 1400.0
@export var friction: float = 1600.0

signal picked_up
signal died
signal won

func _physics_process(delta: float) -> void:
	var input_dir := Vector2(
		Input.get_axis("move_left", "move_right"),
		Input.get_axis("move_up", "move_down"),
	)
	if input_dir.length() > 1.0:
		input_dir = input_dir.normalized()

	if input_dir.length() > 0.05:
		velocity = velocity.move_toward(input_dir * speed, accel * delta)
	else:
		velocity = velocity.move_toward(Vector2.ZERO, friction * delta)

	move_and_slide()
