"""Paso 03 (Blender): construye la maqueta 3D de una zona y la exporta en celdas FBX para Unreal.

Uso (sin abrir la interfaz de Blender):
    blender -b --factory-startup -P scripts/blender/03_construir_zona.py -- altamira
Opciones después de "--":
    --exportar-terreno   exporta también el terreno como malla (si no se usa Landscape)
    --sin-fbx            solo genera el .blend (para revisar)

Requiere haber corrido antes los pasos 01 (osm_local.json) y 02 (terreno/).

Salidas en datos/<ciudad>/<zona>/:
    <zona>.blend                    escena completa para revisar/editar en Blender
    export/celda_<i>_<j>.fbx        edificios, calles, aceras y áreas de cada celda
    export/props.json               posiciones de árboles, farolas, semáforos, tanques...
    export/meta_zona.json           datos para el importador de Unreal (paso 04)

Convenciones (ver scripts/comun.py): metros, X=Este, Y=Norte, Z=arriba, origen en el centro
de la zona a nivel del terreno. Las mallas mantienen su origen en (0,0,0) para que en Unreal
todas se coloquen en (0,0,0) y queden alineadas.
UV0 = metros (paredes: a lo largo / altura desde la base; suelos: X/Y del mundo).
UV1 en calles = (0..1 a lo ancho, metros a lo largo). Vidrios, rejas y santamarías: UV0 = 0..1.
Color de vértice por edificio: R = variación aleatoria, G = estilo/10, B = niveles/50.
Color de vértice en calles: R = carriles/8, G = sentido único, B = clase de vía, A = ancho/30.
Dentro del radio "detalle" de zonas.json las fachadas llevan ventanas, rejas y locales reales.
"""

import json
import math
import random
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import cargar_zona, carpeta_zona  # noqa: E402
import detalle  # noqa: E402

# ---------------------------------------------------------------- parámetros

ALTO_PRETIL = 1.0
GROSOR_PRETIL = 0.2
CLASE_VIA = {"motorway": 1.0, "trunk": 1.0, "primary": 0.9, "secondary": 0.75, "tertiary": 0.6,
             "residential": 0.4, "unclassified": 0.4, "living_street": 0.3, "service": 0.2}
# Barreras: (ancho, alto por defecto, material)
BARRERAS = {"hedge": (0.8, 1.1, "M_Seto"), "wall": (0.25, 1.8, "M_Muro"),
            "fence": (0.06, 1.8, "M_Cerca"), "retaining_wall": (0.4, 1.2, "M_Brocal")}

# Elevación de cada capa sobre el terreno (evita parpadeo z-fighting) y orden de dibujo.
Z_CALLE = {"motorway": 0.16, "trunk": 0.16, "primary": 0.15, "secondary": 0.14, "tertiary": 0.13}
Z_CALLE_DEFECTO = 0.12
Z_SENDERO = 0.10
Z_AREA = {"plaza": 0.05, "estacionamiento": 0.04, "cancha": 0.07, "parque": 0.2, "grama": 0.2, "plataforma": 0.1,
          "aerodromo": 0.03}
AREAS_ELEVADAS = {"parque", "grama"}  # jardineras con brocal
ALTO_ACERA = 0.18          # sobre la calzada
ANCHO_ACERA = 2.5
DIST_ESQUINA = 2.0         # metros extra que se recortan de la acera alrededor de cada intersección
PASO_MAX = 4.0             # longitud máxima de segmento al pegar geometría al terreno
TIPOS_CON_ACERA = {"primary", "secondary", "tertiary", "residential", "unclassified", "living_street",
                   "trunk", "primary_link", "secondary_link", "tertiary_link"}
TIPOS_SENDERO = {"footway", "path", "cycleway", "steps", "pedestrian", "track"}
MATERIAL_AREA = {"parque": "M_Grama", "grama": "M_Grama", "cancha": "M_Cancha",
                 "plaza": "M_Plaza", "estacionamiento": "M_Asfalto", "agua": "M_Agua", "plataforma": "M_Plataforma",
                 "aerodromo": "M_Pasto"}
AREAS_SIN_SUPERFICIE = set()


# ---------------------------------------------------------------- terreno

class Terreno:
    def __init__(self, carpeta):
        self.h = np.load(carpeta / "terreno" / "altura_local.npy")
        with open(carpeta / "terreno" / "meta.json", encoding="utf-8") as f:
            self.meta = json.load(f)
        self.res = self.meta["resolucion_m"]
        self.xmin, self.ymin, self.xmax, self.ymax = self.meta["extension_local"]

    def z(self, x, y):
        n = self.h.shape[0]
        c = min(max((x - self.xmin) / self.res, 0.0), n - 1.001)
        f = min(max((self.ymax - y) / self.res, 0.0), n - 1.001)
        c0, f0 = int(c), int(f)
        dc, df = c - c0, f - f0
        h = self.h
        return float(h[f0, c0] * (1 - df) * (1 - dc) + h[f0, c0 + 1] * (1 - df) * dc
                     + h[f0 + 1, c0] * df * (1 - dc) + h[f0 + 1, c0 + 1] * df * dc)


# ---------------------------------------------------------------- acumulador de mallas

class Malla:
    """Junta vértices/caras de muchas piezas para crear un solo objeto de Blender."""

    def __init__(self):
        self.v, self.caras, self.uv0, self.uv1, self.col, self.mat = [], [], [], [], [], []
        self.materiales = []

    def material(self, nombre):
        if nombre not in self.materiales:
            self.materiales.append(nombre)
        return self.materiales.index(nombre)

    def cara(self, puntos, uv0, material, uv1=None, color=(1, 1, 1, 1)):
        base = len(self.v)
        self.v.extend(puntos)
        self.caras.append(tuple(range(base, base + len(puntos))))
        self.uv0.extend(uv0)
        self.uv1.extend(uv1 or uv0)
        self.col.extend([color] * len(puntos))
        self.mat.append(self.material(material))

    def vacia(self):
        return not self.caras

    def crear_objeto(self, nombre, coleccion):
        me = bpy.data.meshes.new(nombre)
        me.from_pydata(self.v, [], self.caras)
        for m in self.materiales:
            mat = bpy.data.materials.get(m) or bpy.data.materials.new(m)
            me.materials.append(mat)
        me.polygons.foreach_set("material_index", self.mat)
        for nombre_uv, datos in (("UV0", self.uv0), ("UV1", self.uv1)):
            capa = me.uv_layers.new(name=nombre_uv)
            capa.data.foreach_set("uv", [c for uv in datos for c in uv])
        colores = me.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
        colores.data.foreach_set("color", [c for col in self.col for c in col])
        me.validate(clean_customdata=False)
        me.update()
        obj = bpy.data.objects.new(nombre, me)
        coleccion.objects.link(obj)
        return obj


