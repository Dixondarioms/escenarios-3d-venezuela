// Material con textura real repetida cada 'tamano' metros (acera, brocal, techos, santamaría, monumento...).
shader_type spatial;
render_mode depth_draw_opaque, cull_back;
#include "res://shaders/comun.gdshaderinc"

uniform sampler2D albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D rugosidad_tex : hint_roughness_g, filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool tiene_normal = true;
uniform bool tiene_rugosidad = true;
uniform vec2 tamano = vec2(2.0);
uniform vec3 tinte = vec3(1.0);
uniform float macro_cantidad = 0.12;
uniform float normal_fuerza = 1.0;
uniform float rugosidad_mult = 1.0;
uniform bool usar_uv2 = false;
uniform bool con_suciedad = false;
// juntas regulares (losas de plataforma): 0 = no
uniform float junta_cada = 0.0;
uniform vec3 color_junta = vec3(0.06);
uniform float manchas_aceite = 0.0;
// efectos: 0 = ninguno, 1 = zinc pintado por edificio, 2 = lámina de hangar pintada, 3 = grafitis en muro,
// 4 = losas con bandas de ladrillo (Plaza Francia), 5 = mural geométrico del CCCT
uniform int efecto = 0;
uniform sampler2D albedo2 : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec2 tamano2 = vec2(2.0);
uniform float modulo_bandas = 6.0;
uniform float ancho_banda = 0.65;

vec3 rampa(float f, vec3 a, vec3 b, vec3 c, vec3 d, vec3 e, int n) {
	int i = clamp(int(floor(f * float(n))), 0, n - 1);
	return i == 0 ? a : (i == 1 ? b : (i == 2 ? c : (i == 3 ? d : e)));
}

void fragment() {
	vec2 uvm = usar_uv2 ? uv_blender(UV2) : uv_blender(UV);
	vec2 st = uvm / tamano;
	vec3 c = texture(albedo, st).rgb;
	c = macro(c, uvm, macro_cantidad) * tinte;
	if (junta_cada > 0.0) {
		vec2 f = fract(uvm / junta_cada);
		float junta = step(f.x, 0.006) + step(f.y, 0.006);
		c = mix(c, color_junta, clamp(junta, 0.0, 1.0));
	}
	if (manchas_aceite > 0.0) {
		float mancha = clamp((fbm(uvm * 0.25, 5, 0.5) - 0.6) * 3.0, 0.0, 1.0);
		c = mix(c, vec3(0.03, 0.03, 0.028), mancha * manchas_aceite);
	}
	float rug = tiene_rugosidad ? clamp(texture(rugosidad_tex, st).g * rugosidad_mult, 0.0, 1.0) : 0.8;
	float r = COLOR.r;
	if (efecto == 1) {
		float pintado = step(0.6, r) * step(r, 0.995);
		vec3 gris = vec3(dot(c, vec3(0.2126, 0.7152, 0.0722)) * 1.3);
		vec3 pintura = gris * rampa(clamp((r - 0.6) * 2.45, 0.0, 0.999), vec3(0.95, 0.95, 0.93), vec3(0.95, 0.95, 0.93),
		                            vec3(0.62, 0.24, 0.17), vec3(0.95, 0.95, 0.93), vec3(0.58, 0.66, 0.76), 5);
		c = mix(c, pintura, pintado);
		rug = mix(rug, 0.6, pintado);
	} else if (efecto == 2) {
		vec3 gris = vec3(dot(c, vec3(0.2126, 0.7152, 0.0722)) * 1.3);
		c = gris * rampa(r, vec3(0.95, 0.94, 0.9), vec3(0.92, 0.87, 0.76), vec3(0.82, 0.84, 0.83), vec3(0.97, 0.96, 0.94), vec3(1.0), 4);
		rug = 0.6;
	} else if (efecto == 3) {
		float tramo = step(0.6, fbm(vec2(uvm.x * 0.04, 0.0), 2, 0.5));
		float trazo = step(abs(fbm(uvm * 1.6, 3, 0.5) - 0.5), 0.035);
		float relleno = step(0.6, fbm(vec2(uvm.x * 0.7, uvm.y) * 1.2, 2, 0.5));
		float en_altura = step(0.12, uvm.y) * step(uvm.y, 0.82);
		float grafiti = tramo * en_altura * max(trazo, relleno * 0.6);
		vec3 tinta = rampa(fbm(vec2(uvm.x * 0.03, 0.0), 1, 0.5), vec3(0.12, 0.35, 0.7), vec3(0.15, 0.55, 0.55),
		                   vec3(0.2, 0.45, 0.2), vec3(0.05), vec3(0.85), 5);
		c = mix(c, tinta, grafiti * 0.65);
	} else if (efecto == 4) {
		vec2 f = fract(uvm / modulo_bandas);
		float banda = max(step(f.x, ancho_banda / modulo_bandas), step(f.y, ancho_banda / modulo_bandas));
		vec3 ladrillo = texture(albedo2, uvm * 2.5 / tamano2).rgb * vec3(0.95, 0.7, 0.6);
		c = mix(c, ladrillo, banda);
	} else if (efecto == 5) {
		vec3 tono = rampa(voronoi_id(uvm * 0.09).x, vec3(0.92, 0.72, 0.05), vec3(0.05, 0.22, 0.6), vec3(0.92, 0.92, 0.9),
		                  vec3(0.75, 0.12, 0.08), vec3(0.1, 0.45, 0.75), 5);
		c = mix(c, tono, step(1.2, uvm.y) * step(uvm.y, 17.0));
	}
	if (con_suciedad) {
		c = suciedad(c, uvm);
	}
	ALBEDO = c;
	ROUGHNESS = rug;
	if (tiene_normal) {
		NORMAL_MAP = texture(normal_tex, st).rgb;
		NORMAL_MAP_DEPTH = normal_fuerza;
	}
}
