"""Paso 01: descarga datos de OpenStreetMap de una zona y los convierte a coordenadas locales.

Uso:
    python scripts/01_descargar_osm.py altamira
    python scripts/01_descargar_osm.py altamira --sin-descarga   (reprocesa osm_crudo.json)

Salidas en datos/<ciudad>/<zona>/:
    osm_crudo.json   respuesta original de Overpass (© OpenStreetMap contributors, ODbL)
    osm_local.json   edificios, vías, áreas y puntos en metros locales (X=Este, Y=Norte)
"""

import argparse
import json
import math
import random
import re
import sys
import time

import requests

from comun import bbox_geo, cargar_zona, carpeta_zona, extension_local, guardar_json, transformadores

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
CABECERAS = {"User-Agent": "EscenariosVenezuela/0.1 (pipeline 3D personal)", "Accept": "*/*"}

# Ancho (m) y carriles por defecto según el tipo de vía (si OSM no trae 'width'/'lanes').
VIAS = {
    "motorway": (3, 3.6), "motorway_link": (1, 4.5), "trunk": (4, 3.4), "trunk_link": (1, 4.5),
    "primary": (4, 3.3), "primary_link": (1, 4.5), "secondary": (2, 3.4), "secondary_link": (1, 4.5),
    "tertiary": (2, 3.3), "tertiary_link": (1, 4.5), "unclassified": (2, 3.0), "residential": (2, 3.0),
    "living_street": (1, 4.0), "service": (1, 4.0), "pedestrian": (1, 5.0), "footway": (1, 2.0),
    "path": (1, 1.5), "cycleway": (1, 2.0), "steps": (1, 2.0), "track": (1, 3.0),
}
VIAS_IGNORADAS = {"proposed", "construction", "platform", "raceway", "elevator", "corridor",
                  "services", "rest_area", "bus_stop", "abandoned", "razed"}

PUNTOS = {
    ("natural", "tree"): "arbol",
    ("highway", "traffic_signals"): "semaforo",
    ("highway", "street_lamp"): "farola",
    ("highway", "bus_stop"): "parada",
    ("highway", "crossing"): "cruce",
    ("man_made", "obelisk"): "obelisco",
    ("man_made", "tower"): "torre",
    ("railway", "subway_entrance"): "metro",
    ("amenity", "bench"): "banco",
    ("aeroway", "windsock"): "manga",
    ("aeroway", "helipad"): "helipuerto",
    ("aeroway", "parking_position"): "puesto_aeronave",
}
# Aviación: ancho por defecto (m) de pistas y calles de rodaje
AEROVIAS = {"runway": 30.0, "taxiway": 15.0, "taxilane": 10.0}


def consulta_overpass(sur, oeste, norte, este):
    b = f"{sur:.6f},{oeste:.6f},{norte:.6f},{este:.6f}"
    return f"""[out:json][timeout:180];
(
  way["building"]({b});
  relation["building"]["type"="multipolygon"]({b});
  way["highway"]({b});
  way["leisure"~"^(park|garden|playground|pitch)$"]({b});
  relation["leisure"="park"]({b});
  nwr["place"="square"]({b});
  relation["highway"="pedestrian"]({b});
  way["landuse"~"^(grass|recreation_ground)$"]({b});
  way["amenity"="parking"]({b});
  nwr["natural"="water"]({b});
  nwr["amenity"="fountain"]({b});
  way["barrier"~"^(hedge|wall|fence|retaining_wall)$"]({b});
  way["aeroway"~"^(runway|taxiway|taxilane|apron|helipad|aerodrome)$"]({b});
  relation["aeroway"~"^(aerodrome|apron)$"]({b});
  node["aeroway"~"^(windsock|helipad|parking_position)$"]({b});
  node["natural"="tree"]({b});
  node["highway"~"^(traffic_signals|street_lamp|bus_stop|crossing)$"]({b});
  nwr["man_made"~"^(obelisk|tower)$"]({b});
  node["railway"="subway_entrance"]({b});
  node["amenity"="bench"]({b});
);
out body geom;"""


