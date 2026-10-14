## Carga una zona exportada desde Blender (godot/zonas/<zona>/zona.json) y la transmite por celdas
## alrededor del jugador: geometría, materiales, objetos repetidos (MultiMesh), pasto y colisiones.
class_name Mundo
extends Node3D

signal celda_cargada(i: int, j: int)

@export var radio_carga := 1100.0      # m: celdas que se cargan alrededor del jugador
@export var radio_colision := 260.0    # m: celdas con colisión (para caminar y manejar)
@export var radio_pasto := 70.0        # m: distancia máxima del pasto 3D
@export var densidad_pasto := 1.0      # 0..1 de las matas exportadas
@export var calidad := 1               # 0 = baja, 1 = media, 2 = alta

const CAPAS_COLISION := ["Edificios", "Calles", "Aceras", "Senderos", "Areas", "Terreno", "Aviacion", "Detalles"]

var datos := {}
var base := ""
var materiales: Materiales
var biblioteca := {}        # nombre de colección -> Mesh (con materiales reemplazados)
var malla_pasto: Mesh
var celdas := {}            # Vector2i -> {"datos": {...}, "nodo": Node3D, "estado": String}
var foco := Vector3.ZERO    # posición del jugador
var _pendientes := {}       # ruta -> Vector2i
var _tiempo := 0.0


func cargar_zona(id: String) -> void:
	base = "res://zonas/%s/" % id
	var f := FileAccess.open(base + "zona.json", FileAccess.READ)
	if f == null:
		push_error("No existe %szona.json: exporta la zona con scripts/godot/05_exportar_godot.py" % base)
		return
	datos = JSON.parse_string(f.get_as_text())
	materiales = Materiales.new(datos)
	_cargar_biblioteca()
	malla_pasto = Pasto.crear_malla()
	for c in datos["celdas"]:
		celdas[Vector2i(int(c["i"]), int(c["j"]))] = {"datos": c, "nodo": null, "estado": "libre"}
	if datos.get("fondo"):
		var fondo: PackedScene = load(base + datos["fondo"])
		if fondo:
			var n := fondo.instantiate()
			n.name = "Fondo"
			materiales.aplicar(n)
			for mi in n.find_children("*", "MeshInstance3D", true, false):
				mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
				if OS.get_environment("OCULTAR") != "" and String(mi.name).begins_with(OS.get_environment("OCULTAR")):
					mi.visible = false
			add_child(n)


## Carga sin hilos las celdas cercanas a 'p' (para empezar sin ver el mundo vacío).
func cargar_alrededor(p: Vector3, radio := 400.0) -> void:
	foco = p
	for k in celdas:
		var c = celdas[k]
		if _distancia(c["datos"], p) < radio and c["estado"] == "libre":
			var d: Dictionary = c["datos"]
			var escena: PackedScene = load(base + d["glb"]) if d.get("glb") else null
			_montar(k, escena)
	_actualizar_colisiones()
	_actualizar_pasto()


func _process(delta: float) -> void:
	_tiempo += delta
	if _tiempo < 0.4 or datos.is_empty():
		return
	_tiempo = 0.0
	_revisar_pendientes()
	var por_cargar := []
	for k in celdas:
		var c = celdas[k]
		var d := _distancia(c["datos"], foco)
		if d < radio_carga and c["estado"] == "libre":
			por_cargar.append([d, k])
		elif d > radio_carga + 250.0 and c["estado"] == "lista":
			c["nodo"].queue_free()
			c["nodo"] = null
			c["estado"] = "libre"
	por_cargar.sort_custom(func(a, b): return a[0] < b[0])
	_actualizar_pasto()
	for par in por_cargar.slice(0, 3):   # pocas a la vez para no trabar
		var k: Vector2i = par[1]
		var dd: Dictionary = celdas[k]["datos"]
		if dd.get("glb"):
			var ruta: String = base + dd["glb"]
			ResourceLoader.load_threaded_request(ruta, "PackedScene", true)
			_pendientes[ruta] = k
			celdas[k]["estado"] = "cargando"
		else:
			_montar(k, null)
	_actualizar_colisiones()


