"""Renderiza una o varias cámaras de una escena ya preparada (sin reconstruirla).

Uso:
    blender -b datos/caracas/altamira/altamira_realista.blend -P scripts/blender/render_camaras.py -- \
            Cam_Plaza_Calle Cam_Avila [--muestras 128] [--porcentaje 100] [--exposicion -0.3] [--bruma 0.3] \
            [--luz tarde] [--luces mediodia,tarde,nublado]
    (sin nombres de cámara: renderiza todas las de la colección "Camaras")

--luz cambia el sol, las nubes, la exposición y la bruma a una variante de cielo.py / zonas.json ("luces")
sin reconstruir la escena; --luces renderiza cada cámara con varias variantes.
Las imágenes quedan en la carpeta renders/ junto al .blend (con el nombre de la luz si se usa).
"""

import sys
from datetime import datetime
from pathlib import Path

import bpy

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parent))


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

    luces = [None]
    if "luces" in opciones or "luz" in opciones:
        luces = (opciones.get("luces") or opciones["luz"]).split(",")
    zona = None
    if luces != [None]:
        import cielo
        from comun import cargar_zona
        zona_id = escena.get("zona_id") or Path(bpy.data.filepath).stem.replace("_realista", "")
        zona = cargar_zona(zona_id)

    camaras = [o for o in escena.objects if o.type == "CAMERA"]
    if nombres:
        camaras = [c for c in camaras if c.name in nombres]
    salida = Path(bpy.data.filepath).parent / "renders"
    salida.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M")
    for luz in luces:
        sufijo = ""
        if luz is not None:
            cielo.aplicar(escena, zona, luz)
            sufijo = f"_{luz}"
        # los ajustes manuales mandan sobre los de la variante
        if "exposicion" in opciones:
            escena.view_settings.exposure = float(opciones["exposicion"])
        if "bruma" in opciones and escena.node_tree:
            for n in escena.node_tree.nodes:
                if n.bl_idname == "CompositorNodeMath":
                    n.inputs[1].default_value = float(opciones["bruma"])
        for cam in camaras:
            escena.camera = cam
            escena.render.filepath = str(salida / f"{cam.name}{sufijo}_{marca}.jpg")
            print(f"Renderizando {cam.name}{sufijo}...")
            bpy.ops.render.render(write_still=True)
            print(f"RENDER {escena.render.filepath}")


main()
