## Biblioteca de materiales: reemplaza los materiales M_* que vienen de Blender (solo con el nombre) por
## shaders que reproducen los de 03b_realismo.py. Los que no tienen shader propio usan los valores fijos
## exportados en zona.json ("materiales_simples").
class_name Materiales
extends RefCounted

const SH := {
	"tile": preload("res://shaders/tile_pbr.gdshader"),
	"fachada": preload("res://shaders/fachada.gdshader"),
	"vidrio": preload("res://shaders/vidrio.gdshader"),
	"reja": preload("res://shaders/reja.gdshader"),
	"via": preload("res://shaders/via.gdshader"),
	"pasto": preload("res://shaders/pasto.gdshader"),
	"terreno": preload("res://shaders/terreno.gdshader"),
	"fondo": preload("res://shaders/fondo.gdshader"),
	"agua": preload("res://shaders/agua.gdshader"),
	"especial": preload("res://shaders/especial.gdshader"),
}

# nombre -> [shader, textura (material de recursos.json) o "", parámetros]
const ESPEC := {
	"M_Fachada_Friso": ["fachada", "M_Fachada_Friso", {"pintada": true}],
	"M_Fachada_Casa": ["fachada", "M_Fachada_Casa", {"pintada": true}],
	"M_Fachada_Beige": ["fachada", "M_Fachada_Beige", {"pintada": true}],
	"M_Fachada_Comercial": ["fachada", "M_Fachada_Comercial", {"pintada": true}],
	"M_Muro": ["fachada", "M_Fachada_Friso", {"pintada": true}],
	"M_Fachada_Ladrillo": ["fachada", "M_Fachada_Ladrillo", {"pintada": false}],
	"M_Fachada_Ceramica": ["fachada", "M_Fachada_Ceramica", {"pintada": false}],
	"M_Fachada_Concreto": ["fachada", "M_Fachada_Concreto", {"pintada": false}],
	"M_Fachada_Gris": ["fachada", "M_Fachada_Comercial", {"pintada": false, "tinte": Vector3(0.82, 0.83, 0.84)}],
	"M_Vidrio": ["vidrio", "", {"base": Vector3(0.015, 0.02, 0.025), "cortinas": 0.55, "marco_ancho": 0.06, "interior_brillo": 0.05}],
	"M_Vidrio_Oficina": ["vidrio", "", {"base": Vector3(0.03, 0.07, 0.08), "cortinas": 0.15, "marco_ancho": 0.025, "interior_brillo": 0.03}],
	"M_Vidrio_Local": ["vidrio", "", {"base": Vector3(0.02, 0.02, 0.02), "cortinas": 0.3, "marco_ancho": 0.03, "interior_brillo": 0.18}],
	"M_Reja": ["reja", "", {"modo": 0, "barrotes_u": 9.0, "barrotes_v": 2.0}],
	"M_Cerca": ["reja", "", {"modo": 1, "barrotes_u": 8.0, "barrotes_v": 0.55}],
	"M_Barrotes": ["reja", "", {"modo": 2, "barrotes_u": 7.0, "color": Vector3(0.02, 0.02, 0.022), "metal": 0.3, "rugosidad": 0.5}],
	"M_Baranda": ["reja", "", {"modo": 2, "barrotes_u": 9.0, "riel2_a": 0.98, "riel2_b": 1.05, "color": Vector3(0.02, 0.02, 0.022), "metal": 0.3, "rugosidad": 0.5}],
	"M_Marca_Espera": ["reja", "", {"modo": 3, "color": Vector3(0.8, 0.56, 0.04), "metal": 0.0, "rugosidad": 0.6}],
	"M_Asfalto": ["via", "M_Asfalto", {"modo": 0}],
	"M_Cebra": ["via", "M_Asfalto", {"modo": 1}],
	"M_Pista": ["via", "M_Asfalto", {"modo": 2, "tinte": Vector3(0.34, 0.34, 0.36)}],
	"M_Rodaje": ["via", "M_Asfalto", {"modo": 3, "tinte": Vector3(0.4, 0.4, 0.42)}],
	"M_Plataforma": ["tile", "M_Techo_Concreto", {"tinte": Vector3(0.6, 0.63, 0.68), "macro_cantidad": 0.18, "junta_cada": 5.0, "manchas_aceite": 0.55}],
	"M_Pasto": ["pasto", "M_Grama", {"modo": 0}],
	"M_Grama": ["pasto", "M_Grama", {"modo": 1}],
	"M_Seto": ["tile", "M_Grama", {"tinte": Vector3(0.35, 0.55, 0.3), "macro_cantidad": 0.3, "normal_fuerza": 2.0}],
	"M_Agua": ["agua", "", {}],
	"M_Agua_Fuente": ["agua", "", {"color": Vector3(0.05, 0.36, 0.40), "ondas": 0.15}],
	"M_Acera": ["tile", "M_Acera", {"macro_cantidad": 0.18}],
	"M_Brocal": ["tile", "M_Brocal", {"macro_cantidad": 0.1}],
	"M_Sendero": ["tile", "M_Sendero", {"macro_cantidad": 0.12}],
	"M_Escalera": ["tile", "M_Brocal", {"macro_cantidad": 0.1}],
	"M_Plaza": ["tile", "M_Plaza", {"macro_cantidad": 0.1}],
	"M_Cancha": ["tile", "M_Cancha", {"tinte": Vector3(0.55, 0.75, 0.62), "macro_cantidad": 0.1}],
	"M_Techo": ["tile", "M_Techo", {"macro_cantidad": 0.2}],
	"M_Techo_Concreto": ["tile", "M_Techo_Concreto", {"macro_cantidad": 0.2}],
	"M_Santamaria": ["tile", "M_Santamaria", {"macro_cantidad": 0.05, "escala": 0.5}],
	"M_Monumento": ["tile", "M_Fachada_Beige", {"escala": 3.0, "tinte": Vector3(1.0, 0.86, 0.66), "con_suciedad": true}],
	"M_Relieve": ["tile", "M_Fachada_Beige", {"escala": 3.0, "tinte": Vector3(0.92, 0.78, 0.6), "normal_fuerza": 2.0}],
	"M_Piedra_Fuente": ["tile", "M_Brocal", {"tinte": Vector3(0.55, 0.43, 0.32), "rugosidad_mult": 0.45}],
	"M_Muro_Blanco": ["tile", "M_Fachada_Casa", {"tinte": Vector3(1.0, 1.0, 0.97), "con_suciedad": true}],
	"M_Concreto_Claro": ["tile", "M_Fachada_Concreto", {"tinte": Vector3(1.1, 1.08, 1.02), "con_suciedad": true}],
	"M_Quiebrasol": ["tile", "M_Fachada_Comercial", {"tinte": Vector3(1.05, 1.04, 1.0), "con_suciedad": true, "macro_cantidad": 0.1}],
	"M_Techo_Plegado": ["tile", "M_Fachada_Comercial", {"tinte": Vector3(0.62, 0.68, 0.55), "macro_cantidad": 0.25}],
	"M_Tierra_Jardin": ["tile", "M_Terreno", {"tinte": Vector3(0.45, 0.38, 0.3), "macro_cantidad": 0.2}],
	"M_Muro_Cerca": ["tile", "M_Brocal", {"efecto": 3, "con_suciedad": true, "macro_cantidad": 0.15}],
	"M_Zinc": ["tile", "M_Zinc", {"efecto": 1, "macro_cantidad": 0.12}],
	"M_Hangar_Pared": ["tile", "M_Zinc", {"efecto": 2, "con_suciedad": true, "macro_cantidad": 0.08}],
	"M_Mural_CCCT": ["tile", "M_Fachada_Concreto", {"efecto": 5, "tinte": Vector3(0.95, 0.94, 0.9), "con_suciedad": true}],
	"M_Corteza": ["tile", "M_Corteza", {}],
	"M_Corteza_Palma": ["tile", "M_Corteza_Palma", {}],
	"M_Franjas_Azul": ["especial", "", {"modo": 0, "vidrio": Vector3(0.07, 0.17, 0.38), "antepecho": Vector3(0.86, 0.87, 0.88), "piso": 3.4, "banda": 0.55}],
	"M_Franjas_Blanca": ["especial", "", {"modo": 0, "vidrio": Vector3(0.03, 0.05, 0.06), "antepecho": Vector3(0.88, 0.88, 0.86), "piso": 3.3, "banda": 0.5}],
	"M_Franjas_Verde": ["especial", "", {"modo": 0, "vidrio": Vector3(0.10, 0.17, 0.15), "antepecho": Vector3(0.70, 0.71, 0.68), "piso": 3.3, "banda": 0.62, "modulo": 1.35}],
	"M_Franjas_Gris": ["especial", "", {"modo": 0, "vidrio": Vector3(0.03, 0.04, 0.045), "antepecho": Vector3(0.62, 0.61, 0.58), "piso": 3.4, "banda": 0.42}],
	"M_Muro_Cortina": ["especial", "", {"modo": 1}],
	"M_Vidrio_Negro": ["especial", "", {"modo": 2}],
	"M_Azulejo": ["especial", "", {"modo": 3}],
	"M_Azulejo_Claro": ["especial", "", {"modo": 3, "color_a": Vector3(0.62, 0.78, 0.82), "color_b": Vector3(0.85, 0.87, 0.86), "azulejo": 0.2}],
	"M_Bandera": ["especial", "", {"modo": 4}],
	"M_Letrero": ["especial", "", {"modo": 5}],
}

