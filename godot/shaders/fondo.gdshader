// Relieve lejano (El Ávila, el valle y la costa) con la imagen Sentinel-2 real: vegetación más viva,
// ciudad más apagada y textura de copas de árboles, como material_fondo_satelite() de Blender.
shader_type spatial;
render_mode depth_draw_opaque, cull_back;
#include "res://shaders/comun.gdshaderinc"

uniform sampler2D satelite : source_color, filter_linear_mipmap, repeat_disable;
uniform vec4 sat_ext = vec4(-14000.0, -14000.0, 14000.0, 14000.0);
uniform bool con_satelite = true;
uniform float z_mar = -872.0;
// zona jugable: bajo las celdas aún no cargadas se ve el relieve de fondo; ahí se pinta como ciudad oscura
uniform vec4 zona_ext = vec4(0.0);
varying vec3 pos_mundo;

void vertex() {
	pos_mundo = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec2 xy = vec2(pos_mundo.x, -pos_mundo.z);   // Este, Norte
	float z = pos_mundo.y;
	vec3 c;
	if (con_satelite) {
		vec2 st = vec2((xy.x - sat_ext.x) / (sat_ext.z - sat_ext.x), 1.0 - (xy.y - sat_ext.y) / (sat_ext.w - sat_ext.y));
		vec3 s = texture(satelite, st).rgb;
		float dom = s.g - max(s.r, s.b);
		float es_veg = clamp((dom + 0.004) * 120.0, 0.0, 1.0);
		vec3 veg = saturar(s, 1.35) * 1.15;
		vec3 urb = saturar(pow(s, vec3(1.6)), 0.55) * 0.42;
		c = mix(urb, veg, es_veg);
	} else {
		c = vec3(0.03, 0.06, 0.02);
	}
	float copas = fbm(xy * 0.04, 3, 0.7);
	c *= 1.0 - copas * 0.35;
	float mar = step(z, z_mar);
	c = mix(c, vec3(0.01, 0.05, 0.08), mar);
	ALBEDO = c;
	ROUGHNESS = mix(1.0, 0.05, mar);
	SPECULAR = mix(0.2, 0.5, mar);
}
