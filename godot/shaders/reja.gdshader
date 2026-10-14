// Rejas, cerca, barrotes, barandas y marcas de espera: geometría plana con recorte por transparencia.
// modo 0 = reja de ventana (UV 0..1), 1 = malla de cerca (UV en metros), 2 = barrotes verticales con rieles,
// 3 = marca de punto de espera (amarilla).
shader_type spatial;
render_mode cull_disabled, depth_draw_opaque;
#include "res://shaders/comun.gdshaderinc"

uniform int modo = 0;
uniform float barrotes_u = 9.0;
uniform float barrotes_v = 2.0;
uniform float riel1_a = 0.0;
uniform float riel1_b = 0.05;
uniform float riel2_a = 1.32;
uniform float riel2_b = 1.37;
uniform vec3 color = vec3(0.03, 0.03, 0.03);
uniform float metal = 0.7;
uniform float rugosidad = 0.55;

void fragment() {
	vec2 uv = modo == 0 ? UV : uv_blender(UV);
	float alfa = 0.0;
	if (modo == 0 || modo == 1) {
		float bu = step(fract(uv.x * barrotes_u), 0.14);
		float bv = step(fract(uv.y * barrotes_v), 0.08);
		float borde = modo == 0 ? step(min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y)), 0.03) : 0.0;
		alfa = max(max(bu, bv), borde);
	} else if (modo == 2) {
		alfa = step(fract(uv.x * barrotes_u), 0.17);
		alfa = max(alfa, step(riel1_a - 0.001, uv.y) * step(uv.y, riel1_b));
		alfa = max(alfa, step(riel2_a - 0.001, uv.y) * step(uv.y, riel2_b));
	} else {
		float v = uv.y;
		float banda1 = step(0.0, v) * step(v, 0.1) + step(0.2, v) * step(v, 0.3);
		float banda2 = (step(0.55, v) * step(v, 0.65) + step(0.8, v) * step(v, 0.9)) * step(fract(uv.x / 1.8), 0.5);
		alfa = clamp(banda1 + banda2, 0.0, 1.0);
	}
	if (alfa < 0.5) {
		discard;
	}
	ALBEDO = color;
	METALLIC = metal;
	ROUGHNESS = rugosidad;
}
