"""Paso 02: descarga el relieve (Copernicus DEM GLO-30) y genera el terreno de la zona.

Uso:
    python scripts/02_descargar_dem.py altamira

Salidas en datos/<ciudad>/<zona>/terreno/:
    altura_local.npy     rejilla float32 (filas de Norte a Sur, columnas de Oeste a Este),
                         alturas en metros relativas al terreno en el centro de la zona
    meta.json            extensión, resolución, altura del origen y datos para Unreal
    heightmap_ue.png     heightmap 16-bit para importar como Landscape en Unreal
    vista_relieve.png    sombreado del relieve para revisar a ojo

Notas:
  * Copernicus GLO-30 es un modelo de SUPERFICIE (incluye edificios y árboles). Dentro de la
    ciudad se aplica una "apertura" morfológica que elimina bultos más angostos que
    filtro_dsm_px * 30 m, y luego un suavizado, para aproximar el suelo real.
  * Alturas ortométricas (EGM2008). Para Cesium se calcula la ondulación del geoide si pyproj
    puede descargar la rejilla EGM2008; si no, se usa 'ondulacion_geoide_m' de zonas.json.
"""

import argparse
import json
import math
import sys

import numpy as np
import requests

from comun import RAIZ, bbox_geo, cargar_zona, carpeta_zona, transformadores

URL_DEM = ("https://copernicus-dem-30m.s3.amazonaws.com/"
           "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
           "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif")


def nombre_tile(lat, lon):
    return URL_DEM.format(ns="N" if lat >= 0 else "S", lat=abs(lat), ew="E" if lon >= 0 else "W", lon=abs(lon))


def descargar_tiles(sur, oeste, norte, este):
    cache = RAIZ / "datos" / "_dem_cache"
    cache.mkdir(parents=True, exist_ok=True)
    rutas = []
    for lat in range(math.floor(sur), math.floor(norte) + 1):
        for lon in range(math.floor(oeste), math.floor(este) + 1):
            url = nombre_tile(lat, lon)
            ruta = cache / url.rsplit("/", 1)[1]
            if not ruta.exists():
                print(f"  Descargando {ruta.name} ...")
                with requests.get(url, stream=True, timeout=120) as r:
                    if r.status_code == 404:
                        print("    (no existe: probablemente es mar)")
                        continue
                    r.raise_for_status()
                    tmp = ruta.with_suffix(".part")
                    with open(tmp, "wb") as f:
                        for bloque in r.iter_content(1 << 20):
                            f.write(bloque)
                    tmp.replace(ruta)
            rutas.append(ruta)
    if not rutas:
        raise SystemExit("No hay tiles de relieve para esta zona.")
    return rutas


def filtro_ventana(a, k, func):
    """Mínimo/máximo en ventana k×k (k impar) con bordes replicados."""
    r = k // 2
    p = np.pad(a, r, mode="edge")
    v = np.lib.stride_tricks.sliding_window_view(p, (k, k))
    return func(v, axis=(-2, -1))


def desenfoque_caja(a, radio):
    """Desenfoque de caja separable (dos pasadas ≈ gaussiano)."""
    if radio < 1:
        return a
    k = 2 * radio + 1
    for eje in (0, 1):
        p = np.pad(a, [(radio, radio) if e == eje else (0, 0) for e in (0, 1)], mode="edge")
        c = np.cumsum(p, axis=eje, dtype=np.float64)
        c = np.concatenate([np.zeros_like(np.take(c, [0], axis=eje)), c], axis=eje)
        a = (np.take(c, range(k, c.shape[eje]), axis=eje) - np.take(c, range(0, c.shape[eje] - k), axis=eje)) / k
    return a.astype(np.float32)


def bilineal(img, filas, cols):
    filas = np.clip(filas, 0, img.shape[0] - 1.001)
    cols = np.clip(cols, 0, img.shape[1] - 1.001)
    f0, c0 = np.floor(filas).astype(int), np.floor(cols).astype(int)
    df, dc = filas - f0, cols - c0
    return (img[f0, c0] * (1 - df) * (1 - dc) + img[f0, c0 + 1] * (1 - df) * dc
            + img[f0 + 1, c0] * df * (1 - dc) + img[f0 + 1, c0 + 1] * df * dc)


def ondulacion_geoide(lat, lon, alt):
    """N = h_elipsoidal - H_ortométrica (EGM2008). None si no se puede calcular."""
    try:
        import pyproj
        from pyproj import Transformer
        pyproj.network.set_network_enabled(True)
        t = Transformer.from_crs("EPSG:4326+3855", "EPSG:4979", always_xy=True)
        _, _, h = t.transform(lon, lat, alt)
        if not math.isfinite(h) or abs(h - alt) < 1e-6:
            return None
        return h - alt
    except Exception as e:  # noqa: BLE001 - cualquier fallo de PROJ/red cae al valor manual
        print(f"  (no se pudo calcular la ondulación del geoide: {e})")
        return None


