# Godot 4.5.1 API cheatsheet (curated subset)

## Input

```gdscript
Input.is_action_pressed("move_left")         # held
Input.is_action_just_pressed("jump")         # edge: press
Input.is_action_just_released("jump")
Input.get_vector("move_left","move_right","move_up","move_down")  # Vector2
```

## CharacterBody2D

```gdscript
extends CharacterBody2D

const SPEED := 200.0
const JUMP := -350.0
const GRAVITY := 900.0

func _physics_process(delta: float) -> void:
    if not is_on_floor():
        velocity.y += GRAVITY * delta
    var h := Input.get_axis("move_left","move_right")
    velocity.x = h * SPEED
    if Input.is_action_just_pressed("jump") and is_on_floor():
        velocity.y = JUMP
    move_and_slide()
```

## CharacterBody3D (camera-relative walker)

```gdscript
extends CharacterBody3D
@export var speed := 5.0
@export var jump := 5.5
@export var gravity := 20.0
@onready var cam: Camera3D = get_tree().get_first_node_in_group("camera")

func _physics_process(delta: float) -> void:
    velocity.y -= gravity * delta
    var input := Vector2(
        Input.get_axis("move_left","move_right"),
        Input.get_axis("move_up","move_down"))
    var basis := cam.global_transform.basis
    var fwd := Vector3(basis.z.x, 0, basis.z.z).normalized()
    var right := Vector3(basis.x.x, 0, basis.x.z).normalized()
    var move := (-fwd * input.y + right * input.x) * speed
    velocity.x = move.x
    velocity.z = move.z
    if Input.is_action_just_pressed("jump") and is_on_floor():
        velocity.y = jump
    move_and_slide()
```

## Signals

```gdscript
signal hit(damage: int)

# elsewhere:
player.hit.connect(_on_player_hit)
func _on_player_hit(damage: int) -> void: ...
player.hit.emit(5)
```

## Tween (juice)

```gdscript
var t := create_tween()
t.tween_property(sprite, "modulate", Color.WHITE, 0.08)
t.tween_property(sprite, "modulate", Color(1,1,1,1), 0.08)
```

## Screen shake (Camera2D)

```gdscript
func shake(amount := 4.0, duration := 0.15) -> void:
    var t := create_tween()
    for i in 6:
        var off := Vector2(randf_range(-amount, amount), randf_range(-amount, amount))
        t.tween_property(self, "offset", off, duration/6.0)
    t.tween_property(self, "offset", Vector2.ZERO, 0.05)
```

## AudioStreamPlayer (one-shot SFX)

```gdscript
@onready var sfx_jump: AudioStreamPlayer = $Sfx/Jump
func _on_jump() -> void: sfx_jump.play()
```

## Load/preload

```gdscript
const SCENE := preload("res://scenes/enemy.tscn")
var inst := SCENE.instantiate()
add_child(inst)
```
