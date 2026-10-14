// Agua de fuentes, espejos de agua y del río: reflectante, con ondas suaves que se mueven.
shader_type spatial;
render_mode depth_draw_opaque, cull_back;
#include "res://shaders/comun.gdshaderinc"

uniform vec3 color = vec3(0.02, 0.07, 0.07);
uniform float ondas = 0.35;
uniform float velocidad = 0.25;
varying vec3 pos_mundo;

void vertex() {
	pos_mundo = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec2 p = pos_mundo.xz * 1.5;
	float t = TIME * velocidad;
	float e = 0.05;
	float h0 = fbm(p + vec2(t, t * 0.7), 3, 0.5);
	float hx = fbm(p + vec2(e, 0.0) + vec2(t, t * 0.7), 3, 0.5);
	float hz = fbm(p + vec2(0.0, e) + vec2(t, t * 0.7), 3, 0.5);
	vec3 n = normalize(vec3((h0 - hx) * ondas / e, 1.0, (h0 - hz) * ondas / e));
	NORMAL = normalize((VIEW_MATRIX * vec4(n, 0.0)).xyz);
	ALBEDO = color;
	ROUGHNESS = 0.03;
	SPECULAR = 0.7;
}
