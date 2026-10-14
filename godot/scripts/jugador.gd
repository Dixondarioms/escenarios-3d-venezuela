## Jugador en primera persona: camina con gravedad y colisiones, o vuela libre (tecla F).
class_name Jugador
extends CharacterBody3D

@export var velocidad := 4.5
@export var velocidad_correr := 9.0
@export var velocidad_vuelo := 30.0
@export var sensibilidad := 0.0022
@export var gravedad := 9.8
@export var salto := 4.2

var volando := false
var camara: Camera3D
var _pitch := 0.0


func _ready() -> void:
	var forma := CollisionShape3D.new()
	var capsula := CapsuleShape3D.new()
	capsula.radius = 0.3
	capsula.height = 1.75
	forma.shape = capsula
	forma.position.y = 0.875
	add_child(forma)
	camara = Camera3D.new()
	camara.position.y = 1.65
	camara.near = 0.08
	camara.far = 30000.0
	camara.fov = 70.0
	add_child(camara)
	camara.make_current()
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func colocar(t: Transform3D, fov := 70.0) -> void:
	# las cámaras de Blender miran hacia su -Z local, que al pasar a Godot (Y arriba) queda en -Y local
	var adelante := -t.basis.y
	global_position = t.origin - Vector3(0, 1.65, 0)
	rotation = Vector3(0, atan2(-adelante.x, -adelante.z), 0)
	_pitch = asin(clamp(adelante.y, -1.0, 1.0))
	camara.rotation.x = _pitch
	camara.fov = clamp(fov * 1.15, 50.0, 90.0)
	velocity = Vector3.ZERO


func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotate_y(-e.relative.x * sensibilidad)
		_pitch = clamp(_pitch - e.relative.y * sensibilidad, -1.5, 1.5)
		camara.rotation.x = _pitch
	elif e is InputEventMouseButton and e.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	elif e.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif e is InputEventKey and e.pressed and not e.echo and e.keycode == KEY_F:
		volando = not volando
		velocity = Vector3.ZERO


func _physics_process(delta: float) -> void:
	var dir := Vector3.ZERO
	var b := camara.global_transform.basis if volando else global_transform.basis
	if Input.is_key_pressed(KEY_W): dir -= b.z
	if Input.is_key_pressed(KEY_S): dir += b.z
	if Input.is_key_pressed(KEY_A): dir -= b.x
	if Input.is_key_pressed(KEY_D): dir += b.x
	if volando:
		if Input.is_key_pressed(KEY_E) or Input.is_key_pressed(KEY_SPACE): dir += Vector3.UP
		if Input.is_key_pressed(KEY_Q) or Input.is_key_pressed(KEY_CTRL): dir -= Vector3.UP
		var v := velocidad_vuelo * (4.0 if Input.is_key_pressed(KEY_SHIFT) else 1.0)
		velocity = dir.normalized() * v
		global_position += velocity * delta
		return
	dir.y = 0.0
	dir = dir.normalized()
	var v := velocidad_correr if Input.is_key_pressed(KEY_SHIFT) else velocidad
	velocity.x = dir.x * v
	velocity.z = dir.z * v
	if is_on_floor():
		if Input.is_key_pressed(KEY_SPACE):
			velocity.y = salto
	else:
		velocity.y -= gravedad * delta
	move_and_slide()
	if global_position.y < -2000.0:
		volando = true