def descargar(consulta):
    ultimo_error = None
    for intento in range(3):
        for url in SERVIDORES:
            try:
                print(f"  Consultando {url} (intento {intento + 1})...")
                r = requests.post(url, data={"data": consulta}, headers=CABECERAS, timeout=240)
                if r.status_code == 200:
                    return r.json()
                ultimo_error = f"HTTP {r.status_code}"
            except (requests.RequestException, ValueError) as e:
                ultimo_error = str(e)
            print(f"    falló: {ultimo_error}")
        time.sleep(10 * (intento + 1))
    raise SystemExit(f"No se pudo descargar de Overpass: {ultimo_error}")


# ---------------------------------------------------------------- geometría 2D

def area_firmada(anillo):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def orientar(anillo, antihorario):
    """Quita el punto de cierre repetido y orienta el anillo."""
    if len(anillo) > 1 and anillo[0] == anillo[-1]:
        anillo = anillo[:-1]
    if (area_firmada(anillo) > 0) != antihorario:
        anillo = anillo[::-1]
    return anillo


def unir_anillos(tramos):
    """Une tramos de vía (miembros de una relación) en anillos cerrados."""
    tramos = [list(t) for t in tramos if len(t) >= 2]
    anillos = []
    while tramos:
        actual = tramos.pop(0)
        cambio = True
        while actual[0] != actual[-1] and cambio:
            cambio = False
            for i, t in enumerate(tramos):
                if t[0] == actual[-1]:
                    actual += t[1:]
                elif t[-1] == actual[-1]:
                    actual += t[::-1][1:]
                elif t[-1] == actual[0]:
                    actual = t + actual[1:]
                elif t[0] == actual[0]:
                    actual = t[::-1] + actual[1:]
                else:
                    continue
                tramos.pop(i)
                cambio = True
                break
        if actual[0] == actual[-1] and len(actual) >= 4:
            anillos.append(actual)
    return anillos


def punto_en_poligono(x, y, anillo):
    dentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i]
        xj, yj = anillo[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def recortar_segmento(p, q, ext):
    """Liang-Barsky: devuelve (t0, t1) del segmento p->q dentro del rectángulo, o None."""
    xmin, ymin, xmax, ymax = ext
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, p[0] - xmin), (dx, xmax - p[0]), (-dy, p[1] - ymin), (dy, ymax - p[1])):
        if pk == 0:
            if qk < 0:
                return None
            continue
        t = qk / pk
        if pk < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return t0, t1


def recortar_polilinea(puntos, nodos, ext):
    """Corta una polilínea al rectángulo; devuelve lista de (puntos, nodos)."""
    if len(nodos) != len(puntos):
        nodos = [None] * len(puntos)
    piezas, pts, nds = [], [], []

    def cerrar():
        nonlocal pts, nds
        if len(pts) >= 2:
            piezas.append((pts, nds))
        pts, nds = [], []

    for i in range(len(puntos) - 1):
        p, q = puntos[i], puntos[i + 1]
        r = recortar_segmento(p, q, ext)
        if r is None:
            cerrar()
            continue
        t0, t1 = r
        a = (p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0)
        b = (p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1)
        if not pts:
            pts, nds = [a], [nodos[i] if t0 == 0 else None]
        pts.append(b)
        nds.append(nodos[i + 1] if t1 == 1 else None)
        if t1 < 1:
            cerrar()
    cerrar()
    return piezas


