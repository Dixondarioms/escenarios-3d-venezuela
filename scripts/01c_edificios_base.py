"""Edificios de una base militar que no aparecen en OSM ni en Microsoft Building Footprints.

Uso:
    .venv\\Scripts\\python scripts\\01c_edificios_base.py libertador

1. Estructuras altas: en el modelo de superficie Copernicus (DSM, 30 m remuestreado a 10 m) se resta el suelo
   (apertura morfológica) y se buscan manchas de más de 4 m de alto dentro del aeródromo que no sean árboles
   (NDVI bajo). Cada mancha se vuelve un rectángulo alineado con la pista: los grandes junto a la plataforma son
   hangares y el resto edificios militares bajos. Es aproximado (30 m de resolución), pero en su lugar real.
2. Relleno: edificios de 1-2 pisos a lo largo de las calles internas de la base (cuarteles, oficinas, talleres),
   sin pisar pistas, rodajes, plataforma ni las estructuras del punto 1.
Se agregan a osm_local.json con "fuente" para poder distinguirlos y se pueden corregir a mano en
scripts/config/zonas.json → "hitos" (por id "dsm_N" / "base_N").
"""

import json
import math
import random
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFilter
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import RAIZ, cargar_zona, carpeta_zona, proj_local  # noqa: E402

RES = 10.0


