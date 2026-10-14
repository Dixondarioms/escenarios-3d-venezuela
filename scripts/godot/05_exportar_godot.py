"""Exporta una zona (escena realista de Blender) al proyecto de Godot 4.4 en godot/.

Uso:
    blender -b datos/caracas/lacarlota/lacarlota_realista.blend -P scripts/godot/05_exportar_godot.py -- lacarlota

Escribe godot/zonas/<zona>/:
    celdas/celda_I_J.glb   geometría de cada celda de 252 m (todas las capas), con UV0, UV1 y color de
                           vértice; los materiales van solo por nombre (M_*): Godot los reemplaza por shaders
    celdas/celda_I_J.json  instancias de la celda: {modelo: [transform Godot de 12 números, ...]}
    celdas/pasto_I_J.bin   puntos de matas de pasto (float32 x, y, z en coordenadas Godot)
    biblioteca.glb         un nodo por modelo repetido (farola, árbol, carros, aeronaves...), con texturas
    fondo.glb              relieve lejano y ciudad lejana
    zona.json              celdas, cámaras, sol, materiales simples, imagen satelital, créditos
Coordenadas: Godot = (x, z, -y) de Blender (Este, Arriba, Sur), en metros.
"""

import json
import math
import random
import shutil
import struct
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI.parent / "blender"))
from comun import RAIZ, cargar_zona, carpeta_zona  # noqa: E402
import cielo  # noqa: E402

C = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
CI = C.inverted()
CAPAS = ("Edificios", "Calles", "Aceras", "Senderos", "Areas", "Detalles", "Aviacion", "Terreno")
TEX_MAX = 1024           # las texturas de los modelos descargados se reducen (VRAM de la GT 750: 1-2 GB)
PASTO_DENSIDAD = 0.6     # matas por m² en grama y pasto (Godot muestra solo las cercanas)


def a_godot(M):
    """Matriz 4x4 de Blender -> 12 números de Transform3D de Godot (columnas x, y, z del basis y origen)."""
    G = C @ M @ CI
    return [round(v, 4) for v in (G[0][0], G[1][0], G[2][0], G[0][1], G[1][1], G[2][1],
                                  G[0][2], G[1][2], G[2][2], G[0][3], G[1][3], G[2][3])]


def p_godot(v):
    return [round(v[0], 3), round(v[2], 3), round(-v[1], 3)]


def deseleccionar():
    for o in bpy.context.view_layer.objects:
        o.select_set(False)


def exportar_glb(ruta, objetos, imagenes=False):
    deseleccionar()
    for o in objetos:
        o.hide_set(False)
        o.hide_viewport = False
        o.select_set(True)
    bpy.context.view_layer.objects.active = objetos[0]
    bpy.ops.export_scene.gltf(
        filepath=str(ruta), export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
        export_texcoords=True, export_normals=True, export_tangents=False, export_vertex_color="ACTIVE",
        export_materials="EXPORT", export_image_format="AUTO" if imagenes else "NONE",
        export_animations=False, export_cameras=False, export_lights=False, export_extras=False)
    deseleccionar()


def malla_unida(objetos, nombre, coleccion_destino, centrar=False):
    """Une objetos malla (con sus transformaciones) en un solo objeto en el origen."""
    dg = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    mats = []
    objetos = [o for o in objetos if o.type == "MESH"]
    copias = []
    for o in objetos:
        ev = o.evaluated_get(dg)
        tmp = ev.to_mesh()
        copias.append((o, tmp.copy()))
        ev.to_mesh_clear()
    for o, me in copias:
        me.transform(o.matrix_world)
        if centrar:
            me.transform(Matrix.Translation(-o.matrix_world.translation))
        if o.matrix_world.determinant() < 0:
            me.flip_normals()
        locales = []
        for slot in o.material_slots:
            m = slot.material
            if m not in mats:
                mats.append(m)
            locales.append(mats.index(m))
        if locales:
            idx = [locales[min(p.material_index, len(locales) - 1)] for p in me.polygons]
            me.polygons.foreach_set("material_index", idx)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    if not bm.verts:
        bm.free()
        return None
    me = bpy.data.meshes.new(nombre)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    obj = bpy.data.objects.new(nombre, me)
    coleccion_destino.objects.link(obj)
    return obj


