// Ventanas modeladas: marco perimetral y parteluz, vidrio reflectante y cortinas/interiores distintos por
// ventana (UV = 0..1 dentro de cada abertura), como material_vidrio() de Blender.
shader_type spatial;
render_mode depth_draw_opaque, cull_back;
#include "res://shaders/comun.gdshaderinc"

uniform vec3 base = vec3(0.015, 0.02, 0.025);
uniform float cortinas = 0.55;
uniform float marco_ancho = 0.06;
uniform float interior_brillo = 0.05;
varying vec3 pos_mundo;

void vertex() {
	pos_mundo = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec2 uv = UV;
	float borde = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
	float es_marco = max(step(borde, marco_ancho), step(abs(uv.x - 0.5), marco_ancho * 0.6));
	vec2 azar = voronoi_id(pos_mundo.xz * 0.45 + vec2(pos_mundo.y * 0.31));
	float con_cortina = step(1.0 - cortinas, azar.x);
	vec3 tono = mix(vec3(0.55, 0.50, 0.42), vec3(0.75, 0.72, 0.66), azar.y);
	vec3 interior = mix(vec3(interior_brillo), tono, con_cortina);
	vec3 vidrio = mix(base, interior, 0.35);
	ALBEDO = mix(vidrio, vec3(0.62, 0.63, 0.65), es_marco);
	ROUGHNESS = mix(0.04, 0.4, es_marco);
	METALLIC = mix(0.0, 1.0, es_marco);
	SPECULAR = 0.6;
}
