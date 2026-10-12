"""Paso 01b: completa los edificios que faltan en OpenStreetMap con Microsoft Global ML Building Footprints.

Uso (después del paso 01; si vuelves a correr 01, repite 01b):
    python scripts/01b_edificios_microsoft.py lacarlota

Fuente: https://github.com/microsoft/GlobalMLBuildingFootprints (licencia CDLA Permissive 2.0).
Huellas detectadas con IA en imágenes satelitales. Se agregan a osm_local.json solo las que:
  * caen dentro de la zona,
  * no se solapan con un edificio de OSM (OSM manda: suele ser más preciso y trae nombres/alturas),
  * no están sobre calles, pistas, plataformas, plazas ni agua (falsos positivos).
La altura viene del dato de Microsoft si existe; si no, se estima por el tamaño de la huella.
Los mosaicos descargados quedan en datos/_ms_cache.
"""

import argparse
import gzip
import json
import random
import sys

import numpy as np

from comun import bbox_geo, cargar_zona, carpeta_zona, extension_local, mosaicos_microsoft, transformadores


def mosaicos(zona):
    return mosaicos_microsoft(*bbox_geo(zona))


def mascara_ocupada(osm, mitad, res=1.0):
    """1 m: edificios OSM + calles + áreas pavimentadas/agua. Devuelve (edificios, superficies)."""
    from PIL import Image, ImageDraw
    n = int(round(2 * mitad / res))
    edif = Image.new("L", (n, n), 0)
    sup = Image.new("L", (n, n), 0)
    de, ds = ImageDraw.Draw(edif), ImageDraw.Draw(sup)

    def px(p):
        return ((p[0] + mitad) / res, (mitad - p[1]) / res)
    for e in osm["edificios"]:
        de.polygon([px(p) for p in e["exterior"]], fill=255)
    for a in osm["areas"]:
        if a["tipo"] in ("agua", "plaza", "plataforma", "estacionamiento", "cancha"):
            ds.polygon([px(p) for p in a["exterior"]], fill=255)
    for v in osm["vias"]:
        if not v["tunel"] and v["tipo"] not in ("footway", "path", "steps"):
            ds.line([px(p) for p in v["puntos"]], fill=255, width=max(1, int(v["ancho"] / res)))
    for a in osm.get("aerovias", []):
        ds.line([px(p) for p in a["puntos"]], fill=255, width=max(1, int(a["ancho"] / res)))
    return np.array(edif) > 0, np.array(sup) > 0


def area(anillo):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]))) / 2


def altura_estimada(area_m2, rnd):
    if area_m2 < 100:
        niveles = rnd.choice([1, 2, 2, 3])
    elif area_m2 < 300:
        niveles = rnd.randint(2, 4)
    elif area_m2 < 900:
        niveles = rnd.randint(3, 8)
    else:
        niveles = rnd.randint(5, 14)
    return niveles * 3.0 + 1.0, niveles


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zona")
    args = ap.parse_args()
    zona = cargar_zona(args.zona)
    carpeta = carpeta_zona(zona)
    ruta_osm = carpeta / "osm_local.json"
    with open(ruta_osm, encoding="utf-8") as f:
        osm = json.load(f)
    osm["edificios"] = [e for e in osm["edificios"] if not e["id"].startswith("ms")]  # idempotente

    a_local, _ = transformadores(zona)
    xmin, ymin, xmax, ymax = extension_local(zona)
    mitad = xmax
    edif, sup = mascara_ocupada(osm, mitad)
    n = edif.shape[0]
    rnd = random.Random(3)
    nuevos, descartados = [], {"osm": 0, "superficie": 0, "pequeño": 0}

    for ruta in mosaicos(zona):
        with gzip.open(ruta, "rt", encoding="utf-8") as f:
            for linea in f:
                feat = json.loads(linea)
                geom = feat["geometry"]
                if geom["type"] != "Polygon":
                    continue
                anillo_geo = geom["coordinates"][0]
                lon0, lat0 = anillo_geo[0]
                x0, y0 = a_local.transform(lon0, lat0)
                if not (xmin < x0 < xmax and ymin < y0 < ymax):
                    continue
                xs, ys = a_local.transform([p[0] for p in anillo_geo], [p[1] for p in anillo_geo])
                anillo = [(round(x, 2), round(y, 2)) for x, y in zip(xs, ys)]
                if anillo[0] == anillo[-1]:
                    anillo = anillo[:-1]
                a = area(anillo)
                if a < 25:
                    descartados["pequeño"] += 1
                    continue
                # muestreo de puntos interiores aproximados (vértices contraídos hacia el centroide)
                cx = sum(p[0] for p in anillo) / len(anillo)
                cy = sum(p[1] for p in anillo) / len(anillo)
                muestras = [(cx, cy)] + [(cx + (x - cx) * 0.6, cy + (y - cy) * 0.6) for x, y in anillo]
                idx = [(int(mitad - y), int(x + mitad)) for x, y in muestras]
                idx = [(f_, c_) for f_, c_ in idx if 0 <= f_ < n and 0 <= c_ < n]
                if not idx:
                    continue
                if sum(edif[f_, c_] for f_, c_ in idx) / len(idx) > 0.25:
                    descartados["osm"] += 1
                    continue
                if sum(sup[f_, c_] for f_, c_ in idx) / len(idx) > 0.4:
                    descartados["superficie"] += 1
                    continue
                firmada = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]))
                if firmada < 0:  # el paso 03 espera anillos exteriores antihorarios
                    anillo = anillo[::-1]
                h_ms = feat.get("properties", {}).get("height", -1) or -1
                if h_ms and h_ms > 2:
                    altura, niveles, estimada = float(h_ms), max(1, round(h_ms / 3)), False
                else:
                    altura, niveles = altura_estimada(a, rnd)
                    estimada = True
                nuevos.append({"id": f"ms{len(nuevos)}", "tipo": "yes", "nombre": None, "altura": round(altura, 1),
                               "altura_original": round(altura, 1),
                               "niveles": niveles, "altura_estimada": estimada, "altura_minima": 0.0,
                               "techo_color": None, "fachada_color": None, "exterior": anillo, "huecos": [],
                               "area": round(a, 1), "fuente": "Microsoft Global ML Building Footprints"})

    osm["edificios"] += nuevos
    osm["atribucion"] = ("© OpenStreetMap contributors (ODbL); "
                         "edificios adicionales: Microsoft Global ML Building Footprints (CDLA Permissive 2.0)")
    with open(ruta_osm, "w", encoding="utf-8") as f:
        json.dump(osm, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  Agregados {len(nuevos)} edificios de Microsoft (descartados: {descartados['osm']} ya en OSM, "
          f"{descartados['superficie']} sobre calles/plazas, {descartados['pequeño']} muy pequeños)")
    print(f"  Total de edificios en la zona: {len(osm['edificios'])}")


if __name__ == "__main__":
    sys.exit(main())