def reducir_imagenes(objetos):
    """Reduce a TEX_MAX px las imágenes usadas por los modelos (también las de grupos de nodos)."""
    usadas = set()

    def recorrer(arbol):
        for n in arbol.nodes:
            if getattr(n, "image", None) is not None:
                usadas.add(n.image)
            if n.type == "GROUP" and n.node_tree:
                recorrer(n.node_tree)
    for o in objetos:
        for m in o.data.materials:
            if m and m.use_nodes:
                recorrer(m.node_tree)
    n = 0
    for img in usadas:
        try:
            if img.size[0] == 0:
                _ = img.pixels[0]   # fuerza la carga de las imágenes empaquetadas
            w, h = img.size
            if max(w, h) > TEX_MAX:
                f = TEX_MAX / max(w, h)
                img.scale(max(1, int(w * f)), max(1, int(h * f)))
                n += 1
        except (RuntimeError, IndexError):
            pass
    return n


def suelo_zona_lejano(carpeta, coleccion, paso=8):
    """Relieve de la zona jugable a 16 m (paso × resolución), 1,5 m por debajo del suelo real: el relieve de fondo
    tiene un hueco bajo la zona, y en Godot las celdas lejanas aún no cargadas dejarían ver el cielo."""
    import numpy as np
    ruta = carpeta / "terreno" / "altura_local.npy"
    if not ruta.exists():
        return None
    h = np.load(ruta)
    with open(carpeta / "terreno" / "meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    res = meta["resolucion_m"]
    xmin, ymin, xmax, ymax = meta["extension_local"]
    filas = range(0, h.shape[0], paso)
    cols = range(0, h.shape[1], paso)
    verts = [(xmin + c * res, ymax - f * res, float(h[f, c]) - 1.5) for f in filas for c in cols]
    nc = len(cols)
    caras = [(i * nc + j, (i + 1) * nc + j, (i + 1) * nc + j + 1, i * nc + j + 1)
             for i in range(len(filas) - 1) for j in range(nc - 1)]
    me = bpy.data.meshes.new("Zona_Lejana")
    me.from_pydata(verts, [], caras)
    me.update()
    mat = bpy.data.materials.get("M_Fondo") or bpy.data.materials.new("M_Fondo")
    me.materials.append(mat)
    obj = bpy.data.objects.new("Zona_Lejana", me)
    coleccion.objects.link(obj)
    return obj


def limite_triangulos(nombre):
    """Triángulos máximos por modelo repetido (cientos de copias en la GT 750)."""
    if nombre.startswith("Usr_helicoptero") or nombre.startswith("Usr_avion"):
        return 25000
    if nombre.startswith("Usr_"):
        return 8000
    return 6000


def arbol_liviano(obj, n_hojas=380, tris_ramas=3500, seed=5):
    """El jacarandá de Poly Haven tiene 3,9 millones de triángulos (hojas modeladas una a una): para el juego
    se reducen tronco y ramas, y el follaje se reemplaza por ~380 tarjetas de 1,2-1,9 m con la textura de
    hojas (recorte por transparencia), repartidas donde estaban las hojas originales."""
    me = obj.data
    mats = list(me.materials)
    hojas_idx = [i for i, m in enumerate(mats) if m and "leaves" in m.name]
    me.calc_loop_triangles()
    rnd = random.Random(seed)
    tris_hojas = [t for t in me.loop_triangles if t.material_index in hojas_idx]
    areas = [t.area for t in tris_hojas]
    total = sum(areas) or 1.0
    # puntos de follaje ponderados por área
    acum, a = [], 0.0
    for x in areas:
        a += x
        acum.append(a)
    import bisect
    centros = []
    for _ in range(n_hojas):
        r = rnd.random() * total
        t = tris_hojas[min(bisect.bisect_left(acum, r), len(tris_hojas) - 1)]
        centros.append(Vector(t.center))
    # tronco y ramas: se quitan las hojas y se reduce el resto
    bm = bmesh.new()
    bm.from_mesh(me)
    quitar = [f for f in bm.faces if f.material_index in hojas_idx]
    bmesh.ops.delete(bm, geom=quitar, context="FACES")
    # las ramitas son miles de islas sueltas que no se pueden simplificar: se quedan las ramas más grandes
    bm.faces.ensure_lookup_table()
    visto, islas = set(), []
    for f in bm.faces:
        if f.index in visto:
            continue
        pila, isla = [f], []
        visto.add(f.index)
        while pila:
            g = pila.pop()
            isla.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in visto:
                        visto.add(h.index)
                        pila.append(h)
        islas.append((sum(x.calc_area() for x in isla), isla))
    islas.sort(key=lambda t: -t[0])
    conservar, cuenta = set(), 0
    for area, isla in islas:
        if cuenta > tris_ramas * 3:
            break
        conservar.update(x.index for x in isla)
        cuenta += sum(len(x.verts) - 2 for x in isla)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in conservar], context="FACES")
    ramas = bpy.data.meshes.new(obj.name + "_ramas")
    bm.to_mesh(ramas)
    bm.free()
    for m in mats:
        ramas.materials.append(m)
    tmp = bpy.data.objects.new("tmp_ramas", ramas)
    bpy.context.scene.collection.objects.link(tmp)
    reducir_triangulos(tmp, tris_ramas)
    bm = bmesh.new()
    bm.from_mesh(tmp.data)
    uv = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
    mat_hojas = hojas_idx[0] if hojas_idx else 0
    for c in centros:
        lado = rnd.uniform(1.2, 1.9) / 2
        eje = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-0.4, 0.4))).normalized()
        u = eje.cross(Vector((0, 0, 1))).normalized() if abs(eje.z) < 0.95 else Vector((1, 0, 0))
        v = eje.cross(u).normalized()
        vs = [bm.verts.new(c + (u * su + v * sv) * lado) for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        f = bm.faces.new(vs)
        f.material_index = mat_hojas
        f.smooth = True
        for loop, coord in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
            loop[uv].uv = coord
    nueva = bpy.data.meshes.new(obj.name + "_juego")
    bm.to_mesh(nueva)
    bm.free()
    for m in mats:
        nueva.materials.append(m)
    viejo = obj.data
    obj.data = nueva
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(viejo)
    nueva.calc_loop_triangles()
    return len(nueva.loop_triangles)


def envolvente(obj):
    """Malla convexa que envuelve el modelo (para verlo de lejos) con el material de mayor área."""
    me = obj.data
    areas = {}
    for p in me.polygons:
        areas[p.material_index] = areas.get(p.material_index, 0.0) + p.area
    mat = max(areas, key=areas.get) if areas else 0
    bm = bmesh.new()
    bm.from_mesh(me)
    res = bmesh.ops.convex_hull(bm, input=bm.verts)
    quitar = set(res.get("geom_interior", [])) | set(res.get("geom_unused", []))
    bmesh.ops.delete(bm, geom=[v for v in quitar if isinstance(v, bmesh.types.BMVert)], context="VERTS")
    for f in bm.faces:
        f.material_index = mat
    bm.to_mesh(me)
    bm.free()


def _decimar(obj, me, limite, unir):
    """Copia de 'me' simplificada a ~limite triángulos (unir: junta antes los vértices de las costuras)."""
    trabajo = me.copy()
    if unir:
        bm = bmesh.new()
        bm.from_mesh(trabajo)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0005)
        bm.to_mesh(trabajo)
        bm.free()
    trabajo.calc_loop_triangles()
    n = len(trabajo.loop_triangles)
    obj.data = trabajo
    mod = obj.modifiers.new("Reducir", "DECIMATE")
    mod.ratio = max(limite / max(n, 1), 0.005)
    mod.use_collapse_triangulate = True
    dg = bpy.context.evaluated_depsgraph_get()
    nueva = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.remove(mod)
    obj.data = me
    bpy.data.meshes.remove(trabajo)
    nueva.calc_loop_triangles()
    return nueva, len(nueva.loop_triangles)


