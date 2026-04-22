extends CharacterBody3D
# Minimal third-person walker. World-space WASD relative to camera yaw.
# Synthesize may retune exports and swap the MeshInstance3D child's mesh.

@export var speed: float = 5.5
@export var jump_velocity: float = 6.0
@export var gravity: float = 18.0
@export var turn_speed: float = 12.0

@onready var _mesh_pivot: Node3D = $MeshPivot
@onready var _camera_yaw: Node3D = get_node("../CameraRig")

signal died
signal won

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y -= gravity * delta

	if Input.is_action_just_pressed("jump") and is_on_floor():
		velocity.y = jump_velocity

	var input_dir := Vector2(
		Input.get_axis("move_left", "move_right"),
		Input.get_axis("move_forward", "move_back"),
	)

	var yaw := _camera_yaw.rotation.y if _camera_yaw else 0.0
	var forward := Vector3(sin(yaw), 0, cos(yaw))
	var right := Vector3(cos(yaw), 0, -sin(yaw))
	var wish := (right * input_dir.x + forward * input_dir.y)
	if wish.length() > 1.0:
		wish = wish.normalized()

	velocity.x = wish.x * speed
	velocity.z = wish.z * speed

	move_and_slide()

	if wish.length() > 0.05:
		var target_yaw := atan2(wish.x, wish.z)
		_mesh_pivot.rotation.y = lerp_angle(_mesh_pivot.rotation.y, target_yaw, delta * turn_speed)

	if global_position.y < -20.0:
		died.emit()
		global_position = Vector3(0, 3, 0)
		velocity = Vector3.ZERO