def dentro(x, y, pol):
    c = False
    for (x1, y1), (x2, y2) in zip(pol, pol[1:] + pol[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def rect(cx, cy, largo, ancho, ang):
    """Rectángulo antihorario centrado, con el lado largo a 'ang' radianes del Este."""
    u = (math.cos(ang), math.sin(ang))
    v = (-u[1], u[0])
    h, w = largo / 2, ancho / 2
    return [(round(cx + u[0] * a * h + v[0] * b * w, 2), round(cy + u[1] * a * h + v[1] * b * w, 2))
            for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def estructuras_dsm(zona, carpeta, aero, mascara_libre):
    m = zona["tamano_m"] / 2
    n = int(2 * m / RES)
    tiles = sorted((RAIZ / "datos" / "_dem_cache").glob("Copernicus_DSM_*.tif"))
    dsm = np.full((n, n), np.nan, np.float32)
    for t in tiles:
        tmp = np.full((n, n), np.nan, np.float32)
        with rasterio.open(t) as src:
            reproject(rasterio.band(src, 1), tmp, dst_transform=from_origin(-m, m, RES, RES), dst_crs=proj_local(zona),
                      resampling=Resampling.bilinear, dst_nodata=np.nan)
        dsm = np.where(np.isnan(dsm), tmp, dsm)
    dsm = np.nan_to_num(dsm, nan=float(np.nanmedian(dsm)))
    im = Image.fromarray(dsm, "F")
    suelo = np.array(im.filter(ImageFilter.MinFilter(15)).filter(ImageFilter.MaxFilter(15)))
    alto = dsm - suelo
    base = Image.new("L", (n, n), 0)
    ImageDraw.Draw(base).polygon([((x + m) / RES, (m - y) / RES) for x, y in aero], fill=1)
    base = np.array(base) > 0
    ndvi = np.array(Image.open(carpeta / "terreno" / "ndvi_zona.png").convert("L").resize((n, n))) / 255.0
    candidato = (alto > 4.0) & base & (ndvi < 0.45)
    visto = np.zeros((n, n), bool)
    manchas = []
    for f0 in range(n):
        for c0 in range(n):
            if not candidato[f0, c0] or visto[f0, c0]:
                continue
            pila, pts = [(f0, c0)], []
            visto[f0, c0] = True
            while pila:
                f, c = pila.pop()
                pts.append((f, c))
                for df, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    g, k = f + df, c + dc
                    if 0 <= g < n and 0 <= k < n and candidato[g, k] and not visto[g, k]:
                        visto[g, k] = True
                        pila.append((g, k))
            if len(pts) * RES * RES < 300:
                continue
            xs = np.array([-m + (c + 0.5) * RES for _, c in pts])
            ys = np.array([m - (f + 0.5) * RES for f, _ in pts])
            manchas.append({"x": xs, "y": ys, "alto": float(np.percentile([alto[p] for p in pts], 75)),
                            "area": len(pts) * RES * RES})
    return manchas


def main():
    zona = cargar_zona(sys.argv[1])
    carpeta = carpeta_zona(zona)
    ruta = carpeta / "osm_local.json"
    osm = json.load(open(ruta, encoding="utf-8"))
    osm["edificios"] = [e for e in osm["edificios"] if e.get("fuente") not in ("DSM Copernicus", "relleno base")]
    aero = [a["exterior"] for a in osm["areas"] if a["tipo"] == "aerodromo"]
    if not aero:
        raise SystemExit("La zona no tiene aeródromo en OSM")
    aero = max(aero, key=len)
    pista = max((a for a in osm["aerovias"] if a["tipo"] == "runway"), key=lambda a: len(a["puntos"]))
    (x0, y0), (x1, y1) = pista["puntos"][0], pista["puntos"][-1]
    ang = math.atan2(y1 - y0, x1 - x0)
    plataformas = [a["exterior"] for a in osm["areas"] if a["tipo"] == "plataforma"]
    rnd = random.Random(12)

    # zonas prohibidas (pavimentos del aeródromo y calles) en una máscara de 2 m
    m = zona["tamano_m"] / 2
    R2 = 2.0
    n2 = int(2 * m / R2)
    libre = Image.new("L", (n2, n2), 0)
    dr = ImageDraw.Draw(libre)

    def px(p):
        return ((p[0] + m) / R2, (m - p[1]) / R2)
    for a in plataformas:
        dr.polygon([px(p) for p in a], fill=255)
    for a in osm["aerovias"]:
        dr.line([px(p) for p in a["puntos"]], fill=255, width=int((a["ancho"] + 30) / R2))
    for v in osm["vias"]:
        dr.line([px(p) for p in v["puntos"]], fill=255, width=max(2, int((v["ancho"] + 4) / R2)))

    nuevos = []

    def choca(anillo):
        xs = [p[0] for p in anillo]
        ys = [p[1] for p in anillo]
        c0, c1 = int((min(xs) + m) / R2), int((max(xs) + m) / R2) + 1
        f0, f1 = int((m - max(ys)) / R2), int((m - min(ys)) / R2) + 1
        if c0 < 0 or f0 < 0 or c1 >= n2 or f1 >= n2:
            return True
        sub = libre.crop((c0, f0, c1, f1))
        prueba = Image.new("L", sub.size, 0)
        ImageDraw.Draw(prueba).polygon([((x + m) / R2 - c0, (m - y) / R2 - f0) for x, y in anillo], fill=255)
        return np.any((np.array(sub) > 0) & (np.array(prueba) > 0))

    def agregar(anillo, alto, tipo, fuente, i):
        a = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]))) / 2
        nuevos.append({"id": f"{'dsm' if fuente.startswith('DSM') else 'base'}_{i}", "tipo": tipo, "nombre": None,
                       "altura": round(alto, 1), "niveles": max(1, round(alto / 3.3)), "altura_estimada": False,
                       "exterior": anillo, "huecos": [], "area": round(a, 1), "fuente": fuente})
        ImageDraw.Draw(libre).polygon([px(p) for p in rect_ampliado(anillo, 6)], fill=255)

    def rect_ampliado(anillo, d):
        cx = sum(p[0] for p in anillo) / 4
        cy = sum(p[1] for p in anillo) / 4
        return [(cx + (x - cx) * (1 + d / max(1.0, math.dist((x, y), (cx, cy)))),
                 cy + (y - cy) * (1 + d / max(1.0, math.dist((x, y), (cx, cy))))) for x, y in anillo]

    # 1) estructuras del DSM
    manchas = estructuras_dsm(zona, carpeta, aero, libre)
    u = (math.cos(ang), math.sin(ang))
    v = (-u[1], u[0])
    for i, mch in enumerate(sorted(manchas, key=lambda q: -q["area"])):
        cx, cy = float(mch["x"].mean()), float(mch["y"].mean())
        pu = (mch["x"] - cx) * u[0] + (mch["y"] - cy) * u[1]
        pv = (mch["x"] - cx) * v[0] + (mch["y"] - cy) * v[1]
        largo = max(float(pu.max() - pu.min()) + RES, 20.0)
        ancho = max(float(pv.max() - pv.min()) + RES, 15.0)
        f = math.sqrt(mch["area"] * 0.85 / (largo * ancho))  # las manchas del DSM salen infladas
        largo, ancho = largo * min(f, 1.0), ancho * min(f, 1.0)
        junto_plataforma = any(dentro(cx, cy + d, p) or dentro(cx, cy - d, p) for p in plataformas for d in (0, 60))
        grande = mch["area"] > 1800
        tipo = "hangar" if grande and junto_plataforma else ("hangar" if mch["area"] > 4000 else "military")
        alto = min(max(mch["alto"] * 1.25, 6.0), 16.0) if tipo == "hangar" else min(max(mch["alto"], 4.0), 10.0)
        anillo = rect(cx, cy, largo, ancho, ang)
        agregar(anillo, alto, tipo, "DSM Copernicus", i)
    n_dsm = len(nuevos)

    # 2) relleno a lo largo de las calles internas de la base
    k = 0
    for via in osm["vias"]:
        if via["tipo"] in ("footway", "path", "steps", "track", "motorway", "trunk"):
            continue
        pts = via["puntos"]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            L = math.dist((ax, ay), (bx, by))
            if L < 20:
                continue
            d = ((bx - ax) / L, (by - ay) / L)
            nrm = (-d[1], d[0])
            s = rnd.uniform(5, 25)
            while s < L - 10:
                for lado in (1, -1):
                    if rnd.random() < 0.35:
                        continue
                    largo = rnd.choice([18, 24, 30, 36, 45])
                    ancho = rnd.choice([9, 10, 12, 14])
                    sep = via["ancho"] / 2 + 8 + ancho / 2
                    cx = ax + d[0] * s + nrm[0] * sep * lado
                    cy = ay + d[1] * s + nrm[1] * sep * lado
                    if not dentro(cx, cy, aero):
                        continue
                    anillo = rect(cx, cy, largo, ancho, math.atan2(d[1], d[0]))
                    if choca(anillo):
                        continue
                    alto = rnd.choice([3.6, 4.0, 4.5, 7.0, 7.5])
                    agregar(anillo, alto, "military", "relleno base", k)
                    k += 1
                s += rnd.uniform(40, 70)
    osm["edificios"] += nuevos
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(osm, f, ensure_ascii=False)
    print(f"Agregados {n_dsm} edificios del DSM (hangares: {sum(1 for e in nuevos if e['tipo'] == 'hangar')}) "
          f"y {len(nuevos) - n_dsm} de relleno a lo largo de las calles de la base -> {ruta}")


if __name__ == "__main__":
    main()