var texturas := {}
var simples := {}
var zona := {}
var _cache := {}


func _init(datos_zona: Dictionary) -> void:
	zona = datos_zona
	simples = zona.get("materiales_simples", {})
	var f := FileAccess.open("res://texturas/texturas.json", FileAccess.READ)
	if f:
		texturas = JSON.parse_string(f.get_as_text())


func material(nombre: String) -> Material:
	if _cache.has(nombre):
		return _cache[nombre]
	var m: Material = _crear(nombre)
	_cache[nombre] = m
	return m


## Reemplaza los materiales M_* de todas las mallas bajo 'nodo'.
func aplicar(nodo: Node) -> void:
	for mi in nodo.find_children("*", "MeshInstance3D", true, false):
		var malla: Mesh = mi.mesh
		if malla == null:
			continue
		for s in malla.get_surface_count():
			var actual := malla.surface_get_material(s)
			if actual and actual.resource_name.begins_with("M_"):
				mi.set_surface_override_material(s, material(actual.resource_name))


## Copia de la malla con los materiales M_* reemplazados (para MultiMesh). Las hojas de los árboles
## (tarjetas con la textura de hojas) se recortan por transparencia y dejan pasar la luz.
func malla_con_materiales(malla: Mesh) -> Mesh:
	var copia: Mesh = malla.duplicate()
	for s in copia.get_surface_count():
		var actual := copia.surface_get_material(s)
		if actual and actual.resource_name.begins_with("M_"):
			copia.surface_set_material(s, material(actual.resource_name))
		elif actual is BaseMaterial3D and "leaves" in actual.resource_name:
			var hojas := ShaderMaterial.new()
			hojas.shader = preload("res://shaders/hojas.gdshader")
			hojas.set_shader_parameter("albedo", (actual as BaseMaterial3D).albedo_texture)
			copia.surface_set_material(s, hojas)
	return copia


