// Tarjetas de hojas de los árboles: la textura de hojas de Poly Haven tiene el fondo negro (sin canal alfa
// útil), así que se recorta por luminosidad; las hojas dejan pasar la luz (contraluz).
shader_type spatial;
render_mode cull_disabled, depth_draw_opaque;

uniform sampler2D albedo : source_color, filter_linear_mipmap, repeat_disable;
uniform float umbral = 0.07;
uniform vec3 tinte = vec3(0.95, 1.0, 0.9);

void fragment() {
	vec4 c = texture(albedo, UV);
	if (max(max(c.r, c.g), c.b) < umbral || c.a < 0.5) {
		discard;
	}
	ALBEDO = c.rgb * tinte;
	ROUGHNESS = 0.7;
	SPECULAR = 0.3;
	BACKLIGHT = c.rgb * 0.6;
}
