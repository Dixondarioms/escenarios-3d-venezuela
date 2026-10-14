"""Plan de paradas para revisar fachadas (Street View o fotos propias) alrededor de una zona.

Uso:
    .venv\\Scripts\\python scripts\\sv_plan.py lacarlota "Avenida Río de Janeiro" "Avenida Araure" ...

Para cada calle, agrupa los edificios cercanos (fuera del aeródromo, de 3+ pisos) en paradas cada ~60 m.
Cada parada trae: lat/lon en la calle, rumbo de la cámara hacia los edificios y la lista de edificios
(id de OSM / Microsoft) ordenados de izquierda a derecha en la imagen, para anotar su fachada en
scripts/config/fachadas_<zona>.json.
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import cargar_zona, carpeta_zona, transformadores  # noqa: E402


def dentro(x, y, pol):
    c = False
    for (x1, y1), (x2, y2) in zip(pol, pol[1:] + pol[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def proyectar(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy or 1.0
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    q = (a[0] + dx * t, a[1] + dy * t)
    return math.dist(p, q), q


def main():
    zona = cargar_zona(sys.argv[1])
    calles = sys.argv[2:]
    osm = json.load(open(carpeta_zona(zona) / "osm_local.json", encoding="utf-8"))
    _, a_geo = transformadores(zona)
    aero = [a["exterior"] for a in osm["areas"] if a["tipo"] == "aerodromo"]
    paradas = []
    for calle in calles:
        segs = [(a, b) for v in osm["vias"] if v.get("nombre") == calle for a, b in zip(v["puntos"], v["puntos"][1:])]
        if not segs:
            print(f"(sin datos para {calle})")
            continue
        eds = []
        for e in osm["edificios"]:
            ext = e["exterior"]
            c = (sum(p[0] for p in ext) / len(ext), sum(p[1] for p in ext) / len(ext))
            if any(dentro(*c, a) for a in aero) or e["altura"] < 9:
                continue
            d, q = min(proyectar(c, a, b) for a, b in segs)
            if d < 45:
                eds.append((q, c, e))
        # ordenar a lo largo de la calle (por proyección sobre el primer segmento largo) y agrupar cada 60 m
        a0, b0 = max(segs, key=lambda s: math.dist(*s))
        ux, uy = (b0[0] - a0[0]) / math.dist(a0, b0), (b0[1] - a0[1]) / math.dist(a0, b0)
        eds.sort(key=lambda t: t[0][0] * ux + t[0][1] * uy)
        grupo = []
        for item in eds + [None]:
            if item is not None and (not grupo or math.dist(item[0], grupo[0][0]) < 60):
                grupo.append(item)
                continue
            if grupo:
                qx = sum(g[0][0] for g in grupo) / len(grupo)
                qy = sum(g[0][1] for g in grupo) / len(grupo)
                cx = sum(g[1][0] for g in grupo) / len(grupo)
                cy = sum(g[1][1] for g in grupo) / len(grupo)
                rumbo = math.degrees(math.atan2(cx - qx, cy - qy)) % 360  # desde el norte, sentido horario
                orden = sorted(grupo, key=lambda g: ((math.degrees(math.atan2(g[1][0] - qx, g[1][1] - qy)) - rumbo + 540) % 360) - 180)
                lon, lat = a_geo.transform(qx, qy)
                paradas.append({
                    "calle": calle, "lat": round(lat, 6), "lon": round(lon, 6), "rumbo": round(rumbo),
                    "local": [round(qx, 1), round(qy, 1)],
                    "edificios": [{"id": g[2]["id"], "nombre": g[2].get("nombre"), "altura": g[2]["altura"],
                                   "angulo": round(((math.degrees(math.atan2(g[1][0] - qx, g[1][1] - qy)) - rumbo + 540) % 360) - 180)}
                                  for g in orden],
                })
            grupo = [item] if item is not None else []
    print(json.dumps(paradas, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
