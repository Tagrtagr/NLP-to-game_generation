extends Node3D

@onready var player: CharacterBody3D = $Player
@onready var goal: Area3D = $Goal
@onready var banner: Label = $UI/Banner

func _ready() -> void:
	goal.body_entered.connect(_on_goal_entered)
	player.died.connect(_on_player_died)
	banner.visible = false

func _on_goal_entered(body: Node) -> void:
	if body == player:
		banner.text = "YOU WIN"
		banner.visible = true
		player.won.emit()

func _on_player_died() -> void:
	banner.text = "FELL — RESTART"
	banner.visible = true
	await get_tree().create_timer(0.6).timeout
	banner.visible = false
