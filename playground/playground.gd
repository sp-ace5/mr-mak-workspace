extends Node3D
## Walkaround scene. Everything is built at runtime from what tools/sync_packs.gd put in res://addons:
## spatial shaders on spheres on a pedestal grid, AudioStreamRandomizers as footsteps (name contains
## "foot" or "step") or as buttons in the sound panel. Other content types come later.

const Player := preload("res://player.gd")
const COLUMNS := 4
const SPACING := 3.0

var shader_count := 0
var sound_count := 0


func _ready() -> void:
	_world()
	var player: CharacterBody3D = Player.new()
	player.position = Vector3(0, 0.1, 6)
	add_child(player)
	var hud := CanvasLayer.new()
	add_child(hud)
	var panel := VBoxContainer.new()
	panel.position = Vector2(16, 16)
	hud.add_child(panel)
	for addon in _addons():
		for path in _files(addon.path_join("shaders"), ".gdshader"):
			var shader := load(path) as Shader
			if shader and shader.get_mode() == Shader.MODE_SPATIAL:
				_pedestal(shader_count, shader, "%s / %s" % [addon.get_file(), path.get_file().get_basename()])
				shader_count += 1
		for path in _files(addon, ".tres"):
			var stream := load(path) as AudioStreamRandomizer
			if stream == null:
				continue
			sound_count += 1
			var label := path.get_file().get_basename()
			if "foot" in label.to_lower() or "step" in label.to_lower():
				player.footsteps = stream
			else:
				_sound_button(panel, label, stream)
	if shader_count + sound_count == 0:
		var empty := Label.new()
		empty.text = "No approved, packaged packs yet. Approve and package one in the Asset Studio."
		panel.add_child(empty)


func _addons() -> PackedStringArray:
	var found := PackedStringArray()
	if not DirAccess.dir_exists_absolute("res://addons"):   # nothing synced yet
		return found
	for name in DirAccess.get_directories_at("res://addons"):
		if not name.begins_with("."):
			found.append("res://addons".path_join(name))
	return found


func _files(dir: String, ext: String) -> PackedStringArray:
	var found := PackedStringArray()
	if not DirAccess.dir_exists_absolute(dir):
		return found
	for name in DirAccess.get_files_at(dir):
		if name.ends_with(ext):
			found.append(dir.path_join(name))
	return found


func _pedestal(index: int, shader: Shader, title: String) -> void:
	var spot := Vector3((index % COLUMNS - (COLUMNS - 1) / 2.0) * SPACING, 0, -floorf(index / float(COLUMNS)) * SPACING)
	var base := StaticBody3D.new()
	base.position = spot + Vector3(0, 0.5, 0)
	var column := MeshInstance3D.new()
	var cylinder := CylinderMesh.new()
	cylinder.top_radius = 0.45
	cylinder.bottom_radius = 0.5
	cylinder.height = 1.0
	column.mesh = cylinder
	base.add_child(column)
	var hit := CollisionShape3D.new()
	var shape := CylinderShape3D.new()
	shape.radius = 0.5
	shape.height = 1.0
	hit.shape = shape
	base.add_child(hit)
	add_child(base)
	var ball := MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 0.5
	sphere.height = 1.0
	ball.mesh = sphere
	var material := ShaderMaterial.new()
	material.shader = shader
	ball.material_override = material
	ball.position = spot + Vector3(0, 1.6, 0)
	add_child(ball)
	var tag := Label3D.new()
	tag.text = title
	tag.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	tag.font_size = 24
	tag.position = spot + Vector3(0, 2.4, 0)
	add_child(tag)


func _sound_button(panel: VBoxContainer, label: String, stream: AudioStream) -> void:
	var player := AudioStreamPlayer.new()
	player.stream = stream
	add_child(player)
	var button := Button.new()
	button.text = label
	button.pressed.connect(player.play)
	panel.add_child(button)


func _world() -> void:
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_SKY
	env.environment.sky = Sky.new()
	env.environment.sky.sky_material = ProceduralSkyMaterial.new()
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, -30, 0)
	sun.shadow_enabled = true
	add_child(sun)
	var ground := StaticBody3D.new()
	var floor_mesh := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(60, 60)
	floor_mesh.mesh = plane
	ground.add_child(floor_mesh)
	var hit := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(60, 1, 60)
	hit.shape = box
	hit.position = Vector3(0, -0.5, 0)
	ground.add_child(hit)
	add_child(ground)
