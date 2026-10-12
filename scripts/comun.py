"""Utilidades compartidas del pipeline (configuración de zonas, rutas y proyección).

Este módulo no importa pyproj al cargarse para que Blender también pueda usarlo
(el Python de Blender no trae pyproj). La proyección solo se usa en los pasos 01 y 02.

Sistema de coordenadas local de cada zona (en metros):
  - Origen (0, 0, 0) = punto "centro" de la zona, a nivel del terreno.
  - X = Este, Y = Norte, Z = arriba (igual que Blender).
  - Proyección transversa de Mercator centrada en el origen con escala 1, así que
    coincide con el plano tangente Este-Norte que usa CesiumGeoreference
    (error < 10 cm en 1 km). En Unreal: X = Este, Y = -Norte (Sur), unidades en cm.
"""

import json
import math
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_ZONAS = RAIZ / "scripts" / "config" / "zonas.json"


def cargar_zona(nombre):
    with open(CONFIG_ZONAS, encoding="utf-8") as f:
        zonas = json.load(f)
    if nombre not in zonas:
        raise SystemExit(f"Zona '{nombre}' no existe. Zonas disponibles: {', '.join(zonas)}")
    zona = dict(zonas[nombre])
    zona["id"] = nombre
    return zona


def carpeta_zona(zona):
    """datos/<ciudad>/<zona>/ (se crea si no existe)."""
    carpeta = RAIZ / "datos" / zona["ciudad"] / zona["id"]
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def proj_local(zona):
    c = zona["centro"]
    return (f"+proj=tmerc +lat_0={c['lat']} +lon_0={c['lon']} +k=1 "
            "+x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs")


def transformadores(zona):
    """(lonlat -> local, local -> lonlat) usando pyproj."""
    from pyproj import Transformer
    a_local = Transformer.from_crs("EPSG:4326", proj_local(zona), always_xy=True)
    a_geo = Transformer.from_crs(proj_local(zona), "EPSG:4326", always_xy=True)
    return a_local, a_geo


def extension_local(zona, margen_m=0.0):
    """(xmin, ymin, xmax, ymax) del cuadrado de la zona en coordenadas locales."""
    m = zona["tamano_m"] / 2.0 + margen_m
    return (-m, -m, m, m)


def bbox_geo(zona, margen_m=0.0):
    """(sur, oeste, norte, este) en grados que cubre el cuadrado de la zona."""
    _, a_geo = transformadores(zona)
    xmin, ymin, xmax, ymax = extension_local(zona, margen_m)
    lons, lats = [], []
    for x in (xmin, 0.0, xmax):
        for y in (ymin, 0.0, ymax):
            lon, lat = a_geo.transform(x, y)
            lons.append(lon)
            lats.append(lat)
    return (min(lats), min(lons), max(lats), max(lons))


INDICE_MICROSOFT = "https://bfppub.blob.core.windows.net/%24web/2026-07-24/dataset-links.csv"


def quadkey(lat, lon, z=9):
    """Clave de mosaico Bing/Microsoft (nivel 9 = mosaicos de Microsoft Building Footprints)."""
    x = (lon + 180) / 360
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    tx, ty = int(x * 2 ** z), int(y * 2 ** z)
    q = ""
    for i in range(z, 0, -1):
        m = 1 << (i - 1)
        q += str((1 if tx & m else 0) + (2 if ty & m else 0))
    return q


def mosaicos_microsoft(sur, oeste, norte, este, region="Venezuela"):
    """Rutas locales (descargando si hace falta) de los mosaicos de Microsoft que cubren el bbox."""
    import csv
    import io

    import requests
    claves = set()
    pasos = 12
    for i in range(pasos + 1):
        for j in range(pasos + 1):
            claves.add(quadkey(sur + (norte - sur) * i / pasos, oeste + (este - oeste) * j / pasos))
    cache = RAIZ / "datos" / "_ms_cache"
    cache.mkdir(parents=True, exist_ok=True)
    ruta_indice = cache / "dataset-links.csv"
    if not ruta_indice.exists():
        r = requests.get(INDICE_MICROSOFT, timeout=120)
        r.raise_for_status()
        ruta_indice.write_bytes(r.content)
    rutas = []
    for f in csv.DictReader(io.StringIO(ruta_indice.read_text(encoding="utf-8"))):
        if f["QuadKey"] in claves and f["Location"] == region:
            ruta = cache / f"{f['QuadKey']}.csv.gz"
            if not ruta.exists():
                print(f"  Descargando mosaico de edificios {f['QuadKey']} ({f['Size']})...")
                r = requests.get(f["Url"], timeout=300)
                r.raise_for_status()
                ruta.write_bytes(r.content)
            rutas.append(ruta)
    return rutas


def guardar_json(ruta, datos):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))


def distancia(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])
