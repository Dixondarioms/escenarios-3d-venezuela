"""Paso 02b: imagen satelital Sentinel-2 (Copernicus) para el relieve de fondo y la vegetación de la zona.

Uso:
    python scripts/02b_imagen_satelital.py altamira [--escena S2A_T19PGM_20240218T145722_L2A] [--listar]

Usa Sentinel-2 nivel 2A (Copernicus, datos libres incluso para uso comercial, con atribución)
del catálogo abierto de AWS (Earth Search). Solo lee por HTTP el recorte necesario, no la escena entera.

Salidas en datos/<ciudad>/<zona>/terreno/:
    satelite_fondo.jpg     color real a 10 m cubriendo el relieve de fondo (proyección local de la zona)
    ndvi_zona.png          índice de vegetación (NDVI) a 10 m sobre la zona (0 = sin vegetación, 255 = muy verde)
    satelite_meta.json     escena usada, extensiones y atribución
    arboles_satelite.json  árboles adicionales donde el satélite ve vegetación y no hay edificios ni calles
                           (requiere haber corrido 01 y 02)
"""

import argparse
import json
import math
import random
import sys

import numpy as np
import requests

from comun import cargar_zona, carpeta_zona, proj_local

STAC = "https://earth-search.aws.element84.com/v1/search"
ATRIBUCION = "Contiene datos modificados de Copernicus Sentinel {año} (ESA), procesados con Earth Search (Element 84)"