def ajustar_alturas(ruta_osm, sobre_suelo, res, mitad):
    """Mejora las alturas ESTIMADAS de los edificios con la altura de la superficie sobre el suelo
    (modelo Copernicus, 30 m). Pesa más en edificios grandes, donde ese modelo es más fiable.
    Siempre parte de la estimación original, así que se puede correr varias veces."""
    if not ruta_osm.exists():
        return
    with open(ruta_osm, encoding="utf-8") as f:
        osm = json.load(f)
    n = sobre_suelo.shape[0]
    ajustados = 0
    for e in osm["edificios"]:
        if not e.get("altura_estimada") or e["area"] < 300 or e["tipo"] in ("obelisk", "control_tower"):
            continue
        base = e.setdefault("altura_original", e["altura"])
        ext = e["exterior"]
        cx = sum(p[0] for p in ext) / len(ext)
        cy = sum(p[1] for p in ext) / len(ext)
        muestras = [(cx, cy)] + [(cx + (x - cx) * f, cy + (y - cy) * f) for x, y in ext for f in (0.3, 0.6)]
        valores = []
        for x, y in muestras:
            fi, co = int(round((mitad - y) / res)), int(round((x + mitad) / res))
            if 0 <= fi < n and 0 <= co < n:
                valores.append(float(sobre_suelo[fi, co]))
        if not valores:
            continue
        h_dsm = float(np.percentile(valores, 75))
        if h_dsm < 3.0:
            continue  # el modelo no "ve" el edificio (bajo o más pequeño que un píxel)
        peso = 0.85 if e["area"] >= 1500 else 0.6 if e["area"] >= 600 else 0.35
        h = peso * min(h_dsm, 200.0) + (1 - peso) * base
        e["altura"] = round(max(h, 3.5), 1)
        e["niveles"] = max(1, int(round((e["altura"] - 1.0) / 3.0)))
        e["altura_fuente"] = "superficie Copernicus"
        ajustados += 1
    with open(ruta_osm, "w", encoding="utf-8") as f:
        json.dump(osm, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  Alturas ajustadas con el modelo de superficie: {ajustados} edificios estimados")


def sombreado(alturas, res):
    gy, gx = np.gradient(alturas, res)
    pendiente = np.arctan(np.hypot(gx, gy))
    aspecto = np.arctan2(-gx, gy)
    az, el = math.radians(315), math.radians(45)
    s = np.sin(el) * np.cos(pendiente) + np.cos(el) * np.sin(pendiente) * np.cos(az - aspecto)
    return (np.clip(s, 0, 1) * 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zona")
    args = ap.parse_args()

    import rasterio
    from rasterio.merge import merge
    from PIL import Image

    zona = cargar_zona(args.zona)
    salida = carpeta_zona(zona) / "terreno"
    salida.mkdir(exist_ok=True)

    def leer_dem(margen_m):
        sur, oeste, norte, este = bbox_geo(zona, margen_m=margen_m)
        fuentes = [rasterio.open(r) for r in descargar_tiles(sur, oeste, norte, este)]
        dem, transf = merge(fuentes, bounds=(oeste, sur, este, norte))
        nodata = fuentes[0].nodata
        for f in fuentes:
            f.close()
        dem = dem[0].astype(np.float32)
        if nodata is not None:
            dem[dem == nodata] = np.nan
        if np.isnan(dem).any():
            dem = np.where(np.isnan(dem), 0.0, dem)  # sin dato = mar
        return dem, transf

    _, a_geo = transformadores(zona)

    def muestrear(dem, transf, n, res):
        mitad = (n - 1) * res / 2.0
        X, Y = np.meshgrid(-mitad + np.arange(n) * res, mitad - np.arange(n) * res)
        lon, lat = a_geo.transform(X.ravel(), Y.ravel())
        cols = (np.asarray(lon) - transf.c) / transf.a - 0.5
        filas = (np.asarray(lat) - transf.f) / transf.e - 0.5
        return bilineal(dem, filas, cols).reshape(n, n).astype(np.float32), mitad

    print(f"Relieve de '{zona['nombre']}'")
    dem, transf = leer_dem(zona["margen_dem_m"])
    print(f"  Recorte DEM: {dem.shape[1]}x{dem.shape[0]} px, {np.min(dem):.0f}–{np.max(dem):.0f} m s.n.m.")

    dem_superficie = dem.copy()  # con edificios y árboles: sirve para estimar alturas

    # Superficie -> aproximación de suelo
    k = int(zona.get("filtro_dsm_px", 0))
    if k >= 3:
        k += (k + 1) % 2
        dem = filtro_ventana(filtro_ventana(dem, k, np.min), k, np.max)
        # La apertura deja mesetas de k×k píxeles: se suavizan en la rejilla de 30 m.
        r = max(1, k // 2)
        dem = desenfoque_caja(desenfoque_caja(dem, r), r)

    # Rejilla local regular
    res = float(zona["resolucion_terreno_m"])
    n = int(round(zona["tamano_m"] / res)) + 1
    alturas, mitad = muestrear(dem, transf, n, res)

    radio = int(round(zona.get("suavizado_terreno_m", 0) / res / 2))
    alturas = desenfoque_caja(desenfoque_caja(alturas, radio), radio)

    z_origen = float(alturas[n // 2, n // 2])
    rel = alturas - z_origen
    np.save(salida / "altura_local.npy", rel)

    superficie, _ = muestrear(dem_superficie, transf, n, res)
    ajustar_alturas(carpeta_zona(zona) / "osm_local.json", superficie - alturas, res, mitad)

    # Heightmap 16-bit para Unreal: h = Zloc + (v - 32768) / 128 * ZScale / 100   (metros)
    hmin, hmax = float(rel.min()), float(rel.max())
    rango = (hmax - hmin) * 1.02 + 1.0
    escala_z = rango / 512.0 * 100.0
    z_centro = (hmax + hmin) / 2.0
    v = np.clip(np.round(32768 + (rel - z_centro) * 128.0 * 100.0 / escala_z), 0, 65535).astype(np.uint16)
    Image.fromarray(v).save(salida / "heightmap_ue.png")
    Image.fromarray(sombreado(rel, res)).save(salida / "vista_relieve.png")

    c = zona["centro"]
    N = ondulacion_geoide(c["lat"], c["lon"], z_origen)
    if N is None:
        N = zona.get("ondulacion_geoide_m")
    meta = {
        "zona": zona["id"], "centro": c, "resolucion_m": res, "pixeles": n,
        "extension_local": [-mitad, -mitad, mitad, mitad],
        "z_origen_msnm": round(z_origen, 2),
        "ondulacion_geoide_m": None if N is None else round(N, 2),
        "altura_elipsoidal_origen": None if N is None else round(z_origen + N, 2),
        "relativa_min_m": round(hmin, 2), "relativa_max_m": round(hmax, 2),
        "unreal_landscape": {
            "archivo": "heightmap_ue.png",
            "resolucion": f"{n} x {n}",
            "ubicacion_cm": [round(-mitad * 100, 1), round(-mitad * 100, 1), round(z_centro * 100, 1)],
            "escala": [res * 100, res * 100, round(escala_z, 4)],
        },
        "fuente": "Copernicus DEM GLO-30 © DLR e.V. 2010-2014 y © Airbus Defence and Space GmbH 2014-2018, "
                  "proporcionado bajo COPERNICUS por la Unión Europea y la ESA",
    }
    with open(salida / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"  Terreno: {n}x{n} a {res} m, altura del origen {z_origen:.1f} m s.n.m., "
          f"desnivel en la zona {hmin:+.1f} / {hmax:+.1f} m")
    if N is None:
        print("  AVISO: sin ondulación del geoide. Ajusta 'ondulacion_geoide_m' en zonas.json "
              "o la altura del CesiumGeoreference a mano (ver docs/02_flujo_de_trabajo.md).")
    else:
        print(f"  Ondulación del geoide: {N:+.2f} m  ->  altura elipsoidal del origen {z_origen + N:.2f} m")
    lu = meta["unreal_landscape"]
    print(f"  Unreal Landscape: ubicación {lu['ubicacion_cm']} cm, escala {lu['escala']}")

    # Relieve de fondo (montañas, valle y costa) para el horizonte de los renders
    fondo = zona.get("fondo")
    if fondo:
        dem_f, transf_f = leer_dem(fondo["radio_m"] + 500)
        res_f = float(fondo["resolucion_m"])
        n_f = int(round(2 * fondo["radio_m"] / res_f)) + 1
        alt_f, mitad_f = muestrear(dem_f, transf_f, n_f, res_f)
        np.save(salida / "fondo_altura.npy", alt_f - z_origen)
        with open(salida / "fondo_meta.json", "w", encoding="utf-8") as f:
            json.dump({"resolucion_m": res_f, "pixeles": n_f,
                       "extension_local": [-mitad_f, -mitad_f, mitad_f, mitad_f],
                       "max_msnm": round(float(alt_f.max()), 1)}, f, indent=2)
        Image.fromarray(sombreado(alt_f, res_f)).save(salida / "fondo_relieve.png")
        print(f"  Fondo: {n_f}x{n_f} a {res_f:.0f} m ({2 * mitad_f / 1000:.0f} km), "
              f"punto más alto {alt_f.max():.0f} m s.n.m.")
    print(f"Listo: {salida}")


if __name__ == "__main__":
    sys.exit(main())
