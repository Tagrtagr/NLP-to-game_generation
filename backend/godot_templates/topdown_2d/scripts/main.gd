extends Node2D

@onready var player: CharacterBody2D = $Player
@onready var pickups: Node2D = $Pickups
@onready var banner: Label = $UI/Banner
@onready var counter: Label = $UI/Counter

var _collected: int = 0
var _total: int = 0

func _ready() -> void:
	banner.visible = false
	_total = pickups.get_child_count()
	_refresh_counter()
	for child in pickups.get_children():
		if child is Area2D:
			child.body_entered.connect(_on_pickup.bind(child))

func _on_pickup(body: Node, pickup: Area2D) -> void:
	if body != player or not pickup.visible:
		return
	pickup.visible = false
	pickup.monitoring = false
	_collected += 1
	_refresh_counter()
	ScreenShake.kick(3.0, 0.08)
	player.picked_up.emit()
	if _collected >= _total:
		_win()

func _refresh_counter() -> void:
	counter.text = "%d / %d" % [_collected, _total]

func _win() -> void:
	banner.text = "YOU WIN"
	banner.visible = true
	ScreenShake.kick(8.0, 0.35)
	player.won.emit()
