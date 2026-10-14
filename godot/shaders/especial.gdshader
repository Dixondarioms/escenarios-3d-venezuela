// Materiales dibujados sin textura: 0 = franjas de vidrio y antepecho (Caracas Palace, Torre Delta, CCCT),
// 1 = muro cortina con retícula (Torre Británica), 2 = vidrio negro espejado (Cubo Negro), 3 = azulejo,
// 4 = bandera de Venezuela, 5 = letrero de rodaje.
shader_type spatial;
render_mode depth_draw_opaque, cull_back;
#include "res://shaders/comun.gdshaderinc"

uniform int modo = 0;
uniform vec3 vidrio = vec3(0.07, 0.17, 0.38);
uniform vec3 antepecho = vec3(0.86, 0.87, 0.88);
uniform float piso = 3.4;
uniform float banda = 0.55;
uniform float modulo = 1.5;
uniform vec3 color_a = vec3(0.04, 0.42, 0.45);
uniform vec3 color_b = vec3(0.75, 0.75, 0.72);
uniform float azulejo = 0.15;
varying vec3 pos_local;

void vertex() {
	pos_local = VERTEX;
}

void fragment() {
	vec2 uvm = uv_blender(UV);
	if (modo == 0) {
		float f = fract(uvm.y / piso);
		float en_vidrio = step(0.22, f) * step(f, 0.22 + banda);
		float parteluz = step(fract(uvm.x / modulo), 0.035);
		float vf = en_vidrio * (1.0 - parteluz);
		float var = fbm(uvm * vec2(0.25, 0.6) * 3.0, 2, 0.5);
		vec3 tono = mix(vidrio * 0.7, vidrio, var);
		vec3 c = mix(antepecho, antepecho * 0.55, en_vidrio);
		ALBEDO = mix(c, tono, vf);
		ROUGHNESS = mix(0.55, 0.04, vf);
		METALLIC = mix(0.0, 0.35, vf);
	} else if (modo == 1) {
		float perfil = max(step(fract(uvm.x / 1.5), 0.04), step(fract(uvm.y / 3.6), 0.03));
		float var = fbm(uvm * vec2(0.3, 0.25) * 3.0, 2, 0.5);
		vec3 v = mix(vec3(0.015, 0.02, 0.025), vec3(0.03, 0.04, 0.05), var);
		ALBEDO = mix(v, vec3(0.08, 0.08, 0.085), perfil);
		ROUGHNESS = mix(0.03, 0.4, perfil);
		METALLIC = mix(0.4, 0.8, perfil);
	} else if (modo == 2) {
		float junta = max(step(fract(uvm.x / 1.6), 0.02), step(fract(uvm.y / 1.6), 0.02));
		ALBEDO = mix(vec3(0.008, 0.008, 0.01), vec3(0.05, 0.05, 0.055), junta);
		METALLIC = 0.9;
		ROUGHNESS = mix(0.02, 0.4, junta);
	} else if (modo == 3) {
		float ju = step(fract(uvm.x / azulejo), 0.06);
		float jv = step(fract(uvm.y / azulejo), 0.06);
		float var = ruido(floor(uvm / azulejo) * 3.7);
		ALBEDO = mix(mix(color_a, color_a * 1.2, var), color_b, max(ju, jv));
		ROUGHNESS = 0.15;
	} else if (modo == 4) {
		// coordenadas del objeto (Blender: x = 0..3 m desde el asta, z = 9,8..11,8 m)
		float u = pos_local.x - 0.05;
		float v = pos_local.y - 9.8;
		vec3 c = v > 4.0 / 3.0 ? vec3(0.88, 0.70, 0.02) : (v > 2.0 / 3.0 ? vec3(0.01, 0.06, 0.32) : vec3(0.62, 0.02, 0.04));
		for (int k = 0; k < 8; k++) {
			float ang = radians(160.0 - float(k) * 140.0 / 7.0);
			vec2 s = vec2(1.5 + 0.42 * cos(ang), 0.78 + 0.42 * sin(ang));
			if (distance(vec2(u, v), s) < 0.055) c = vec3(0.9);
		}
		ALBEDO = c;
		ROUGHNESS = 0.8;
	} else {
		float u = (-pos_local.z + 1.2) / 2.4;
		float v = pos_local.y - 0.4;
		float rojo = step(u, 0.45);
		vec3 fondo = mix(vec3(0.85, 0.62, 0.03), vec3(0.6, 0.02, 0.02), rojo);
		float trazo = step(fract(u * 14.0), 0.55) * step(0.3, v) * step(v, 0.7) * step(0.15, fract(u * 2.22));
		ALBEDO = mix(fondo, mix(vec3(0.02), vec3(0.9), rojo), trazo);
		ROUGHNESS = 0.5;
	}
}