def buscar_escenas(bbox):
    consulta = {"collections": ["sentinel-2-c1-l2a"], "bbox": bbox, "limit": 50,
                "datetime": "2020-01-01T00:00:00Z/2030-01-01T00:00:00Z",
                "query": {"eo:cloud_cover": {"lt": 10}},
                "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}]}
    r = requests.post(STAC, json=consulta, timeout=120)
    r.raise_for_status()
    return r.json()["features"]


def leer_recorte(href, extension, res, crs_local, remuestreo):
    """Lee un COG remoto reproyectado a la rejilla local (x hacia el Este, filas de Norte a Sur)."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    xmin, ymin, xmax, ymax = extension
    ancho = int(round((xmax - xmin) / res))
    alto = int(round((ymax - ymin) / res))
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES",
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        with rasterio.open(href) as src:
            with WarpedVRT(src, crs=crs_local, transform=from_origin(xmin, ymax, res, res), width=ancho, height=alto,
                           resampling=getattr(Resampling, remuestreo), src_nodata=0, nodata=0) as vrt:
                return vrt.read()


def estirar(rgb):
    """Ajuste de niveles suave (percentiles 0,5–99,5 %) para que el color se vea natural."""
    salida = np.zeros_like(rgb, dtype=np.float32)
    validos = rgb.sum(axis=0) > 0
    for i in range(3):
        canal = rgb[i].astype(np.float32)
        lo, hi = np.percentile(canal[validos], [0.5, 99.5])
        salida[i] = np.clip((canal - lo) / max(hi - lo, 1), 0, 1) ** 0.95
    return (salida * 255).astype(np.uint8)


def ocupacion(osm, mitad, res=1.0):
    """Máscara 1 m de lo que NO puede tener árboles: edificios, calles con aceras, agua."""
    from PIL import Image, ImageDraw
    n = int(round(2 * mitad / res))
    img = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(img)

    def px(p):
        return ((p[0] + mitad) / res, (mitad - p[1]) / res)
    for e in osm["edificios"]:
        d.polygon([px(p) for p in e["exterior"]], fill=255)
    for a in osm["areas"]:
        if a["tipo"] in ("agua", "cancha", "estacionamiento", "plaza", "plataforma", "aerodromo"):
            d.polygon([px(p) for p in a["exterior"]], fill=255)
    for v in osm["vias"]:
        if v["tunel"]:
            continue
        sendero = v["tipo"] in ("footway", "path", "steps", "cycleway")
        ancho = v["ancho"] + (0.5 if sendero else 2 * 2.5 + 1.0)
        d.line([px(p) for p in v["puntos"]], fill=255, width=max(1, int(round(ancho / res))))
    return np.array(img) > 0


def arboles_satelite(ndvi, ndvi_res, mitad, osm, alturas, alt_res, rnd, separacion=7.0, umbral=0.42):
    ocu = ocupacion(osm, mitad)
    existentes = [(p["x"], p["y"]) for p in osm["puntos"] if p["tipo"] == "arbol"]
    celda_exist = {}
    for x, y in existentes:
        celda_exist.setdefault((int(x // 6), int(y // 6)), []).append((x, y))
    arboles = []
    n_ndvi = ndvi.shape[0]
    n_alt = alturas.shape[0]
    pasos = int(2 * mitad / separacion)
    for i in range(pasos):
        for j in range(pasos):
            x = -mitad + (i + rnd.random()) * separacion
            y = -mitad + (j + rnd.random()) * separacion
            f = int((mitad - y) / ndvi_res)
            c = int((x + mitad) / ndvi_res)
            if not (0 <= f < n_ndvi and 0 <= c < n_ndvi):
                continue
            v = ndvi[f, c]
            if v < umbral or rnd.random() > min(1.0, (v - umbral) / 0.25):
                continue
            fo, co = int(mitad - y), int(x + mitad)
            r = 2
            if ocu[max(fo - r, 0):fo + r + 1, max(co - r, 0):co + r + 1].any():
                continue
            cerca = any(math.hypot(x - a, y - b) < 5.0
                        for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                        for a, b in celda_exist.get((int(x // 6) + dx, int(y // 6) + dy), []))
            if cerca:
                continue
            fa = min(max(int(round((mitad - y) / alt_res)), 0), n_alt - 1)
            ca = min(max(int(round((x + mitad) / alt_res)), 0), n_alt - 1)
            arboles.append({"tipo": "arbol", "x": round(x, 2), "y": round(y, 2), "z": round(float(alturas[fa, ca]), 2),
                            "rumbo": round(rnd.uniform(0, 360), 1), "escala": round(rnd.uniform(0.7, 1.35), 2),
                            "origen": "satelite"})
    return arboles


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zona")
    ap.add_argument("--escena", help="id de la escena Sentinel-2 (por defecto la de menos nubes)")
    ap.add_argument("--listar", action="store_true", help="solo lista las escenas disponibles")
    args = ap.parse_args()

    from PIL import Image
    from pyproj import Transformer
    from rasterio.crs import CRS

    zona = cargar_zona(args.zona)
    carpeta = carpeta_zona(zona)
    salida = carpeta / "terreno"
    with open(salida / "meta.json", encoding="utf-8") as f:
        meta_terreno = json.load(f)
    fondo = zona.get("fondo", {"radio_m": zona["tamano_m"] / 2})
    R = fondo["radio_m"]
    a_geo = Transformer.from_crs(proj_local(zona), "EPSG:4326", always_xy=True)
    lons, lats = a_geo.transform([-R, R, -R, R], [-R, -R, R, R])
    bbox = [min(lons), min(lats), max(lons), max(lats)]

    escenas = buscar_escenas(bbox)
    if args.listar or not escenas:
        for e in escenas:
            print(f"  {e['id']}  {e['properties']['datetime'][:10]}  nubes {e['properties']['eo:cloud_cover']:.1f} %")
        return
    escena = next((e for e in escenas if e["id"] == args.escena), None) if args.escena else escenas[0]
    if escena is None:
        raise SystemExit(f"No encontré la escena {args.escena}; usa --listar")
    fecha = escena["properties"]["datetime"][:10]
    print(f"Escena {escena['id']} ({fecha}, nubes {escena['properties']['eo:cloud_cover']:.1f} %)")
    crs_local = CRS.from_string(proj_local(zona))

    # 1) Color real para el fondo (10 m)
    print("  Leyendo color real del fondo...")
    rgb = leer_recorte(escena["assets"]["visual"]["href"], (-R, -R, R, R), 10.0, crs_local, "bilinear")
    vacio = (rgb.sum(axis=0) == 0).mean()
    Image.fromarray(np.moveaxis(estirar(rgb), 0, 2)).save(salida / "satelite_fondo.jpg", quality=92)
    print(f"  satelite_fondo.jpg: {rgb.shape[2]}x{rgb.shape[1]} px ({vacio * 100:.1f} % sin datos)")

    # 2) NDVI de la zona (10 m) con las bandas roja e infrarroja
    mitad = meta_terreno["extension_local"][2]
    ext = (-mitad, -mitad, mitad, mitad)
    def reflectancia(banda):
        """DN -> reflectancia con la escala/desplazamiento de la escena (desde 2022 hay offset -0,1)."""
        asset = escena["assets"][banda]
        info = (asset.get("raster:bands") or [{}])[0]
        dn = leer_recorte(asset["href"], ext, 10.0, crs_local, "bilinear")[0].astype(np.float32)
        r = dn * info.get("scale", 0.0001) + info.get("offset", 0.0)
        return np.where(dn > 0, np.clip(r, 0, None), np.nan)

    rojo, nir = reflectancia("red"), reflectancia("nir")
    ndvi = np.nan_to_num((nir - rojo) / np.maximum(nir + rojo, 1e-4), nan=0.0)
    Image.fromarray((np.clip(ndvi, 0, 1) * 255).astype(np.uint8)).save(salida / "ndvi_zona.png")
    print(f"  ndvi_zona.png: vegetación (NDVI>0,4) en {(ndvi > 0.4).mean() * 100:.0f} % de la zona")

    año = fecha[:4]
    with open(salida / "satelite_meta.json", "w", encoding="utf-8") as f:
        json.dump({"escena": escena["id"], "fecha": fecha, "resolucion_m": 10.0,
                   "fondo_extension": [-R, -R, R, R], "zona_extension": list(ext),
                   "atribucion": ATRIBUCION.format(año=año)}, f, ensure_ascii=False, indent=2)

    # 3) Árboles donde hay vegetación libre
    ruta_osm = carpeta / "osm_local.json"
    if ruta_osm.exists():
        with open(ruta_osm, encoding="utf-8") as f:
            osm = json.load(f)
        alturas = np.load(salida / "altura_local.npy")
        arboles = arboles_satelite(ndvi, 10.0, mitad, osm, alturas, meta_terreno["resolucion_m"], random.Random(11))
        with open(salida / "arboles_satelite.json", "w", encoding="utf-8") as f:
            json.dump(arboles, f)
        print(f"  arboles_satelite.json: {len(arboles)} árboles nuevos (además de los {sum(p['tipo'] == 'arbol' for p in osm['puntos'])} de OSM)")
    print("Listo.")


if __name__ == "__main__":
    sys.exit(main())