func _revisar_pendientes() -> void:
	for ruta in _pendientes.keys():
		var st := ResourceLoader.load_threaded_get_status(ruta)
		if st == ResourceLoader.THREAD_LOAD_IN_PROGRESS:
			continue
		var k: Vector2i = _pendientes[ruta]
		_pendientes.erase(ruta)
		var escena: PackedScene = ResourceLoader.load_threaded_get(ruta) if st == ResourceLoader.THREAD_LOAD_LOADED else null
		_montar(k, escena)


func _distancia(d: Dictionary, p: Vector3) -> float:
	var c: Array = d["centro"]
	return Vector2(c[0] - p.x, c[2] - p.z).length()


func _montar(k: Vector2i, escena: PackedScene) -> void:
	var c = celdas[k]
	var d: Dictionary = c["datos"]
	var nodo := Node3D.new()
	nodo.name = "Celda_%d_%d" % [k.x, k.y]
	if escena:
		var geo := escena.instantiate()
		materiales.aplicar(geo)
		nodo.add_child(geo)
	if d.get("instancias"):
		_instancias(nodo, base + d["instancias"])
	add_child(nodo)
	c["nodo"] = nodo
	c["estado"] = "lista"
	c["colision"] = false
	c["pasto_nodo"] = null
	celda_cargada.emit(k.x, k.y)


## El pasto solo existe en las celdas cercanas (cada trozo es un MultiMesh: muchos agotan la GPU).
func _actualizar_pasto() -> void:
	if densidad_pasto <= 0.0:
		return
	var limite := radio_pasto + 200.0
	for k in celdas:
		var c = celdas[k]
		if c["estado"] != "lista" or not c["datos"].get("pasto"):
			continue
		var cerca := _distancia(c["datos"], foco) < limite
		if cerca and c.get("pasto_nodo") == null:
			var n := Node3D.new()
			n.name = "Pasto"
			Pasto.sembrar(n, base + c["datos"]["pasto"], malla_pasto, radio_pasto, densidad_pasto)
			c["nodo"].add_child(n)
			c["pasto_nodo"] = n
		elif not cerca and c.get("pasto_nodo") != null:
			c["pasto_nodo"].queue_free()
			c["pasto_nodo"] = null


func _actualizar_colisiones() -> void:
	for k in celdas:
		var c = celdas[k]
		if c["estado"] != "lista" or c.get("colision", false):
			continue
		if _distancia(c["datos"], foco) < radio_colision:
			for mi in c["nodo"].find_children("*", "MeshInstance3D", true, false):
				if not mi.name.get_slice("_", 0) in CAPAS_COLISION:
					continue
				var cuerpo := StaticBody3D.new()
				var forma := CollisionShape3D.new()
				forma.shape = mi.mesh.create_trimesh_shape()
				cuerpo.add_child(forma)
				mi.add_child(cuerpo)
			c["colision"] = true


func _cargar_biblioteca() -> void:
	var escena: PackedScene = load(base + datos.get("biblioteca", "biblioteca.glb"))
	if escena == null:
		return
	var raiz := escena.instantiate()
	for mi in raiz.find_children("*", "MeshInstance3D", true, false):
		if mi.mesh:
			biblioteca[String(mi.name)] = materiales.malla_con_materiales(mi.mesh)
	raiz.free()


func _malla_de(nombre: String) -> Mesh:
	var n := nombre.validate_node_name()
	return biblioteca.get(n, biblioteca.get(nombre, null))


