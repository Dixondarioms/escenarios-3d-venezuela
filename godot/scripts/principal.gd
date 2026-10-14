## Escena principal: carga la zona, el cielo y el jugador, y muestra la ayuda en pantalla.
## Teclas: WASD mover · Shift correr · Espacio saltar · F volar/caminar (E/Q subir/bajar al volar)
##         1-9 ir a las cámaras de Blender · L cambiar luz · C calidad · Tab cambiar zona · H ayuda · Esc soltar ratón
## Desde la línea de comandos: godot -- --zona=altamira --calidad=0 --camara=Cam_Aeronaves
extends Node3D

const ZONAS := ["lacarlota", "altamira"]

var zona_id := "lacarlota"
var calidad := 0
var mundo: Mundo
var entorno: Entorno
var jugador: Jugador
var texto: Label
var ayuda: Label
var camaras := []
var _cuenta := 0.0
var _captura := ""          # --captura=ruta.png: guarda una imagen tras --esperar segundos y cierra
var _esperar := 12.0
var _luz_inicial := ""
var _radio := -1.0
var _sin_pasto := false


func _ready() -> void:
	var cam_inicial := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--zona="):
			zona_id = a.get_slice("=", 1)
		elif a.begins_with("--calidad="):
			calidad = int(a.get_slice("=", 1))
		elif a.begins_with("--camara="):
			cam_inicial = a.get_slice("=", 1)
		elif a.begins_with("--captura="):
			_captura = a.get_slice("=", 1)
		elif a.begins_with("--esperar="):
			_esperar = float(a.get_slice("=", 1))
		elif a.begins_with("--luz="):
			_luz_inicial = a.get_slice("=", 1)
		elif a.begins_with("--radio="):
			_radio = float(a.get_slice("=", 1))
		elif a == "--sin-pasto":
			_sin_pasto = true
		elif a == "--sin-fondo":
			set_meta("sin_fondo", true)
		elif a == "--caja":
			set_meta("caja", true)
	entorno = Entorno.new()
	add_child(entorno)
	_interfaz()
	_cargar(zona_id, cam_inicial)


func _cargar(id: String, cam_inicial := "") -> void:
	if mundo:
		mundo.queue_free()
	if jugador:
		jugador.queue_free()
	zona_id = id
	mundo = Mundo.new()
	mundo.calidad = calidad
	mundo.radio_pasto = [45.0, 70.0, 100.0][calidad]
	mundo.densidad_pasto = [0.45, 0.8, 1.0][calidad]
	mundo.radio_carga = [600.0, 800.0, 1300.0][calidad] if _radio < 0.0 else _radio
	if _sin_pasto:
		mundo.densidad_pasto = 0.0
	add_child(mundo)
	mundo.cargar_zona(id)
	if has_meta("sin_fondo") and mundo.has_node("Fondo"):
		mundo.get_node("Fondo").visible = false
	entorno.luces = mundo.datos.get("luces", {})
	entorno.aplicar_luz(_luz_inicial if _luz_inicial != "" else mundo.datos.get("luz_inicial", "mediodia"))
	entorno.aplicar_calidad(calidad, get_viewport())
	camaras = mundo.datos.get("camaras", {}).keys()
	camaras.sort()
	jugador = Jugador.new()
	add_child(jugador)
	var inicio := cam_inicial if cam_inicial in camaras else _camara_a_pie()
	_ir_a_camara(inicio)


func _camara_a_pie() -> String:
	# la primera cámara cercana al suelo (las de Blender con "ojo" están a 1,7 m)
	for c in camaras:
		var t: Array = mundo.datos["camaras"][c]["transform"]
		if t[10] < mundo.datos.get("z_origen_msnm", 0.0) * 0.0 + 60.0:
			return c
	return camaras[0] if camaras.size() > 0 else ""


func _ir_a_camara(nombre: String) -> void:
	if nombre == "":
		return
	var c: Dictionary = mundo.datos["camaras"][nombre]
	var t: Array = c["transform"]
	var tr := Transform3D(Basis(Vector3(t[0], t[1], t[2]), Vector3(t[3], t[4], t[5]), Vector3(t[6], t[7], t[8])),
		Vector3(t[9], t[10], t[11]))
	mundo.cargar_alrededor(tr.origin, 420.0)
	jugador.colocar(tr, float(c.get("fov", 60.0)))
	# alto sobre el suelo (azoteas, drones): empieza volando
	jugador.volando = tr.origin.y - mundo.altura_suelo(tr.origin.x, tr.origin.z, tr.origin.y + 0.5) > 4.0
	_mensaje("Cámara: %s" % nombre)
	if has_meta("caja"):  # prueba de sombras: caja de 4 × 6 m delante de la cámara
		var caja := MeshInstance3D.new()
		caja.mesh = BoxMesh.new()
		caja.mesh.size = Vector3(4, 6, 4)
		var adelante := -jugador.global_transform.basis.z
		var p := jugador.global_position + adelante * 14.0
		caja.position = Vector3(p.x, mundo.altura_suelo(p.x, p.z, p.y + 50.0) + 3.0, p.z)
		add_child(caja)