def recortar_poligono(anillo, ext):
    """Sutherland-Hodgman contra el rectángulo de la zona."""
    xmin, ymin, xmax, ymax = ext
    bordes = [
        (lambda p: p[0] >= xmin, lambda p, q: (xmin, p[1] + (q[1] - p[1]) * (xmin - p[0]) / (q[0] - p[0]))),
        (lambda p: p[0] <= xmax, lambda p, q: (xmax, p[1] + (q[1] - p[1]) * (xmax - p[0]) / (q[0] - p[0]))),
        (lambda p: p[1] >= ymin, lambda p, q: (p[0] + (q[0] - p[0]) * (ymin - p[1]) / (q[1] - p[1]), ymin)),
        (lambda p: p[1] <= ymax, lambda p, q: (p[0] + (q[0] - p[0]) * (ymax - p[1]) / (q[1] - p[1]), ymax)),
    ]
    salida = list(anillo)
    for dentro, corte in bordes:
        entrada, salida = salida, []
        if not entrada:
            break
        for i, q in enumerate(entrada):
            p = entrada[i - 1]
            if dentro(q):
                if not dentro(p):
                    salida.append(corte(p, q))
                salida.append(q)
            elif dentro(p):
                salida.append(corte(p, q))
    return salida


# ---------------------------------------------------------------- etiquetas

def numero(texto):
    if texto is None:
        return None
    valores = [float(v.replace(",", ".")) for v in re.findall(r"\d+(?:[.,]\d+)?", str(texto))]
    if not valores:
        return None
    v = max(valores)
    if "'" in str(texto) or "ft" in str(texto):
        v *= 0.3048
    return v


def altura_edificio(tags, area_m2, osm_id):
    """Devuelve (altura_m, niveles, estimada)."""
    rnd = random.Random(osm_id)
    h = numero(tags.get("height"))
    niveles = numero(tags.get("building:levels"))
    if h and h > 1:
        return h, niveles or max(1, round(h / 3.0)), False
    if niveles:
        return niveles * 3.0 + 1.0, niveles, False

    tipo = tags.get("building", "yes")
    if tipo in ("house", "detached", "semidetached_house", "garage", "shed", "kiosk", "hut"):
        niveles = rnd.choice([1, 2, 2, 2, 3])
    elif tipo in ("apartments", "residential"):
        niveles = rnd.randint(6, 14) if area_m2 > 300 else rnd.randint(3, 6)
    elif tipo in ("office", "commercial", "hotel"):
        niveles = rnd.randint(8, 18) if area_m2 > 400 else rnd.randint(3, 8)
    elif tipo in ("retail", "supermarket", "school", "church", "public", "civic"):
        niveles = rnd.randint(1, 3)
    elif tipo in ("roof", "carport"):
        return 5.0, 1, True
    else:  # "yes" y otros: estimar por tamaño de huella
        if area_m2 < 150:
            niveles = rnd.randint(1, 2)
        elif area_m2 < 600:
            niveles = rnd.randint(2, 5)
        else:
            niveles = rnd.randint(6, 12)
    return niveles * 3.0 + 1.0, niveles, True


def capa(tags):
    try:
        return int(float(tags.get("layer", 0)))
    except ValueError:
        return 0


def unir_lineas(tramos):
    """Une tramos abiertos que comparten extremos (p. ej. una pista partida en varias vías)."""
    tramos = [list(t) for t in tramos if len(t) >= 2]
    unidas = []
    while tramos:
        actual = tramos.pop(0)
        cambio = True
        while cambio:
            cambio = False
            for i, t in enumerate(tramos):
                if math.dist(t[0], actual[-1]) < 0.5:
                    actual += t[1:]
                elif math.dist(t[-1], actual[-1]) < 0.5:
                    actual += t[::-1][1:]
                elif math.dist(t[-1], actual[0]) < 0.5:
                    actual = t + actual[1:]
                elif math.dist(t[0], actual[0]) < 0.5:
                    actual = t[::-1] + actual[1:]
                else:
                    continue
                tramos.pop(i)
                cambio = True
                break
        unidas.append(actual)
    return unidas


