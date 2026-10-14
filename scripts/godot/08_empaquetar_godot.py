"""Empaqueta el proyecto de Godot (carpeta godot/) en un .zip para copiarlo a otra PC sin Git.

Uso:
    .venv\\Scripts\\python scripts\\godot\\08_empaquetar_godot.py [--sin-cache]

Crea paquetes/escenarios_godot_<fecha>.zip. Por defecto incluye la caché de importación (godot/.godot/imported):
así Godot 4.4 abre el proyecto en segundos en vez de reimportar todo. Con --sin-cache el zip pesa la mitad,
pero la primera apertura tarda varios minutos.
"""

import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comun import RAIZ  # noqa: E402

YA_COMPRIMIDOS = {".glb", ".jpg", ".jpeg", ".png", ".webp", ".ctex", ".scn", ".res", ".mesh"}
LEEME = """Escenarios 3D de Venezuela - proyecto de Godot 4.4
====================================================

1. Instala Godot 4.4 (versión estándar, no .NET): https://godotengine.org/download/archive/4.4.1-stable/
2. Descomprime este zip en una carpeta de ruta CORTA y sin acentos, por ejemplo C:\\Juegos. Algunos archivos
   internos tienen nombres largos y Windows no acepta rutas de más de 260 caracteres (en el Escritorio o en
   Descargas puede fallar).
3. Abre Godot, pulsa "Importar", elige el archivo project.godot de esta carpeta y luego "Importar y editar".
4. Pulsa F5 (o el botón de Play arriba a la derecha).

Controles: WASD mover · ratón mirar · Shift correr · Espacio saltar · F volar (E/Q subir/bajar)
           1-9 cámaras · L luz (mediodía, mañana, tarde, nublado) · C calidad · Tab zona · H ayuda · Esc soltar ratón

Empieza en calidad baja (pensado para una GeForce GT 750). Si va fluido, sube con la tecla C.
El número de FPS aparece arriba a la izquierda.

Créditos: © OpenStreetMap contributors; Copernicus DEM y Sentinel-2 (ESA); texturas y modelos CC0 de
Poly Haven; modelos de Sketchfab (CC BY, ver créditos en el repositorio). No redistribuir los modelos sueltos.
"""


def main():
    con_cache = "--sin-cache" not in sys.argv
    godot = RAIZ / "godot"
    salida = RAIZ / "paquetes"
    salida.mkdir(exist_ok=True)
    ruta = salida / f"escenarios_godot_{datetime.now():%Y%m%d_%H%M}.zip"
    n = 0
    with zipfile.ZipFile(ruta, "w", allowZip64=True) as z:
        for f in sorted(godot.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(godot)
            partes = rel.parts
            if partes[0] == ".godot":
                if not con_cache or (len(partes) > 1 and partes[1] in ("editor", "shader_cache")):
                    continue
            if partes[0] in ("exportado",):
                continue
            modo = zipfile.ZIP_STORED if f.suffix.lower() in YA_COMPRIMIDOS else zipfile.ZIP_DEFLATED
            z.write(f, f"EscenariosVenezuela/{rel.as_posix()}", compress_type=modo)
            n += 1
        z.writestr("EscenariosVenezuela/LEEME.txt", LEEME.replace("\n", "\r\n"))
    print(f"Listo: {ruta} ({ruta.stat().st_size / 1e9:.2f} GB, {n} archivos, caché {'incluida' if con_cache else 'no'})")


if __name__ == "__main__":
    main()