func _interfaz() -> void:
	var capa := CanvasLayer.new()
	add_child(capa)
	texto = Label.new()
	texto.position = Vector2(12, 8)
	texto.add_theme_color_override("font_shadow_color", Color.BLACK)
	texto.add_theme_constant_override("shadow_offset_x", 1)
	texto.add_theme_constant_override("shadow_offset_y", 1)
	capa.add_child(texto)
	ayuda = Label.new()
	ayuda.position = Vector2(12, 34)
	ayuda.text = ("WASD mover · Shift correr · Espacio saltar · F volar (E/Q subir/bajar)\n"
		+ "1-9 cámaras · L luz · C calidad · Tab zona · H ocultar ayuda · Esc soltar ratón")
	ayuda.add_theme_color_override("font_shadow_color", Color.BLACK)
	ayuda.add_theme_constant_override("shadow_offset_x", 1)
	ayuda.add_theme_constant_override("shadow_offset_y", 1)
	capa.add_child(ayuda)


func _mensaje(m: String) -> void:
	_cuenta = 3.0
	texto.set_meta("mensaje", m)


func _process(delta: float) -> void:
	if mundo and jugador:
		mundo.foco = jugador.global_position
	if _captura != "":
		_esperar -= delta
		if _esperar <= 0.0:
			var ruta := _captura
			_captura = ""
			ayuda.visible = false
			texto.visible = false
			var celdas_listas := 0
			for k in mundo.celdas:
				if mundo.celdas[k]["estado"] == "lista":
					celdas_listas += 1
			print("FPS ", Engine.get_frames_per_second(), " celdas ", celdas_listas,
				" objetos ", RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_OBJECTS_IN_FRAME),
				" primitivas ", RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_PRIMITIVES_IN_FRAME),
				" llamadas ", RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME),
				" VRAM MB ", RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_VIDEO_MEM_USED) / 1048576)
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(ruta)
			print("CAPTURA ", ruta, " sol ", -entorno.sol.global_transform.basis.z, " energia ", entorno.sol.light_energy, " sombras ", entorno.sol.shadow_enabled)
			_diagnostico()
			get_tree().quit()
			return
	_cuenta -= delta
	var linea := "%s · %d FPS · luz: %s · calidad: %s · %s" % [mundo.datos.get("nombre", zona_id) if mundo else "",
		Engine.get_frames_per_second(), entorno.luz_actual, ["baja", "media", "alta"][calidad],
		"volando" if jugador and jugador.volando else "a pie"]
	if _cuenta > 0.0:
		linea += "   ·   " + str(texto.get_meta("mensaje", ""))
	texto.text = linea


func _unhandled_input(e: InputEvent) -> void:
	if not (e is InputEventKey and e.pressed and not e.echo):
		return
	match e.keycode:
		KEY_L:
			_mensaje("Luz: %s" % entorno.siguiente_luz())
		KEY_C:
			calidad = (calidad + 1) % 3
			entorno.aplicar_calidad(calidad, get_viewport())
			mundo.calidad = calidad
			_mensaje("Calidad: %s (el pasto y la distancia cambian al recargar con Tab)" % ["baja", "media", "alta"][calidad])
		KEY_TAB:
			_cargar(ZONAS[(ZONAS.find(zona_id) + 1) % ZONAS.size()])
		KEY_H:
			ayuda.visible = not ayuda.visible
		_:
			if e.keycode >= KEY_1 and e.keycode <= KEY_9:
				var i: int = e.keycode - KEY_1
				if i < camaras.size():
					_ir_a_camara(camaras[i])


func _tris(m: Mesh) -> int:
	var n := 0
	for s in m.get_surface_count():
		var arr := m.surface_get_arrays(s)
		var idx = arr[Mesh.ARRAY_INDEX]
		n += (idx.size() if idx != null else arr[Mesh.ARRAY_VERTEX].size()) / 3
	return n


func _diagnostico() -> void:
	for mi in find_children("*", "GeometryInstance3D", true, false):
		var bb: AABB = mi.get_aabb()
		if bb.size.x > 700.0 or bb.size.z > 700.0:
			print("GRANDE ", mi.get_path(), " ", bb.size, " y=", bb.position.y)
	var por_tipo := {}
	for mmi in mundo.find_children("*", "MultiMeshInstance3D", true, false):
		var mm: MultiMesh = mmi.multimesh
		var clave := String(mmi.name) if not mmi.get_parent().name == "Pasto" else "Pasto"
		var t: int = _tris(mm.mesh) * mm.instance_count
		por_tipo[clave] = por_tipo.get(clave, 0) + t
	for mi in mundo.find_children("*", "MeshInstance3D", true, false):
		var clave := "Celda:" + String(mi.name).get_slice("_", 0)
		por_tipo[clave] = por_tipo.get(clave, 0) + _tris(mi.mesh)
	var lista := por_tipo.keys()
	lista.sort_custom(func(a, b): return por_tipo[a] > por_tipo[b])
	for k in lista.slice(0, 25):
		print("TRIS ", k, " ", por_tipo[k])