func _tex(clave: String, mapa: String) -> Texture2D:
	var t: Dictionary = texturas.get(clave, {})
	var ruta: String = t.get("mapas", {}).get(mapa, "")
	return load(ruta) if ruta != "" else null


func _tamano(clave: String) -> Vector2:
	var t: Dictionary = texturas.get(clave, {})
	var tam: Array = t.get("tamano_m", [2.0, 2.0])
	return Vector2(tam[0], tam[1])


func _crear(nombre: String) -> Material:
	if nombre == "M_Terreno":
		return _terreno()
	if nombre == "M_Fondo":
		return _fondo()
	if not ESPEC.has(nombre):
		return _simple(nombre)
	var e: Array = ESPEC[nombre]
	var m := ShaderMaterial.new()
	m.resource_name = nombre
	m.shader = SH[e[0]]
	var clave: String = e[1]
	var p: Dictionary = (e[2] as Dictionary).duplicate()
	if clave != "":
		m.set_shader_parameter("albedo", _tex(clave, "color"))
		var n := _tex(clave, "normal")
		var r := _tex(clave, "rugosidad")
		m.set_shader_parameter("normal_tex", n)
		m.set_shader_parameter("rugosidad_tex", r)
		if e[0] == "tile":
			m.set_shader_parameter("tiene_normal", n != null)
			m.set_shader_parameter("tiene_rugosidad", r != null)
		m.set_shader_parameter("tamano", _tamano(clave) * float(p.get("escala", 1.0)))
	p.erase("escala")
	if nombre == "M_Pasto":
		var cfg: Dictionary = zona.get("pasto", {})
		p["rayas_angulo"] = float(cfg.get("rayas_angulo", 0.0))
		p["seco"] = cfg.get("color", "verde") == "seco"
	if nombre == "M_Plaza":
		var cfg_plaza: Dictionary = zona.get("plaza", {})
		if cfg_plaza.get("patron", "") == "bandas_ladrillo":
			m.set_shader_parameter("albedo", _tex("M_Acera", "color"))
			m.set_shader_parameter("tamano", _tamano("M_Acera"))
			p["tinte"] = Vector3(1.08, 0.98, 0.85)
			p["efecto"] = 4
			m.set_shader_parameter("albedo2", _tex("M_Fachada_Ladrillo", "color"))
			m.set_shader_parameter("tamano2", _tamano("M_Fachada_Ladrillo"))
			p["modulo_bandas"] = float(cfg_plaza.get("modulo_m", 6.0))
			p["ancho_banda"] = float(cfg_plaza.get("banda_m", 0.65))
		elif cfg_plaza.has("tinte"):
			var t: Array = cfg_plaza["tinte"]
			p["tinte"] = Vector3(t[0], t[1], t[2])
	for k in p:
		m.set_shader_parameter(k, p[k])
	return m


