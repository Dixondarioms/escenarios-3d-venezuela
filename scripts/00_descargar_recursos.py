"""Paso 00: descarga texturas, modelos y cielos CC0 de Poly Haven (se hace una sola vez).

Uso:
    python scripts/00_descargar_recursos.py

Lee scripts/config/recursos.json y guarda todo en la carpeta indicada (por defecto C:/UE/Recursos,
fuera de OneDrive). Escribe manifiesto.json con rutas, tamaño físico real de cada textura (para
escalar las UV en metros) y la fuente. Lo ya descargado no se vuelve a bajar.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import requests

from comun import RAIZ

API = "https://api.polyhaven.com"
CABECERAS = {"User-Agent": "EscenariosVenezuela/0.1 (pipeline 3D personal)"}
MAPAS = {"Diffuse": "color", "nor_gl": "normal", "Rough": "rugosidad", "Displacement": "altura"}


def obtener(url):
    for intento in range(4):
        try:
            r = requests.get(url, headers=CABECERAS, timeout=120)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if intento == 3:
                raise
            print(f"    reintento ({e})")
            time.sleep(3 * (intento + 1))


def bajar(url, ruta, md5=None):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists() and (md5 is None or hashlib.md5(ruta.read_bytes()).hexdigest() == md5):
        return False
    tmp = ruta.with_name(ruta.name + ".part")
    with requests.get(url, headers=CABECERAS, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for bloque in r.iter_content(1 << 20):
                f.write(bloque)
    tmp.replace(ruta)
    return True


def main():
    with open(RAIZ / "scripts" / "config" / "recursos.json", encoding="utf-8") as f:
        cfg = json.load(f)
    carpeta = Path(cfg["carpeta"])
    res = cfg["resolucion"]
    manifiesto = {"carpeta": str(carpeta), "texturas": {}, "modelos": {}, "hdris": {},
                  "licencia": "CC0 - Poly Haven (polyhaven.com)"}
    total = 0

    for tid, material in cfg["texturas"].items():
        info = obtener(f"{API}/info/{tid}").json()
        archivos = obtener(f"{API}/files/{tid}").json()
        mapas = {}
        for clave, nombre in MAPAS.items():
            if clave not in archivos or res not in archivos[clave]:
                continue
            datos = archivos[clave][res]["jpg" if "jpg" in archivos[clave][res] else "png"]
            ruta = carpeta / "texturas" / tid / datos["url"].rsplit("/", 1)[1]
            if bajar(datos["url"], ruta, datos.get("md5")):
                total += datos["size"]
            mapas[nombre] = str(ruta)
        dim = info.get("dimensions") or [2000, 2000]
        manifiesto["texturas"][tid] = {"material": material, "mapas": mapas,
                                       "tamano_m": [round(dim[0] / 1000, 3), round(dim[1] / 1000, 3)],
                                       "nombre": info.get("name"), "autores": list(info.get("authors", {}))}
        print(f"  textura {tid:28s} -> {material}  ({dim[0] / 1000:.2f} m)")

    for mid in cfg["modelos"]:
        archivos = obtener(f"{API}/files/{mid}").json()
        g = archivos["gltf"][cfg.get("resolucion_modelos", {}).get(mid, res)]["gltf"]
        base = carpeta / "modelos" / mid
        if bajar(g["url"], base / g["url"].rsplit("/", 1)[1], g.get("md5")):
            total += g["size"]
        for rel, datos in g.get("include", {}).items():
            if bajar(datos["url"], base / rel, datos.get("md5")):
                total += datos["size"]
        manifiesto["modelos"][mid] = str(base / g["url"].rsplit("/", 1)[1])
        print(f"  modelo  {mid}")

    for hid in cfg["hdris"]:
        archivos = obtener(f"{API}/files/{hid}").json()
        d = archivos["hdri"][res]["hdr"]
        ruta = carpeta / "hdris" / d["url"].rsplit("/", 1)[1]
        if bajar(d["url"], ruta, d.get("md5")):
            total += d["size"]
        manifiesto["hdris"][hid] = str(ruta)
        print(f"  cielo   {hid}")

    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / "manifiesto.json", "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
    print(f"Listo: {total / 1e6:.0f} MB descargados en {carpeta}")


if __name__ == "__main__":
    sys.exit(main())
