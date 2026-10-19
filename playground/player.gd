extends CharacterBody3D
## Capsule third-person controller: WASD or arrows to walk, click to capture the mouse and look, Esc to release.

const SPEED := 5.0
const LOOK := 0.004
const STEP_SECONDS := 0.45

var footsteps: AudioStream:
	set(value):
		footsteps = value
		if _steps:
			_steps.stream = value

var _arm: SpringArm3D
var _steps: AudioStreamPlayer3D
var _step_left := 0.0


func _ready() -> void:
	var body := CollisionShape3D.new()
	body.shape = CapsuleShape3D.new()   # radius 0.5, height 2
	body.position.y = 1.0
	add_child(body)
	var look := MeshInstance3D.new()
	look.mesh = CapsuleMesh.new()
	look.position.y = 1.0
	add_child(look)
	_arm = SpringArm3D.new()
	_arm.position.y = 1.6
	_arm.spring_length = 4.0
	_arm.add_excluded_object(get_rid())
	add_child(_arm)
	_arm.add_child(Camera3D.new())
	_steps = AudioStreamPlayer3D.new()
	_steps.stream = footsteps
	add_child(_steps)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	elif event is InputEventKey and event.pressed and event.physical_keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotate_y(-event.relative.x * LOOK)
		_arm.rotation.x = clampf(_arm.rotation.x - event.relative.y * LOOK, -1.2, 0.4)


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity += get_gravity() * delta
	var input := Vector2(_key(KEY_D, KEY_RIGHT) - _key(KEY_A, KEY_LEFT), _key(KEY_S, KEY_DOWN) - _key(KEY_W, KEY_UP))
	var direction := (transform.basis * Vector3(input.x, 0, input.y)).normalized()
	velocity.x = direction.x * SPEED
	velocity.z = direction.z * SPEED
	move_and_slide()
	if footsteps and is_on_floor() and direction != Vector3.ZERO:
		_step_left -= delta
		if _step_left <= 0.0:
			_steps.play()
			_step_left = STEP_SECONDS


func _key(a: Key, b: Key) -> float:
	return 1.0 if Input.is_physical_key_pressed(a) or Input.is_physical_key_pressed(b) else 0.0
