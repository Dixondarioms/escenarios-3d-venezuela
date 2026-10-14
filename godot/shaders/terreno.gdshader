// Suelo entre edificios: grama y tierra donde el satélite ve vegetación (NDVI), concreto y asfalto donde no;
// el color general sale de la imagen Sentinel-2 real (como material_suelo() de Blender).
shader_type spatial;
render_mode depth_draw_opaque, cull_back;
#include "res://shaders/comun.gdshaderinc"

uniform sampler2D tex_concreto : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D tex_grama : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D tex_tierra : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D tex_asfalto : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec2 tam_concreto = vec2(2.0);
uniform vec2 tam_grama = vec2(2.0);
uniform vec2 tam_tierra = vec2(2.0);
uniform vec2 tam_asfalto = vec2(2.0);
uniform sampler2D ndvi : filter_linear, repeat_disable;
uniform vec4 ndvi_ext = vec4(-2016.0, -2016.0, 2016.0, 2016.0);
uniform sampler2D satelite : source_color, filter_linear, repeat_disable;
uniform vec4 sat_ext = vec4(-14000.0, -14000.0, 14000.0, 14000.0);
uniform bool con_satelite = false;

vec2 a_imagen(vec2 xy, vec4 ext) {
	// coordenadas locales (Este, Norte) -> UV de una imagen con el norte arriba
	return vec2((xy.x - ext.x) / (ext.z - ext.x), 1.0 - (xy.y - ext.y) / (ext.w - ext.y));
}

void fragment() {
	vec2 uvm = uv_blender(UV);
	float ruido_borde = (fbm(uvm * 0.3 * 3.0, 5, 0.5) - 0.5) * 0.25;
	float verde = step(0.42, texture(ndvi, a_imagen(uvm, ndvi_ext)).r + ruido_borde);
	float tierra = step(0.6, fbm(uvm * 0.11 * 3.0, 4, 0.5));
	float asfalto = step(0.55, fbm(uvm * 0.025 * 3.0, 3, 0.5));
	vec3 gris = texture(tex_concreto, uvm / tam_concreto).rgb * vec3(0.62, 0.62, 0.61);
	vec3 duro = mix(gris, texture(tex_asfalto, uvm / tam_asfalto).rgb * vec3(0.42, 0.42, 0.44), asfalto);
	vec3 blando = mix(texture(tex_grama, uvm / tam_grama).rgb * vec3(0.8, 0.85, 0.7),
	                  texture(tex_tierra, uvm / tam_tierra).rgb * vec3(0.55, 0.45, 0.38), tierra);
	vec3 c = mix(duro, blando, verde);
	if (con_satelite) {
		vec3 sat = pow(texture(satelite, a_imagen(uvm, sat_ext)).rgb, vec3(1.4));
		float detalle = dot(c, vec3(0.2126, 0.7152, 0.0722));
		c = mix(c, detalle * sat * 0.75 * 2.2, 0.7);
	}
	ALBEDO = c;
	ROUGHNESS = mix(0.85, 0.95, verde);
}
