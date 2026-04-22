extends Node
# Fires window.__GODOT_READY__ = true one frame after the main scene
# is fully loaded. Playwright in Phase 5 polls this flag; DO NOT remove.

var _fired := false

func _ready() -> void:
	await get_tree().process_frame
	_fire()

func _fire() -> void:
	if _fired:
		return
	_fired = true
	if OS.has_feature("web"):
		JavaScriptBridge.eval("window.__GODOT_READY__ = true;", true)
	else:
		print("[ready_signal] ready (non-web build)")
