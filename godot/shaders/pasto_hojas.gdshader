// Hojas de pasto: verde tropical de riego (más oscuro en la base), translúcidas a contraluz y movidas por
// el viento. COLOR.r = tono de la hoja, COLOR.g = altura relativa (0 base, 1 punta).
shader_type spatial;
render_mode cull_disabled, depth_draw_opaque;

uniform vec3 base_color = vec3(0.02, 0.045, 0.01);
uniform vec3 punta_a = vec3(0.05, 0.11, 0.025);
uniform vec3 punta_b = vec3(0.085, 0.15, 0.035);
uniform float viento = 0.04;

varying float altura;
varying float tono;

void vertex() {
	altura = COLOR.g;
	tono = COLOR.r;
	vec3 mundo = (MODEL_MATRIX * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
	float fase = TIME * 1.7 + mundo.x * 0.21 + mundo.z * 0.17;
	float empuje = (sin(fase) * 0.6 + sin(fase * 2.3 + 1.0) * 0.4) * viento * altura * altura;
	VERTEX.x += empuje;
	VERTEX.z += empuje * 0.5;
	// la normal apunta hacia arriba (iluminación suave como de césped)
	NORMAL = normalize(mix(NORMAL, vec3(0.0, 1.0, 0.0), 0.7));
}

void fragment() {
	vec3 punta = mix(punta_a, punta_b, tono);
	ALBEDO = mix(base_color, punta, smoothstep(0.0, 1.0, altura));
	ROUGHNESS = 0.75;
	SPECULAR = 0.25;
	BACKLIGHT = vec3(0.15, 0.2, 0.05);
	AO = mix(0.4, 1.0, altura);
	AO_LIGHT_AFFECT = 0.6;
}
