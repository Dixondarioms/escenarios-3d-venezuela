// Cielo de Caracas: degradado atmosférico según la altura del sol, halo y disco solar, y cúmulos
// procedurales que se espesan hacia el norte (sobre El Ávila) y hacia el horizonte, como cielo.py en Blender.
shader_type sky;
render_mode use_debanding;

uniform float nubes : hint_range(0.0, 1.0) = 0.35;
uniform float brillo = 1.0;
uniform float velocidad_nubes = 0.004;
uniform vec3 suelo_color = vec3(0.18, 0.17, 0.15);

float h(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

float rn(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(h(i), h(i + vec2(1, 0)), u.x), mix(h(i + vec2(0, 1)), h(i + vec2(1, 1)), u.x), u.y);
}

float fbm(vec2 p) {
	float v = 0.0;
	float a = 0.5;
	float t = 0.0;
	for (int k = 0; k < 7; k++) {
		v += a * rn(p);
		t += a;
		p = p * 2.03 + vec2(11.3, 4.7);
		a *= 0.62;
	}
	return v / t;
}

void sky() {
	vec3 d = EYEDIR;
	vec3 sol = LIGHT0_DIRECTION;
	float elev = sol.y;                      // seno de la elevación del sol
	float dia = clamp(elev * 4.0 + 0.2, 0.0, 1.0);
	float ocaso = clamp(1.0 - elev * 2.0, 0.0, 1.0) * dia;
	// degradado: cénit azul profundo, horizonte claro y algo lechoso (bruma del valle)
	vec3 cenit = mix(vec3(0.02, 0.03, 0.06), vec3(0.16, 0.33, 0.68), dia);
	vec3 horizonte = mix(vec3(0.04, 0.04, 0.06), vec3(0.72, 0.80, 0.88), dia);
	horizonte = mix(horizonte, vec3(1.0, 0.62, 0.36), ocaso * 0.75);
	float alto = clamp(d.y, 0.0, 1.0);
	vec3 c = mix(horizonte, cenit, pow(alto, 0.45));
	// halo alrededor del sol (dispersión de Mie)
	float cs = max(dot(d, sol), 0.0);
	vec3 color_sol = mix(vec3(1.0, 0.97, 0.92), vec3(1.0, 0.55, 0.25), ocaso);
	c += color_sol * (pow(cs, 8.0) * 0.25 + pow(cs, 64.0) * 0.5) * dia;
	// nubes: proyección de la dirección sobre un plano a gran altura
	if (d.y > 0.0 && nubes > 0.0) {
		vec2 p = d.xz / max(d.y, 0.035) * 0.9 + vec2(TIME * velocidad_nubes, 0.0);
		float n = fbm(p * 1.6 + vec2(3.0));
		float norte = max(-d.z, 0.0) * clamp(1.0 - d.y * 3.0, 0.0, 1.0);
		float umbral = 0.62 - nubes * 0.28 - norte * 0.08;
		float dens = clamp((n - umbral) * 9.0, 0.0, 1.0) * clamp((d.y - 0.015) * 12.0, 0.0, 1.0);
		vec3 claro = mix(vec3(1.0, 0.98, 0.95), vec3(1.0, 0.78, 0.55), ocaso);
		vec3 oscuro = mix(vec3(0.55, 0.57, 0.62), vec3(0.62, 0.48, 0.45), ocaso) * mix(1.0, 0.65, nubes);
		vec3 nube = mix(oscuro, claro, pow(n, 2.2) * 1.4) * (0.35 + 0.65 * dia);
		nube += color_sol * pow(cs, 6.0) * 0.4 * dia;   // bordes iluminados cerca del sol
		c = mix(c, nube, dens);
	}
	// disco solar
	if (AT_CUBEMAP_PASS == false) {
		c += color_sol * smoothstep(0.99996, 0.99999, cs) * 40.0 * (1.0 - nubes * 0.8);
	}
	// bajo el horizonte: suelo/bruma
	c = mix(c, suelo_color * (0.3 + 0.7 * dia), smoothstep(0.0, -0.08, d.y));
	COLOR = c * brillo;
}
