"""Empaqueta los renders de todas las zonas en un .zip para llevarlos a otra PC.

Uso:
    .venv\\Scripts\\python scripts\\empaquetar_renders.py

Crea paquetes/renders_<fecha>.zip con:
    finales/<zona>/   la versión más reciente de cada cámara (y de cada luz: mediodia, tarde...)
    historial/<zona>/ todos los renders, incluidas las versiones anteriores
    LEEME.txt         índice con la lista de imágenes finales
"""

import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import RAIZ  # noqa: E402

PATRON = re.compile(r"^(?P<clave>.+)_(?P<marca>\d{8}_\d{4})\.jpg$")


def main():
    zonas = sorted(p for p in (RAIZ / "datos").glob("*/*/renders") if p.is_dir())
    salida = RAIZ / "paquetes"
    salida.mkdir(exist_ok=True)
    ruta_zip = salida / f"renders_{datetime.now():%Y%m%d_%H%M}.zip"
    indice = [f"Renders de Escenarios 3D de Venezuela ({datetime.now():%d-%m-%Y %H:%M})", "",
              "finales/   la versión más reciente de cada cámara y luz",
              "historial/ todas las versiones (el nombre termina en AAAAMMDD_HHMM)", ""]
    total = 0
    with zipfile.ZipFile(ruta_zip, "w", compression=zipfile.ZIP_STORED) as z:  # los JPG ya están comprimidos
        for carpeta in zonas:
            zona = carpeta.parent.name
            ultimos = {}
            for img in sorted(carpeta.glob("*.jpg")):
                z.write(img, f"historial/{zona}/{img.name}")
                total += 1
                m = PATRON.match(img.name)
                clave, marca = (m["clave"], m["marca"]) if m else (img.stem, "")
                if clave not in ultimos or marca > ultimos[clave][0]:
                    ultimos[clave] = (marca, img)
            indice.append(f"== {zona} ({len(ultimos)} vistas finales) ==")
            for clave, (marca, img) in sorted(ultimos.items()):
                z.write(img, f"finales/{zona}/{clave}.jpg")
                fecha = datetime.strptime(marca, "%Y%m%d_%H%M").strftime("%d-%m-%Y %H:%M") if marca else ""
                indice.append(f"  {clave}.jpg  ({fecha})")
            indice.append("")
        z.writestr("LEEME.txt", "\r\n".join(indice))
    mb = ruta_zip.stat().st_size / 1e6
    print(f"Listo: {ruta_zip} ({mb:.0f} MB, {total} imágenes en historial)")


if __name__ == "__main__":
    main()