func _terreno() -> Material:
	var m := ShaderMaterial.new()
	m.resource_name = "M_Terreno"
	m.shader = SH["terreno"]
	for par in [["tex_concreto", "tam_concreto", "M_Techo_Concreto"], ["tex_grama", "tam_grama", "M_Grama"],
			["tex_tierra", "tam_tierra", "M_Terreno"], ["tex_asfalto", "tam_asfalto", "M_Asfalto"]]:
		m.set_shader_parameter(par[0], _tex(par[2], "color"))
		m.set_shader_parameter(par[1], _tamano(par[2]))
	var sat = zona.get("satelite")
	if sat:
		var base := "res://zonas/%s/" % zona["id"]
		m.set_shader_parameter("ndvi", load(base + sat["ndvi"]))
		m.set_shader_parameter("satelite", load(base + sat["fondo"]))
		var ze: Array = sat["zona_extension"]
		var fe: Array = sat["fondo_extension"]
		m.set_shader_parameter("ndvi_ext", Vector4(ze[0], ze[1], ze[2], ze[3]))
		m.set_shader_parameter("sat_ext", Vector4(fe[0], fe[1], fe[2], fe[3]))
		m.set_shader_parameter("con_satelite", true)
	return m


func _fondo() -> Material:
	var m := ShaderMaterial.new()
	m.resource_name = "M_Fondo"
	m.shader = SH["fondo"]
	var sat = zona.get("satelite")
	if sat:
		m.set_shader_parameter("satelite", load("res://zonas/%s/%s" % [zona["id"], sat["fondo"]]))
		var fe: Array = sat["fondo_extension"]
		m.set_shader_parameter("sat_ext", Vector4(fe[0], fe[1], fe[2], fe[3]))
	else:
		m.set_shader_parameter("con_satelite", false)
	m.set_shader_parameter("z_mar", -872.0)
	var ze: Array = zona.get("extension_local", [0, 0, 0, 0])
	m.set_shader_parameter("zona_ext", Vector4(ze[0], ze[1], ze[2], ze[3]))
	return m


func _simple(nombre: String) -> Material:
	var s: Dictionary = simples.get(nombre, {})
	var m := StandardMaterial3D.new()
	m.resource_name = nombre
	var c: Array = s.get("color", [0.6, 0.6, 0.6])
	m.albedo_color = Color(c[0], c[1], c[2]).linear_to_srgb()
	m.roughness = float(s.get("rugosidad", 0.6))
	m.metallic = float(s.get("metal", 0.0))
	var fuerza := float(s.get("emision_fuerza", 0.0))
	if fuerza > 0.0:
		var e: Array = s.get("emision", [0, 0, 0])
		m.emission_enabled = true
		m.emission = Color(e[0], e[1], e[2]).linear_to_srgb()
		m.emission_energy_multiplier = fuerza
	var alfa := float(s.get("alfa", 1.0))
	var transmision := float(s.get("transmision", 0.0))
	if alfa < 0.99 or transmision > 0.3:
		m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		m.albedo_color.a = min(alfa, 1.0 - transmision * 0.6)
	return m
