"""Paso 02c: volumen para la ciudad que rodea la zona (fondo de los renders y del simulador de vuelo).

Uso (después de 02):
    python scripts/02c_ciudad_lejana.py altamira

Toma las huellas de Microsoft Global ML Building Footprints dentro de 'ciudad_lejana.radio_m'
(zonas.json) pero FUERA de la zona detallada, y calcula la altura de cada edificio con el modelo
Copernicus (superficie − suelo). Además aplana el relieve de fondo en las áreas urbanas: el modelo
de superficie trae los edificios "derretidos" como bultos y los nuevos quedarían enterrados.

Salidas en datos/<ciudad>/<zona>/terreno/:
    ciudad_lejana.json   [[x, y, z_suelo, altura, [[x, y], ...]], ...] en metros locales
    fondo_altura.npy     relieve de fondo con suelo (no superficie) en zonas urbanas
    fondo_altura_dsm.npy copia del relieve original (solo se crea la primera vez)
"""

import argparse
import gzip
import importlib.util
import json
import random
import sys
from pathlib import Path

import numpy as np

from comun import bbox_geo, cargar_zona, carpeta_zona, mosaicos_microsoft, transformadores

_spec = importlib.util.spec_from_file_location("dem", Path(__file__).with_name("02_descargar_dem.py"))
dem_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dem_mod)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zona")
    args = ap.parse_args()

    import rasterio
    from PIL import Image, ImageDraw
    from rasterio.merge import merge

    zona = cargar_zona(args.zona)
    cfg = zona.get("ciudad_lejana", {"radio_m": 7000, "area_min_m2": 60})
    R = cfg["radio_m"]
    carpeta = carpeta_zona(zona) / "terreno"
    with open(carpeta / "meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    z_origen = meta["z_origen_msnm"]
    mitad_zona = meta["extension_local"][2]
    a_local, a_geo = transformadores(zona)
    rnd = random.Random(9)

    # --- suelo (DTM) y superficie (DSM) a 30 m sobre el área
    sur, oeste, norte, este = bbox_geo(zona, margen_m=R - zona["tamano_m"] / 2 + 600)
    fuentes = [rasterio.open(r) for r in dem_mod.descargar_tiles(sur, oeste, norte, este)]
    dsm, transf = merge(fuentes, bounds=(oeste, sur, este, norte))
    for f in fuentes:
        f.close()
    dsm = np.nan_to_num(dsm[0].astype(np.float32), nan=0.0)
    k = int(zona.get("filtro_dsm_px", 5)) | 1
    dtm = dem_mod.filtro_ventana(dem_mod.filtro_ventana(dsm, k, np.min), k, np.max)
    dtm = dem_mod.desenfoque_caja(dem_mod.desenfoque_caja(dtm, k // 2), k // 2)
    filas, cols = dsm.shape

    def pixel(lon, lat):
        return int((lat - transf.f) / transf.e), int((lon - transf.c) / transf.a)

    # --- edificios de Microsoft en el anillo alrededor de la zona
    edificios = []
    for ruta in mosaicos_microsoft(sur, oeste, norte, este):
        with gzip.open(ruta, "rt", encoding="utf-8") as fh:
            for linea in fh:
                feat = json.loads(linea)
                if feat["geometry"]["type"] != "Polygon":
                    continue
                anillo_geo = feat["geometry"]["coordinates"][0]
                lon0, lat0 = anillo_geo[0]
                if not (oeste < lon0 < este and sur < lat0 < norte):
                    continue
                x0, y0 = a_local.transform(lon0, lat0)
                if abs(x0) > R or abs(y0) > R or (abs(x0) < mitad_zona + 30 and abs(y0) < mitad_zona + 30):
                    continue
                xs, ys = a_local.transform([p[0] for p in anillo_geo[:-1]], [p[1] for p in anillo_geo[:-1]])
                anillo = [(round(x, 1), round(y, 1)) for x, y in zip(xs, ys)]
                firmada = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1])) / 2
                if abs(firmada) < cfg.get("area_min_m2", 60):
                    continue
                if firmada < 0:
                    anillo = anillo[::-1]
                # altura: superficie − suelo en el centro y en los vértices
                lons = [p[0] for p in anillo_geo]
                lats = [p[1] for p in anillo_geo]
                muestras = [(sum(lons) / len(lons), sum(lats) / len(lats))] + list(zip(lons, lats))
                difs, suelos = [], []
                for lon, lat in muestras:
                    fi, co = pixel(lon, lat)
                    if 0 <= fi < filas and 0 <= co < cols:
                        difs.append(dsm[fi, co] - dtm[fi, co])
                        suelos.append(dtm[fi, co])
                if not difs:
                    continue
                h = float(np.percentile(difs, 75))
                if h < 3.0:  # el modelo no lo distingue: casa o edificio bajo
                    h = rnd.choice([3.5, 4.0, 6.5, 7.0, 9.5]) if abs(firmada) < 400 else rnd.uniform(7, 13)
                h = min(h, 160.0)
                z = float(min(suelos)) - z_origen
                edificios.append([round(x0, 1), round(y0, 1), round(z, 1), round(h, 1), anillo])
    with open(carpeta / "ciudad_lejana.json", "w", encoding="utf-8") as f:
        json.dump(edificios, f, separators=(",", ":"))
    print(f"  ciudad_lejana.json: {len(edificios)} edificios entre la zona y {R / 1000:.0f} km")

    # --- relieve de fondo: suelo en vez de superficie donde hay ciudad
    ruta_fondo = carpeta / "fondo_altura.npy"
    if not ruta_fondo.exists():
        print("  (no hay relieve de fondo: corre el paso 02 con 'fondo' en zonas.json)")
        return
    respaldo = carpeta / "fondo_altura_dsm.npy"
    if not respaldo.exists():
        np.save(respaldo, np.load(ruta_fondo))
    fondo = np.load(respaldo)
    with open(carpeta / "fondo_meta.json", encoding="utf-8") as f:
        fmeta = json.load(f)
    n, res = fondo.shape[0], fmeta["resolucion_m"]
    xmin, _, _, ymax = fmeta["extension_local"]
    mascara = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(mascara)
    for x, y, _, _, anillo in edificios:
        d.polygon([((p[0] - xmin) / res, (ymax - p[1]) / res) for p in anillo], fill=255)
    urbano = np.array(mascara) > 0
    urbano = dem_mod.filtro_ventana(urbano.astype(np.float32), 3, np.max) > 0  # un poco de margen
    X, Y = np.meshgrid(xmin + np.arange(n) * res, ymax - np.arange(n) * res)
    lon, lat = a_geo.transform(X.ravel(), Y.ravel())
    c = (np.asarray(lon) - transf.c) / transf.a - 0.5
    fi = (np.asarray(lat) - transf.f) / transf.e - 0.5
    dentro = (c >= 0) & (c < cols - 1) & (fi >= 0) & (fi < filas - 1)
    suelo = np.full(n * n, np.nan, np.float32)
    suelo[dentro] = dem_mod.bilineal(dtm, fi[dentro], c[dentro])
    suelo = suelo.reshape(n, n) - z_origen
    nuevo = np.where(urbano & ~np.isnan(suelo), np.minimum(fondo, suelo), fondo)
    np.save(ruta_fondo, nuevo.astype(np.float32))
    print(f"  fondo_altura.npy: suelo urbano aplanado en {urbano.mean() * 100:.0f} % del fondo")


if __name__ == "__main__":
    sys.exit(main())