class Celdas:
    """Reparte geometría en celdas cuadradas (una malla por capa y celda)."""

    def __init__(self, ext, tam):
        self.xmin, self.ymin = ext[0], ext[1]
        self.tam = tam
        self.n = max(1, int(math.ceil((ext[2] - ext[0]) / tam)))
        self.mallas = {}

    def indice(self, x, y):
        i = min(max(int((x - self.xmin) // self.tam), 0), self.n - 1)
        j = min(max(int((y - self.ymin) // self.tam), 0), self.n - 1)
        return i, j

    def malla(self, capa, x, y):
        clave = (capa,) + self.indice(x, y)
        if clave not in self.mallas:
            self.mallas[clave] = Malla()
        return self.mallas[clave]


# ---------------------------------------------------------------- geometría 2D

def densificar(puntos, paso=PASO_MAX):
    salida = [puntos[0]]
    for a, b in zip(puntos, puntos[1:]):
        d = math.dist(a, b)
        n = max(1, int(math.ceil(d / paso)))
        for k in range(1, n + 1):
            t = k / n
            salida.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return salida


def normales_polilinea(puntos):
    """Normal (izquierda) en cada vértice, con unión en inglete limitada."""
    normales = []
    n = len(puntos)
    for i in range(n):
        a = puntos[max(i - 1, 0)]
        b = puntos[min(i + 1, n - 1)]
        if i == 0:
            a, b = puntos[0], puntos[1]
        elif i == n - 1:
            a, b = puntos[-2], puntos[-1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        if 0 < i < n - 1:  # inglete: escala por 1/cos(medio ángulo)
            d1 = (puntos[i][0] - puntos[i - 1][0], puntos[i][1] - puntos[i - 1][1])
            l1 = math.hypot(*d1) or 1.0
            n1 = (-d1[1] / l1, d1[0] / l1)
            cos_m = max(nx * n1[0] + ny * n1[1], 0.5)
            nx, ny = nx / cos_m, ny / cos_m
        normales.append((nx, ny))
    return normales


def longitudes(puntos):
    s = [0.0]
    for a, b in zip(puntos, puntos[1:]):
        s.append(s[-1] + math.dist(a, b))
    return s


def tramos_fuera(puntos, s, posiciones_excluidas, radio):
    """Intervalos [s0, s1] de la polilínea que quedan lejos de las intersecciones."""
    cortes = sorted((max(p - radio, 0), min(p + radio, s[-1])) for p in posiciones_excluidas)
    libres, actual = [], 0.0
    for c0, c1 in cortes:
        if c0 > actual:
            libres.append((actual, c0))
        actual = max(actual, c1)
    if actual < s[-1]:
        libres.append((actual, s[-1]))
    return [(a, b) for a, b in libres if b - a > 1.0]


def sub_polilinea(puntos, s, s0, s1):
    def interp(t):
        for i in range(len(s) - 1):
            if s[i] <= t <= s[i + 1]:
                f = (t - s[i]) / ((s[i + 1] - s[i]) or 1)
                return (puntos[i][0] + (puntos[i + 1][0] - puntos[i][0]) * f,
                        puntos[i][1] + (puntos[i + 1][1] - puntos[i][1]) * f)
        return puntos[-1]
    medio = [p for p, si in zip(puntos, s) if s0 < si < s1]
    return [interp(s0)] + medio + [interp(s1)]


def triangular(exterior, huecos=()):
    """Triangula un polígono con huecos. Devuelve (lista de puntos 2D, triángulos)."""
    anillos = [list(exterior)] + [list(h) for h in huecos]
    planos = [p for a in anillos for p in a]
    tris = tessellate_polygon([[Vector((x, y, 0)) for x, y in a] for a in anillos])
    salida = []
    for a, b, c in tris:
        pa, pb, pc = planos[a], planos[b], planos[c]
        if (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0]) < 0:
            b, c = c, b
        salida.append((a, b, c))
    return planos, salida


def subdividir(puntos, tris, max_lado=PASO_MAX, max_nivel=5):
    """Subdivide triángulos uniformemente (sin uniones en T) hasta que los lados midan <= max_lado."""
    lado = max((math.dist(puntos[a], puntos[b]) for t in tris for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))), default=0)
    niveles = min(max_nivel, max(0, int(math.ceil(math.log2(max(lado / max_lado, 1))))))
    puntos = list(puntos)
    for _ in range(niveles):
        medios, nuevos = {}, []

        def medio(a, b):
            k = (min(a, b), max(a, b))
            if k not in medios:
                puntos.append(((puntos[a][0] + puntos[b][0]) / 2, (puntos[a][1] + puntos[b][1]) / 2))
                medios[k] = len(puntos) - 1
            return medios[k]
        for a, b, c in tris:
            ab, bc, ca = medio(a, b), medio(b, c), medio(c, a)
            nuevos += [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]
        tris = nuevos
    return puntos, tris


# ---------------------------------------------------------------- constructores

def construir_edificio(ed, terreno, celdas, rnd, props, zona_detalle):
    ext = ed["exterior"]
    cx = sum(p[0] for p in ext) / len(ext)
    cy = sum(p[1] for p in ext) / len(ext)
    suelos = [terreno.z(x, y) for x, y in ext]
    base = min(suelos) - 0.5 + ed.get("altura_minima", 0.0)
    techo = min(suelos) + ed["altura"]
    if techo - base < 2.0:
        return None
    estilo = detalle.estilo_de(ed["tipo"])
    mat_fachada = detalle.elegir_fachada(estilo, rnd)
    hito = HITOS.get(ed.get("id"))
    if hito and hito.get("material"):
        mat_fachada = hito["material"]
    hangar = estilo == "hangar"
    con_detalle = en_zona_detalle(cx, cy, zona_detalle) and not hangar and not (hito and hito.get("material"))
    # A = 1: ventanas modeladas o sin ventanas (el material no las dibuja); A = 0: el material las pinta
    color = (rnd.random(), (list(detalle.ESTILOS).index(estilo) + 1) / 10.0, min(ed["niveles"] / 50.0, 1.0),
             1.0 if con_detalle or hangar else 0.0)
    m = celdas.malla("Edificios", cx, cy)

    if hito and hito.get("altura"):
        techo = min(suelos) + hito["altura"]
    if hito and hito.get("modelo", "normal") != "normal":
        construir_hito(ed, hito, ext, base, techo, m, color)
        return None
    if ed["tipo"] == "obelisk":
        if ed["altura"] > 25:  # el de Plaza Francia: pedestal tallado sobre la fuente escalonada
            detalle.obelisco_plaza_francia(m, ext, base, techo, max(suelos) + Z_AREA["plaza"])
        else:
            construir_obelisco(ext, cx, cy, base, techo, m)
        return None
    if ed["tipo"] == "control_tower":
        cabina, tope = detalle.torre_control(m, ext, base, techo - base, "M_Fachada_Concreto")
        planos, tris = triangular(cabina)
        for a, b, c in tris:
            pts = [planos[a], planos[b], planos[c]]
            m.cara([(x, y, tope) for x, y in pts], [(x, y) for x, y in pts], "M_Techo_Concreto")
        return None
    if hangar and ed.get("frente"):
        # techo a dos aguas con el frente abierto hacia la plataforma (como en las fotos de La Carlota)
        piso = max(suelos) + Z_AREA["plataforma"]
        c, f, hf, hw, alto_puerta = detalle.hangar_dos_aguas(
            m, celdas.malla("Aviacion", cx, cy), ext, base, piso, techo - base, ed["frente"], rnd, color,
            abierto=rnd.random() < 0.75)
        if 2 * hw > 22 and 2 * hf > 16 and alto_puerta > 5.0 and rnd.random() < 0.6:
            tipo = elegir_aeronave(rnd)
            x, y = c[0] + f[0] * hf * 0.25, c[1] + f[1] * hf * 0.25
            props.append({"tipo": tipo, "x": round(x, 2), "y": round(y, 2), "z": round(piso, 2),
                          "rumbo": round(math.degrees(math.atan2(f[1], f[0])), 1), "escala": 1.0})
        return None
    if hangar and ed["area"] > 300:
        detalle.hangar_boveda(m, ext, base, techo - base, rnd)
        return None

    anillos = [ext] + ed["huecos"]
    # Pretil (muro perimetral de la azotea) en edificios de techo plano
    interiores = None
    if estilo not in ("casa", "hangar") and ed["area"] > 40 and ed["tipo"] not in ("roof", "carport"):
        interiores = [detalle.offset_anillo(a, GROSOR_PRETIL) for a in anillos]
        if not all(detalle.offset_valido(a, i) for a, i in zip(anillos, interiores)):
            interiores = None
    alto_pretil = ALTO_PRETIL if interiores else 0.0

    con_locales = con_detalle and rnd.random() < detalle.ESTILOS[estilo]["locales"]

    for anillo in anillos:
        if con_detalle:
            suelos_anillo = [terreno.z(x, y) for x, y in anillo]
            detalle.fachada(m, anillo, suelos_anillo, base, techo, estilo, mat_fachada, color, rnd, props, con_locales)
            z0 = techo  # franja del pretil por encima de las ventanas
        else:
            z0 = base
        if alto_pretil or not con_detalle:
            u = 0.0
            for a, b in zip(anillo, anillo[1:] + anillo[:1]):
                L = math.dist(a, b)
                if L < 0.01:
                    continue
                pared = detalle.Pared(a, b)
                pared.quad(m, 0, L, z0, techo + alto_pretil, 0, mat_fachada, u, base, color)
                u += L

    mat_techo = "M_Techo" if estilo in ("residencial", "oficina") and rnd.random() < 0.65 else "M_Techo_Concreto"
    if hangar:
        mat_techo = "M_Zinc"
    if interiores:
        for anillo in anillos:
            detalle.pretil(m, anillo, techo, ALTO_PRETIL, GROSOR_PRETIL, mat_fachada, "M_Techo_Concreto", color)
        borde_ext, borde_huecos = interiores[0], interiores[1:]
    else:
        borde_ext, borde_huecos = ext, ed["huecos"]
    planos, tris = triangular(borde_ext, borde_huecos)
    for a, b, c in tris:
        pts = [planos[a], planos[b], planos[c]]
        m.cara([(x, y, techo) for x, y in pts], [(x, y) for x, y in pts], mat_techo, color=color)
    if hito and hito.get("letrero_techo"):  # letras sobre la azotea, mirando hacia la plaza
        lt = hito["letrero_techo"]
        c0, ea, ef, ha, hf = detalle.ejes_hacia(ext, tuple(hito.get("mira_hacia", PLAZA)))
        p = (c0[0] + ef[0] * (hf - 2.0), c0[1] + ef[1] * (hf - 2.0))
        letrero_en(m, [[lt["texto"], lt.get("material", "M_Letrero_Rojo")]], lt.get("alto", 2.0), 0.3, p, ef,
                   techo + alto_pretil + 0.6)
        for s in (-1, 0, 1):  # perfiles que sostienen las letras
            q = (p[0] + ea[0] * s * ha * 0.6, p[1] + ea[1] * s * ha * 0.6)
            detalle.tubo(m, [(q[0], q[1], techo), (q[0], q[1], techo + alto_pretil + 0.6 + lt.get("alto", 2.0))], 0.06, "M_Metal_Oscuro")
    return (cx, cy, techo, borde_ext)


# Edificios emblemáticos de zonas.json ("hitos": {id OSM: {...}}) y punto hacia el que miran sus fachadas
HITOS = {}
PLAZA = (0.0, 0.0)
# Zonas de detalle adicionales ("detalles_extra": [{"centro": [x, y], "radio_m": r}, ...])
DETALLES_EXTRA = []


def en_zona_detalle(x, y, zona_detalle):
    return any(math.hypot(x - d["centro"][0], y - d["centro"][1]) < d["radio_m"] for d in [zona_detalle] + DETALLES_EXTRA)


def construir_hito(ed, hito, ext, base, techo, m, color):
    """Edificios con forma propia (ver detalle.py): torre_escalonada, torre_marco, torre_arcos, balcones."""
    color = (color[0], color[1], color[2], 0.0)  # A = 0: las fachadas lisas dibujan ventanas
    modelo = hito["modelo"]
    letrero = hito.get("letrero")
    frente = tuple(hito.get("mira_hacia", PLAZA))
    if modelo == "torre_escalonada":
        detalle.torre_escalonada(m, ext, base, frente, hito["escalones"], hito.get("material", "M_Franjas_Azul"), color,
                                 hito.get("aletas"))
    elif modelo == "unefa":
        ancla, ef, z_letras, esquina, z_techo = detalle.unefa(m, ext, base, techo, frente, color,
                                                              retiro_atras=hito.get("retiro_atras", 0.0))
        if letrero:
            letrero_en(m, [[letrero["texto"], letrero.get("material", "M_Letras")]], letrero.get("alto", 1.4), 0.2,
                       ancla, ef, z_letras - letrero.get("alto", 1.4) - 0.3)
        lt = hito.get("letrero_techo")
        if lt:
            letrero_en(m, [[lt["texto"], lt.get("material", "M_Letrero_Rojo")]], lt.get("alto", 3.5), 0.4, esquina, ef,
                       z_techo + 0.8)
            for s in (-6, 0, 6):
                q = (esquina[0] + (-ef[1]) * s, esquina[1] + ef[0] * s)
                detalle.tubo(m, [(q[0], q[1], z_techo), (q[0], q[1], z_techo + 0.8 + lt.get("alto", 3.5))], 0.07, "M_Metal_Oscuro")
    elif modelo == "cubo_negro":
        detalle.cubo_negro(m, ext, base, techo, frente, color)
    elif modelo == "piramide_invertida":
        detalle.piramide_invertida(m, ext, base, techo, color)
    elif modelo == "torre_marco":
        ancla, frente, z = detalle.torre_marco(m, ext, base, techo, PLAZA, color)
        if letrero:
            letrero_en(m, [[letrero["texto"], letrero.get("material", "M_Letrero_Rojo")]], letrero.get("alto", 1.8), 0.25,
                       ancla, frente, z - letrero.get("alto", 1.8) / 2)
    elif modelo == "torre_arcos":
        c, ef, hf, z = detalle.torre_arcos(m, ext, base, techo, PLAZA, color)
        if letrero:
            ancla = (c[0] + ef[0] * (hf + 0.1), c[1] + ef[1] * (hf + 0.1))
            letrero_en(m, [[letrero["texto"], letrero.get("material", "M_Letrero_Azul")]], letrero.get("alto", 0.9), 0.2,
                       ancla, ef, z)
    elif modelo == "balcones":
        detalle.edificio_balcones(m, ext, base, techo, color)
        planos, tris = triangular(ext, ed["huecos"])
        for a, b, c in tris:
            pts = [planos[a], planos[b], planos[c]]
            m.cara([(x, y, techo) for x, y in pts], [(x, y) for x, y in pts], "M_Techo_Concreto", color=color)


def construir_obelisco(ext, cx, cy, base, techo, m, afinado=0.55, punta=0.07):
    """Fuste que se afina hacia arriba y termina en un piramidión (punta = fracción de la altura)."""
    alto = techo - base
    z_fuste = techo - alto * punta

    def escalar(p, f):
        return (cx + (p[0] - cx) * f, cy + (p[1] - cy) * f)
    arriba = [escalar(p, afinado) for p in ext]
    u = 0.0
    for k in range(len(ext)):
        a, b = ext[k], ext[(k + 1) % len(ext)]
        a2, b2 = arriba[k], arriba[(k + 1) % len(ext)]
        L = math.dist(a, b)
        m.cara([(a[0], a[1], base), (b[0], b[1], base), (b2[0], b2[1], z_fuste), (a2[0], a2[1], z_fuste)],
               [(u, base), (u + L, base), (u + L, z_fuste), (u, z_fuste)], "M_Monumento")
        m.cara([(a2[0], a2[1], z_fuste), (b2[0], b2[1], z_fuste), (cx, cy, techo)],
               [(u, z_fuste), (u + L, z_fuste), (u + L / 2, techo)], "M_Monumento")
        u += L


def nodos_interseccion(vias):
    uso = {}
    for v in vias:
        if v["tunel"] or v["tipo"] in TIPOS_SENDERO:
            continue
        for k, nd in enumerate(v["nodos"]):
            if nd is None:
                continue
            extremo = k in (0, len(v["nodos"]) - 1)
            uso.setdefault(nd, []).append((v, extremo))
    # Un nodo es intersección si lo comparten 2+ vías y no es solo la continuación de la misma calle.
    return {nd for nd, usos in uso.items() if len(usos) >= 3 or (len(usos) == 2 and not all(e for _, e in usos))
            or (len(usos) == 2 and usos[0][0]["nombre"] != usos[1][0]["nombre"])}


def altura_via(v, terreno, puntos):
    off = Z_SENDERO if v["tipo"] in TIPOS_SENDERO else Z_CALLE.get(v["tipo"].replace("_link", ""), Z_CALLE_DEFECTO)
    if v["puente"] and v["tipo"] in TIPOS_SENDERO:
        # pasarela peatonal: tablero horizontal a 6 m sobre lo más alto que cruza (torres de escalera en los extremos)
        return [max(terreno.z(*p) for p in puntos) + 6.0] * len(puntos)
    if v["puente"]:
        za, zb = terreno.z(*puntos[0]), terreno.z(*puntos[-1])
        s = longitudes(puntos)
        total = s[-1] or 1.0
        zs = [za + (zb - za) * si / total + off for si in s]
        # el tablero del puente queda al menos 5 m por encima del suelo que cruza
        return [max(z, terreno.z(*p) + 5.0) if 0 < i < len(puntos) - 1 else z
                for i, (p, z) in enumerate(zip(puntos, zs))]
    return [terreno.z(*p) + off for p in puntos]


def estructura_puente(puntos, normales, zs, medio_ancho, peatonal, terreno, celdas):
    """Tablero con espesor (cara inferior y cantos), barandas de concreto y pilas donde el tablero va alto.
    Las pasarelas peatonales llevan antepechos de 1,1 m y torres de escalera en los extremos."""
    grosor = 0.6 if peatonal else 1.3
    alto_bar, ancho_bar = (1.1, 0.15) if peatonal else (0.85, 0.3)
    mat_bar = "M_Concreto_Claro" if peatonal else "M_Brocal"
    m = celdas.malla("Detalles", *puntos[len(puntos) // 2])
    for lado in (1, -1):
        bordes = [(p[0] + n[0] * medio_ancho * lado, p[1] + n[1] * medio_ancho * lado) for p, n in zip(puntos, normales)]
        s = 0.0
        for i in range(len(puntos) - 1):
            a, b = bordes[i], bordes[i + 1]
            L = math.dist(a, b)
            za, zb = zs[i], zs[i + 1]
            # canto del tablero
            q = [(*a, za - grosor), (*b, zb - grosor), (*b, zb), (*a, za)]
            m.cara(q if lado < 0 else q[::-1], [(s, 0), (s + L, 0), (s + L, grosor), (s, grosor)][:: 1 if lado < 0 else -1], "M_Concreto_Claro")
            s += L
        # baranda de concreto a lo largo del borde
        normales_b = [(n[0] * lado, n[1] * lado) for n in normales]
        hacia_adentro = [(-n[0], -n[1]) for n in normales_b]
        detalle.extruir_polilinea(m, [(p[0] - n[0] * ancho_bar / 2, p[1] - n[1] * ancho_bar / 2) for p, n in zip(bordes, normales_b)],
                                  hacia_adentro, [z + 0.1 for z in zs], ancho_bar, alto_bar, mat_bar)
    # cara inferior
    izq = [(p[0] + n[0] * medio_ancho, p[1] + n[1] * medio_ancho) for p, n in zip(puntos, normales)]
    der = [(p[0] - n[0] * medio_ancho, p[1] - n[1] * medio_ancho) for p, n in zip(puntos, normales)]
    for i in range(len(puntos) - 1):
        m.cara([(*izq[i], zs[i] - grosor), (*izq[i + 1], zs[i + 1] - grosor), (*der[i + 1], zs[i + 1] - grosor), (*der[i], zs[i] - grosor)],
               [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Concreto_Claro")
    # pilas (cada ~30 m donde el tablero está a más de 3 m del suelo)
    s_total = longitudes(puntos)
    siguiente = 15.0
    for i, p in enumerate(puntos):
        if s_total[i] < siguiente:
            continue
        siguiente = s_total[i] + 30.0
        suelo = terreno.z(*p)
        if zs[i] - grosor - suelo < 3.0 or 0 in (i,) or i == len(puntos) - 1:
            continue
        d = normales[i]
        ancho_pila = medio_ancho * (0.5 if peatonal else 0.7)
        detalle.caja(m, p[0], p[1], suelo - 0.5, zs[i] - grosor, ancho_pila if peatonal else 0.9, d, "M_Concreto_Claro")
    if peatonal:
        for i, j in ((0, 1), (-1, -2)):
            p, q = puntos[i], puntos[j]
            L = math.dist(p, q) or 1.0
            eje = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
            x, y = p[0] - eje[0] * 2.5, p[1] - eje[1] * 2.5
            detalle.torre_escalera(m, x, y, terreno.z(x, y), zs[i], eje)


def construir_via(v, terreno, celdas, intersecciones, props):
    if v["tunel"] or len(v["puntos"]) < 2:
        return
    puntos = densificar(v["puntos"])
    normales = normales_polilinea(puntos)
    zs = altura_via(v, terreno, puntos)
    s = longitudes(puntos)
    medio_ancho = v["ancho"] / 2.0
    sendero = v["tipo"] in TIPOS_SENDERO
    mat = ("M_Escalera" if v["tipo"] == "steps" else "M_Sendero") if sendero else "M_Asfalto"
    capa = "Senderos" if sendero else "Calles"
    # Datos para que el material pinte las líneas de carril
    color = (min(v["carriles"] / 8.0, 1.0), 1.0 if v["sentido_unico"] else 0.0,
             CLASE_VIA.get(v["tipo"].replace("_link", ""), 0.2), min(v["ancho"] / 30.0, 1.0))

    for i in range(len(puntos) - 1):
        (x0, y0), (x1, y1) = puntos[i], puntos[i + 1]
        (nx0, ny0), (nx1, ny1) = normales[i], normales[i + 1]
        izq0 = (x0 + nx0 * medio_ancho, y0 + ny0 * medio_ancho)
        der0 = (x0 - nx0 * medio_ancho, y0 - ny0 * medio_ancho)
        izq1 = (x1 + nx1 * medio_ancho, y1 + ny1 * medio_ancho)
        der1 = (x1 - nx1 * medio_ancho, y1 - ny1 * medio_ancho)
        quad = [(*der0, zs[i]), (*der1, zs[i + 1]), (*izq1, zs[i + 1]), (*izq0, zs[i])]
        uv0 = [(p[0], p[1]) for p in quad]
        uv1 = [(0, s[i]), (0, s[i + 1]), (1, s[i + 1]), (1, s[i])]
        celdas.malla(capa, (x0 + x1) / 2, (y0 + y1) / 2).cara(quad, uv0, mat, uv1=uv1, color=color)

    if v["puente"]:
        estructura_puente(puntos, normales, zs, medio_ancho, sendero, terreno, celdas)
    if sendero or v["puente"] or v["tipo"] not in TIPOS_CON_ACERA or v["acera"] in ("no", "none"):
        return
    lados = {"left": [1], "right": [-1]}.get(v["acera"], [1, -1])

    # Recorta las aceras cerca de las intersecciones para no invadir la calle transversal.
    pos_inter = []
    s_orig = longitudes(v["puntos"])
    for k, nd in enumerate(v["nodos"]):
        if nd in intersecciones:
            pos_inter.append(s_orig[k])
    radio = medio_ancho + ANCHO_ACERA + DIST_ESQUINA + 4.0
    for s0, s1 in tramos_fuera(v["puntos"], s_orig, pos_inter, radio):
        tramo = densificar(sub_polilinea(v["puntos"], s_orig, s0, s1))
        if len(tramo) < 2:
            continue
        nrm = normales_polilinea(tramo)
        st = longitudes(tramo)
        for lado in lados:
            construir_acera(tramo, nrm, st, lado, medio_ancho, v, terreno, celdas)
        sembrar_farolas(tramo, nrm, st, medio_ancho, v, terreno, props)


def construir_acera(puntos, normales, s, lado, medio_ancho, v, terreno, celdas):
    off_calle = Z_CALLE.get(v["tipo"].replace("_link", ""), Z_CALLE_DEFECTO)
    for i in range(len(puntos) - 1):
        filas = []
        for k in (i, i + 1):
            x, y = puntos[k]
            nx, ny = normales[k][0] * lado, normales[k][1] * lado
            interior = (x + nx * medio_ancho, y + ny * medio_ancho)
            exterior = (x + nx * (medio_ancho + ANCHO_ACERA), y + ny * (medio_ancho + ANCHO_ACERA))
            z_calle = terreno.z(x, y) + off_calle
            filas.append((interior, exterior, z_calle, z_calle + ALTO_ACERA, terreno.z(*exterior) - 0.3))
        (i0, e0, zc0, za0, zt0), (i1, e1, zc1, za1, zt1) = filas
        m = celdas.malla("Aceras", (i0[0] + i1[0]) / 2, (i0[1] + i1[1]) / 2)
        L = s[i + 1] - s[i]
        superior = [(*i0, za0), (*i1, za1), (*e1, za1), (*e0, za0)]
        brocal = [(*i0, zc0 - 0.05), (*i1, zc1 - 0.05), (*i1, za1), (*i0, za0)]
        borde = [(*e0, za0), (*e1, za1), (*e1, zt1), (*e0, zt0)]
        if lado < 0:  # al otro lado la orientación de las caras se invierte
            superior, brocal, borde = superior[::-1], brocal[::-1], borde[::-1]
        m.cara(superior, [(p[0], p[1]) for p in superior], "M_Acera")
        m.cara(brocal, [(0, 0), (L, 0), (L, ALTO_ACERA), (0, ALTO_ACERA)] if lado > 0 else
               [(0, ALTO_ACERA), (L, ALTO_ACERA), (L, 0), (0, 0)], "M_Brocal")
        m.cara(borde, [(0, 0), (L, 0), (L, 1), (0, 1)], "M_Acera")


def sembrar_farolas(puntos, normales, s, medio_ancho, v, terreno, props, separacion=32.0):
    if v["tipo"] not in ("primary", "secondary", "tertiary", "trunk", "residential"):
        return
    if v["tipo"] == "residential":
        separacion = 40.0
    t, lado = separacion / 2, 1
    for i in range(len(puntos) - 1):
        while t <= s[i + 1]:
            f = (t - s[i]) / ((s[i + 1] - s[i]) or 1)
            x = puntos[i][0] + (puntos[i + 1][0] - puntos[i][0]) * f
            y = puntos[i][1] + (puntos[i + 1][1] - puntos[i][1]) * f
            nx, ny = normales[i]
            d = (medio_ancho + 0.5) * lado
            px, py = x + nx * d, y + ny * d
            rumbo = math.degrees(math.atan2(-ny * lado, -nx * lado))  # el brazo mira hacia la calle
            props.append({"tipo": "farola", "x": round(px, 2), "y": round(py, 2),
                          "z": round(terreno.z(px, py) + Z_CALLE_DEFECTO + ALTO_ACERA, 2), "rumbo": round(rumbo, 1)})
            t += separacion
            lado = -lado if v["tipo"] in ("primary", "secondary", "trunk") else lado


def construir_area(ar, terreno, celdas, obeliscos=(), hundida=None):
    if ar["tipo"] in AREAS_SIN_SUPERFICIE:
        return
    anillo = ar["exterior"]
    if hundida:
        if ar.get("id") in hundida.get("omitir_areas", []):
            return
        y_min = hundida.get("recortar_y_min", {}).get(ar.get("id"))
        if y_min is not None:
            anillo = recortar_semiplano(anillo, lambda p: p[1] - y_min)
            if detalle.area_firmada(anillo) < 0:
                anillo = anillo[::-1]
    cx = sum(p[0] for p in anillo) / len(anillo)
    cy = sum(p[1] for p in anillo) / len(anillo)
    m = celdas.malla("Areas", cx, cy)

    if ar["tipo"] == "agua":  # fuente / espejo de agua: borde de muro y lámina de agua horizontal
        z_ref = max(terreno.z(x, y) for x, y in anillo) + Z_AREA["plaza"]
        recortado = bool(hundida and ar.get("id") in hundida.get("recortar_y_min", {}))
        if recortado:
            # el espejo de agua termina en la cascada: el agua rebosa sobre el borde sur (cortina de agua)
            y_min = hundida["recortar_y_min"][ar["id"]]
            alto = ar.get("borde") or 0.5
            TOPE_BORDE[ar["id"]] = z_ref + alto
            x0c, x1c = hundida["x_cascada"]
            detalle.borde_fuente(m, anillo, z_ref, alto, 0.3, "M_Brocal", z_fondo=z_ref - 6.0)
            m.cara([(x0c, y_min - 0.03, z_ref - 1.5), (x1c, y_min - 0.03, z_ref - 1.5), (x1c, y_min - 0.03, z_ref + alto),
                    (x0c, y_min - 0.03, z_ref + alto)], [(0, 1), (x1c - x0c, 1), (x1c - x0c, 0), (0, 0)], "M_Cortina_Agua")
            interior = detalle.offset_anillo(anillo, 0.3)
            planos, tris = triangular(interior)
            for a, b, c in tris:
                pts = [planos[a], planos[b], planos[c]]
                m.cara([(x, y, z_ref + alto - 0.12) for x, y in pts], [(x, y) for x, y in pts], "M_Agua")
            return
        for ox, oy, alto_ob in obeliscos:
            radios = [math.dist(p, (ox, oy)) for p in anillo]
            if alto_ob > 25 and dentro_poligono(ox, oy, anillo) and max(radios) - min(radios) < 1.5:
                # fuente redonda alrededor de un obelisco grande (Plaza Francia): platos escalonados
                detalle.fuente_escalonada(celdas.malla("Detalles", ox, oy), ox, oy, z_ref, sum(radios) / len(radios))
                return
        alto = ar.get("borde") or 0.5
        interior = detalle.borde_fuente(m, anillo, z_ref, alto, 0.3, "M_Brocal")
        planos, tris = triangular(interior)
        z_agua = z_ref + alto - 0.12
        for a, b, c in tris:
            pts = [planos[a], planos[b], planos[c]]
            m.cara([(x, y, z_agua) for x, y in pts], [(x, y) for x, y in pts], "M_Agua")
        return

    planos, tris = triangular(anillo)
    # El terreno está suavizado a escala de ~60 m: con lados de 16 m el error es de centímetros.
    puntos, tris = subdividir(planos, tris, max_lado=16.0, max_nivel=5 if ar["tipo"] == "aerodromo" else 4)
    mat = MATERIAL_AREA.get(ar["tipo"], "M_Grama")
    dz = Z_AREA.get(ar["tipo"], 0.05)
    for a, b, c in tris:
        pts = [puntos[a], puntos[b], puntos[c]]
        tx = sum(p[0] for p in pts) / 3
        ty = sum(p[1] for p in pts) / 3
        for trozo in (fuera_de_huecos(pts) if HUECOS else [pts]):
            celdas.malla("Areas", tx, ty).cara([(x, y, terreno.z(x, y) + dz) for x, y in trozo],
                                               [(x, y) for x, y in trozo], mat)
    if ar["tipo"] in AREAS_ELEVADAS:  # brocal alrededor de la jardinera
        for p, q in zip(densificar(anillo + anillo[:1]), densificar(anillo + anillo[:1])[1:]):
            L = math.dist(p, q)
            m.cara([(p[0], p[1], terreno.z(*p) - 0.05), (q[0], q[1], terreno.z(*q) - 0.05),
                    (q[0], q[1], terreno.z(*q) + dz), (p[0], p[1], terreno.z(*p) + dz)],
                   [(0, 0), (L, 0), (L, dz), (0, dz)], "M_Brocal")


# ---------------------------------------------------------------- aviación

DECLINACION_MAGNETICA = -12.5  # grados (Oeste negativo); Caracas ~2026. Solo se usa para ubicar los números de pista
Z_PISTA = {"runway": 0.14, "taxiway": 0.12, "taxilane": 0.115}


def texto_poligonos(texto, alto):
    """Polígonos 2D (m) de un texto centrado en el origen, con letras de 'alto' metros."""
    curva = bpy.data.curves.new("tmp_texto", "FONT")
    curva.body = texto
    curva.size = alto / 0.72  # los dígitos miden ~72 % del tamaño de la fuente
    curva.align_x = "CENTER"
    curva.align_y = "CENTER"
    obj = bpy.data.objects.new("tmp_texto", curva)
    bpy.context.scene.collection.objects.link(obj)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    # triángulos: los polígonos con hueco (0, 4, 6, 8, 9...) no sobreviven como n-gonos
    me.calc_loop_triangles()
    polys = [[tuple(me.vertices[i].co[:2]) for i in t.vertices] for t in me.loop_triangles]
    polys = [p if (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[1][1] - p[0][1]) * (p[2][0] - p[0][0]) > 0 else p[::-1]
             for p in polys]
    ev.to_mesh_clear()
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(curva)
    return polys


def pintar_texto(m, texto, alto, centro, arriba, altura, material):
    """Texto pintado en el suelo: 'arriba' es la dirección hacia donde se lee (unitaria).
    'altura(x, y)' da la z de la superficie en cada vértice (la pista tiene pendiente transversal)."""
    derecha = (arriba[1], -arriba[0])
    for poly in texto_poligonos(texto, alto):
        pts = [(centro[0] + x * derecha[0] + y * arriba[0], centro[1] + x * derecha[1] + y * arriba[1]) for x, y in poly]
        m.cara([(x, y, altura(x, y)) for x, y in pts], [(x, y) for x, y in pts], material)


FUENTE_LETREROS = "C:/Windows/Fonts/arialbd.ttf"


def texto_3d_local(texto, alto, grosor):
    """Triángulos 3D (x a lo ancho, y hacia arriba desde 0, z = grosor hacia el frente) de un texto con volumen."""
    curva = bpy.data.curves.new("tmp_texto3d", "FONT")
    curva.body = texto
    if Path(FUENTE_LETREROS).exists():
        curva.font = bpy.data.fonts.load(FUENTE_LETREROS, check_existing=True)
    curva.size = alto / 0.72
    curva.extrude = grosor / 2
    obj = bpy.data.objects.new("tmp_texto3d", curva)
    bpy.context.scene.collection.objects.link(obj)
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    me.calc_loop_triangles()
    y0 = min(v.co.y for v in me.vertices) if me.vertices else 0.0
    tris = [[(me.vertices[i].co.x, me.vertices[i].co.y - y0, me.vertices[i].co.z + grosor / 2) for i in t.vertices]
            for t in me.loop_triangles]
    ev.to_mesh_clear()
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(curva)
    return tris


def construir_letrero_3d(cfg, terreno, celdas):
    """Letras corpóreas de pie sobre el piso (p. ej. "YO ♥ CHACAO" en Plaza Francia).
    cfg: partes [[texto, material(, escala)], ...], centro [x, y], frente [dx, dy] (hacia donde se lee), alto, grosor."""
    cx, cy = cfg["centro"]
    z0 = terreno.z(cx, cy) + Z_AREA["plaza"] + cfg.get("elevacion", 0.0)
    if cfg.get("sobre_borde_de") in TOPE_BORDE:  # de pie sobre el borde de una fuente o espejo de agua
        z0 = TOPE_BORDE[cfg["sobre_borde_de"]]
    letrero_en(celdas.malla("Detalles", cx, cy), cfg["partes"], cfg.get("alto", 1.6), cfg.get("grosor", 0.35),
               (cx, cy), cfg["frente"], z0, cfg.get("separacion", 0.25))


def letrero_en(m, partes, alto, grosor, centro, frente, z0, sep=0.25):
    """Letras con volumen centradas en 'centro' (xy), con la base en z0, legibles desde el lado 'frente'."""
    piezas = []
    for parte in partes:
        texto, mat = parte[0], parte[1]
        tris = texto_3d_local(texto, alto * (parte[2] if len(parte) > 2 else 1.0), grosor)
        if tris:
            xs = [p[0] for t in tris for p in t]
            piezas.append((tris, min(xs), max(xs), mat))
    if not piezas:
        return
    ancho = sum(b - a for _, a, b, _ in piezas) + sep * (len(piezas) - 1)
    fx, fy = frente
    Lf = math.hypot(fx, fy) or 1.0
    fx, fy = fx / Lf, fy / Lf
    derecha = (-fy, fx)
    cx, cy = centro
    x = -ancho / 2
    for tris, a, b, mat in piezas:
        for t in tris:
            pts = [(cx + derecha[0] * (x + px - a) + fx * (pz - grosor), cy + derecha[1] * (x + px - a) + fy * (pz - grosor), z0 + py)
                   for px, py, pz in t]
            m.cara(pts, [(px, py) for px, py, _ in t], mat)
        x += (b - a) + sep


def rumbo_magnetico(d):
    verdadero = math.degrees(math.atan2(d[0], d[1])) % 360
    return (verdadero - DECLINACION_MAGNETICA) % 360


def construir_aerovias(osm, terreno, celdas):
    """Pistas y calles de rodaje. Las marcas (umbral, eje, punto de mira) las dibuja el material
    con UV1 = (0..1 a lo ancho, metros a lo largo) y color de vértice A = largo/4000, R = ancho/80."""
    n = 0
    for a in osm.get("aerovias", []):
        pista = a["tipo"] == "runway"
        puntos = densificar(a["puntos"], 6.0)
        if len(puntos) < 2:
            continue
        normales = normales_polilinea(puntos)
        s = longitudes(puntos)
        largo = s[-1]
        h = a["ancho"] / 2
        dz = Z_PISTA.get(a["tipo"], 0.12)
        mat = "M_Pista" if pista else "M_Rodaje"
        color = (min(a["ancho"] / 80.0, 1.0), 1.0 if pista else 0.0, 0.0, min(largo / 4000.0, 1.0))
        for i in range(len(puntos) - 1):
            (x0, y0), (x1, y1) = puntos[i], puntos[i + 1]
            (nx0, ny0), (nx1, ny1) = normales[i], normales[i + 1]
            esquinas = [(x0 - nx0 * h, y0 - ny0 * h), (x1 - nx1 * h, y1 - ny1 * h),
                        (x1 + nx1 * h, y1 + ny1 * h), (x0 + nx0 * h, y0 + ny0 * h)]
            quad = [(x, y, terreno.z(x, y) + dz) for x, y in esquinas]
            uv1 = [(0, s[i]), (0, s[i + 1]), (1, s[i + 1]), (1, s[i])]
            celdas.malla("Aviacion", (x0 + x1) / 2, (y0 + y1) / 2).cara(quad, [(x, y) for x, y in esquinas], mat,
                                                                       uv1=uv1, color=color)
        n += 1
        if not pista or not a.get("ref"):
            continue
        # Números de pista (9 m de alto) a ~52 m de cada umbral, legibles para quien aterriza
        numeros = [t.strip() for t in str(a["ref"]).split("/") if t.strip()]
        extremos = []
        for p0, p1 in ((puntos[0], puntos[min(8, len(puntos) - 1)]), (puntos[-1], puntos[max(-9, -len(puntos))])):
            L = math.dist(p0, p1) or 1.0
            extremos.append((p0, ((p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L)))
        for p0, d in extremos:
            rm = rumbo_magnetico(d)
            num = min(numeros, key=lambda t: abs(((int("".join(c for c in t if c.isdigit()) or 0) * 10 - rm) + 180) % 360 - 180))
            c = (p0[0] + d[0] * 52, p0[1] + d[1] * 52)
            der = (d[1], -d[0])

            def sobre_pista(x, y, c=c, der=der):
                # misma superficie que la pista: interpolación lineal entre sus dos bordes
                lat = (x - c[0]) * der[0] + (y - c[1]) * der[1]
                qx, qy = x - der[0] * lat, y - der[1] * lat
                zi = terreno.z(qx - der[0] * h, qy - der[1] * h)
                zd = terreno.z(qx + der[0] * h, qy + der[1] * h)
                return zi + (zd - zi) * (lat + h) / (2 * h) + Z_PISTA["runway"] + 0.03

            pintar_texto(celdas.malla("Aviacion", *c), num, 9.0, c, d, sobre_pista, "M_Pintura_Blanca")
            print(f"  Pista {a['ref']}: número {num} en el umbral con rumbo magnético {rm:.0f}°")
    return n


def distancia_a_polilinea(p, puntos):
    mejor = 1e18
    for a, b in zip(puntos, puntos[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        mejor = min(mejor, math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dy * t))
    return mejor


def detalles_aviacion(osm, terreno, celdas, props, rnd):
    """Luces de pista y rodaje, marcas de espera, guías de estacionamiento, letreros, cerca y bandera."""
    pistas = [a for a in osm.get("aerovias", []) if a["tipo"] == "runway"]
    rodajes = [a for a in osm.get("aerovias", []) if a["tipo"] != "runway"]
    n_luces = 0

    def luz(tipo, x, y, rumbo=0.0, dz=Z_PISTA["runway"]):
        nonlocal n_luces
        props.append({"tipo": tipo, "x": round(x, 2), "y": round(y, 2), "z": round(terreno.z(x, y) + dz, 2),
                      "rumbo": round(rumbo, 1), "escala": 1.0})
        n_luces += 1

    # Luces de borde de pista (blancas cada 60 m) y de umbral (verdes cada 3 m)
    for pista in pistas:
        pts = densificar(pista["puntos"], 6.0)
        s = longitudes(pts)
        h = pista["ancho"] / 2 + 1.5
        for x, y, d in puntos_a_lo_largo(pts, s, 60.0, 60.0, random.Random(1)):
            for lado in (1, -1):
                luz("luz_pista", x - d[1] * h * lado, y + d[0] * h * lado)
        for p0, p1 in ((pts[0], pts[1]), (pts[-1], pts[-2])):
            L = math.dist(p0, p1) or 1.0
            d = ((p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L)
            k = -h
            while k <= h:
                luz("luz_umbral", p0[0] - d[1] * k, p0[1] + d[0] * k)
                k += 3.0
    # Luces azules de borde de rodaje (cada 30 m) y punto de espera antes de la pista
    for r in rodajes:
        pts = densificar(r["puntos"], 6.0)
        if len(pts) < 2:
            continue
        s = longitudes(pts)
        h = r["ancho"] / 2 + 1.0
        for x, y, d in puntos_a_lo_largo(pts, s, 30.0, 30.0, random.Random(2)):
            if pistas and min(distancia_a_polilinea((x, y), p["puntos"]) for p in pistas) < pistas[0]["ancho"]:
                continue
            for lado in (1, -1):
                luz("luz_rodaje", x - d[1] * h * lado, y + d[0] * h * lado, dz=Z_PISTA.get(r["tipo"], 0.12))
        if r["tipo"] != "taxiway" or not pistas:
            continue
        for extremo, siguiente in ((0, 1), (-1, -2)):
            if min(distancia_a_polilinea(pts[extremo], p["puntos"]) for p in pistas) > 70:
                continue
            # caminar desde la pista hasta 45 m del eje: allí van las marcas de espera y el letrero
            orden = pts if extremo == 0 else pts[::-1]
            for i in range(1, len(orden)):
                q = orden[i]
                if min(distancia_a_polilinea(q, p["puntos"]) for p in pistas) >= 45:
                    a = orden[i - 1]
                    L = math.dist(a, q) or 1.0
                    d = ((a[0] - q[0]) / L, (a[1] - q[1]) / L)  # hacia la pista
                    nrm = (-d[1], d[0])
                    w = r["ancho"] / 2
                    z = lambda x, y: terreno.z(x, y) + Z_PISTA["taxiway"] + 0.012  # noqa: E731
                    esquinas = [(q[0] - nrm[0] * w, q[1] - nrm[1] * w), (q[0] - nrm[0] * w + d[0] * 1.6, q[1] - nrm[1] * w + d[1] * 1.6),
                                (q[0] + nrm[0] * w + d[0] * 1.6, q[1] + nrm[1] * w + d[1] * 1.6), (q[0] + nrm[0] * w, q[1] + nrm[1] * w)]
                    celdas.malla("Aviacion", *q).cara([(x, y, z(x, y)) for x, y in esquinas],
                                                      [(0, 0), (0, 1), (2 * w, 1), (2 * w, 0)], "M_Marca_Espera")
                    sx, sy = q[0] + nrm[0] * (w + 9), q[1] + nrm[1] * (w + 9)
                    props.append({"tipo": "letrero_rodaje", "x": round(sx, 2), "y": round(sy, 2),
                                  "z": round(terreno.z(sx, sy), 2),
                                  "rumbo": round(math.degrees(math.atan2(-d[1], -d[0])), 1), "escala": 1.0})
                    break
    # Guías amarillas de estacionamiento (desde cada puesto hacia la nariz del avión)
    for p in props:
        if p["tipo"] in ("avion_jet", "avion_turbohelice"):
            ang = math.radians(p["rumbo"])
            d = (math.cos(ang), math.sin(ang))
            a = (p["x"] - d[0] * 8, p["y"] - d[1] * 8)
            b = (p["x"] + d[0] * 25, p["y"] + d[1] * 25)
            nrm = (-d[1] * 0.08, d[0] * 0.08)
            esquinas = [(a[0] - nrm[0], a[1] - nrm[1]), (b[0] - nrm[0], b[1] - nrm[1]), (b[0] + nrm[0], b[1] + nrm[1]), (a[0] + nrm[0], a[1] + nrm[1])]
            celdas.malla("Aviacion", p["x"], p["y"]).cara([(x, y, terreno.z(x, y) + Z_AREA["plataforma"] + 0.012) for x, y in esquinas],
                                                         [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Pintura_Amarilla")
    # Cerca perimetral de la base: muro bajo + reja de barrotes con el tope curvo hacia la calle.
    # Se parte en tramos de ~60 m para que cada tramo caiga en su celda.
    for a in osm["areas"]:
        if a["tipo"] != "aerodromo":
            continue
        anillo = a["exterior"] if detalle.area_firmada(a["exterior"]) > 0 else a["exterior"][::-1]
        puntos = densificar(anillo + anillo[:1], 3.0)
        afuera = [(-n[0], -n[1]) for n in normales_polilinea(puntos)]  # la izquierda del anillo antihorario es adentro
        zs = [terreno.z(*q) for q in puntos]
        for i0 in range(0, len(puntos) - 1, 20):
            i1 = min(i0 + 21, len(puntos))
            detalle.cerca_perimetral(celdas.malla("Detalles", *puntos[i0]), puntos[i0:i1], afuera[i0:i1], zs[i0:i1])
    # Bandera junto a la torre de control
    for e in osm["edificios"]:
        if e["tipo"] == "control_tower":
            cx = sum(q[0] for q in e["exterior"]) / len(e["exterior"])
            cy = sum(q[1] for q in e["exterior"]) / len(e["exterior"])
            bx, by = cx + 22, cy - 18
            props.append({"tipo": "bandera", "x": round(bx, 2), "y": round(by, 2), "z": round(terreno.z(bx, by), 2),
                          "rumbo": 255.0, "escala": 1.0})
    return n_luces


def construir_helipuertos(osm, terreno, celdas, props=None, lado=18.0):
    """Helipuertos a nivel del suelo (los de azotea se omiten: OSM no trae su altura de forma fiable).
    Más de la mitad recibe un helicóptero estacionado."""
    rnd = random.Random(21)
    n = 0
    for p in osm["puntos"]:
        if p["tipo"] != "helipuerto":
            continue
        if any(dentro_poligono(p["x"], p["y"], e["exterior"]) for e in osm["edificios"]
               if abs(e["exterior"][0][0] - p["x"]) < 150 and abs(e["exterior"][0][1] - p["y"]) < 150):
            continue
        m = celdas.malla("Aviacion", p["x"], p["y"])
        z = terreno.z(p["x"], p["y"]) + 0.1
        hl = lado / 2
        esquinas = [(p["x"] - hl, p["y"] - hl), (p["x"] + hl, p["y"] - hl), (p["x"] + hl, p["y"] + hl), (p["x"] - hl, p["y"] + hl)]
        m.cara([(x, y, z) for x, y in esquinas], esquinas, "M_Plataforma")
        pintar_texto(m, "H", 5.0, (p["x"], p["y"]), (0.0, 1.0), lambda x, y: z + 0.01, "M_Pintura_Blanca")
        if props is not None and rnd.random() < 0.6:
            props.append({"tipo": "helicoptero", "x": p["x"], "y": p["y"], "z": round(z, 2),
                          "rumbo": round(rnd.uniform(0, 360), 1), "escala": 1.0})
        n += 1
    return n


def construir_barrera(b, terreno, celdas):
    ancho, alto_def, mat = BARRERAS[b["tipo"]]
    puntos = densificar(b["puntos"], 2.0)
    if len(puntos) < 2:
        return
    normales = normales_polilinea(puntos)
    zs = [terreno.z(*p) + Z_AREA["plaza"] for p in puntos]
    m = celdas.malla("Detalles", *puntos[len(puntos) // 2])
    detalle.extruir_polilinea(m, puntos, normales, zs, ancho, b.get("altura") or alto_def, mat)


def construir_cebras(osm, terreno, celdas, largo=3.0):
    """Paso peatonal pintado en cada nodo 'crossing' que cae sobre una calle."""
    nodo_via = {}
    for v in osm["vias"]:
        if v["tipo"] in TIPOS_SENDERO or v["tunel"]:
            continue
        for k, nd in enumerate(v["nodos"]):
            if nd is not None:
                nodo_via.setdefault(nd, (v, k))
    n = 0
    for p in osm["puntos"]:
        if p["tipo"] != "cruce" or p.get("marcas") in ("no", "none", "unmarked") or p["id"] not in nodo_via:
            continue
        v, k = nodo_via[p["id"]]
        pts = v["puntos"]
        a, b = pts[max(k - 1, 0)], pts[min(k + 1, len(pts) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        d = (dx / L, dy / L)
        nrm = (-d[1], d[0])
        w = v["ancho"] / 2 - 0.3
        z_off = Z_CALLE.get(v["tipo"].replace("_link", ""), Z_CALLE_DEFECTO) + 0.015
        esquinas = []
        for s_l, s_a in ((-1, -1), (-1, 1), (1, 1), (1, -1)):
            x = p["x"] + d[0] * largo / 2 * s_l + nrm[0] * w * s_a
            y = p["y"] + d[1] * largo / 2 * s_l + nrm[1] * w * s_a
            esquinas.append((x, y, terreno.z(x, y) + z_off))
        # orden: (atrás,der) (atrás,izq) (adelante,izq) (adelante,der) -> normal hacia arriba
        quad = [esquinas[0], esquinas[3], esquinas[2], esquinas[1]]
        uv = [(0, 0), (0, largo), (2 * w, largo), (2 * w, 0)]  # u = metros a lo ancho de la calle
        celdas.malla("Calles", p["x"], p["y"]).cara(quad, uv, "M_Cebra")
        n += 1
    return n


# Huecos rectangulares (xmin, xmax, ymin, ymax) donde no va terreno ni superficie de OSM (p. ej. la bajada
# al Metro de Plaza Francia, que se modela aparte). Se llenan en main() desde zonas.json.
HUECOS = []
TOPE_BORDE = {}  # id de área de agua -> z del borde (para apoyar letreros encima)


def recortar_semiplano(poli, f):
    """Parte de un polígono 2D donde f(p) >= 0 (f lineal). Sutherland-Hodgman contra un semiplano."""
    salida = []
    for i, p in enumerate(poli):
        q = poli[(i + 1) % len(poli)]
        fp, fq = f(p), f(q)
        if fp >= 0:
            salida.append(p)
        if (fp >= 0) != (fq >= 0):
            t = fp / (fp - fq)
            salida.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return salida


def fuera_de_huecos(poli):
    """Trozos convexos de un polígono convexo que quedan fuera de todos los HUECOS."""
    trozos = [poli]
    for x0, x1, y0, y1 in HUECOS:
        nuevos = []
        for t in trozos:
            xs, ys = [p[0] for p in t], [p[1] for p in t]
            if max(xs) <= x0 or min(xs) >= x1 or max(ys) <= y0 or min(ys) >= y1:
                nuevos.append(t)
                continue
            resto = t
            for f in (lambda p: x0 - p[0], lambda p: p[0] - x1, lambda p: y0 - p[1], lambda p: p[1] - y1):
                fuera = recortar_semiplano(resto, f)
                if len(fuera) >= 3:
                    nuevos.append(fuera)
                resto = recortar_semiplano(resto, lambda p, f=f: -f(p))
                if len(resto) < 3:
                    break
        trozos = nuevos
    return trozos


def en_hueco(x, y):
    return any(x0 < x < x1 and y0 < y < y1 for x0, x1, y0, y1 in HUECOS)


def construir_terreno(terreno, celdas, paso=2):
    h, res = terreno.h, terreno.res
    n = h.shape[0]
    for f in range(0, n - paso, paso):
        for c in range(0, n - paso, paso):
            x0, x1 = terreno.xmin + c * res, terreno.xmin + (c + paso) * res
            y0, y1 = terreno.ymax - f * res, terreno.ymax - (f + paso) * res
            quad = [(x0, y1, float(h[f + paso, c])), (x1, y1, float(h[f + paso, c + paso])),
                    (x1, y0, float(h[f, c + paso])), (x0, y0, float(h[f, c]))]
            m = celdas.malla("Terreno", (x0 + x1) / 2, (y0 + y1) / 2)
            if HUECOS and any(min(x0, x1) < hx1 and max(x0, x1) > hx0 and min(y0, y1) < hy1 and max(y0, y1) > hy0
                              for hx0, hx1, hy0, hy1 in HUECOS):
                for trozo in fuera_de_huecos([p[:2] for p in quad]):
                    m.cara([(x, y, terreno.z(x, y)) for x, y in trozo], [(x, y) for x, y in trozo], "M_Terreno")
                continue
            m.cara(quad, [(p[0], p[1]) for p in quad], "M_Terreno")


def props_osm(osm, terreno, vias):
    """Árboles, semáforos, paradas, etc. de OSM. Los semáforos se desplazan a la orilla de su calle."""
    props = []
    nodo_via = {}
    for v in vias:
        for k, nd in enumerate(v["nodos"]):
            if nd is not None and v["tipo"] not in TIPOS_SENDERO:
                nodo_via.setdefault(nd, (v, k))
    rnd = random.Random(7)
    for p in osm["puntos"]:
        x, y, rumbo = p["x"], p["y"], rnd.uniform(0, 360)
        if p["tipo"] in ("semaforo", "parada") and p["id"] in nodo_via:
            v, k = nodo_via[p["id"]]
            pts = v["puntos"]
            a, b = pts[max(k - 1, 0)], pts[min(k + 1, len(pts) - 1)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy) or 1.0
            d = v["ancho"] / 2 + 0.8
            x, y = x - dy / L * d, y + dx / L * d
            rumbo = math.degrees(math.atan2(dy, dx))
        if p["tipo"] in ("cruce", "helipuerto", "puesto_aeronave"):  # se tratan aparte
            continue
        if p["tipo"] == "manga":
            rumbo = 255.0  # alisios del Este: la manga apunta hacia el Oeste-Suroeste
        escala = 1.0
        if p["tipo"] == "arbol":
            escala = round(rnd.uniform(0.75, 1.3), 2)
        props.append({"tipo": p["tipo"], "x": round(x, 2), "y": round(y, 2), "z": round(terreno.z(x, y), 2),
                      "rumbo": round(rumbo, 1), "escala": escala, "nombre": p.get("nombre"),
                      "altura": p.get("altura")})
    return props


def dentro_poligono(x, y, anillo):
    dentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i]
        xj, yj = anillo[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


# ---------------------------------------------------------------- vehículos

VEHICULOS_ESTACIONADOS = [("sedan", 0.42), ("hatchback", 0.22), ("camioneta", 0.22), ("pickup", 0.08), ("moto", 0.06)]
VEHICULOS_CIRCULANDO = [("sedan", 0.38), ("hatchback", 0.18), ("camioneta", 0.2), ("pickup", 0.06),
                        ("por_puesto", 0.08), ("moto", 0.1)]
COLORES_AUTO = [((0.85, 0.85, 0.83), 0.28), ((0.55, 0.56, 0.57), 0.2), ((0.02, 0.02, 0.022), 0.15),
                ((0.22, 0.23, 0.24), 0.1), ((0.45, 0.03, 0.02), 0.08), ((0.03, 0.08, 0.25), 0.07),
                ((0.45, 0.40, 0.30), 0.05), ((0.04, 0.12, 0.06), 0.03), ((0.85, 0.65, 0.05), 0.04)]
TIPOS_ESTACIONAMIENTO = {"residential", "tertiary", "secondary", "unclassified", "living_street", "tertiary_link"}
TIPOS_TRAFICO = {"motorway", "trunk", "primary", "secondary", "tertiary",
                 "motorway_link", "trunk_link", "primary_link", "secondary_link"}


def elegir(opciones, rnd):
    r, acum = rnd.random(), 0.0
    for valor, peso in opciones:
        acum += peso
        if r <= acum:
            return valor
    return opciones[-1][0]


def puntos_a_lo_largo(puntos, s, paso_min, paso_max, rnd):
    """(x, y, dirección unitaria) cada paso aleatorio a lo largo de una polilínea."""
    t = rnd.uniform(0, paso_max)
    for i in range(len(puntos) - 1):
        L = s[i + 1] - s[i]
        if L <= 0:
            continue
        d = ((puntos[i + 1][0] - puntos[i][0]) / L, (puntos[i + 1][1] - puntos[i][1]) / L)
        while t <= s[i + 1]:
            f = (t - s[i]) / L
            yield (puntos[i][0] + (puntos[i + 1][0] - puntos[i][0]) * f,
                   puntos[i][1] + (puntos[i + 1][1] - puntos[i][1]) * f, d)
            t += rnd.uniform(paso_min, paso_max)


def sembrar_vehiculos(osm, terreno, intersecciones, rnd, prob_estacionado=0.35):
    """Carros estacionados junto al brocal y circulando por su carril (se maneja por la derecha)."""
    salida = []

    def agregar(tipo, x, y, rumbo, off):
        color = elegir(COLORES_AUTO, rnd) if tipo != "por_puesto" else (0.85, 0.85, 0.83)
        salida.append({"tipo": tipo, "x": round(x, 2), "y": round(y, 2),
                       "z": round(terreno.z(x, y) + off, 2), "rumbo": round(rumbo, 1), "escala": 1.0,
                       "color": [round(c * rnd.uniform(0.9, 1.05), 3) for c in color]})

    for v in osm["vias"]:
        if v["tunel"] or v["puente"] or len(v["puntos"]) < 2:
            continue
        tipo_base = v["tipo"]
        off = Z_CALLE.get(tipo_base.replace("_link", ""), Z_CALLE_DEFECTO)
        s = longitudes(v["puntos"])
        pos_inter = [s[k] for k, nd in enumerate(v["nodos"]) if nd in intersecciones]
        h = v["ancho"] / 2
        for s0, s1 in tramos_fuera(v["puntos"], s, pos_inter, h + 7.0):
            tramo = sub_polilinea(v["puntos"], s, s0, s1)
            st = longitudes(tramo)
            # estacionados (en calles locales, a ambos lados)
            if tipo_base in TIPOS_ESTACIONAMIENTO and v["ancho"] >= 5.5:
                for x, y, d in puntos_a_lo_largo(tramo, st, 5.2, 6.5, rnd):
                    if rnd.random() > prob_estacionado:
                        continue
                    lado = rnd.choice((1, -1))
                    nx, ny = -d[1] * lado, d[0] * lado
                    tipo = elegir(VEHICULOS_ESTACIONADOS, rnd)
                    rumbo = math.degrees(math.atan2(d[1], d[0])) + (0 if lado < 0 else 180)
                    agregar(tipo, x + nx * (h - 1.05), y + ny * (h - 1.05), rumbo + rnd.uniform(-3, 3), off)
            # tráfico
            if tipo_base in TIPOS_TRAFICO:
                carriles = max(1, int(round(v["carriles"])))
                ancho_c = v["ancho"] / carriles
                for i in range(carriles):
                    if v["sentido_unico"]:
                        desplaz, sentido = -h + (i + 0.5) * ancho_c, 1
                    else:
                        mitad = max(1, carriles // 2)
                        if i < mitad:
                            desplaz, sentido = -h + (i + 0.5) * ancho_c, 1      # derecha: a favor
                        else:
                            desplaz, sentido = -h + (i + 0.5) * ancho_c, -1     # izquierda: en contra
                    for x, y, d in puntos_a_lo_largo(tramo, st, 14.0, 70.0, rnd):
                        nx, ny = -d[1], d[0]
                        rumbo = math.degrees(math.atan2(d[1], d[0])) + (0 if sentido > 0 else 180)
                        agregar(elegir(VEHICULOS_CIRCULANDO, rnd), x + nx * desplaz, y + ny * desplaz, rumbo, off)
    return salida


def sembrar_flores(osm, terreno, zona, props, rnd):
    """Macizos de flores (cannas rojas y amarillas) en las jardineras elevadas de la zona de detalle."""
    cfg = zona["flores"]
    det = zona.get("detalle", {"centro": [0, 0], "radio_m": 0})
    paso = 1.0 / math.sqrt(cfg.get("densidad_m2", 2.0))
    n = 0
    for ar in osm["areas"]:
        if ar["tipo"] != "parque":
            continue
        anillo = ar["exterior"]
        xs, ys = [p[0] for p in anillo], [p[1] for p in anillo]
        if math.hypot((min(xs) + max(xs)) / 2 - det["centro"][0], (min(ys) + max(ys)) / 2 - det["centro"][1]) > det["radio_m"]:
            continue
        y = min(ys) + paso / 2
        while y < max(ys):
            x = min(xs) + paso / 2
            while x < max(xs):
                px, py = x + rnd.uniform(-0.4, 0.4) * paso, y + rnd.uniform(-0.4, 0.4) * paso
                if dentro_poligono(px, py, anillo) and distancia_a_polilinea((px, py), anillo + anillo[:1]) > 0.45:
                    r, acum, tipo = rnd.random(), 0.0, "canna_hojas"
                    for t, peso in cfg["tipos"]:
                        acum += peso
                        if r <= acum:
                            tipo = t
                            break
                    props.append({"tipo": tipo, "x": round(px, 2), "y": round(py, 2),
                                  "z": round(terreno.z(px, py) + Z_AREA["parque"], 2),
                                  "rumbo": round(rnd.uniform(0, 360), 1), "escala": round(rnd.uniform(0.8, 1.25), 2)})
                    n += 1
                x += paso
            y += paso
    return n


def edificio_de_base(ed, aerodromos, puntos_rodaje):
    """Dentro de un aeródromo los edificios sin etiqueta son hangares (grandes, o medianos junto a un rodaje)
    o edificios militares bajos. Los hangares reciben 'frente': dirección hacia el rodaje más cercano."""
    ext = ed["exterior"]
    cx = sum(p[0] for p in ext) / len(ext)
    cy = sum(p[1] for p in ext) / len(ext)
    if not any(dentro_poligono(cx, cy, a) for a in aerodromos):
        return ed
    ed = dict(ed)
    cercano = min(puntos_rodaje, key=lambda q: math.dist(q, (cx, cy))) if puntos_rodaje else None
    junto_a_rodaje = cercano is not None and math.dist(cercano, (cx, cy)) < 70
    if ed["tipo"] == "hangar" or ed["area"] > 700 or (ed["area"] > 200 and junto_a_rodaje):
        ed["tipo"] = "hangar"
        if ed.get("altura_estimada"):  # el DSM confunde los árboles vecinos con el techo
            ed["altura"] = min(max(ed["altura"], 8.0), 14.0) if ed["area"] > 700 else 7.5
        if cercano is not None:
            L = math.dist(cercano, (cx, cy)) or 1.0
            ed["frente"] = ((cercano[0] - cx) / L, (cercano[1] - cy) / L)
    else:
        ed["tipo"] = "military"
        if ed.get("altura_estimada"):
            ed["altura"], ed["niveles"] = min(ed["altura"], 7.0), min(ed["niveles"], 2)
    return ed


TIPOS_AERONAVE = [("helicoptero", 0.35), ("avion_turbohelice", 0.4), ("avion_jet", 0.25)]


def elegir_aeronave(rnd):
    r, acum = rnd.random(), 0.0
    for tipo, peso in TIPOS_AERONAVE:
        acum += peso
        if r <= acum:
            return tipo
    return TIPOS_AERONAVE[-1][0]


def props_aeronaves(osm, terreno, rnd):
    """Aeronaves en los puestos de estacionamiento, con la nariz hacia la pista más cercana."""
    pistas = [a["puntos"] for a in osm.get("aerovias", []) if a["tipo"] == "runway"]
    salida = []
    for p in osm["puntos"]:
        if p["tipo"] != "puesto_aeronave":
            continue
        rumbo = rnd.uniform(0, 360)
        if pistas:
            cercano = min((q for pista in pistas for q in densificar(pista, 20.0)), key=lambda q: math.dist(q, (p["x"], p["y"])))
            rumbo = math.degrees(math.atan2(cercano[1] - p["y"], cercano[0] - p["x"])) + rnd.uniform(-8, 8)
        salida.append({"tipo": elegir_aeronave(rnd), "x": p["x"], "y": p["y"], "z": round(terreno.z(p["x"], p["y"]) + 0.1, 2),
                       "rumbo": round(rumbo, 1), "escala": 1.0})
    return salida


def props_azotea(ed, techo, rnd):
    """Tanques de agua y casilla de ascensores: lo más típico de las azoteas caraqueñas."""
    _, _, z, borde = techo
    if ed["tipo"] in ("house", "detached", "roof", "garage", "obelisk") or ed["area"] < 120:
        return []
    xs, ys = [p[0] for p in borde], [p[1] for p in borde]
    salida = []

    def punto_libre(margen):
        for _ in range(30):
            x, y = rnd.uniform(min(xs), max(xs)), rnd.uniform(min(ys), max(ys))
            if all(dentro_poligono(x + dx, y + dy, borde) for dx, dy in
                   ((margen, 0), (-margen, 0), (0, margen), (0, -margen))):
                return x, y
        return None

    if ed["niveles"] >= 6:
        p = punto_libre(2.5)
        if p:
            salida.append({"tipo": "casilla", "x": round(p[0], 2), "y": round(p[1], 2), "z": round(z, 2),
                           "rumbo": round(rnd.choice([0, 90, 180, 270]) + rnd.uniform(-3, 3), 1),
                           "escala": round(rnd.uniform(0.9, 1.3), 2)})
    if ed["niveles"] >= 3 and rnd.random() < 0.75:
        for _ in range(rnd.choice([1, 1, 2, 3])):
            p = punto_libre(1.3)
            if p:
                salida.append({"tipo": "tanque", "x": round(p[0], 2), "y": round(p[1], 2), "z": round(z, 2),
                               "rumbo": round(rnd.uniform(0, 360), 1), "escala": round(rnd.uniform(0.8, 1.15), 2)})
    return salida


# ---------------------------------------------------------------- exportación

def limpiar_escena():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    for me in list(bpy.data.meshes):
        bpy.data.meshes.remove(me)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0


COLORES_VISTA = {  # vista rápida en Blender; 03b_realismo.py los reemplaza por materiales con texturas
    "M_Fachada_Friso": (0.80, 0.74, 0.62), "M_Fachada_Beige": (0.82, 0.75, 0.60),
    "M_Fachada_Ladrillo": (0.55, 0.30, 0.22), "M_Fachada_Ceramica": (0.70, 0.68, 0.64),
    "M_Fachada_Concreto": (0.60, 0.60, 0.58), "M_Fachada_Comercial": (0.75, 0.70, 0.65),
    "M_Fachada_Casa": (0.88, 0.85, 0.78),
    "M_Techo": (0.45, 0.30, 0.25), "M_Techo_Concreto": (0.55, 0.54, 0.52),
    "M_Vidrio": (0.10, 0.13, 0.16), "M_Vidrio_Oficina": (0.18, 0.28, 0.35), "M_Vidrio_Local": (0.12, 0.14, 0.15),
    "M_Marco": (0.65, 0.66, 0.68), "M_Reja": (0.05, 0.05, 0.05), "M_Santamaria": (0.50, 0.52, 0.54),
    "M_Asfalto": (0.08, 0.08, 0.085), "M_Acera": (0.55, 0.54, 0.52), "M_Cebra": (0.85, 0.85, 0.85),
    "M_Brocal": (0.75, 0.75, 0.72), "M_Sendero": (0.60, 0.57, 0.52), "M_Escalera": (0.6, 0.6, 0.6),
    "M_Plaza": (0.72, 0.66, 0.58), "M_Grama": (0.20, 0.38, 0.12), "M_Cancha": (0.25, 0.45, 0.30),
    "M_Agua": (0.10, 0.25, 0.30), "M_Seto": (0.10, 0.25, 0.08), "M_Muro": (0.78, 0.74, 0.66),
    "M_Cerca": (0.1, 0.1, 0.1), "M_Terreno": (0.35, 0.33, 0.25), "M_Monumento": (0.86, 0.73, 0.56),
    "M_Pista": (0.07, 0.07, 0.075), "M_Rodaje": (0.09, 0.09, 0.09), "M_Plataforma": (0.5, 0.5, 0.48),
    "M_Pintura_Blanca": (0.9, 0.9, 0.88), "M_Zinc": (0.6, 0.62, 0.63), "M_Pasto": (0.12, 0.3, 0.06),
    "M_Pintura_Amarilla": (0.85, 0.6, 0.05), "M_Marca_Espera": (0.85, 0.6, 0.05),
    "M_Hangar_Pared": (0.82, 0.8, 0.74), "M_Muro_Cerca": (0.62, 0.61, 0.58), "M_Barrotes": (0.03, 0.03, 0.03),
    "M_Metal_Oscuro": (0.04, 0.045, 0.05),
    "M_Relieve": (0.75, 0.63, 0.48), "M_Placa": (0.22, 0.14, 0.07), "M_Piedra_Fuente": (0.5, 0.4, 0.3),
    "M_Azulejo": (0.06, 0.47, 0.48), "M_Agua_Fuente": (0.05, 0.36, 0.4), "M_Chorro": (0.85, 0.92, 0.95),
    "M_Cortina_Agua": (0.8, 0.88, 0.92), "M_Letras": (0.86, 0.86, 0.84), "M_Corazon": (0.72, 0.02, 0.03),
    "M_Muro_Blanco": (0.9, 0.9, 0.87), "M_Pintura_Verde": (0.03, 0.3, 0.2), "M_Azulejo_Claro": (0.75, 0.84, 0.86),
    "M_Lamina_Agua": (0.9, 0.95, 0.97), "M_Metro_Boca": (0.01, 0.01, 0.012), "M_Tierra_Jardin": (0.15, 0.11, 0.08),
    "M_Franjas_Azul": (0.35, 0.45, 0.62), "M_Franjas_Blanca": (0.62, 0.63, 0.63), "M_Muro_Cortina": (0.04, 0.05, 0.06),
    "M_Concreto_Claro": (0.8, 0.79, 0.76), "M_Fachada_Gris": (0.7, 0.71, 0.72), "M_Losa_Blanca": (0.84, 0.84, 0.82),
    "M_Antepecho": (0.9, 0.9, 0.88), "M_Letrero_Rojo": (0.7, 0.03, 0.03), "M_Letrero_Azul": (0.06, 0.2, 0.52),
    "M_Franjas_Verde": (0.4, 0.46, 0.43), "M_Franjas_Gris": (0.45, 0.45, 0.43), "M_Quiebrasol": (0.78, 0.78, 0.75),
    "M_Techo_Plegado": (0.5, 0.55, 0.45), "M_Vidrio_Negro": (0.02, 0.02, 0.025), "M_Mural_CCCT": (0.6, 0.6, 0.58),
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("Indica la zona: blender -b -P 03_construir_zona.py -- altamira")
    zona = cargar_zona(argv[0])
    exportar_terreno = "--exportar-terreno" in argv
    sin_fbx = "--sin-fbx" in argv

    carpeta = carpeta_zona(zona)
    with open(carpeta / "osm_local.json", encoding="utf-8") as f:
        osm = json.load(f)
    terreno = Terreno(carpeta)
    celdas = Celdas(terreno.meta["extension_local"], zona["celda_m"])
    rnd = random.Random(42)

    print(f"Construyendo '{zona['nombre']}': {len(osm['edificios'])} edificios, {len(osm['vias'])} vías")
    limpiar_escena()
    for nombre, rgb in COLORES_VISTA.items():
        mat = bpy.data.materials.new(nombre)
        mat.diffuse_color = (*rgb, 1.0)

    props = props_osm(osm, terreno, osm["vias"])
    zona_detalle = zona.get("detalle", {"centro": [0, 0], "radio_m": 0})
    HITOS.update(zona.get("hitos", {}))
    DETALLES_EXTRA.extend(zona.get("detalles_extra", []))
    global PLAZA
    PLAZA = tuple(zona_detalle["centro"])
    aerodromos = [a["exterior"] for a in osm["areas"] if a["tipo"] == "aerodromo"]
    puntos_rodaje = [q for a in osm.get("aerovias", []) for q in densificar(a["puntos"], 10.0)]
    for ed in osm["edificios"]:
        if aerodromos and ed["tipo"] in ("yes", "military", "hangar"):
            ed = edificio_de_base(ed, aerodromos, puntos_rodaje)
        techo = construir_edificio(ed, terreno, celdas, rnd, props, zona_detalle)
        if techo:
            props += props_azotea(ed, techo, rnd)

    intersecciones = nodos_interseccion(osm["vias"])
    for v in sorted(osm["vias"], key=lambda v: v["capa"]):
        construir_via(v, terreno, celdas, intersecciones, props)
    vehiculos = sembrar_vehiculos(osm, terreno, intersecciones, random.Random(31))
    props += vehiculos
    print(f"  Vehículos: {len(vehiculos)}")
    obeliscos = [(sum(p[0] for p in e["exterior"]) / len(e["exterior"]), sum(p[1] for p in e["exterior"]) / len(e["exterior"]),
                  e["altura"]) for e in osm["edificios"] if e["tipo"] == "obelisk"]
    hundida = zona.get("plaza_hundida")
    if hundida:
        HUECOS.append(tuple(hundida["hueco"]))
        props[:] = [p for p in props if not en_hueco(p["x"], p["y"])]
    for ar in sorted(osm["areas"], key=lambda a: a["tipo"] == "agua"):
        construir_area(ar, terreno, celdas, obeliscos, hundida)
    if hundida:
        hx0, hx1, hy0, hy1 = hundida["hueco"]
        xc = (hx0 + hx1) / 2
        nivel = terreno.z(xc, hy1 + 2.0) + Z_AREA["plaza"]
        nivel_sur = terreno.z(xc, hy0 - 2.0) + Z_AREA["plaza"]
        detalle.plaza_hundida(celdas.malla("Detalles", xc, (hy0 + hy1) / 2), hundida, nivel, props, random.Random(77),
                              zona.get("flores"), nivel_sur)
        for x, y, tipo in hundida.get("banderas", []):
            props.append({"tipo": tipo, "x": x, "y": y, "z": round(terreno.z(x, y) + Z_AREA["plaza"], 2), "rumbo": 90.0, "escala": 0.8})
    if zona.get("flores"):
        print(f"  Flores: {sembrar_flores(osm, terreno, zona, props, random.Random(78))}")
    for letrero in zona.get("letreros_3d", []):
        construir_letrero_3d(letrero, terreno, celdas)
    for b in osm.get("barreras", []):
        if HUECOS and any(en_hueco(*q) for q in b["puntos"]):
            continue
        construir_barrera(b, terreno, celdas)
    n_cebras = construir_cebras(osm, terreno, celdas)
    print(f"  Pasos de cebra: {n_cebras}, barreras: {len(osm.get('barreras', []))}")
    if osm.get("aerovias"):
        aeronaves = props_aeronaves(osm, terreno, random.Random(17))
        props += aeronaves
        print(f"  Aviación: {construir_aerovias(osm, terreno, celdas)} pistas/rodajes, "
              f"{construir_helipuertos(osm, terreno, celdas, props)} helipuertos, {len(aeronaves)} aeronaves en puestos")
        print(f"  Luces de pista y rodaje: {detalles_aviacion(osm, terreno, celdas, props, random.Random(23))}")
    # Vista previa a 8 m; si se exporta como malla, a 4 m (más detalle pesa demasiado con 8 GB de RAM).
    construir_terreno(terreno, celdas, paso=2 if exportar_terreno else 4)

    # Crear objetos por celda
    raiz = bpy.data.collections.new(zona["id"])
    bpy.context.scene.collection.children.link(raiz)
    colecciones = {}
    objetos_por_celda = {}
    for (capa, i, j), malla in sorted(celdas.mallas.items()):
        if malla.vacia():
            continue
        if capa not in colecciones:
            colecciones[capa] = bpy.data.collections.new(capa)
            raiz.children.link(colecciones[capa])
        obj = malla.crear_objeto(f"{capa}_{i}_{j}", colecciones[capa])
        if capa == "Terreno" and not exportar_terreno:
            continue
        objetos_por_celda.setdefault((i, j), []).append(obj)

    ruta_blend = carpeta / f"{zona['id']}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(ruta_blend), compress=True)
    print(f"  Escena guardada: {ruta_blend}")

    export = carpeta / "export"
    export.mkdir(exist_ok=True)
    archivos = []
    if not sin_fbx:
        for viejo in export.glob("celda_*.fbx"):
            viejo.unlink()
        for (i, j), objs in sorted(objetos_por_celda.items()):
            bpy.ops.object.select_all(action="DESELECT")
            for o in objs:
                o.select_set(True)
            bpy.context.view_layer.objects.active = objs[0]
            ruta = export / f"celda_{i}_{j}.fbx"
            bpy.ops.export_scene.fbx(filepath=str(ruta), use_selection=True, object_types={"MESH"},
                                     apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS",
                                     mesh_smooth_type="FACE", use_mesh_modifiers=False,
                                     add_leaf_bones=False, bake_anim=False, axis_forward="-Z", axis_up="Y")
            archivos.append(ruta.name)
        print(f"  {len(archivos)} celdas exportadas en {export}")

    with open(export / "props.json", "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False)

    inicio = zona.get("inicio_jugador", {"x": 0, "y": 0})
    meta = {
        "zona": zona["id"], "nombre": zona["nombre"], "centro": zona["centro"],
        "celdas": archivos,
        "materiales": sorted({m for malla in celdas.mallas.values() for m in malla.materiales}),
        "terreno": terreno.meta,
        "inicio_jugador": {"x": inicio["x"], "y": inicio["y"], "z": round(terreno.z(inicio["x"], inicio["y"]) + 1.0, 2)},
        "conteo_props": {t: sum(1 for p in props if p["tipo"] == t) for t in sorted({p["tipo"] for p in props})},
    }
    with open(export / "meta_zona.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  Props: {meta['conteo_props']}")
    print("Listo.")


if __name__ == "__main__":
    main()
