// Fachadas: textura real + color de la paleta caraqueña por edificio (color de vértice R), suciedad, y
// ventanas pintadas en los edificios sin ventanas modeladas (A = 0), como materiales_fachada() de Blender.
shader_type spatial;
render_mode depth_draw_opaque, cull_back;
#include "res://shaders/comun.gdshaderinc"

uniform sampler2D albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D rugosidad_tex : hint_roughness_g, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec2 tamano = vec2(2.0);
uniform vec3 tinte = vec3(1.0);
uniform bool pintada = true;   // friso pintado: toma el color de la paleta
uniform float macro_cantidad = 0.08;
const vec3 paleta[11] = {
	vec3(0.86, 0.79, 0.63), vec3(0.93, 0.92, 0.89), vec3(0.87, 0.64, 0.52), vec3(0.91, 0.83, 0.57),
	vec3(0.72, 0.45, 0.33), vec3(0.77, 0.77, 0.75), vec3(0.64, 0.74, 0.81), vec3(0.72, 0.79, 0.64),
	vec3(0.95, 0.90, 0.80), vec3(0.84, 0.72, 0.60), vec3(0.42, 0.66, 0.66)
};

void fragment() {
	vec2 uvm = uv_blender(UV);
	vec2 st = uvm / tamano;
	vec3 c = texture(albedo, st).rgb;
	c = macro(c, uvm, macro_cantidad) * tinte;
	float r = COLOR.r;
	if (pintada) {
		float g = dot(c, vec3(0.2126, 0.7152, 0.0722)) * 1.25;
		int i = clamp(int(floor(r * 11.0)), 0, 10);
		c = vec3(g) * paleta[i];
	} else {
		c *= mix(0.82, 1.12, r);  // ladrillo, cerámica, concreto: solo cambia el brillo por edificio
	}
	c = suciedad(c, uvm);
	float rug = texture(rugosidad_tex, st).g;
	vec3 albedo_final = c;
	float rug_final = rug;
	float metal = 0.0;
	if (COLOR.a < 0.5) {
		// ventanas pintadas: módulo de 3 m × 2,8 m (oficinas: franjas de 1,5 m × 3,6 m), sin planta baja
		bool oficina = abs(COLOR.g - 0.2) < 0.03;
		float vano = oficina ? 1.5 : 3.0;
		float piso = oficina ? 3.6 : 2.8;
		float fu = fract(uvm.x / vano);
		float fv = fract((uvm.y - 3.6) / piso);
		float ancho = oficina ? 0.05 : 0.27;
		float en_u = step(ancho, fu) * step(fu, 1.0 - ancho);
		float en_v = step(oficina ? 0.18 : 0.33, fv) * step(fv, 0.82);
		float ventana = en_u * en_v * step(3.9, uvm.y);
		// cada ventana con su propio brillo (cortinas, luces, reflejos)
		vec2 id = floor(vec2(uvm.x / vano, (uvm.y - 3.6) / piso));
		float h = hash12(id + floor(r * 97.0));
		vec3 vidrio = oficina ? vec3(0.03, 0.06, 0.07) : mix(vec3(0.015, 0.02, 0.025), vec3(0.09, 0.08, 0.07), step(0.6, h) * h);
		albedo_final = mix(c, vidrio, ventana);
		rug_final = mix(rug, 0.06, ventana);
		metal = ventana * 0.2;
	}
	ALBEDO = albedo_final;
	ROUGHNESS = rug_final;
	METALLIC = metal;
	NORMAL_MAP = texture(normal_tex, st).rgb;
	NORMAL_MAP_DEPTH = 0.8;
}