def reducir_triangulos(obj, limite):
    """Simplifica la malla del objeto a ~limite triángulos (prueba con y sin unir costuras; se queda la menor)."""
    me = obj.data
    me.calc_loop_triangles()
    antes = len(me.loop_triangles)
    if antes <= limite:
        return antes, antes
    mejor, n = _decimar(obj, me, limite, False)
    if n > limite * 1.5:
        otra, m = _decimar(obj, me, limite, True)
        if m < n:
            bpy.data.meshes.remove(mejor)
            mejor, n = otra, m
        else:
            bpy.data.meshes.remove(otra)
    obj.data = mejor
    bpy.data.meshes.remove(me)
    return antes, n


def principled_de(mat):
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat.use_nodes else None


def materiales_simples():
    """Valores fijos (sin texturas ni nodos conectados) de los materiales M_*: Godot los usa cuando no hay
    un shader propio para ese nombre."""
    salida = {}
    for m in bpy.data.materials:
        if not m.name.startswith("M_"):
            continue
        p = principled_de(m)
        if p is None:
            continue

        def val(nombre, defecto):
            s = p.inputs.get(nombre)
            if s is None or s.is_linked:
                return defecto
            v = s.default_value
            return [round(x, 4) for x in v][:3] if hasattr(v, "__len__") else round(float(v), 4)
        salida[m.name] = {
            "color": val("Base Color", [0.6, 0.6, 0.6]), "rugosidad": val("Roughness", 0.6),
            "metal": val("Metallic", 0.0), "emision": val("Emission Color", [0, 0, 0]),
            "emision_fuerza": val("Emission Strength", 0.0), "alfa": val("Alpha", 1.0),
            "transmision": val("Transmission Weight", 0.0),
            "con_nodos": any(s.is_linked for s in p.inputs),
        }
    return salida


