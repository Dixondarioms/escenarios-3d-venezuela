// Grama del aeródromo (modo 0: verde de riego con franjas de corte paralelas a la pista) y de parques
// (modo 1), sobre la textura 'leafy_grass' llevada a verde tropical, como material_pasto() de Blender.
shader_type spatial;
render_mode depth_draw_opaque, cull_back;
#include "res://shaders/comun.gdshaderinc"

uniform sampler2D albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec2 tamano = vec2(2.0);
uniform int modo = 0;
uniform bool seco = false;
uniform float rayas_angulo = 0.0;  // grados desde el Este

void fragment() {
	vec2 uvm = uv_blender(UV);
	vec2 st = uvm / tamano;
	float gris = dot(texture(albedo, st).rgb, vec3(0.2126, 0.7152, 0.0722));
	vec3 c;
	float rug = 0.85;
	if (modo == 0) {
		float n1 = fbm(uvm * 0.04 * 3.0, 3, 0.5);
		float n2 = fbm(uvm * 0.15 * 3.0, 4, 0.5);
		vec3 tono;
		if (!seco) {
			tono = mix(vec3(0.05, 0.11, 0.025), vec3(0.085, 0.15, 0.035), n1);
			tono = mix(tono, vec3(0.12, 0.15, 0.05), step(0.62, n2) * 0.6);
		} else {
			tono = mix(vec3(0.40, 0.34, 0.15), vec3(0.20, 0.25, 0.09), n1);
			tono = mix(tono, vec3(0.50, 0.42, 0.22), step(0.6, n2) * 0.7);
		}
		c = gris * tono * 2.0;
		float a = radians(rayas_angulo);
		float perp = uvm.y * cos(a) - uvm.x * sin(a);
		float franja = step(fract(perp / 20.0), 0.5);
		c *= mix(vec3(0.88), vec3(1.12, 1.15, 1.08), franja);
		rug = mix(0.85, 0.7, franja);
	} else {
		float n1 = fbm(uvm * 0.08 * 3.0, 3, 0.5);
		vec3 tono = mix(vec3(0.05, 0.14, 0.02), vec3(0.10, 0.20, 0.035), n1);
		c = gris * tono * 2.5;
		c = macro(c, uvm, 0.25);
	}
	ALBEDO = c;
	ROUGHNESS = rug;
	NORMAL_MAP = texture(normal_tex, st).rgb;
	NORMAL_MAP_DEPTH = 1.6;
}
