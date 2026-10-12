"""Modelos 3D descargados por el usuario (Sketchfab, Fab, etc.) que reemplazan a los procedurales.

Carpeta: <recursos>/modelos_usuario/<tipo>/  (por ejemplo C:/UE/Recursos/modelos_usuario/helicoptero/)
Tipos: helicoptero, avion_turbohelice, avion_jet, sedan, hatchback, camioneta, pickup, por_puesto, moto
Formatos: .glb / .gltf / .fbx / .obj. Si hay varios modelos de un tipo, se alternan al azar.

Cada modelo se:
  * revisa: los .glb de Sketchfab traen autor y licencia; los NoComercial (NC) se omiten salvo que
    ajustes.json diga {"permitir_nc": true}. Los créditos van a docs/creditos_modelos.md.
  * simplifica si pasa de 'max_triangulos' (los de 1–4 millones de triángulos no caben en 8 GB de RAM),
  * escala a su medida real, apoya en el suelo, centra y orienta con el frente hacia +X,
  * guarda ya procesado en <tipo>/_cache/*.blend (la próxima vez carga en segundos).
Ajustes opcionales por archivo en <tipo>/ajustes.json:
    {"mi_modelo.glb": {"largo_m": 18.4, "girar": 180, "max_triangulos": 150000}}
"""

import json
import math
import struct
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

TIPOS = ("helicoptero", "avion_turbohelice", "avion_jet", "sedan", "hatchback", "camioneta", "pickup",
         "por_puesto", "moto")
# Dimensión horizontal más larga real (m): rotor/envergadura en aeronaves, largo en carros
LARGO_DEFECTO = {"helicoptero": 21.0, "avion_turbohelice": 17.6, "avion_jet": 16.0, "sedan": 4.5,
                 "hatchback": 3.75, "camioneta": 4.8, "pickup": 5.3, "por_puesto": 5.6, "moto": 2.0}
MAX_TRIANGULOS = 200_000
GIRO_DEFECTO = 90.0  # los glTF suelen quedar con el frente hacia -Y al importarse en Blender
EXTENSIONES = (".glb", ".gltf", ".fbx", ".obj")
VERSION_CACHE = 2


def metadatos_glb(ruta):
    """Autor, licencia, fuente y título guardados por Sketchfab en el encabezado del .glb."""
    if ruta.suffix.lower() != ".glb":
        return {}
    try:
        with open(ruta, "rb") as f:
            f.read(12)
            largo, _ = struct.unpack("<II", f.read(8))
            datos = json.loads(f.read(largo))
        return datos.get("asset", {}).get("extras", {}) or {}
    except (OSError, ValueError, struct.error):
        return {}


def importar(ruta):
    antes = set(bpy.data.objects)
    ext = ruta.suffix.lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(ruta))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(ruta))
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=str(ruta))
    return [o for o in bpy.data.objects if o not in antes]


def simplificar(mallas, max_tris):
    """Aplica Decimate (colapso) para dejar el modelo por debajo de max_tris."""
    bpy.context.view_layer.update()
    total = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in mallas)
    if total <= max_tris:
        return total, total
    ratio = max(max_tris / total, 0.01)
    dg = bpy.context.evaluated_depsgraph_get()
    hechas = {}
    for o in mallas:
        if o.data.name in hechas:  # mallas compartidas: una sola vez
            o.data = hechas[o.data.name]
            continue
        nombre = o.data.name
        mod = o.modifiers.new("simplificar", "DECIMATE")
        mod.ratio = ratio
        mod.use_collapse_triangulate = True
        dg.update()
        nueva = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
        o.modifiers.remove(mod)
        o.data = nueva
        hechas[nombre] = nueva
    final = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in mallas)
    return total, final


def normalizar(objetos, largo_m, giro_grados, es_carro):
    """Escala, gira, centra y apoya en z=0 el conjunto de objetos importados."""
    bpy.context.view_layer.update()
    raices = [o for o in objetos if o.parent is None]
    mallas = [o for o in objetos if o.type == "MESH"]
    if not mallas:
        return False
    pts = [o.matrix_world @ Vector(c) for o in mallas for c in o.bound_box]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    giro = giro_grados
    if es_carro:  # el largo de un carro es siempre su dimensión mayor: se alinea con X
        giro += GIRO_DEFECTO if (mx.y - mn.y) > (mx.x - mn.x) else 0.0
    else:         # en aeronaves la envergadura puede ser mayor que el largo: se asume frente hacia -Y
        giro += GIRO_DEFECTO
    centro = (mn + mx) / 2
    escala = largo_m / max(mx.x - mn.x, mx.y - mn.y, 1e-6)
    m = (Matrix.Rotation(math.radians(giro), 4, "Z") @ Matrix.Scale(escala, 4)
         @ Matrix.Translation(Vector((-centro.x, -centro.y, -mn.z))))
    for o in raices:
        o.matrix_world = m @ o.matrix_world
    bpy.context.view_layer.update()
    return True


def desde_cache(ruta_cache, nombre_col):
    with bpy.data.libraries.load(str(ruta_cache), link=False) as (origen, destino):
        if nombre_col not in origen.collections:
            return None
        destino.collections = [nombre_col]
    return destino.collections[0]