def biblioteca_de_colecciones():
    """{nombre_colección: colección} de los modelos repetidos (Lib_* y Usr_*), sin el grupo Lib_Vehiculos."""
    bib = bpy.data.collections.get("Biblioteca")
    salida = {}

    def recorrer(c):
        for h in c.children:
            if h.name == "Lib_Vehiculos":
                recorrer(h)
                continue
            if h.name.startswith(("Lib_", "Usr_")) and h.name not in ("Lib_Grama", "Lib_grass_bermuda_01", "Lib_grass_medium_02"):
                salida[h.name] = h
    if bib:
        recorrer(bib)
    return salida


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    zona = cargar_zona(argv[0])
    solo = next((a.split("=", 1)[1].split(",") for a in argv if a.startswith("--solo=")), None)

    def hacer(parte):  # --solo=biblioteca,instancias,celdas,pasto,fondo (por defecto, todo)
        return solo is None or parte in solo
    carpeta = carpeta_zona(zona)
    destino = RAIZ / "godot" / "zonas" / zona["id"]
    if solo is None and destino.exists():
        shutil.rmtree(destino / "celdas", ignore_errors=True)
    (destino / "celdas").mkdir(parents=True, exist_ok=True)
    with open(carpeta / "terreno" / "meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    xmin, ymin, xmax, ymax = meta["extension_local"]
    tam = zona["celda_m"]
    n_celdas = max(1, int(math.ceil((xmax - xmin) / tam)))

    def celda_de(x, y):
        return (min(max(int((x - xmin) // tam), 0), n_celdas - 1), min(max(int((y - ymin) // tam), 0), n_celdas - 1))

    escena = bpy.context.scene
    temp = bpy.data.collections.new("Exportar_Godot")
    escena.collection.children.link(temp)

    # ------------------------------------------------------------- biblioteca de modelos repetidos
    libs = biblioteca_de_colecciones()
    obj_a_lib = {}
    for nombre, col in libs.items():
        for o in col.all_objects:
            obj_a_lib.setdefault(o.name, nombre)
    if hacer("biblioteca"):
        unidos = []
        tris_antes = tris_despues = 0
        for nombre, col in sorted(libs.items()):
            obj = malla_unida(list(col.all_objects), nombre, temp)
            if obj and nombre == "Lib_arbol":
                obj.data.calc_loop_triangles()
                a = len(obj.data.loop_triangles)
                lejos = obj.copy()
                lejos.data = obj.data.copy()
                lejos.name = nombre + "__lejos"
                temp.objects.link(lejos)
                b = arbol_liviano(obj)
                arbol_liviano(lejos, n_hojas=70, tris_ramas=120)
                tris_antes += a
                tris_despues += b
                unidos += [obj, lejos]
                continue
            if obj:
                a, b = reducir_triangulos(obj, limite_triangulos(nombre))
                tris_antes += a
                tris_despues += b
                unidos.append(obj)
                # versión lejana (LOD): ~4 % de los triángulos, para verla de lejos sin costo
                if b > 600:
                    lejos = obj.copy()
                    lejos.data = obj.data.copy()
                    lejos.name = nombre + "__lejos"
                    temp.objects.link(lejos)
                    _, c = reducir_triangulos(lejos, max(int(b * 0.04), 300))
                    if c > max(int(b * 0.04), 300) * 2:
                        envolvente(lejos)
                    unidos.append(lejos)
        n_img = reducir_imagenes(unidos)
        exportar_glb(destino / "biblioteca.glb", unidos, imagenes=True)
        print(f"  Biblioteca: {len(unidos)} modelos, {tris_antes:,} -> {tris_despues:,} triángulos, "
              f"{n_img} imágenes reducidas a {TEX_MAX}px")

    # ------------------------------------------------------------- instancias por celda
    instancias = {}

    def agregar(lib, M, x, y, extra=None):
        i, j = celda_de(x, y)
        d = instancias.setdefault((i, j), {})
        d.setdefault(lib, []).append(a_godot(M) + (extra or []))

    for o in escena.objects:
        if o.type == "EMPTY" and o.instance_type == "COLLECTION" and o.instance_collection:
            lib = o.instance_collection.name
            if lib in libs:
                M = o.matrix_world
                agregar(lib, M, M.translation.x, M.translation.y)
    # árboles y vehículos: puntos con atributos (los Geometry Nodes solo muestran una fracción en el viewport)
    arboles = bpy.data.objects.get("Arboles")
    if arboles and "Lib_arbol" in libs:
        me = arboles.data
        rot = me.attributes["rot"].data
        esc = me.attributes["esc"].data
        for k, v in enumerate(me.vertices):
            s = esc[k].value
            M = Matrix.Translation(arboles.matrix_world @ v.co) @ Matrix.Rotation(rot[k].vector[2], 4, "Z") @ Matrix.Diagonal((s, s, s, 1))
            agregar("Lib_arbol", M, M.translation.x, M.translation.y)
    vehiculos = bpy.data.objects.get("Vehiculos")
    padre = bpy.data.collections.get("Lib_Vehiculos")
    if vehiculos and padre:
        variantes = [c.name for c in padre.children]
        me = vehiculos.data
        rot, idx, col = me.attributes["rot"].data, me.attributes["idx"].data, me.attributes["col_auto"].data
        for k, v in enumerate(me.vertices):
            lib = variantes[idx[k].value % len(variantes)]
            if lib not in libs:
                continue
            M = Matrix.Translation(vehiculos.matrix_world @ v.co) @ Matrix.Rotation(rot[k].vector[2], 4, "Z")
            c = col[k].color
            agregar(lib, M, M.translation.x, M.translation.y, [round(c[0], 3), round(c[1], 3), round(c[2], 3)])
    n_inst = 0
    for (i, j), d in instancias.items():
        if hacer("instancias"):
            with open(destino / "celdas" / f"celda_{i}_{j}.json", "w", encoding="utf-8") as f:
                json.dump(d, f, separators=(",", ":"))
        n_inst += sum(len(v) for v in d.values())
    print(f"  Instancias: {n_inst} en {len(instancias)} celdas")

    # ------------------------------------------------------------- celdas de geometría
    celdas = []
    por_celda = {}
    for capa in CAPAS:
        col = bpy.data.collections.get(capa)
        if not col:
            continue
        for o in col.objects:
            if o.type != "MESH" or not o.data.polygons:
                continue
            partes = o.name.rsplit("_", 2)
            if len(partes) != 3:
                continue
            ij = (int(partes[1]), int(partes[2]))
            if o.data.color_attributes.get("Col"):
                o.data.color_attributes.active_color = o.data.color_attributes["Col"]
            por_celda.setdefault(ij, []).append(o)
    for (i, j), objs in sorted(por_celda.items()):
        ruta = destino / "celdas" / f"celda_{i}_{j}.glb"
        if hacer("celdas"):
            exportar_glb(ruta, objs)
        x0, y0 = xmin + i * tam, ymin + j * tam
        zs = [(o.matrix_world @ Vector(c)).z for o in objs for c in o.bound_box]
        celdas.append({"i": i, "j": j, "glb": f"celdas/celda_{i}_{j}.glb",
                       "instancias": f"celdas/celda_{i}_{j}.json" if (i, j) in instancias else None,
                       "centro": p_godot((x0 + tam / 2, y0 + tam / 2, (min(zs) + max(zs)) / 2)),
                       "z_min": round(min(zs), 2), "z_max": round(max(zs), 2),
                       "capas": sorted({o.name.rsplit("_", 2)[0] for o in objs})})
    for (i, j) in instancias:  # celdas solo con instancias (sin geometría propia)
        if (i, j) not in por_celda:
            x0, y0 = xmin + i * tam, ymin + j * tam
            celdas.append({"i": i, "j": j, "glb": None, "instancias": f"celdas/celda_{i}_{j}.json",
                           "centro": p_godot((x0 + tam / 2, y0 + tam / 2, 0)), "z_min": 0, "z_max": 0, "capas": []})
    print(f"  Celdas: {len(por_celda)} con geometría")

    # ------------------------------------------------------------- puntos de pasto (como el Pasto 3D de Blender)
    obstaculos = []
    for capa in (("Aviacion", "Calles", "Senderos", "Aceras", "Detalles", "Edificios") if hacer("pasto") else ()):
        col = bpy.data.collections.get(capa)
        if col:
            obstaculos += [o for o in col.objects if o.type == "MESH"]
    verts, tris = [], []
    for o in obstaculos:
        me = o.data
        me.calc_loop_triangles()
        base = len(verts)
        mw = o.matrix_world
        verts += [mw @ v.co for v in me.vertices]
        tris += [(base + t.vertices[0], base + t.vertices[1], base + t.vertices[2]) for t in me.loop_triangles]
    arbol_bvh = BVHTree.FromPolygons(verts, tris) if tris else None
    rnd = random.Random(7)
    puntos = {}
    areas = bpy.data.collections.get("Areas")
    if not hacer("pasto"):
        areas = None
        for c in celdas:
            if (destino / "celdas" / f"pasto_{c['i']}_{c['j']}.bin").exists():
                c["pasto"] = f"celdas/pasto_{c['i']}_{c['j']}.bin"
    for o in (areas.objects if areas else []):
        me = o.data
        nombres = [m.name if m else "" for m in me.materials]
        if not any(n in ("M_Pasto", "M_Grama") for n in nombres):
            continue
        me.calc_loop_triangles()
        mw = o.matrix_world
        for t in me.loop_triangles:
            if nombres[t.material_index] not in ("M_Pasto", "M_Grama"):
                continue
            a, b, c = (mw @ me.vertices[k].co for k in t.vertices)
            area = ((b - a).cross(c - a)).length / 2
            n = area * PASTO_DENSIDAD
            cuantos = int(n) + (1 if rnd.random() < n - int(n) else 0)
            for _ in range(cuantos):
                r1, r2 = rnd.random(), rnd.random()
                if r1 + r2 > 1:
                    r1, r2 = 1 - r1, 1 - r2
                p = a + (b - a) * r1 + (c - a) * r2
                if arbol_bvh and arbol_bvh.ray_cast(p + Vector((0, 0, 0.01)), Vector((0, 0, 1)), 3.0)[0] is not None:
                    continue
                puntos.setdefault(celda_de(p.x, p.y), []).append(p)
    n_pasto = 0
    for (i, j), ps in puntos.items():
        with open(destino / "celdas" / f"pasto_{i}_{j}.bin", "wb") as f:
            for p in ps:
                f.write(struct.pack("<3f", p.x, p.z, -p.y))
        n_pasto += len(ps)
        for c in celdas:
            if (c["i"], c["j"]) == (i, j):
                c["pasto"] = f"celdas/pasto_{i}_{j}.bin"
    print(f"  Pasto: {n_pasto} matas en {len(puntos)} celdas")

    # ------------------------------------------------------------- fondo
    col_fondo = bpy.data.collections.get("Fondo")
    fondo = [o for o in (col_fondo.objects if col_fondo else []) if o.type == "MESH"]
    if hacer("fondo"):
        z = suelo_zona_lejano(carpeta, temp)
        if z:
            fondo.append(z)
    if fondo and hacer("fondo"):
        exportar_glb(destino / "fondo.glb", fondo)
    print(f"  Fondo: {[o.name for o in fondo]}")

    # ------------------------------------------------------------- cámaras, sol y metadatos
    camaras = {}
    for o in escena.objects:
        if o.type == "CAMERA":
            camaras[o.name] = {"transform": a_godot(o.matrix_world),
                               "fov": round(math.degrees(o.data.angle_y), 2)}
    luces = {}
    for nombre in list(cielo.LUCES) + list(zona.get("luces", {})):
        _, luz = cielo.variante(zona, nombre)
        dia = __import__("datetime").date.fromisoformat(luz.get("fecha") or zona.get("render", {}).get("fecha", "2026-03-15"))
        h, mnt = (int(x) for x in luz["hora"].split(":"))
        elev, az = cielo.posicion_solar(zona["centro"]["lat"], zona["centro"]["lon"], dia, h + mnt / 60)
        luces[nombre] = dict(luz, elevacion=round(elev, 2), azimut=round(az, 2))
    sat = {}
    meta_sat = carpeta / "terreno" / "satelite_meta.json"
    if meta_sat.exists():
        with open(meta_sat, encoding="utf-8") as f:
            sat = json.load(f)
        shutil.copy(carpeta / "terreno" / "satelite_fondo.jpg", destino / "satelite_fondo.jpg")
        shutil.copy(carpeta / "terreno" / "ndvi_zona.png", destino / "ndvi_zona.png")
    datos = {
        "id": zona["id"], "nombre": zona["nombre"], "celda_m": tam, "extension_local": meta["extension_local"],
        "z_origen_msnm": meta.get("z_origen_msnm"), "celdas": celdas, "camaras": camaras, "luces": luces,
        "luz_inicial": "mediodia", "pasto": zona.get("pasto", {}), "plaza": zona.get("plaza", {}),
        "satelite": {"fondo": "satelite_fondo.jpg", "fondo_extension": sat.get("fondo_extension"),
                     "ndvi": "ndvi_zona.png", "zona_extension": sat.get("zona_extension")} if sat else None,
        "fondo": "fondo.glb" if fondo else None, "biblioteca": "biblioteca.glb",
        "materiales_simples": materiales_simples(),
        "creditos": ["© OpenStreetMap contributors (ODbL)", "Copernicus DEM GLO-30 © DLR e.V. y Airbus",
                     sat.get("atribucion", ""), "Texturas y modelos CC0 de Poly Haven",
                     "Modelos de Sketchfab: ver docs/creditos_modelos.md"],
    }
    with open(destino / "zona.json", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    print(f"  Listo: {destino}")


main()
