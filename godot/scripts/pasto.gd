## Pasto 3D: matas de hojas generadas en código (livianas para la GT 750) sobre los puntos exportados de
## las superficies de grama de Blender (ya filtrados: no hay pasto bajo pistas, calles ni edificios).
## Se agrupan en trozos de 32 m que solo se dibujan cerca de la cámara.
class_name Pasto
extends RefCounted

const SHADER := preload("res://shaders/pasto_hojas.gdshader")
const TROZO := 63.0


static func crear_malla(hojas := 22) -> ArrayMesh:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var rnd := RandomNumberGenerator.new()
	rnd.seed = 11
	for h in hojas:
		var ang := rnd.randf() * TAU
		var r := sqrt(rnd.randf()) * 0.32
		var base := Vector3(cos(ang) * r, 0.0, sin(ang) * r)
		var alto := rnd.randf_range(0.07, 0.17)
		var ancho := rnd.randf_range(0.008, 0.014)
		var giro := rnd.randf() * TAU
		var lado := Vector3(cos(giro), 0.0, sin(giro)) * ancho
		var curva := Vector3(cos(giro + PI / 2), 0.0, sin(giro + PI / 2)) * rnd.randf_range(0.01, 0.05)
		var tono := rnd.randf()
		var n := 2
		var prev_l := base - lado
		var prev_r := base + lado
		for k in range(1, n + 1):
			var t := float(k) / n
			var centro := base + Vector3(0.0, alto * t, 0.0) + curva * t * t
			var w := 1.0 - t * 0.9
			var l := centro - lado * w
			var rr := centro + lado * w
			var c0 := Color(tono, t - 1.0 / n, 0.0, 1.0)
			var c1 := Color(tono, t, 0.0, 1.0)
			for v in [[prev_l, c0], [prev_r, c0], [rr, c1], [prev_l, c0], [rr, c1], [l, c1]]:
				st.set_color(v[1])
				st.set_normal(Vector3.UP)
				st.add_vertex(v[0])
			prev_l = l
			prev_r = rr
	var malla := st.commit()
	var m := ShaderMaterial.new()
	m.shader = SHADER
	malla.surface_set_material(0, m)
	return malla


static func sembrar(nodo: Node3D, ruta: String, malla: Mesh, alcance: float, densidad: float) -> void:
	var f := FileAccess.open(ruta, FileAccess.READ)
	if f == null:
		return
	var datos := f.get_buffer(f.get_length())
	var n := datos.size() / 12
	var trozos := {}
	var rnd := RandomNumberGenerator.new()
	rnd.seed = n
	for i in n:
		if densidad < 1.0 and rnd.randf() > densidad:
			continue
		var p := Vector3(datos.decode_float(i * 12), datos.decode_float(i * 12 + 4), datos.decode_float(i * 12 + 8))
		var k := Vector2i(floori(p.x / TROZO), floori(p.z / TROZO))
		if not trozos.has(k):
			trozos[k] = PackedVector3Array()
		trozos[k].append(p)
	for k in trozos:
		var puntos: PackedVector3Array = trozos[k]
		var centro := Vector3.ZERO
		for q in puntos:
			centro += q
		centro /= puntos.size()
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.mesh = malla
		mm.instance_count = puntos.size()
		for i in puntos.size():
			var s := rnd.randf_range(0.7, 1.35)
			var b := Basis(Vector3.UP, rnd.randf() * TAU).scaled(Vector3(s, s * rnd.randf_range(0.8, 1.2), s))
			mm.set_instance_transform(i, Transform3D(b, puntos[i] - centro))
		var mmi := MultiMeshInstance3D.new()
		mmi.position = centro
		mmi.multimesh = mm
		mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		mmi.visibility_range_end = alcance
		mmi.visibility_range_end_margin = 12.0
		mmi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF
		nodo.add_child(mmi)

