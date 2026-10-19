extends Node3D
# Fixed preview rig: same camera, light, sky and turntable for every asset, so store thumbnails match.
# Shader:  godot --path godot_harness --rendering-method forward_plus --resolution 512x512 \
#            --write-movie build/prev/x/f.png --fixed-fps 30 --quit-after 90 res://preview.tscn -- res://pack/x.gdshader

const SPIN_DEG_PER_S := 120.0   # 90 frames @ 30 fps = one full 360 turn: first and last frame line up
var subject: Node3D

func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	var target: String = args[0] if args.size() > 0 else ""
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.08, 0.09, 0.11)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.35, 0.37, 0.42)
	add_child(env)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-45, 35, 0)
	add_child(sun)

	var cam := Camera3D.new()
	cam.position = Vector3(0, 0.75, 1.5)   # 1 m sphere fills ~40% of frame height
	cam.look_at_from_position(cam.position, Vector3(0, 0.5, 0))
	add_child(cam)

	subject = Node3D.new()
	add_child(subject)
	if target.ends_with(".gdshader"):
		var mi := MeshInstance3D.new()
		var sphere := SphereMesh.new()
		var mat := ShaderMaterial.new()
		var sh: Shader = load(target)
		mat.shader = sh
		sphere.material = mat
		mi.mesh = sphere
		mi.position.y = 0.5
		subject.add_child(mi)
	elif target.ends_with(".tscn") or target.ends_with(".glb"):
		subject.add_child((load(target) as PackedScene).instantiate())
	print("preview: ", target)

func _process(delta: float) -> void:
	subject.rotate_y(deg_to_rad(SPIN_DEG_PER_S) * delta)
