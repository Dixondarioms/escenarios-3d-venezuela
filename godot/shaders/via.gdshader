// Pavimentos de calles y del aeródromo, con las marcas pintadas por el shader (como en Blender):
// modo 0 = asfalto con carriles, 1 = paso de cebra, 2 = pista (marcas OACI), 3 = calle de rodaje,
// 4 = asfalto liso.
// UV2 = (0..1 a lo ancho, metros a lo largo); color de vértice: en calles R = carriles/8, G = sentido único,
// B = clase de vía, A = ancho/30; en pistas R = ancho/80, A = largo/4000.
shader_type spatial;
render_mode depth_draw_opaque, cull_back;
#include "res://shaders/comun.gdshaderinc"

uniform sampler2D albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D rugosidad_tex : hint_roughness_g, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec2 tamano = vec2(2.0);
uniform vec3 tinte = vec3(0.42, 0.42, 0.44);
uniform int modo = 0;

float entre(float a, float lo, float hi) {
	return step(lo, a) * step(a, hi);
}

void fragment() {
	vec2 uvm = uv_blender(UV);
	vec2 uv2 = uv_blender(UV2);
	vec2 st = uvm / tamano;
	vec3 c = macro(texture(albedo, st).rgb, uvm, 0.15) * tinte;
	float rug = texture(rugosidad_tex, st).g;
	float pintura = 0.0;
	vec3 color_pintura = vec3(0.78, 0.78, 0.74);
	float desgaste = step(0.36, fbm(uvm * 0.7, 5, 0.5));
	if (modo == 0) {
		float u = uv2.x;
		float v = uv2.y;
		float carriles = max(round(COLOR.r * 8.0), 1.0);
		float ancho = COLOR.a * 30.0;
		float marcada = step(0.55, COLOR.b);
		float doble = 1.0 - COLOR.g;
		float x = u * carriles;
		float d = abs(fract(x + 0.5) - 0.5);
		float d_m = d * ancho / carriles;
		float linea = step(d_m, 0.06) * step(0.5, x) * step(x, carriles - 0.5);
		float centro_m = abs(u - 0.5) * ancho;
		float en_centro = doble * step(centro_m, 0.3);
		linea *= 1.0 - en_centro;
		float blanca = linea * step(fract(v / 9.0), 0.35);
		float borde_m = min(u * ancho, (1.0 - u) * ancho);
		float orilla = entre(borde_m, 0.25, 0.38) * step(0.7, COLOR.b);
		blanca = max(blanca, orilla);
		float amarilla = doble * step(1.5, carriles) * step(centro_m, 0.07);
		blanca *= marcada * desgaste;
		amarilla *= marcada * desgaste;
		c = mix(c, vec3(0.78, 0.78, 0.74), blanca);
		c = mix(c, vec3(0.80, 0.58, 0.08), amarilla);
		rug = mix(rug, 0.55, max(blanca, amarilla));
	} else if (modo == 1) {
		float franja = step(fract(uvm.x), 0.5) * step(0.33, fbm(uvm * 0.9, 5, 0.5));
		c = mix(c, vec3(0.8, 0.8, 0.77), franja);
	} else if (modo == 2) {
		float W = COLOR.r * 80.0;
		float L = COLOR.a * 4000.0;
		float x = abs((uv2.x - 0.5) * W);
		float v = uv2.y;
		float d = min(v, L - v);
		float borde_lateral = W / 2.0 - 1.5;
		float umbral = entre(d, 6.0, 36.0) * step(fract((x - 0.9) / 3.6), 0.5) * step(1.8, x) * step(x, borde_lateral);
		float eje = step(x, 0.45) * step(fract(v / 50.0), 0.6) * step(110.0, d);
		float mira = entre(d, 400.0, 445.0) * entre(x, 5.0, 9.0);
		float toma = max(entre(d, 150.0, 172.5), entre(d, 300.0, 322.5)) * entre(x, 5.5, 7.3);
		float lado = entre(x, W / 2.0 - 1.0, W / 2.0 - 0.1);
		pintura = max(max(umbral, eje), max(max(mira, toma), lado)) * step(0.25, fbm(uvm * 0.5, 5, 0.5));
		float caucho = entre(d, 120.0, 800.0) * step(x, 9.0) * fbm(vec2(uv2.x * 2.0, uv2.y * 0.05), 4, 0.5) * 0.9;
		c = mix(c, vec3(0.01), caucho);
		c = mix(c, vec3(0.75, 0.75, 0.72), pintura);
	} else if (modo == 3) {
		float x = abs((uv2.x - 0.5) * COLOR.r * 80.0);
		float eje = step(x, 0.08) * step(0.3, fbm(uvm * 0.5, 5, 0.5));
		c = mix(c, vec3(0.78, 0.55, 0.06), eje);
	}
	ALBEDO = c;
	ROUGHNESS = rug;
	NORMAL_MAP = texture(normal_tex, st).rgb;
	NORMAL_MAP_DEPTH = 0.6;
}