def sin_emision_plana(col):
    """Apaga la emisión de color plano (sin textura): algunos .glb exportados traen emissiveFactor = 1
    sin mapa y el modelo entero brilla en blanco (p. ej. un repintado horneado en una sola textura).
    Las luces con textura de emisión se respetan. Devuelve cuántos materiales se corrigieron."""
    n = 0
    mats = {s.material for o in col.all_objects for s in o.material_slots if s.material and s.material.use_nodes}
    for mat in mats:
        for nodo in mat.node_tree.nodes:
            if nodo.type != "BSDF_PRINCIPLED":
                continue
            color, fuerza = nodo.inputs["Emission Color"], nodo.inputs["Emission Strength"]
            if not color.is_linked and not fuerza.is_linked and fuerza.default_value > 0 and max(color.default_value[:3]) > 0.01:
                fuerza.default_value = 0.0
                n += 1
    return n


def preparar(ruta, tipo, aj):
    """Importa, simplifica y normaliza un modelo; devuelve su colección (o None)."""
    col, nota = _preparar(ruta, tipo, aj)
    if col is not None and not aj.get("conservar_emision"):
        corregidos = sin_emision_plana(col)
        if corregidos:
            nota += f", emisión plana apagada en {corregidos} materiales"
    return col, nota


def _preparar(ruta, tipo, aj):
    nombre_col = f"Usr_{tipo}_{ruta.stem}"[:60]
    cache = ruta.parent / "_cache" / f"{ruta.stem}.blend"
    firma = f"{VERSION_CACHE}|{ruta.stat().st_mtime}|{json.dumps(aj, sort_keys=True)}"
    firma_ruta = cache.with_suffix(".firma")
    if cache.exists() and firma_ruta.exists() and firma_ruta.read_text(encoding="utf-8") == firma:
        col = desde_cache(cache, nombre_col)
        if col is not None:
            return col, "caché"
    objetos = importar(ruta)
    if not objetos:
        return None, "sin objetos"
    col = bpy.data.collections.new(nombre_col)
    for o in objetos:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        col.objects.link(o)
    bpy.context.scene.collection.children.link(col)  # temporal: para evaluar modificadores
    mallas = [o for o in objetos if o.type == "MESH"]
    antes, despues = simplificar(mallas, aj.get("max_triangulos", MAX_TRIANGULOS))
    es_carro = tipo not in ("helicoptero", "avion_turbohelice", "avion_jet")
    ok = normalizar(objetos, aj.get("largo_m", LARGO_DEFECTO[tipo]), aj.get("girar", 0.0), es_carro)
    bpy.context.scene.collection.children.unlink(col)
    if not ok:
        return None, "sin mallas"
    for o in mallas:
        o.display_type = "BOUNDS"  # los modelos detallados no caben en el viewport de una iGPU
    for m in [m for m in bpy.data.meshes if m.users == 0]:  # libera las mallas originales sin simplificar
        bpy.data.meshes.remove(m)
    cache.parent.mkdir(exist_ok=True)
    bpy.data.libraries.write(str(cache), {col}, fake_user=True, compress=True)
    firma_ruta.write_text(firma, encoding="utf-8")
    nota = f"{antes:,} → {despues:,} triángulos" if despues < antes else f"{antes:,} triángulos"
    return col, nota


def cargar(carpeta_recursos, coleccion_padre):
    """Devuelve {tipo: [colección, ...]} con los modelos encontrados (vacío si no hay ninguno)."""
    base = Path(carpeta_recursos) / "modelos_usuario"
    base.mkdir(parents=True, exist_ok=True)
    encontrados, creditos, omitidos = {}, [], []
    for tipo in TIPOS:
        carpeta = base / tipo
        carpeta.mkdir(exist_ok=True)
        ajustes = {}
        if (carpeta / "ajustes.json").exists():
            ajustes = json.loads((carpeta / "ajustes.json").read_text(encoding="utf-8-sig"))  # tolera BOM (Bloc de notas)
        for ruta in sorted(p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES):
            aj = ajustes.get(ruta.name, {})
            meta = metadatos_glb(ruta)
            licencia = str(meta.get("license", ""))
            if "-NC" in licencia.upper() and not aj.get("permitir_nc"):
                omitidos.append(f"{tipo}/{ruta.name} ({licencia.split(' ')[0]})")
                continue
            col, nota = preparar(ruta, tipo, aj)
            if col is None:
                print(f"  Modelo omitido: {tipo}/{ruta.name} ({nota})")
                continue
            coleccion_padre.children.link(col)
            encontrados.setdefault(tipo, []).append(col)
            print(f"  Modelo del usuario: {tipo} <- {ruta.name} ({nota})")
            if meta:
                creditos.append(f"- **{meta.get('title', ruta.stem)}** ({tipo}): {meta.get('author', '?')}. "
                                f"Licencia: {licencia or '?'}. Fuente: {meta.get('source', '?')}")
            elif (carpeta / "credito.txt").exists():
                creditos.append(f"- {tipo}: {(carpeta / 'credito.txt').read_text(encoding='utf-8').strip()}")
    for o in omitidos:
        print(f"  Omitido por licencia NoComercial: {o}")
    if creditos:
        raiz = Path(__file__).resolve().parent.parent.parent
        (raiz / "docs" / "creditos_modelos.md").write_text(
            "# Créditos de modelos 3D descargados\n\n"
            "Modelos de terceros usados en las escenas (generado automáticamente).\n\n" + "\n".join(creditos) + "\n",
            encoding="utf-8")
    return encontrados