## Distancias (m) de [detalle completo, versión lejana] de cada tipo de objeto, según la calidad.
func _alcance(nombre: String) -> Vector2:
	var f: float = [0.7, 1.0, 1.5][calidad]
	var a := Vector2(250.0, 900.0)
	if nombre.begins_with("Usr_") and not ("helicoptero" in nombre or "avion" in nombre):
		a = Vector2(90.0, 600.0)
	elif "helicoptero" in nombre or "avion" in nombre:
		a = Vector2(250.0, 1800.0)
	elif "aire" in nombre or "tapa" in nombre or "hidrante" in nombre or "papelera" in nombre or "canna" in nombre:
		a = Vector2(70.0, 160.0)
	elif "tanque" in nombre or "casilla" in nombre or "banco" in nombre or "luz_" in nombre:
		a = Vector2(150.0, 450.0)
	elif "arbol" in nombre:
		a = Vector2(160.0, 2400.0)
	return a * f


func _instancias(nodo: Node3D, ruta: String) -> void:
	var f := FileAccess.open(ruta, FileAccess.READ)
	if f == null:
		return
	var d: Dictionary = JSON.parse_string(f.get_as_text())
	for nombre in d:
		var malla := _malla_de(nombre)
		if malla == null:
			continue
		var lejos := _malla_de(nombre + "__lejos")
		var a := _alcance(nombre)
		var sombra: bool = not ("aire" in nombre or "tapa" in nombre or "canna" in nombre or "luz_" in nombre or "hidrante" in nombre)
		# la distancia de visibilidad se mide desde el centro de cada grupo: grupos pequeños para alcances cortos
		if lejos:
			for g in _agrupar(d[nombre], clamp(a.x * 0.6, 40.0, 260.0)):
				_multimesh(nodo, nombre, malla, g, 0.0, a.x, sombra)
			for g in _agrupar(d[nombre], clamp(a.y * 0.4, 60.0, 260.0)):
				_multimesh(nodo, nombre + "__lejos", lejos, g, a.x, a.y, sombra and "arbol" in nombre)
		else:
			for g in _agrupar(d[nombre], clamp(a.y * 0.6, 40.0, 260.0)):
				_multimesh(nodo, nombre, malla, g, 0.0, a.y, sombra)


func _agrupar(lista: Array, lado: float) -> Array:
	var grupos := {}
	for t in lista:
		var k := Vector2i(floori(t[9] / lado), floori(t[11] / lado))
		if not grupos.has(k):
			grupos[k] = []
		grupos[k].append(t)
	return grupos.values()


func _multimesh(nodo: Node3D, nombre: String, malla: Mesh, lista: Array, desde: float, hasta: float, sombra: bool) -> void:
	# el nodo va en el centro de sus instancias (la distancia de visibilidad se mide desde ahí)
	var centro := Vector3.ZERO
	for t in lista:
		centro += Vector3(t[9], t[10], t[11])
	centro /= max(lista.size(), 1)
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = malla
	mm.instance_count = lista.size()
	for i in lista.size():
		var t: Array = lista[i]
		mm.set_instance_transform(i, Transform3D(Basis(Vector3(t[0], t[1], t[2]), Vector3(t[3], t[4], t[5]),
			Vector3(t[6], t[7], t[8])), Vector3(t[9], t[10], t[11]) - centro))
	var mmi := MultiMeshInstance3D.new()
	mmi.name = nombre.validate_node_name()
	mmi.position = centro
	mmi.multimesh = mm
	mmi.visibility_range_begin = desde
	mmi.visibility_range_end = hasta
	mmi.visibility_range_begin_margin = 10.0
	mmi.visibility_range_end_margin = 20.0
	mmi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_DISABLED
	if not sombra:
		mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	nodo.add_child(mmi)


## Altura del suelo bajo (x, z) usando las colisiones cargadas (o la de la celda si no hay).
func altura_suelo(x: float, z: float, desde := 3000.0) -> float:
	var espacio := get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(Vector3(x, desde, z), Vector3(x, -2000.0, z))
	var r := espacio.intersect_ray(q)
	return r["position"].y if r else 0.0
