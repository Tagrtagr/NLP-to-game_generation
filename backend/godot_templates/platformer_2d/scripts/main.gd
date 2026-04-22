extends Node2D

@onready var player: CharacterBody2D = $Player
@onready var goal: Area2D = $Goal
@onready var banner: Label = $UI/Banner

func _ready() -> void:
	goal.body_entered.connect(_on_goal_entered)
	player.died.connect(_on_player_died)
	banner.visible = false

func _on_goal_entered(body: Node) -> void:
	if body == player:
		banner.text = "YOU WIN"
		banner.visible = true
		ScreenShake.kick(8.0, 0.35)
		player.won.emit()

func _on_player_died() -> void:
	banner.text = "OUCH — RESTART"
	banner.visible = true
	ScreenShake.kick(12.0, 0.4)
	await get_tree().create_timer(0.6).timeout
	banner.visible = false