def tipo_area(tags):
    if tags.get("aeroway") == "aerodrome":
        return "aerodromo"
    if tags.get("aeroway") == "apron":
        return "plataforma"
    if tags.get("aeroway") == "helipad":
        return "helipuerto"
    if tags.get("natural") == "water" or tags.get("amenity") == "fountain":
        return "agua"
    if tags.get("leisure") in ("park", "garden", "playground"):
        return "parque"
    if tags.get("leisure") == "pitch":
        return "cancha"
    if tags.get("place") == "square" or (tags.get("highway") == "pedestrian" and tags.get("area") == "yes"):
        return "plaza"
    if tags.get("landuse") in ("grass", "recreation_ground"):
        return "grama"
    if tags.get("amenity") == "parking":
        return "estacionamiento"
    return None


# ---------------------------------------------------------------- proceso principal

def procesar(crudo, zona):
    a_local, _ = transformadores(zona)
    ext = extension_local(zona)
    xmin, ymin, xmax, ymax = ext

    def local(geom):
        return [tuple(round(v, 3) for v in a_local.transform(g["lon"], g["lat"])) for g in geom if g]

    def dentro(x, y, margen=0.0):
        return xmin - margen <= x <= xmax + margen and ymin - margen <= y <= ymax + margen

    edificios, vias, areas, puntos, barreras, cruces, aerovias_crudas = [], [], [], [], [], [], []

    for el in crudo["elements"]:
        tags = el.get("tags", {})
        oid = f"{el['type'][0]}{el['id']}"

        # -- puntos (nodos, o el centro de vías/relaciones como el Obelisco, que en OSM es un polígono)
        tipo_punto = next((t for (k, v), t in PUNTOS.items() if tags.get(k) == v), None)
        if tipo_punto and "building" not in tags and el["type"] != "node":
            g = local(el.get("geometry") or [p for m in el.get("members", []) for p in (m.get("geometry") or [])])
            if len(g) > 1 and g[0] == g[-1]:
                g = g[:-1]
            if g:
                x, y = sum(p[0] for p in g) / len(g), sum(p[1] for p in g) / len(g)
                if dentro(x, y):
                    puntos.append({"id": el["id"], "tipo": tipo_punto, "x": round(x, 3), "y": round(y, 3),
                                   "nombre": tags.get("name"), "altura": numero(tags.get("height"))})
            continue
        if el["type"] == "node":
            for (k, v), tipo in PUNTOS.items():
                if tags.get(k) == v:
                    x, y = a_local.transform(el["lon"], el["lat"])
                    if dentro(x, y):
                        puntos.append({"id": el["id"], "tipo": tipo, "x": round(x, 3), "y": round(y, 3),
                                       "nombre": tags.get("name"),
                                       "altura": numero(tags.get("height")),
                                       "marcas": tags.get("crossing:markings") or tags.get("crossing")})
                    break
            continue

        # -- anillos de polígonos (vías cerradas o relaciones multipolígono)
        exteriores, interiores = [], []
        if el["type"] == "way" and "geometry" in el:
            g = local(el["geometry"])
            if len(g) >= 4 and g[0] == g[-1]:
                exteriores = [g]
        elif el["type"] == "relation":
            ext_t = [local(m["geometry"]) for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
            int_t = [local(m["geometry"]) for m in el.get("members", []) if m.get("role") == "inner" and m.get("geometry")]
            exteriores, interiores = unir_anillos(ext_t), unir_anillos(int_t)

        # -- edificios
        if "building" in tags and tags["building"] != "no" and exteriores:
            for anillo in exteriores:
                anillo = orientar(anillo, antihorario=True)
                if len(anillo) < 3:
                    continue
                cx = sum(p[0] for p in anillo) / len(anillo)
                cy = sum(p[1] for p in anillo) / len(anillo)
                if not dentro(cx, cy):
                    continue
                huecos = [orientar(h, antihorario=False) for h in interiores
                          if punto_en_poligono(h[0][0], h[0][1], anillo)]
                area = abs(area_firmada(anillo)) - sum(abs(area_firmada(h)) for h in huecos)
                if area < 4:
                    continue
                altura, niveles, estimada = altura_edificio(tags, area, el["id"])
                conocida = zona.get("alturas_conocidas", {}).get(oid)
                if conocida:  # correcciones manuales en zonas.json
                    altura, estimada = conocida["altura"], False
                    niveles = conocida.get("niveles", max(1, round(altura / 3.0)))
                tipo_ed = "control_tower" if tags.get("aeroway") in ("tower", "control_tower") else tags.get("building", "yes")
                if tipo_ed == "control_tower" and estimada:
                    altura, niveles = 24.0, 6  # torre de control típica de base pequeña
                edificios.append({
                    "id": oid, "tipo": tipo_ed, "nombre": tags.get("name"),
                    "altura": round(altura, 2), "niveles": niveles, "altura_estimada": estimada,
                    "altura_minima": numero(tags.get("min_height")) or 0.0,
                    "techo_color": tags.get("roof:colour"), "fachada_color": tags.get("building:colour"),
                    "exterior": anillo, "huecos": huecos, "area": round(area, 1),
                })
            continue

        # -- áreas
        ta = tipo_area(tags)
        if ta and exteriores:
            for anillo in exteriores:
                recorte = recortar_poligono(orientar(anillo, antihorario=True), ext)
                if len(recorte) >= 3 and abs(area_firmada(recorte)) > (1 if ta == "agua" else 10):
                    areas.append({"id": oid, "tipo": ta, "nombre": tags.get("name"),
                                  "borde": numero(tags.get("height")) or (0.5 if ta == "agua" else 0.0),
                                  "exterior": [(round(x, 3), round(y, 3)) for x, y in recorte]})
            continue

        # -- barreras lineales (setos, muros, rejas)
        barrera = tags.get("barrier")
        if el["type"] == "way" and barrera in ("hedge", "wall", "fence", "retaining_wall") and "geometry" in el:
            for pts, _ in recortar_polilinea(local(el["geometry"]), [], ext):
                barreras.append({"id": oid, "tipo": barrera, "puntos": pts,
                                 "altura": numero(tags.get("height"))})
            continue

        # -- pistas y calles de rodaje
        aero = tags.get("aeroway")
        if el["type"] == "way" and aero in AEROVIAS and "geometry" in el:
            for pts, _ in recortar_polilinea(local(el["geometry"]), [], ext):
                aerovias_crudas.append({"id": oid, "tipo": aero, "ref": tags.get("ref"),
                                        "ancho": numero(tags.get("width")) or AEROVIAS[aero], "puntos": pts})
            continue

        # -- pasos peatonales (se dibujan como rayado de cebra)
        if el["type"] == "way" and tags.get("footway") == "crossing" and "geometry" in el:
            if tags.get("crossing:markings", tags.get("crossing_ref", "zebra")) not in ("no", "none"):
                for pts, _ in recortar_polilinea(local(el["geometry"]), [], ext):
                    cruces.append({"id": oid, "puntos": pts})
            continue

        # -- vías
        hw = tags.get("highway")
        if el["type"] == "way" and hw and hw not in VIAS_IGNORADAS and "geometry" in el:
            if hw == "footway" and tags.get("footway") in ("sidewalk", "crossing"):
                continue  # las aceras se generan a partir de las calles; los cruces son marcas viales
            carriles_def, ancho_carril = VIAS.get(hw, (1, 3.0))
            carriles = numero(tags.get("lanes")) or carriles_def
            ancho = numero(tags.get("width")) or max(carriles * ancho_carril, ancho_carril)
            acera = tags.get("sidewalk", "auto")
            for pts, nds in recortar_polilinea(local(el["geometry"]), el.get("nodes", []), ext):
                vias.append({
                    "id": oid, "tipo": hw, "nombre": tags.get("name"), "carriles": carriles,
                    "ancho": round(ancho, 2), "sentido_unico": tags.get("oneway") in ("yes", "1", "true"),
                    "puente": tags.get("bridge") not in (None, "no"),
                    "tunel": tags.get("tunnel") not in (None, "no"),
                    "capa": capa(tags), "acera": acera, "puntos": pts, "nodos": nds,
                })

    # Las pistas vienen partidas en varias vías con la misma designación: se unen en una sola
    aerovias = []
    pistas_por_ref = {}
    for a in aerovias_crudas:
        if a["tipo"] == "runway":
            pistas_por_ref.setdefault(a["ref"] or a["id"], []).append(a)
        else:
            aerovias.append(a)
    for ref, tramos in pistas_por_ref.items():
        for linea in unir_lineas([t["puntos"] for t in tramos]):
            aerovias.append({"id": tramos[0]["id"], "tipo": "runway", "ref": ref,
                             "ancho": max(t["ancho"] for t in tramos), "puntos": linea})

    return {"zona": zona["id"], "centro": zona["centro"], "extension": ext,
            "atribucion": "© OpenStreetMap contributors (ODbL)",
            "edificios": edificios, "vias": vias, "areas": areas, "puntos": puntos,
            "barreras": barreras, "cruces": cruces, "aerovias": aerovias}


def resumen(datos):
    ed = datos["edificios"]
    print(f"  Edificios: {len(ed)}  (altura real: {sum(not e['altura_estimada'] for e in ed)}, "
          f"estimada: {sum(e['altura_estimada'] for e in ed)})")
    if ed:
        alto = max(ed, key=lambda e: e["altura"])
        print(f"  Más alto: {alto['nombre'] or alto['id']} ({alto['altura']:.0f} m)")
    print(f"  Tramos de vía: {len(datos['vias'])}  "
          f"(longitud total {sum(sum(math.dist(a, b) for a, b in zip(v['puntos'], v['puntos'][1:])) for v in datos['vias']) / 1000:.1f} km)")
    tipos_area = {}
    for a in datos["areas"]:
        tipos_area[a["tipo"]] = tipos_area.get(a["tipo"], 0) + 1
    print(f"  Áreas: {len(datos['areas'])} ({', '.join(f'{k}={v}' for k, v in sorted(tipos_area.items()))})")
    print(f"  Barreras: {len(datos['barreras'])}  Pasos de cebra: {len(datos['cruces'])}")
    for a in datos.get("aerovias", []):
        if a["tipo"] == "runway":
            largo = sum(math.dist(p, q) for p, q in zip(a["puntos"], a["puntos"][1:]))
            print(f"  Pista {a['ref']}: {largo:.0f} m × {a['ancho']:.0f} m")
    if datos.get("aerovias"):
        print(f"  Calles de rodaje: {sum(a['tipo'] != 'runway' for a in datos['aerovias'])}")
    conteo = {}
    for p in datos["puntos"]:
        conteo[p["tipo"]] = conteo.get(p["tipo"], 0) + 1
    print("  Puntos: " + ", ".join(f"{k}={v}" for k, v in sorted(conteo.items())))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zona")
    ap.add_argument("--sin-descarga", action="store_true", help="reutiliza osm_crudo.json existente")
    args = ap.parse_args()

    zona = cargar_zona(args.zona)
    carpeta = carpeta_zona(zona)
    ruta_crudo = carpeta / "osm_crudo.json"

    if args.sin_descarga and ruta_crudo.exists():
        with open(ruta_crudo, encoding="utf-8") as f:
            crudo = json.load(f)
    else:
        sur, oeste, norte, este = bbox_geo(zona, margen_m=50)
        print(f"Descargando OSM de '{zona['nombre']}' bbox=({sur:.5f}, {oeste:.5f}, {norte:.5f}, {este:.5f})")
        crudo = descargar(consulta_overpass(sur, oeste, norte, este))
        with open(ruta_crudo, "w", encoding="utf-8") as f:
            json.dump(crudo, f, ensure_ascii=False)
        print(f"  {len(crudo['elements'])} elementos descargados -> {ruta_crudo}")

    datos = procesar(crudo, zona)
    guardar_json(carpeta / "osm_local.json", datos)
    resumen(datos)
    print(f"Listo: {carpeta / 'osm_local.json'}")


if __name__ == "__main__":
    sys.exit(main())
