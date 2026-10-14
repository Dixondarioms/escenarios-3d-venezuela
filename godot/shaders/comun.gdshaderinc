// Funciones compartidas por los shaders del mundo (equivalentes a los nodos usados en Blender).
// Convenciones de las mallas exportadas desde Blender:
//   UV  (UV0) en metros: en fachadas u = metros a lo largo de la pared, v = metros desde la base;
//                         en el suelo u = Este, v = Norte. glTF invierte v: se recupera con uv_blender().
//   UV2 (UV1) en calles y pistas: x = 0..1 a lo ancho, y = metros a lo largo.
//   COLOR (color de vértice) lleva datos: en edificios R = variación/paleta, G = estilo/10, B = pisos/50,
//   A = 1 si las ventanas están modeladas (el shader no las dibuja).

vec2 uv_blender(vec2 uv) {
	return vec2(uv.x, 1.0 - uv.y);
}

float hash12(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

vec2 hash22(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.xx + p3.yz) * p3.zy);
}

float ruido(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x),
	           mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y);
}

// fBm parecido al "Noise Texture" de Blender (valor 0..1 centrado en 0,5)
float fbm(vec2 p, int octavas, float rugosidad) {
	float v = 0.0;
	float a = 0.5;
	float total = 0.0;
	for (int k = 0; k < 8; k++) {
		if (k >= octavas) break;
		v += a * ruido(p);
		total += a;
		p = p * 2.03 + vec2(17.1, 9.3);
		a *= rugosidad;
	}
	return v / total;
}

// Celda de Voronoi: id aleatorio estable por celda (cortinas distintas por ventana, mural del CCCT)
vec2 voronoi_id(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	float mejor = 8.0;
	vec2 id = vec2(0.0);
	for (int y = -1; y <= 1; y++) {
		for (int x = -1; x <= 1; x++) {
			vec2 g = vec2(float(x), float(y));
			vec2 o = hash22(i + g);
			vec2 r = g + o - f;
			float d = dot(r, r);
			if (d < mejor) {
				mejor = d;
				id = i + g;
			}
		}
	}
	return hash22(id * 1.37);
}

// Manchas de humedad que escurren y zócalo más sucio (v = metros desde la base)
vec3 suciedad(vec3 color, vec2 uvm) {
	float chorreado = clamp((fbm(vec2(uvm.x * 1.6, uvm.y * 0.12) * 0.6, 6, 0.6) - 0.45) * 1.6, 0.0, 1.0);
	float zocalo = clamp(1.0 - uvm.y / 1.4, 0.0, 1.0);
	float sucio = max(chorreado * 0.2, zocalo * 0.4);
	return mix(color, color * vec3(0.18, 0.16, 0.13), sucio);
}

// Variación macro anti-repetición (como pbr() en 03b_realismo.py)
vec3 macro(vec3 color, vec2 uvm, float cantidad) {
	float n = fbm(uvm * 0.06 * 3.0, 3, 0.5);
	return color * mix(1.0 - cantidad, 1.0 + cantidad, n);
}

vec3 saturar(vec3 c, float s) {
	float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
	return mix(vec3(l), c, s);
}
