extends CharacterBody2D
# Minimal platformer controller. Tunables exposed so synthesize can retune
# per-game without rewriting the script.

@export var speed: float = 240.0
@export var jump_velocity: float = -420.0
@export var gravity: float = 1200.0
@export var coyote_time: float = 0.08
@export var jump_buffer: float = 0.1

var _coyote := 0.0
var _buffer := 0.0

signal died
signal won

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y += gravity * delta
		_coyote = max(_coyote - delta, 0.0)
	else:
		_coyote = coyote_time

	var dir := Input.get_axis("move_left", "move_right")
	velocity.x = dir * speed

	_buffer = max(_buffer - delta, 0.0)
	if Input.is_action_just_pressed("jump"):
		_buffer = jump_buffer
	if _buffer > 0.0 and _coyote > 0.0:
		velocity.y = jump_velocity
		_buffer = 0.0
		_coyote = 0.0

	move_and_slide()

	if global_position.y > 1200.0:
		died.emit()
		global_position = Vector2(80, 200)
		velocity = Vector2.ZERO
