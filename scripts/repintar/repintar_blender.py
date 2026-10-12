"""Prepara, hornea y exporta un modelo .glb para repintarlo (lo usa repintar.py).

blender -b --factory-startup -P repintar_blender.py -- preparar config.json
    Importa el .glb original, gira el modelo para que el largo quede en Y con la nariz hacia +Y y los
    costados en ±X, y según la configuración:
      * "material": prefijo del material del fuselaje ("*" = todos los que tengan textura)
      * "dividir": true  -> las caras con x < 0 pasan a una copia del material (texturas en espejo)
      * "uv_nuevas": true -> une las mallas y crea un mapa UV nuevo sin solapes (modelos con UV pobres)
    Guarda <trabajo>/preparado.blend y hornea en <trabajo>/: pos_<lado>.npy, nor_<lado>.npy
    y color_<lado>.npy (textura original en lineal, pasada al mapa UV nuevo si "uv_nuevas"), y mapa.npz.
blender -b --factory-startup -P repintar_blender.py -- exportar config.json
    Abre preparado.blend, pone las texturas <trabajo>/tex_<lado>.png, deshace el giro y exporta "salida".
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix

args = sys.argv[sys.argv.index("--") + 1:]
modo, conf_ruta = args[0], Path(args[1])
conf = json.loads(conf_ruta.read_text(encoding="utf-8-sig"))  # tolera BOM (Bloc de notas)
trabajo = Path(conf["trabajo"])
trabajo.mkdir(parents=True, exist_ok=True)
TAM = conf.get("tam_textura", 2048)
LADOS = ["der", "izq"] if conf.get("dividir") else ["unico"]


def raices():
    return [o for o in bpy.data.objects if o.parent is None]


def es_cuerpo(mat):
    if mat is None or not mat.use_nodes:
        return False
    pref = conf.get("material", "*")
    if pref != "*":
        return mat.name.startswith(pref)
    return any(n.type == "TEX_IMAGE" for n in mat.node_tree.nodes)


def nodo_color(mat):
    pr = [n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"][0]
    entrada = pr.inputs["Base Color"]
    return entrada.links[0].from_node if entrada.links else None


if modo == "preparar":
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.import_scene.gltf(filepath=conf["original"])
    giro = Matrix.Rotation(math.radians(conf.get("girar", 0.0)), 4, "Z")
    for o in raices():
        o.matrix_world = giro @ o.matrix_world
    bpy.context.view_layer.update()
    cuerpos = [o for o in bpy.data.objects if o.type == "MESH" and len(o.data.polygons) > 0
               and any(es_cuerpo(s.material) for s in o.material_slots)]
    print("CUERPO", [o.name for o in cuerpos])

    if conf.get("uv_nuevas"):
        # une las mallas del fuselaje (sin jerarquía) y crea un mapa UV nuevo
        for o in cuerpos:
            mw = o.matrix_world.copy()
            o.parent = None
            o.matrix_world = mw
        bpy.ops.object.select_all(action="DESELECT")
        for o in cuerpos:
            o.select_set(True)
        bpy.context.view_layer.objects.active = cuerpos[0]
        bpy.ops.object.make_single_user(object=True, obdata=True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        if len(cuerpos) > 1:
            bpy.ops.object.join()
        cuerpo = bpy.context.view_layer.objects.active
        cuerpo.name = "Cuerpo_repintado"
        uv_orig = cuerpo.data.uv_layers.active.name
        nueva = cuerpo.data.uv_layers.new(name="repinte")
        cuerpo.data.uv_layers.active = nueva
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.004, area_weight=0.0)
        bpy.ops.object.mode_set(mode="OBJECT")
        cuerpo["uv_original"] = uv_orig
        cuerpos = [cuerpo]

    mats = []
    for o in cuerpos:
        for s in o.material_slots:
            if es_cuerpo(s.material) and s.material not in mats:
                mats.append(s.material)
    if conf.get("dividir"):
        o = cuerpos[0]
        for m in list(mats):
            copia = m.copy()
            copia.name = m.name + "_izq"
            o.data.materials.append(copia)
            i_der = list(o.data.materials).index(m)
            i_izq = len(o.data.materials) - 1
            mw = o.matrix_world
            for p in o.data.polygons:
                if p.material_index == i_der and (mw @ p.center).x < 0:
                    p.material_index = i_izq
            m["lado"], copia["lado"] = "der", "izq"
    else:
        for m in mats:
            m["lado"] = "unico"
    esc = bpy.context.scene
    esc["giro_repinte"] = conf.get("girar", 0.0)
    bpy.ops.wm.save_as_mainfile(filepath=str(trabajo / "preparado.blend"))

    # --- mapa de oclusión: primer impacto (x) de rayos lanzados desde cada costado -------------------
    import bmesh
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    for o in cuerpos:
        tmp = o.data.copy()
        tmp.transform(o.matrix_world)
        bm.from_mesh(tmp)
    arbol = BVHTree.FromBMesh(bm)
    vs = np.array([v.co for v in bm.verts])
    mn, mx = vs.min(0), vs.max(0)
    paso = conf.get("paso_mapa", float((mx - mn)[1:].max()) / 800)
    ys, zs = np.arange(mn[1], mx[1], paso), np.arange(mn[2], mx[2], paso)
    mapa = {"mn": mn, "mx": mx, "paso": paso}
    for nombre, signo in (("x_pos", 1), ("x_neg", -1)):
        hx = np.full((len(zs), len(ys)), np.nan, np.float32)
        d = Vector((-signo, 0, 0))
        for iz, z in enumerate(zs):
            for iy, y in enumerate(ys):
                loc = arbol.ray_cast(Vector((signo * 1e4, y, z)), d)[0]
                if loc is not None:
                    hx[iz, iy] = loc.x
        mapa[nombre] = hx
    np.savez_compressed(trabajo / "mapa.npz", **mapa)
    print("MAPA", {k: getattr(v, "shape", v) for k, v in mapa.items()})

    # --- horneado: posición, normal y (con UV nuevas) el color original -----------------------------
    esc.render.engine = "CYCLES"
    esc.cycles.device = "CPU"
    esc.cycles.samples = 1
    esc.render.bake.margin = 16
    bpy.ops.object.select_all(action="DESELECT")
    for o in cuerpos:
        o.select_set(True)
    bpy.context.view_layer.objects.active = cuerpos[0]
    imagenes = {lado: bpy.data.images.new(f"bake_{lado}", TAM, TAM, alpha=False, float_buffer=True) for lado in LADOS}
    for img in imagenes.values():
        img.colorspace_settings.name = "Non-Color"
    nodos = []
    todos = [s.material for o in cuerpos for s in o.material_slots if s.material and "lado" in s.material]
    for m in dict.fromkeys(todos):
        # se conserva la red original del material: el "color" horneado es exactamente lo que llega al
        # Base Color (textura × factor, mezclas, etc.), leído con el mapa UV original
        nt = m.node_tree
        pr = [n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"][0]
        entrada = pr.inputs["Base Color"]
        fuente = entrada.links[0].from_socket if entrada.links else None
        constante = tuple(entrada.default_value)
        if conf.get("hornear_color") == "textura" and fuente is not None:
            # usa la imagen sin el factor de color (hay modelos con factor negro que tapa la textura)
            pendientes, vistos = [fuente.node], set()
            while pendientes:
                n = pendientes.pop()
                if n.type == "TEX_IMAGE":
                    fuente = n.outputs["Color"]
                    break
                vistos.add(n.name)
                pendientes += [l.from_node for i in n.inputs for l in i.links if l.from_node.name not in vistos]
        if conf.get("uv_nuevas"):
            for n in [n for n in nt.nodes if n.type == "TEX_IMAGE" and not n.inputs["Vector"].links]:
                uvn = nt.nodes.new("ShaderNodeUVMap")
                uvn.uv_map = cuerpos[0]["uv_original"]
                nt.links.new(uvn.outputs["UV"], n.inputs["Vector"])
        for n in [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"]:
            nt.nodes.remove(n)
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        emi = nt.nodes.new("ShaderNodeEmission")
        sal = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(emi.outputs["Emission"], sal.inputs["Surface"])
        destino = nt.nodes.new("ShaderNodeTexImage")
        destino.image = imagenes[m["lado"]]
        nt.nodes.active = destino
        nodos.append((geo, emi, nt, (fuente, constante)))
    canales = ["Position", "Normal", "Color"]
    for canal in canales:
        for geo, emi, nt, (fuente, constante) in nodos:
            for l in list(emi.inputs["Color"].links):
                nt.links.remove(l)
            if canal == "Color":
                if fuente is not None:
                    nt.links.new(fuente, emi.inputs["Color"])
                else:
                    emi.inputs["Color"].default_value = constante
            else:
                nt.links.new(geo.outputs[canal], emi.inputs["Color"])
        for img in imagenes.values():
            img.pixels.foreach_set(np.zeros(TAM * TAM * 4, np.float32))
        bpy.ops.object.bake(type="EMIT")
        for lado, img in imagenes.items():
            px = np.empty(TAM * TAM * 4, np.float32)
            img.pixels.foreach_get(px)
            arr = px.reshape(TAM, TAM, 4)[::-1, :, :3]
            nombre = {"Position": "pos", "Normal": "nor", "Color": "color"}[canal]
            np.save(trabajo / f"{nombre}_{lado}.npy", arr)
            print("HORNEADO", canal, lado)

elif modo == "exportar":
    bpy.ops.wm.open_mainfile(filepath=str(trabajo / "preparado.blend"))
    cargadas = {}
    hechos = set()
    for o in bpy.data.objects:
        for s in o.material_slots:
            m = s.material
            if not (m and "lado" in m) or m.name in hechos:
                continue
            hechos.add(m.name)
            if m["lado"] not in cargadas:
                img = bpy.data.images.load(str(trabajo / f"tex_{m['lado']}.png"))
                img.name = f"{Path(conf['salida']).stem}_{m['lado']}"
                cargadas[m["lado"]] = img
            img = cargadas[m["lado"]]
            nc = nodo_color(m)
            if conf.get("uv_nuevas"):
                # material nuevo y simple sobre el mapa UV nuevo
                nt = m.node_tree
                pr = [n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"][0]
                for n in list(nt.nodes):
                    if n not in (pr,) and n.type != "OUTPUT_MATERIAL":
                        nt.nodes.remove(n)
                t = nt.nodes.new("ShaderNodeTexImage")
                t.image = img
                nt.links.new(t.outputs["Color"], pr.inputs["Base Color"])
                pr.inputs["Metallic"].default_value = 0.0
                pr.inputs["Roughness"].default_value = conf.get("rugosidad", 0.55)
            else:
                nc.image = img
        if o.type == "MESH" and conf.get("uv_nuevas") and "uv_original" in o:
            uvs = o.data.uv_layers
            uvs.remove(uvs[o["uv_original"]])
            uvs.active = uvs["repinte"]
            uvs["repinte"].active_render = True
    giro = Matrix.Rotation(math.radians(-bpy.context.scene["giro_repinte"]), 4, "Z")
    for o in raices():
        o.matrix_world = giro @ o.matrix_world
    bpy.ops.export_scene.gltf(filepath=conf["salida"], export_format="GLB", export_image_format="AUTO",
                              export_animations=False)

    # créditos: copia autor/licencia/fuente del .glb original (Sketchfab) y anota el cambio (CC-BY)
    import struct

    def leer_glb(ruta):
        d = Path(ruta).read_bytes()
        lj = struct.unpack("<I", d[12:16])[0]
        return json.loads(d[20:20 + lj]), d[20 + lj:]

    orig, _ = leer_glb(conf["original"])
    nuevo, resto = leer_glb(conf["salida"])
    extras = dict(orig.get("asset", {}).get("extras", {}))
    if extras:
        extras["title"] = f"{extras.get('title', '')} ({conf.get('nota', 'repintado')})"
        nuevo.setdefault("asset", {})["extras"] = extras
        js = json.dumps(nuevo, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        js += b" " * ((4 - len(js) % 4) % 4)
        Path(conf["salida"]).write_bytes(struct.pack("<III", 0x46546C67, 2, 20 + len(js) + len(resto)) +
                                         struct.pack("<II", len(js), 0x4E4F534A) + js + resto)
    print("EXPORTADO", conf["salida"], extras.get("title", ""))
