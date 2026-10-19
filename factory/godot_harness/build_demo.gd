extends SceneTree
# Builds <addon>/demo/demo.tscn: one sphere per shader in <addon>/shaders, plus light, environment and camera.
# Saved with ResourceSaver so the scene is engine-valid. Needs <addon>/demo/demo.gd in place first.
# Usage: godot --headless --path godot_harness --script res://build_demo.gd -- res://addons/<pack>

const SPACING := 1.4

func _init() -> void:
	var dir: String = OS.get_cmdline_user_args()[0]
	var root := Node3D.new()
	root.name = "Demo"
	root.set_script(load(dir.path_join("demo/demo.gd")))

	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.08, 0.09, 0.11)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.35, 0.37, 0.42)
	_add(root, env, "Environment")

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-45, 35, 0)
	_add(root, sun, "Sun")

	var cam := Camera3D.new()
	cam.position = Vector3(0, 0, 1.8)
	_add(root, cam, "Camera")

	var files := Array(DirAccess.get_files_at(dir.path_join("shaders"))).filter(func(f): return f.ends_with(".gdshader"))
	files.sort()
	for i in files.size():
		var mi := MeshInstance3D.new()
		mi.mesh = SphereMesh.new()
		var mat := ShaderMaterial.new()
		mat.shader = load(dir.path_join("shaders").path_join(files[i]))
		mi.material_override = mat
		mi.position.x = i * SPACING
		_add(root, mi, files[i].get_basename())
		var label := Label3D.new()
		label.text = files[i].get_basename().capitalize()
		label.position = Vector3(i * SPACING, -0.75, 0)
		label.pixel_size = 0.002
		_add(root, label, files[i].get_basename() + "_label")

	var ps := PackedScene.new()
	ps.pack(root)
	var out := dir.path_join("demo/demo.tscn")
	var err := ResourceSaver.save(ps, out)
	print("%s  shaders=%d  err=%d" % [out, files.size(), err])
	root.free()
	quit()

func _add(root: Node, n: Node, n_name: String) -> void:
	n.name = n_name
	root.add_child(n)
	n.owner = root
