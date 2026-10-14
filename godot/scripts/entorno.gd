## Cielo, sol, niebla de valle y ajustes de calidad. Las "luces" (mediodía, mañana, tarde, nublado) vienen
## de zona.json (las mismas variantes de cielo.py en Blender).
class_name Entorno
extends Node3D

var mundo_env: WorldEnvironment
var sol: DirectionalLight3D
var cielo_mat: ShaderMaterial
var luces := {}
var luz_actual := ""


func _ready() -> void:
	cielo_mat = ShaderMaterial.new()
	cielo_mat.shader = preload("res://shaders/cielo.gdshader")
	var sky := Sky.new()
	sky.sky_material = cielo_mat
	sky.process_mode = Sky.PROCESS_MODE_REALTIME
	sky.radiance_size = Sky.RADIANCE_SIZE_256
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
	env.set("tonemap_mode", 4)   # AgX (como en Blender); en versiones sin AgX queda el valor por defecto
	env.tonemap_white = 6.0
	env.glow_enabled = true
	env.glow_intensity = 0.35
	env.glow_bloom = 0.04
	env.glow_hdr_threshold = 1.2
	env.fog_enabled = true
	env.fog_mode = Environment.FOG_MODE_EXPONENTIAL
	env.fog_density = 0.00012
	env.fog_sky_affect = 0.0
	env.fog_aerial_perspective = 0.85
	env.adjustment_enabled = true
	env.adjustment_saturation = 1.1
	env.adjustment_contrast = 1.08
	mundo_env = WorldEnvironment.new()
	mundo_env.environment = env
	add_child(mundo_env)
	sol = DirectionalLight3D.new()
	sol.shadow_enabled = true
	sol.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
	sol.directional_shadow_max_distance = 600.0
	sol.shadow_blur = 1.2
	sol.light_angular_distance = 0.5
	add_child(sol)


func aplicar_luz(nombre: String) -> void:
	if not luces.has(nombre):
		return
	luz_actual = nombre
	var l: Dictionary = luces[nombre]
	var elev := deg_to_rad(float(l["elevacion"]))
	var az := deg_to_rad(float(l["azimut"]))
	# dirección hacia el sol en Godot (x = Este, y = arriba, -z = Norte)
	var hacia_sol := Vector3(sin(az) * cos(elev), sin(elev), -cos(az) * cos(elev))
	sol.look_at_from_position(Vector3.ZERO, -hacia_sol, Vector3.UP if abs(hacia_sol.y) < 0.99 else Vector3.FORWARD)
	var nubes := float(l.get("nubes", 0.35))
	var ocaso: float = clamp(1.0 - rad_to_deg(elev) / 28.0, 0.0, 1.0)
	sol.light_color = Color(1.0, 0.97 - 0.27 * ocaso, 0.92 - 0.47 * ocaso)
	# sol fuerte y cielo más suave: el contraste de luz y sombra del trópico
	sol.light_energy = lerp(1.0, 0.3, clamp(nubes - 0.4, 0.0, 1.0) * 1.6) * clamp(sin(elev) * 3.0, 0.35, 1.0) * 4.5
	cielo_mat.set_shader_parameter("nubes", nubes)
	var env := mundo_env.environment
	# exposición: en Blender va de -1,3 (mediodía) a 0,2 (tarde); aquí se traduce a la energía del tonemap
	env.tonemap_exposure = 0.75 + ocaso * 0.25
	env.fog_density = 0.00002 + float(l.get("bruma", 0.32)) * 0.00006
	env.fog_light_color = Color(0.72, 0.78, 0.86).lerp(Color(1.0, 0.72, 0.5), ocaso * 0.6)
	env.ambient_light_energy = lerp(0.22, 0.7, clamp(nubes - 0.3, 0.0, 1.0) * 1.8)


func siguiente_luz() -> String:
	var nombres := luces.keys()
	var i := (nombres.find(luz_actual) + 1) % nombres.size()
	aplicar_luz(nombres[i])
	return nombres[i]


## 0 = baja (GT 750 y similares), 1 = media, 2 = alta
func aplicar_calidad(nivel: int, viewport: Viewport) -> void:
	var env := mundo_env.environment
	env.ssao_enabled = nivel >= 1
	env.ssao_radius = 1.5
	env.ssao_intensity = 1.6
	env.ssil_enabled = nivel >= 2
	env.ssr_enabled = nivel >= 2
	env.sdfgi_enabled = false
	sol.shadow_enabled = true
	sol.directional_shadow_max_distance = [250.0, 500.0, 900.0][nivel]
	RenderingServer.directional_shadow_atlas_set_size([2048, 4096, 8192][nivel], true)
	RenderingServer.directional_soft_shadow_filter_set_quality([RenderingServer.SHADOW_QUALITY_SOFT_VERY_LOW,
		RenderingServer.SHADOW_QUALITY_SOFT_LOW, RenderingServer.SHADOW_QUALITY_SOFT_MEDIUM][nivel])
	viewport.msaa_3d = Viewport.MSAA_DISABLED
	viewport.screen_space_aa = Viewport.SCREEN_SPACE_AA_FXAA
	viewport.use_taa = nivel >= 2
	viewport.scaling_3d_mode = Viewport.SCALING_3D_MODE_FSR if nivel == 0 else Viewport.SCALING_3D_MODE_BILINEAR
	viewport.scaling_3d_scale = [0.75, 1.0, 1.0][nivel]
	viewport.mesh_lod_threshold = [4.0, 1.0, 0.5][nivel]
