extends Node3D
## Walkaround scene. Everything is built at runtime from what tools/sync_packs.gd put in res://addons:
## - spatial shaders (shaders/*.gdshader) on spheres on a pedestal grid
## - AudioStreamRandomizers (*.tres): footsteps when the name has "foot" or "step", else sound-panel buttons
## - UI Themes (*.tres): applied to the sound panel and the pause menu (Esc)
## - VFX scenes (*.tscn at the addon root) on pads in a row behind the shaders
## - mesh kits (*.glb, *.gltf) laid out on a 0.5 m grid to the side

const Player := preload("res://player.gd")
const COLUMNS := 4
const SPACING := 3.0
const MESH_GRID := 0.5

var shader_count := 0
var sound_count := 0
var footsteps := false
var button_count := 0
var vfx_count := 0
var mesh_count := 0
var theme_count := 0

var _player: CharacterBody3D
var _panel: VBoxContainer
var _pause: PanelContainer


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS   # the pause menu keeps working while the world is paused
	_world()
	_player = Player.new()
	_player.position = Vector3(0, 0.1, 6)
	_player.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(_player)
	var hud := CanvasLayer.new()
	add_child(hud)
	_panel = VBoxContainer.new()
	_panel.position = Vector2(16, 16)
	hud.add_child(_panel)
	_pause = _pause_menu()
	hud.add_child(_pause)
	for addon in _addons():
		_place_addon(addon)
	if shader_count + sound_count + vfx_count + mesh_count == 0:
		var empty := Label.new()
		empty.text = "No approved, packaged packs yet. Approve and package one in the Asset Studio."
		_panel.add_child(empty)


func counts() -> Dictionary:
	return {"shaders": shader_count, "sounds": sound_count, "footsteps": footsteps, "buttons": button_count,
		"vfx": vfx_count, "meshes": mesh_count, "themes": theme_count}


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.physical_keycode == KEY_ESCAPE:
		_set_paused(not get_tree().paused)
		get_viewport().set_input_as_handled()


func _set_paused(paused: bool) -> void:
	get_tree().paused = paused
	_pause.visible = paused
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


func _place_addon(addon: String) -> void:
	var title := addon.get_file()
	for path in _files(addon.path_join("shaders"), [".gdshader"]):
		var shader := load(path) as Shader
		if shader and shader.get_mode() == Shader.MODE_SPATIAL:
			_pedestal(shader_count, shader, "%s / %s" % [title, path.get_file().get_basename()])
			shader_count += 1
	for path in _files(addon, [".tres"]):
		var res := load(path)
		var label := path.get_file().get_basename()
		if res is AudioStreamRandomizer:
			sound_count += 1
			if "foot" in label.to_lower() or "step" in label.to_lower():
				_player.footsteps = res
				footsteps = true
			else:
				_sound_button(label, res)
		elif res is Theme:
			theme_count += 1
			_panel.theme = res
			_pause.theme = res
	for path in _files(addon, [".tscn"]):
		var scene := load(path) as PackedScene
		if scene:
			_vfx(vfx_count, scene.instantiate(), "%s / %s" % [title, path.get_file().get_basename()])
			vfx_count += 1
	for path in _files(addon, [".glb", ".gltf"]):
		var scene := load(path) as PackedScene
		if scene:
			_mesh(mesh_count, scene.instantiate())
			mesh_count += 1


func _addons() -> PackedStringArray:
	var found := PackedStringArray()
	if not DirAccess.dir_exists_absolute("res://addons"):   # nothing synced yet
		return found
	for name in DirAccess.get_directories_at("res://addons"):
		if not name.begins_with("."):
			found.append("res://addons".path_join(name))
	return found


func _files(dir: String, extensions: Array) -> PackedStringArray:
	var found := PackedStringArray()
	if not DirAccess.dir_exists_absolute(dir):
		return found
	for name in DirAccess.get_files_at(dir):
		if extensions.has("." + name.get_extension().to_lower()):
			found.append(dir.path_join(name))
	return found


func _grid_spot(index: int, row_offset: float) -> Vector3:
	return Vector3((index % COLUMNS - (COLUMNS - 1) / 2.0) * SPACING, 0, row_offset - floorf(index / float(COLUMNS)) * SPACING)


func _pedestal(index: int, shader: Shader, title: String) -> void:
	var spot := _grid_spot(index, 0.0)
	_column(spot, 1.0)
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
	_tag(spot + Vector3(0, 2.4, 0), title)


func _vfx(index: int, node: Node, title: String) -> void:
	var spot := _grid_spot(index, -12.0)   # a row behind the shader pedestals
	_column(spot, 0.2)
	if node is Node3D:
		node.position = spot + Vector3(0, 0.6, 0)
	add_child(node)
	_tag(spot + Vector3(0, 2.0, 0), title)


func _mesh(index: int, node: Node) -> void:
	# Kits snap together on a 0.5 m grid, so they are laid out on it (2 m apart) to the right of the pedestals.
	var spot := Vector3(snappedf(8.0 + (index % 4) * 2.0, MESH_GRID), 0, snappedf(-floorf(index / 4.0) * 2.0, MESH_GRID))
	if node is Node3D:
		node.position = spot
	add_child(node)


func _column(spot: Vector3, height: float) -> void:
	var base := StaticBody3D.new()
	base.position = spot + Vector3(0, height / 2.0, 0)
	var column := MeshInstance3D.new()
	var cylinder := CylinderMesh.new()
	cylinder.top_radius = 0.45
	cylinder.bottom_radius = 0.5
	cylinder.height = height
	column.mesh = cylinder
	base.add_child(column)
	var hit := CollisionShape3D.new()
	var shape := CylinderShape3D.new()
	shape.radius = 0.5
	shape.height = height
	hit.shape = shape
	base.add_child(hit)
	add_child(base)


func _tag(at: Vector3, text: String) -> void:
	var tag := Label3D.new()
	tag.text = text
	tag.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	tag.font_size = 24
	tag.position = at
	add_child(tag)


func _sound_button(label: String, stream: AudioStream) -> void:
	var player := AudioStreamPlayer.new()
	player.stream = stream
	add_child(player)
	var button := Button.new()
	button.text = label
	button.pressed.connect(player.play)
	_panel.add_child(button)
	button_count += 1


func _pause_menu() -> PanelContainer:
	var menu := PanelContainer.new()
	menu.visible = false
	menu.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	var box := VBoxContainer.new()
	menu.add_child(box)
	var title := Label.new()
	title.text = "Paused"
	box.add_child(title)
	var resume := Button.new()
	resume.text = "Resume"
	resume.pressed.connect(_set_paused.bind(false))
	box.add_child(resume)
	var quit := Button.new()
	quit.text = "Quit"
	quit.pressed.connect(get_tree().quit)
	box.add_child(quit)
	return menu


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
