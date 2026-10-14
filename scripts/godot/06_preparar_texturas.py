"""Copia las texturas de Poly Haven (C:/UE/Recursos) al proyecto de Godot y escribe godot/texturas/texturas.json.

Uso:
    .venv\\Scripts\\python scripts\\godot\\06_preparar_texturas.py

El color va a 2048 px; normal y rugosidad a 1024 px (la GT 750 tiene poca VRAM y a esa distancia no se nota).
"""

import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comun import RAIZ  # noqa: E402

TAMANOS = {"color": 2048, "normal": 1024, "rugosidad": 1024}


def main():
    with open(RAIZ / "scripts" / "config" / "recursos.json", encoding="utf-8") as f:
        carpeta = Path(json.load(f)["carpeta"])
    with open(carpeta / "manifiesto.json", encoding="utf-8") as f:
        manifiesto = json.load(f)
    destino = RAIZ / "godot" / "texturas"
    destino.mkdir(parents=True, exist_ok=True)
    salida = {}
    for tid, t in manifiesto["texturas"].items():
        mapas = {}
        for clave, lado in TAMANOS.items():
            origen = t["mapas"].get(clave)
            if not origen or not Path(origen).exists():
                continue
            nombre = f"{tid}_{clave}.jpg"
            img = Image.open(origen)
            if max(img.size) > lado:
                img = img.resize((lado, lado), Image.LANCZOS)
            img.convert("RGB").save(destino / nombre, quality=92)
            mapas[clave] = f"res://texturas/{nombre}"
        salida[t["material"]] = {"id": tid, "tamano_m": t["tamano_m"], "mapas": mapas}
        print(f"  {t['material']:<22} {tid}")
    with open(destino / "texturas.json", "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    print(f"Listo: {len(salida)} texturas en {destino}")


if __name__ == "__main__":
    main()
