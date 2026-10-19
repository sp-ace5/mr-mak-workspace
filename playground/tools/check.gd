extends SceneTree
# Usage: godot --headless --path playground --script res://tools/check.gd
# Loads Playground.tscn with whatever is synced, runs a few frames, and prints {"shaders":N,"sounds":M}.
# The caller treats any ERROR on stderr as a failed load.


func _initialize() -> void:
	var scene: Node = (load("res://Playground.tscn") as PackedScene).instantiate()
	root.add_child(scene)
	for i in 3:
		await process_frame
	print(JSON.stringify({"shaders": scene.shader_count, "sounds": scene.sound_count}))
	quit(0)
