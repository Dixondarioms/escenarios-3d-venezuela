"""Renderiza una o varias cámaras de una escena ya preparada (sin reconstruirla).

Uso:
    blender -b datos/caracas/altamira/altamira_realista.blend -P scripts/blender/render_camaras.py -- \
            Cam_Plaza_Calle Cam_Avila [--muestras 128] [--porcentaje 100] [--exposicion -0.3] [--bruma 0.3]
    (sin nombres de cámara: renderiza todas las de la colección "Camaras")

Las imágenes quedan en la carpeta renders/ junto al .blend.
"""

import sys
from datetime import datetime
from pathlib import Path

import bpy


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opciones = {}
    nombres = []
    i = 0
    while i < len(argv):
        if argv[i].startswith("--"):
            opciones[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            nombres.append(argv[i])
            i += 1
    escena = bpy.context.scene
    if "muestras" in opciones:
        escena.cycles.samples = int(opciones["muestras"])
    if "porcentaje" in opciones:
        escena.render.resolution_percentage = int(opciones["porcentaje"])
    if "exposicion" in opciones:
        escena.view_settings.exposure = float(opciones["exposicion"])
    if "bruma" in opciones and escena.node_tree:
        for n in escena.node_tree.nodes:
            if n.bl_idname == "CompositorNodeMath":
                n.inputs[1].default_value = float(opciones["bruma"])
    camaras = [o for o in escena.objects if o.type == "CAMERA"]
    if nombres:
        camaras = [c for c in camaras if c.name in nombres]
    salida = Path(bpy.data.filepath).parent / "renders"
    salida.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M")
    for cam in camaras:
        escena.camera = cam
        escena.render.filepath = str(salida / f"{cam.name}_{marca}.jpg")
        print(f"Renderizando {cam.name}...")
        bpy.ops.render.render(write_still=True)
        print(f"RENDER {escena.render.filepath}")


main()
