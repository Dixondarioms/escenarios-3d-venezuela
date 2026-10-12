"""Prepara los modelos descargados (caché) y renderiza una hoja de revisión.

Uso:
    blender -b --factory-startup -P scripts/blender/revisar_modelos.py

Coloca cada modelo de C:/UE/Recursos/modelos_usuario en fila, con una flecha roja que indica hacia
dónde DEBE mirar el frente (+X), y renderiza datos/modelos_revision.jpg (vista lateral y desde arriba).
Si un modelo mira al revés o de lado, agrega "girar" en el ajustes.json de su carpeta.
"""

import json
import math
import sys
from pathlib import Path

import bpy

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parent))
import modelos_usuario  # noqa: E402
from comun import RAIZ  # noqa: E402

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
with open(RAIZ / "scripts" / "config" / "recursos.json", encoding="utf-8") as f:
    recursos = json.load(f)["carpeta"]
lib = bpy.data.collections.new("Biblioteca")
bpy.context.scene.collection.children.link(lib)
modelos = modelos_usuario.cargar(recursos, lib)
lib_capa = [c for c in bpy.context.view_layer.layer_collection.children if c.collection == lib][0]
lib_capa.exclude = True

esc = bpy.context.scene
x = 0.0
filas = {"aeronaves": 0.0, "carros": -30.0}
for tipo, cols in modelos.items():
    fila = "aeronaves" if tipo in ("helicoptero", "avion_turbohelice", "avion_jet") else "carros"
    for col in cols:
        largo = modelos_usuario.LARGO_DEFECTO[tipo]
        filas_x = filas[fila]
        e = bpy.data.objects.new(col.name, None)
        e.instance_type = "COLLECTION"
        e.instance_collection = col
        e.location = (filas_x + largo / 2, 0 if fila == "aeronaves" else -30, 0)
        esc.collection.objects.link(e)
        for o in col.all_objects:
            o.display_type = "TEXTURED"
        # flecha +X (frente esperado)
        bpy.ops.mesh.primitive_cone_add(radius1=0.4 if fila == "carros" else 1.2, depth=1.5 if fila == "carros" else 4,
                                        location=(filas_x + largo + 1.5, e.location.y, 0.5),
                                        rotation=(0, math.radians(90), 0))
        flecha = bpy.context.object
        mat = bpy.data.materials.get("Flecha") or bpy.data.materials.new("Flecha")
        mat.diffuse_color = (1, 0, 0, 1)
        flecha.data.materials.append(mat)
        txt = bpy.data.curves.new("t", "FONT")
        txt.body = col.name.replace("Usr_", "")[:28]
        txt.size = 1.2 if fila == "carros" else 2.5
        to = bpy.data.objects.new("t", txt)
        to.location = (filas_x, e.location.y - (3 if fila == "carros" else 14), 0)
        esc.collection.objects.link(to)
        filas[fila] = filas_x + largo + 6
bpy.ops.mesh.primitive_plane_add(size=600, location=(100, -20, 0))

esc.render.engine = "BLENDER_WORKBENCH"
esc.display.shading.light = "STUDIO"
esc.display.shading.color_type = "TEXTURE"
esc.render.image_settings.file_format = "JPEG"
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
esc.collection.objects.link(cam)
esc.camera = cam
# una hoja por fila (los carros son pequeños): vista desde arriba
for fila, y in (("aeronaves", 0.0), ("carros", -30.0)):
    ancho = filas[fila] + 6
    if ancho < 10:
        continue
    esc.render.resolution_x = 7200 if fila == "carros" else 2400
    esc.render.resolution_y = 500 if fila == "carros" else 1100
    cam.data.ortho_scale = ancho
    cam.location = (ancho / 2 - 3, y - (1 if fila == "carros" else 4), 200)
    salida = RAIZ / "datos" / f"modelos_revision_{fila}.jpg"
    esc.render.filepath = str(salida)
    bpy.ops.render.render(write_still=True)
    print(f"REVISION {salida}")
