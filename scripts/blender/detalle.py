"""Geometría de detalle para edificios y mobiliario (lo usa 03_construir_zona.py).

Todo es geometría real con UV en metros, compatible con Unreal:
  * Fachadas con ventanas hundidas (vano + vidrio), rejas, locales con santamaría,
    muros cortina en oficinas y aires acondicionados de ventana (como props).
  * Pretiles (muro perimetral del techo), bordes de fuentes, setos y muros.

Convención de anillos (igual que 03): exterior antihorario, huecos horario. En ambos casos
el lado izquierdo de cada arista apunta hacia la masa del edificio.
UV de vidrios, rejas y santamarías: (0..1, 0..1) dentro de cada abertura; el material dibuja
marcos, divisiones y barrotes con esas coordenadas.
"""

import math

# ---------------------------------------------------------------- estilos de fachada

ESTILOS = {
    # piso, planta baja, vano (ancho de módulo), ventana (ancho, alto), antepecho, fondo del vano
    "residencial": dict(piso=2.8, pb=3.6, vano=3.0, ventana=(1.5, 1.3), antepecho=0.9, fondo=0.16,
                        vidrio="M_Vidrio", ac=0.28, rejas_pisos=2, locales=0.55),
    "oficina": dict(piso=3.6, pb=4.5, vano=1.5, ventana=(1.38, 2.6), antepecho=0.5, fondo=0.07,
                    vidrio="M_Vidrio_Oficina", ac=0.0, rejas_pisos=0, locales=0.0),
    "comercial": dict(piso=3.0, pb=4.2, vano=3.2, ventana=(1.8, 1.4), antepecho=0.9, fondo=0.15,
                      vidrio="M_Vidrio", ac=0.2, rejas_pisos=1, locales=1.0),
    "casa": dict(piso=3.0, pb=3.0, vano=3.4, ventana=(1.2, 1.25), antepecho=1.0, fondo=0.14,
                 vidrio="M_Vidrio", ac=0.15, rejas_pisos=9, locales=0.0),
    "institucional": dict(piso=3.4, pb=3.8, vano=3.6, ventana=(2.2, 1.6), antepecho=0.9, fondo=0.2,
                          vidrio="M_Vidrio", ac=0.1, rejas_pisos=1, locales=0.0),
    # hangares: paredes de zinc sin ventanas (se construyen lisos)
    "hangar": dict(piso=12.0, pb=12.0, vano=6.0, ventana=(0.0, 0.0), antepecho=0.0, fondo=0.0,
                   vidrio="M_Vidrio", ac=0.0, rejas_pisos=0, locales=0.0),
    # edificios bajos de la base aérea: friso blanco/crema, ventanas con reja
    "militar": dict(piso=3.3, pb=3.6, vano=3.4, ventana=(1.6, 1.4), antepecho=1.0, fondo=0.18,
                    vidrio="M_Vidrio", ac=0.3, rejas_pisos=1, locales=0.0),
}

ESTILO_POR_TIPO = {
    "apartments": "residencial", "residential": "residencial", "yes": "residencial",
    "office": "oficina", "commercial": "oficina", "hotel": "oficina",
    "retail": "comercial", "supermarket": "comercial",
    "house": "casa", "detached": "casa", "semidetached_house": "casa", "garage": "casa",
    "school": "institucional", "university": "institucional", "church": "institucional",
    "public": "institucional", "civic": "institucional",
    "hangar": "hangar", "industrial": "hangar", "warehouse": "hangar",
    "military": "militar", "control_tower": "institucional",
}

# Material de fachada (con textura real) según estilo; se elige uno por edificio con estos pesos.
FACHADAS = {
    "residencial": [("M_Fachada_Friso", 0.45), ("M_Fachada_Beige", 0.2), ("M_Fachada_Ladrillo", 0.2),
                    ("M_Fachada_Ceramica", 0.15)],
    "oficina": [("M_Fachada_Concreto", 0.6), ("M_Fachada_Ceramica", 0.4)],
    "comercial": [("M_Fachada_Comercial", 0.6), ("M_Fachada_Friso", 0.4)],
    "casa": [("M_Fachada_Casa", 0.7), ("M_Fachada_Friso", 0.3)],
    "institucional": [("M_Fachada_Concreto", 0.5), ("M_Fachada_Ladrillo", 0.5)],
    "hangar": [("M_Zinc", 1.0)],
    "militar": [("M_Fachada_Casa", 0.6), ("M_Fachada_Beige", 0.25), ("M_Fachada_Ladrillo", 0.15)],
}


# Colores de friso (mismo orden que PALETA en 03b_realismo.py): el color de vértice R elige uno.
PALETA_NOMBRES = ["arena", "blanco", "salmon", "amarillo", "terracota", "gris", "azul", "verde", "crema",
                  "durazno", "turquesa"]


def r_de_color(nombre):
    """Valor del canal R del color de vértice que selecciona ese color de la paleta."""
    i = PALETA_NOMBRES.index(nombre)
    return (i + 0.5) / len(PALETA_NOMBRES)


def balcones_corridos(m, anillo, z0, techo, piso, rnd, vuelo=1.2, largo_min=7.0):
    """Balcones corridos en las fachadas largas: losa volada en cada piso + antepecho (macizo blanco o
    baranda de barrotes), como los edificios residenciales de los años 60-70 en Chuao y Altamira."""
    mat_ante = "M_Losa_Blanca" if rnd.random() < 0.6 else "M_Baranda"
    n = len(anillo)
    for i in range(n):
        a, b = anillo[i], anillo[(i + 1) % n]
        L = math.dist(a, b)
        if L < largo_min:
            continue
        p = Pared(a, b)
        u0, u1 = 0.6, L - 0.6
        z = z0
        while z < techo - 1.2:
            # losa (cara superior, inferior y canto) por fuera de la pared (p negativo = afuera)
            q = [p.punto(u0, z, 0), p.punto(u1, z, 0), p.punto(u1, z, -vuelo), p.punto(u0, z, -vuelo)]
            m.cara(q[::-1], [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Losa_Blanca")
            m.cara([(x, y, zz - 0.18) for x, y, zz in q], [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Losa_Blanca")
            p.quad(m, u0, u1, z - 0.18, z, -vuelo, "M_Losa_Blanca", 0, z, (1, 1, 1, 1), uv01=False)
            # antepecho al borde de la losa y en los dos extremos
            alto = 1.05
            p.quad(m, u0, u1, z, z + alto, -vuelo, mat_ante, 0, z, (1, 1, 1, 1))
            for uu, sgn in ((u0, 1), (u1, -1)):
                e0, e1 = p.punto(uu, z, 0), p.punto(uu, z, -vuelo)
                cara = [e0, e1, (e1[0], e1[1], z + alto), (e0[0], e0[1], z + alto)]
                m.cara(cara if sgn < 0 else cara[::-1], [(0, 0), (vuelo, 0), (vuelo, alto), (0, alto)], mat_ante)
            z += piso


def muro_parcela(m, anillo, zs_de, cerca_de_calle, rnd, separacion=4.5, alto=2.3):
    """Muro perimetral de la parcela (bloque o concreto pintado, con grafitis) en los lados que dan a la
    calle, con un portón corredizo metálico. cerca_de_calle(x, y) -> True si el punto está junto a una calle
    (entre la acera y la fachada). zs_de(x, y) -> z del terreno."""
    afuera = offset_anillo(anillo, -separacion)
    if area_firmada(afuera) * area_firmada(anillo) <= 0:
        return 0
    n = len(afuera)
    tramos = []
    for i in range(n):
        a, b = afuera[i], afuera[(i + 1) % n]
        if math.dist(a, b) < 3.0:
            continue
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if cerca_de_calle(*mid):
            tramos.append((a, b))
    for k, (a, b) in enumerate(tramos):
        L = math.dist(a, b)
        d = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        nrm = (-d[1], d[0])
        puertas = []
        if k == 0 and L > 9:  # un portón en el primer tramo
            c0 = rnd.uniform(2.0, L - 6.5)
            puertas.append((c0, c0 + 4.5))
        cortes = [0.0] + [x for p in puertas for x in p] + [L]
        for j in range(0, len(cortes) - 1, 2):
            s0, s1 = cortes[j], cortes[j + 1]
            if s1 - s0 < 0.3:
                continue
            pts = [(a[0] + d[0] * s, a[1] + d[1] * s) for s in (s0, s1)]
            extruir_polilinea(m, pts, [nrm, nrm], [zs_de(*q) for q in pts], 0.2, alto, "M_Muro_Cerca")
        for s0, s1 in puertas:  # portón de lámina metálica
            q0 = (a[0] + d[0] * s0, a[1] + d[1] * s0)
            q1 = (a[0] + d[0] * s1, a[1] + d[1] * s1)
            z0 = zs_de(*q0)
            m.cara([(*q0, z0), (*q1, z0), (*q1, z0 + alto - 0.1), (*q0, z0 + alto - 0.1)],
                   [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Santamaria")
            m.cara([(*q1, z0), (*q0, z0), (*q0, z0 + alto - 0.1), (*q1, z0 + alto - 0.1)],
                   [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Santamaria")
    return len(tramos)


def estilo_de(tipo):
    return ESTILO_POR_TIPO.get(tipo, "residencial")


def elegir_fachada(estilo, rnd):
    r, acum = rnd.random(), 0.0
    for nombre, peso in FACHADAS[estilo]:
        acum += peso
        if r <= acum:
            return nombre
    return FACHADAS[estilo][-1][0]


# ---------------------------------------------------------------- utilidades 2D

def offset_anillo(anillo, d):
    """Desplaza un anillo cerrado d metros hacia su izquierda (hacia la masa del edificio)."""
    n = len(anillo)
    salida = []
    for i in range(n):
        p0, p1, p2 = anillo[i - 1], anillo[i], anillo[(i + 1) % n]
        e1 = (p1[0] - p0[0], p1[1] - p0[1])
        e2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1 = math.hypot(*e1) or 1.0
        l2 = math.hypot(*e2) or 1.0
        n1 = (-e1[1] / l1, e1[0] / l1)
        n2 = (-e2[1] / l2, e2[0] / l2)
        bx, by = n1[0] + n2[0], n1[1] + n2[1]
        lb = math.hypot(bx, by)
        if lb < 1e-6:
            bx, by, lb = n2[0], n2[1], 1.0
        bx, by = bx / lb, by / lb
        cos_m = max(bx * n2[0] + by * n2[1], 0.35)  # limita el inglete en ángulos muy agudos
        salida.append((p1[0] + bx * d / cos_m, p1[1] + by * d / cos_m))
    return salida


def area_firmada(anillo):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def offset_valido(original, desplazado):
    """El anillo desplazado conserva orientación y no colapsa."""
    a0, a1 = area_firmada(original), area_firmada(desplazado)
    return a0 * a1 > 0 and abs(a1) > 0.3 * abs(a0)


# ---------------------------------------------------------------- pared con aberturas

class Pared:
    """Sistema de coordenadas de una arista: u a lo largo, z vertical, p hacia adentro."""

    def __init__(self, a, b):
        self.a = a
        dx, dy = b[0] - a[0], b[1] - a[1]
        self.L = math.hypot(dx, dy)
        self.d = (dx / self.L, dy / self.L)
        self.n_in = (-self.d[1], self.d[0])

    def punto(self, u, z, p=0.0):
        return (self.a[0] + self.d[0] * u + self.n_in[0] * p,
                self.a[1] + self.d[1] * u + self.n_in[1] * p, z)

    def rumbo_exterior(self):
        return math.degrees(math.atan2(-self.n_in[1], -self.n_in[0]))

    def quad(self, m, u0, u1, z0, z1, p, mat, u_base, z_base, color, uv01=False):
        """Rectángulo en el plano de la pared (a profundidad p) mirando hacia afuera."""
        if u1 - u0 < 1e-3 or z1 - z0 < 1e-3:
            return
        pts = [self.punto(u0, z0, p), self.punto(u1, z0, p), self.punto(u1, z1, p), self.punto(u0, z1, p)]
        if uv01:
            uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
        else:
            uv = [(u_base + u0, z0 - z_base), (u_base + u1, z0 - z_base), (u_base + u1, z1 - z_base), (u_base + u0, z1 - z_base)]
        m.cara(pts, uv, mat, color=color)

    def abertura(self, m, u0, u1, z0, z1, fondo, mat_pared, mat_fondo, u_base, z_base, color, mat_reja=None):
        """Vano hundido: 4 caras de derrame + cara de fondo (vidrio/santamaría) + reja opcional."""
        P = self.punto
        # derrames (las caras miran hacia el centro del vano)
        derrames = [
            ([P(u0, z0, 0), P(u1, z0, 0), P(u1, z0, fondo), P(u0, z0, fondo)], u1 - u0, fondo),   # antepecho
            ([P(u1, z1, 0), P(u0, z1, 0), P(u0, z1, fondo), P(u1, z1, fondo)], u1 - u0, fondo),   # dintel
            ([P(u0, z0, 0), P(u0, z0, fondo), P(u0, z1, fondo), P(u0, z1, 0)], fondo, z1 - z0),   # jamba izq.
            ([P(u1, z1, 0), P(u1, z1, fondo), P(u1, z0, fondo), P(u1, z0, 0)], fondo, z1 - z0),   # jamba der.
        ]
        for pts, w, h in derrames:
            m.cara(pts, [(u_base, 0), (u_base + w, 0), (u_base + w, h), (u_base, h)], mat_pared, color=color)
        self.quad(m, u0, u1, z0, z1, fondo, mat_fondo, 0, 0, color, uv01=True)
        if mat_reja:
            self.quad(m, u0, u1, z0, z1, 0.04, mat_reja, 0, 0, color, uv01=True)


def fachada(m, anillo, suelos, base, techo, estilo_nombre, mat_fachada, color, rnd, props, con_locales):
    """Paredes con ventanas para un anillo. suelos[i] = altura del terreno en el vértice i."""
    e = dict(ESTILOS[estilo_nombre])
    # variación propia de cada edificio
    ancho_v = e["ventana"][0] * rnd.uniform(0.85, 1.15)
    alto_v = e["ventana"][1] * rnd.uniform(0.92, 1.1)
    usa_ac = rnd.random() < 0.8
    rejas = rnd.random() < 0.75
    u_acum = 0.0
    n = len(anillo)
    for i in range(n):
        a, b = anillo[i], anillo[(i + 1) % n]
        L = math.dist(a, b)
        if L < 0.05:
            continue
        pared = Pared(a, b)
        z_suelo = max(suelos[i], suelos[(i + 1) % n]) + 0.05
        pb_tope = z_suelo + e["pb"]
        if L < 1.6 or techo - z_suelo < 2.5:
            pared.quad(m, 0, L, base, techo, 0, mat_fachada, u_acum, base, color)
            u_acum += L
            continue

        nb = max(1, round(L / e["vano"]))
        vano = L / nb
        w = min(ancho_v, vano - 0.3)
        # zócalo bajo el nivel del suelo (por pendiente)
        pared.quad(m, 0, L, base, z_suelo, 0, mat_fachada, u_acum, base, color)

        # --- planta baja
        pb_tope = min(pb_tope, techo)
        for k in range(nb):
            u0, u1 = k * vano, (k + 1) * vano
            if con_locales and vano > 2.4 and pb_tope - z_suelo > 3.2:
                lu0, lu1 = u0 + 0.25, u1 - 0.25
                lz1 = z_suelo + min(3.0, pb_tope - z_suelo - 0.6)
                fondo_mat = "M_Santamaria" if rnd.random() < 0.45 else "M_Vidrio_Local"
                pared.quad(m, u0, lu0, z_suelo, lz1, 0, mat_fachada, u_acum, base, color)
                pared.quad(m, lu1, u1, z_suelo, lz1, 0, mat_fachada, u_acum, base, color)
                pared.quad(m, u0, u1, lz1, pb_tope, 0, mat_fachada, u_acum, base, color)
                pared.abertura(m, lu0, lu1, z_suelo, lz1, 0.3, mat_fachada, fondo_mat, u_acum, base, color)
            elif estilo_nombre == "oficina":
                lz1 = pb_tope - 0.5
                pared.quad(m, u0, u1, lz1, pb_tope, 0, mat_fachada, u_acum, base, color)
                pared.quad(m, u0, u0 + 0.06, z_suelo, lz1, 0, mat_fachada, u_acum, base, color)
                pared.quad(m, u1 - 0.06, u1, z_suelo, lz1, 0, mat_fachada, u_acum, base, color)
                pared.abertura(m, u0 + 0.06, u1 - 0.06, z_suelo, lz1, 0.1, "M_Marco", "M_Vidrio_Local", u_acum, base, color)
            else:
                ventana_en(pared, m, u0, u1, z_suelo, pb_tope, w, alto_v, e, mat_fachada, u_acum, base, color,
                           rejas and e["rejas_pisos"] > 0, False, rnd, props)

        # --- pisos superiores
        z = pb_tope
        piso = 0
        while z + e["piso"] <= techo + 0.01:
            piso += 1
            con_reja = rejas and piso < e["rejas_pisos"]
            for k in range(nb):
                ventana_en(pared, m, k * vano, (k + 1) * vano, z, z + e["piso"], w, alto_v, e, mat_fachada,
                           u_acum, base, color, con_reja, usa_ac, rnd, props)
            z += e["piso"]
        if techo - z > 0.01:
            pared.quad(m, 0, L, z, techo, 0, mat_fachada, u_acum, base, color)
        u_acum += L


def ventana_en(pared, m, u0, u1, z0, z1, w, h, e, mat, u_base, z_base, color, con_reja, usa_ac, rnd, props):
    vano = u1 - u0
    alto = z1 - z0
    h = min(h, alto - e["antepecho"] - 0.25)
    if h < 0.5 or w < 0.4:
        pared.quad(m, u0, u1, z0, z1, 0, mat, u_base, z_base, color)
        return
    um = (u0 + u1) / 2
    wu0, wu1 = um - w / 2, um + w / 2
    wz0 = z0 + e["antepecho"]
    wz1 = wz0 + h
    pared.quad(m, u0, u1, z0, wz0, 0, mat, u_base, z_base, color)
    pared.quad(m, u0, u1, wz1, z1, 0, mat, u_base, z_base, color)
    pared.quad(m, u0, wu0, wz0, wz1, 0, mat, u_base, z_base, color)
    pared.quad(m, wu1, u1, wz0, wz1, 0, mat, u_base, z_base, color)
    marco = "M_Marco" if e["vidrio"] == "M_Vidrio_Oficina" else mat
    pared.abertura(m, wu0, wu1, wz0, wz1, e["fondo"], marco, e["vidrio"], u_base, z_base, color,
                   "M_Reja" if con_reja else None)
    if usa_ac and rnd.random() < e["ac"] and vano > 1.8:
        lado = 1 if rnd.random() < 0.5 else -1
        x, y, _ = pared.punto(um + lado * (w / 2 + 0.45), 0, -0.22)
        props.append({"tipo": "aire", "x": round(x, 2), "y": round(y, 2), "z": round(wz0 + 0.1, 2),
                      "rumbo": round(pared.rumbo_exterior(), 1), "escala": 1.0})


# ---------------------------------------------------------------- techos

def pretil(m, anillo, techo, alto, grosor, mat_pared, mat_tapa, color):
    """Cara interior y tapa del pretil. Devuelve el anillo interior (borde del techo) o None."""
    interior = offset_anillo(anillo, grosor)
    if not offset_valido(anillo, interior):
        return None
    zt = techo + alto
    n = len(anillo)
    for i in range(n):
        a, b = anillo[i], anillo[(i + 1) % n]
        ai, bi = interior[i], interior[(i + 1) % n]
        L = math.dist(ai, bi)
        # cara interior mirando hacia el centro del techo
        m.cara([(bi[0], bi[1], techo), (ai[0], ai[1], techo), (ai[0], ai[1], zt), (bi[0], bi[1], zt)],
               [(0, 0), (L, 0), (L, alto), (0, alto)], mat_pared, color=color)
        # tapa superior
        m.cara([(a[0], a[1], zt), (b[0], b[1], zt), (bi[0], bi[1], zt), (ai[0], ai[1], zt)],
               [(a[0], a[1]), (b[0], b[1]), (bi[0], bi[1]), (ai[0], ai[1])], mat_tapa, color=color)
    return interior


# ---------------------------------------------------------------- aviación: hangares y torre

def rectangulo_orientado(anillo):
    """Rectángulo que envuelve el polígono, alineado con su arista más larga.
    Devuelve (centro, eje_largo, eje_corto, medio_largo, medio_corto)."""
    mejor = max(range(len(anillo)), key=lambda i: math.dist(anillo[i], anillo[(i + 1) % len(anillo)]))
    a, b = anillo[mejor], anillo[(mejor + 1) % len(anillo)]
    L = math.dist(a, b) or 1.0
    eu = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
    ev = (-eu[1], eu[0])
    us = [p[0] * eu[0] + p[1] * eu[1] for p in anillo]
    vs = [p[0] * ev[0] + p[1] * ev[1] for p in anillo]
    uc, vc = (min(us) + max(us)) / 2, (min(vs) + max(vs)) / 2
    centro = (eu[0] * uc + ev[0] * vc, eu[1] * uc + ev[1] * vc)
    hu, hv = (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2
    if hv > hu:  # que 'eu' sea siempre el lado largo
        eu, hu, hv = ev, hv, hu
        ev = (-eu[1], eu[0])
    return centro, eu, ev, hu, hv


def hangar_boveda(m, anillo, base, alto, rnd, segmentos=12):
    """Hangar con techo abovedado de zinc. La bóveda cruza el lado corto; portón en un extremo."""
    c, eu, ev, hu, hv = rectangulo_orientado(anillo)
    alero = base + max(alto * 0.55, 4.0)
    cumbrera = base + alto
    flecha = cumbrera - alero

    def P(u, v, z):
        return (c[0] + eu[0] * u + ev[0] * v, c[1] + eu[1] * u + ev[1] * v, z)

    # perfil del arco (v de -hv a +hv)
    perfil = [(-hv + 2 * hv * k / segmentos, alero + flecha * math.sin(math.pi * k / segmentos)) for k in range(segmentos + 1)]
    largo = 2 * hu
    # paredes laterales (largas)
    m.cara([P(-hu, -hv, base), P(hu, -hv, base), P(hu, -hv, alero), P(-hu, -hv, alero)],
           [(0, 0), (largo, 0), (largo, alero - base), (0, alero - base)], "M_Zinc")
    m.cara([P(hu, hv, base), P(-hu, hv, base), P(-hu, hv, alero), P(hu, hv, alero)],
           [(0, 0), (largo, 0), (largo, alero - base), (0, alero - base)], "M_Zinc")
    # bóveda
    s = 0.0
    for (v0, z0), (v1, z1) in zip(perfil, perfil[1:]):
        d = math.hypot(v1 - v0, z1 - z0)
        m.cara([P(-hu, v0, z0), P(hu, v0, z0), P(hu, v1, z1), P(-hu, v1, z1)],
               [(0, s), (largo, s), (largo, s + d), (0, s + d)], "M_Zinc")
        s += d
    # frentes (u = ±hu): rectángulo bajo el alero + segmento del arco
    for signo in (1, -1):
        u = hu * signo
        pts = [(-hv, base), (hv, base)] + [(v, z) for v, z in reversed(perfil)] if signo > 0 else \
              [(hv, base), (-hv, base)] + [(v, z) for v, z in perfil]
        cara = [P(u, v, z) for v, z in pts]
        m.cara(cara, [(v, z - base) for v, z in pts], "M_Zinc")
    # portón grande en el frente +u (ligeramente por fuera de la pared)
    pv = hv * 0.8
    pz = min(alero - base, 9.0) + base
    m.cara([P(hu + 0.05, -pv, base), P(hu + 0.05, pv, base), P(hu + 0.05, pv, pz), P(hu + 0.05, -pv, pz)],
           [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Santamaria")
    return cumbrera


def hangar_dos_aguas(m, m_piso, anillo, base, piso, alto, frente, rnd, color, abierto=True):
    """Hangar de La Carlota: techo de zinc a dos aguas de poca pendiente, aleros volados, paredes de lámina
    pintada y el frente (el lado que mira hacia 'frente', p. ej. la plataforma) abierto o con portones.

    m_piso recibe el piso interior (va en la capa de aviación para que no crezca pasto adentro).
    Paredes con 8 cm de grosor (cara exterior + interior) para que se vean bien desde adentro en Unreal.
    Devuelve (centro, eje_frente, medio_fondo, medio_ancho, alto_puerta) para colocar una aeronave adentro.
    """
    c, eu, ev, hu, hv = rectangulo_orientado(anillo)
    ejes = [(eu, hu, hv), (ev, hv, hu), ((-eu[0], -eu[1]), hu, hv), ((-ev[0], -ev[1]), hv, hu)]
    f, hf, hw = max(ejes, key=lambda e: e[0][0] * frente[0] + e[0][1] * frente[1])
    s = (-f[1], f[0])
    subida = min(hw * math.tan(math.radians(rnd.uniform(9, 14))), alto * 0.4)
    alero = base + max(alto - subida, 4.0)
    cumbrera = alero + subida
    vuelo, vuelo_frente, g = 0.7, 1.2, 0.08

    def P(fc, sc, z):
        return (c[0] + f[0] * fc + s[0] * sc, c[1] + f[1] * fc + s[1] * sc, z)

    def z_techo(sc):
        return cumbrera - subida * abs(sc) / hw

    def pared(a, b, z0a, z0b, z1a, z1b, mat="M_Hangar_Pared"):
        """Cara exterior (a→b, normal hacia afuera según el orden) + interior desplazada g hacia adentro."""
        (fa, sa), (fb, sb) = a, b
        L = math.hypot(fb - fa, sb - sa)
        # normal 2D hacia el centro (izquierda del recorrido antihorario)
        nf, ns = -(sb - sa) / L, (fb - fa) / L
        uv = [(0, z0a - base), (L, z0b - base), (L, z1b - base), (0, z1a - base)]
        m.cara([P(fa, sa, z0a), P(fb, sb, z0b), P(fb, sb, z1b), P(fa, sa, z1a)], uv, mat, color=color)
        ia, ib = (fa + nf * g, sa + ns * g), (fb + nf * g, sb + ns * g)
        m.cara([P(*ib, z0b), P(*ia, z0a), P(*ia, z1a), P(*ib, z1b)], uv[::-1][2:] + uv[::-1][:2], mat, color=color)

    # recorrido antihorario visto desde arriba: (-hf,-hw) → (hf,-hw) → (hf,hw) → (-hf,hw)
    pared((-hf, -hw), (hf, -hw), base, base, alero, alero)          # lateral
    pared((hf, hw), (-hf, hw), base, base, alero, alero)            # lateral
    # pared trasera con su hastial (triángulo bajo la cumbrera)
    pared((-hf, hw), (-hf, 0), base, base, alero, cumbrera)
    pared((-hf, 0), (-hf, -hw), base, base, cumbrera, alero)
    # frente: portón de casi todo el ancho; el resto es pared
    pw = hw * rnd.uniform(0.78, 0.9)
    pz = base + min(alero - base - 0.8, 9.0)
    pared((hf, -hw), (hf, -pw), base, base, alero, z_techo(pw))
    pared((hf, pw), (hf, hw), base, base, z_techo(pw), alero)
    pared((hf, -pw), (hf, 0), pz, pz, z_techo(pw), cumbrera)
    pared((hf, 0), (hf, pw), pz, pz, cumbrera, z_techo(pw))
    m.cara([P(hf + 0.02, -pw, pz - 0.6), P(hf + 0.02, pw, pz - 0.6), P(hf + 0.02, pw, pz), P(hf + 0.02, -pw, pz)],
           [(0, 0), (2 * pw, 0), (2 * pw, 0.6), (0, 0.6)], "M_Pintura_Blanca")  # dintel
    if abierto:
        # portones corredizos recogidos a los lados, por fuera
        for lado in (-1, 1):
            a, b = sorted((lado * pw, lado * (pw - min(4.0, pw * 0.35))))
            m.cara([P(hf + 0.25, a, base), P(hf + 0.25, b, base), P(hf + 0.25, b, pz - 0.6), P(hf + 0.25, a, pz - 0.6)],
                   [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Santamaria")
    else:
        m.cara([P(hf + 0.05, -pw, base), P(hf + 0.05, pw, base), P(hf + 0.05, pw, pz - 0.6), P(hf + 0.05, -pw, pz - 0.6)],
               [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Santamaria")
    # techo: dos aguas con aleros; UV v baja por la pendiente (ondas del zinc en esa dirección)
    for lado in (-1, 1):
        sc_alero = lado * (hw + vuelo)
        z_al = cumbrera - subida * (hw + vuelo) / hw
        L = math.hypot(hw + vuelo, cumbrera - z_al)
        f0, f1 = -hf - vuelo, hf + vuelo_frente
        pts = [P(f0, 0, cumbrera), P(f1, 0, cumbrera), P(f1, sc_alero, z_al), P(f0, sc_alero, z_al)]
        uv = [(0, 0), (f1 - f0, 0), (f1 - f0, L), (0, L)]
        if lado < 0:
            pts, uv = pts[::-1], uv[::-1]
        m.cara(pts, uv, "M_Zinc", color=color)
        # fascia (borde del alero) en el frente y en el costado
        m.cara([P(f1, 0, cumbrera - 0.3), P(f1, sc_alero, z_al - 0.3), P(f1, sc_alero, z_al), P(f1, 0, cumbrera)][::lado],
               [(0, 0), (L, 0), (L, 0.3), (0, 0.3)][::lado], "M_Pintura_Blanca")
        m.cara([P(f0, sc_alero, z_al - 0.3), P(f1, sc_alero, z_al - 0.3), P(f1, sc_alero, z_al), P(f0, sc_alero, z_al)][::-lado],
               [(0, 0), (f1 - f0, 0), (f1 - f0, 0.3), (0, 0.3)][::-lado], "M_Pintura_Blanca")
    # piso interior de concreto
    m_piso.cara([P(-hf, -hw, piso), P(hf, -hw, piso), P(hf, hw, piso), P(-hf, hw, piso)],
                [P(-hf, -hw, 0)[:2], P(hf, -hw, 0)[:2], P(hf, hw, 0)[:2], P(-hf, hw, 0)[:2]], "M_Plataforma")
    return c, f, hf, hw, pz - 0.6 - base


def cerca_perimetral(m, puntos, normales_afuera, zs, alto_muro=0.9, alto_reja=1.35, curva=0.55, paso_poste=2.6):
    """Cerca de La Carlota: muro bajo de concreto + reja de barrotes negros cuyo tope se curva hacia afuera.

    Los barrotes van dibujados en el material M_Barrotes (transparencia, UV en metros); los postes son
    geometría. normales_afuera: unitarias hacia el lado de la calle.
    """
    izq = [(-n[0], -n[1]) for n in normales_afuera]  # extruir_polilinea espera la normal izquierda
    extruir_polilinea(m, puntos, izq, zs, 0.25, alto_muro, "M_Muro_Cerca")
    # perfil de la reja (desplazamiento hacia afuera, altura sobre el muro, v acumulado)
    perfil = [(0.0, 0.0)]
    perfil.append((0.0, alto_reja))
    for k in range(1, 6):
        a = math.radians(80 * k / 5)
        perfil.append((curva * (1 - math.cos(a)), alto_reja + curva * math.sin(a)))
    vs = [0.0]
    for (d0, z0), (d1, z1) in zip(perfil, perfil[1:]):
        vs.append(vs[-1] + math.hypot(d1 - d0, z1 - z0))
    s = 0.0
    for i in range(len(puntos) - 1):
        L = math.dist(puntos[i], puntos[i + 1])
        for j in range(len(perfil) - 1):
            (d0, z0), (d1, z1) = perfil[j], perfil[j + 1]
            q = []
            for k, d, z in ((i, d0, z0), (i + 1, d0, z0), (i + 1, d1, z1), (i, d1, z1)):
                n = normales_afuera[k]
                q.append((puntos[k][0] + n[0] * d, puntos[k][1] + n[1] * d, zs[k] + alto_muro + z))
            m.cara(q, [(s, vs[j]), (s + L, vs[j]), (s + L, vs[j + 1]), (s, vs[j + 1])], "M_Barrotes")
        s += L
    # postes cuadrados de 8 cm
    s, sig = 0.0, 0.0
    for i in range(len(puntos) - 1):
        L = math.dist(puntos[i], puntos[i + 1])
        while sig <= s + L:
            t = (sig - s) / L if L else 0.0
            x = puntos[i][0] + (puntos[i + 1][0] - puntos[i][0]) * t
            y = puntos[i][1] + (puntos[i + 1][1] - puntos[i][1]) * t
            z0 = zs[i] + (zs[i + 1] - zs[i]) * t + alto_muro
            caja(m, x, y, z0, z0 + alto_reja + 0.15, 0.04, normales_afuera[i], "M_Metal_Oscuro")
            sig += paso_poste
        s += L


def caja(m, x, y, z0, z1, h, eje, mat):
    """Prisma vertical de sección cuadrada 2h × 2h orientado según 'eje'."""
    a, b = (eje[0] * h, eje[1] * h), (-eje[1] * h, eje[0] * h)
    esquinas = [(x - a[0] - b[0], y - a[1] - b[1]), (x + a[0] - b[0], y + a[1] - b[1]),
                (x + a[0] + b[0], y + a[1] + b[1]), (x - a[0] + b[0], y - a[1] + b[1])]
    for p, q in zip(esquinas, esquinas[1:] + esquinas[:1]):
        m.cara([(*p, z0), (*q, z0), (*q, z1), (*p, z1)], [(0, z0), (2 * h, z0), (2 * h, z1), (0, z1)], mat)
    m.cara([(*p, z1) for p in esquinas], [(0, 0), (1, 0), (1, 1), (0, 1)], mat)


# ---------------------------------------------------------------- monumentos: Obelisco de Plaza Francia

def prisma_orientado(m, c, eu, ev, h0, z0, z1, mat, h1=None, tapa=True, saliente=0.0):
    """Tronco de pirámide de base cuadrada (semilado h0 abajo, h1 arriba) alineado con eu/ev.
    UV en metros: u a lo largo del perímetro, v = z."""
    h1 = h0 if h1 is None else h1

    def esquinas(h):
        return [(c[0] + (eu[0] * a + ev[0] * b) * h, c[1] + (eu[1] * a + ev[1] * b) * h)
                for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    abajo, arriba = esquinas(h0 + saliente), esquinas(h1 + saliente)
    u = 0.0
    for k in range(4):
        a, b, a2, b2 = abajo[k], abajo[(k + 1) % 4], arriba[k], arriba[(k + 1) % 4]
        L = math.dist(a, b)
        m.cara([(*a, z0), (*b, z0), (*b2, z1), (*a2, z1)], [(u, z0), (u + L, z0), (u + L, z1), (u, z1)], mat)
        u += L
    if tapa:
        m.cara([(*p, z1) for p in arriba], [p for p in arriba], mat)
    return arriba


def obelisco_plaza_francia(m, anillo, base, techo, z_suelo, mat="M_Monumento"):
    """Obelisco con zócalo, pedestal tallado (relieves y placa de bronce), cornisa, fuste que se afina
    y piramidión, como el de Plaza Francia (Altamira). Alturas medidas desde el piso de la plaza."""
    c, eu, ev, hu, hv = rectangulo_orientado(anillo)
    h = (hu + hv) / 2  # semilado del fuste en su base (OSM: ~1,5 m)
    z = z_suelo
    prisma_orientado(m, c, eu, ev, 1.25 * h, base, z + 5.2, mat, tapa=False)        # zócalo (dentro de la fuente)
    prisma_orientado(m, c, eu, ev, 1.4 * h, z + 5.2, z + 5.6, mat)                  # moldura
    prisma_orientado(m, c, eu, ev, 1.15 * h, z + 5.6, z + 9.4, mat, tapa=False)     # pedestal
    # relieves (escudo y guirnaldas) en las 4 caras y placa de bronce en la cara sur
    for n in (eu, ev, (-eu[0], -eu[1]), (-ev[0], -ev[1])):
        t = (-n[1], n[0])
        d = 1.15 * h + 0.04
        p0 = (c[0] + n[0] * d, c[1] + n[1] * d)
        w = 0.75 * h
        m.cara([(p0[0] - t[0] * w, p0[1] - t[1] * w, z + 6.1), (p0[0] + t[0] * w, p0[1] + t[1] * w, z + 6.1),
                (p0[0] + t[0] * w, p0[1] + t[1] * w, z + 8.9), (p0[0] - t[0] * w, p0[1] - t[1] * w, z + 8.9)],
               [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Relieve")
    prisma_orientado(m, c, eu, ev, 1.35 * h, z + 9.4, z + 9.8, mat)                 # cornisa
    z_fuste = techo - (techo - z_suelo) * 0.065
    z_base_fuste = z + 9.8
    tope = prisma_orientado(m, c, eu, ev, 0.9 * h, z_base_fuste, z_fuste, mat, h1=0.55 * h, tapa=False)
    # placa en el fuste (cara que mira al sur, como la de "Luis Roche ... 1946")
    cara_sur = min(((eu, 1), (eu, -1), (ev, 1), (ev, -1)), key=lambda e: e[0][1] * e[1])
    n = (cara_sur[0][0] * cara_sur[1], cara_sur[0][1] * cara_sur[1])
    t = (-n[1], n[0])
    za, zb = z + 11.4, z + 13.4
    ancho = lambda zz: 0.9 * h + (0.55 * h - 0.9 * h) * (zz - z_base_fuste) / (z_fuste - z_base_fuste)  # noqa: E731
    pts = []
    for zz, s in ((za, -1), (za, 1), (zb, 1), (zb, -1)):
        d = ancho(zz) + 0.03
        pts.append((c[0] + n[0] * d + t[0] * s * 0.45 * h, c[1] + n[1] * d + t[1] * s * 0.45 * h, zz))
    m.cara(pts, [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Placa")
    for k in range(4):  # piramidión
        a, b = tope[k], tope[(k + 1) % 4]
        L = math.dist(a, b)
        m.cara([(*a, z_fuste), (*b, z_fuste), (c[0], c[1], techo)], [(0, z_fuste), (L, z_fuste), (L / 2, techo)], mat)


def circulo(cx, cy, r, n, a0=0.0):
    return [(cx + r * math.cos(a0 + 2 * math.pi * k / n), cy + r * math.sin(a0 + 2 * math.pi * k / n)) for k in range(n)]


def anillo_plano(m, cx, cy, r0, r1, z, mat, n=48, color=(1, 1, 1, 1)):
    """Corona horizontal entre los radios r0 < r1 (r0 = 0: disco), cara hacia arriba. UV = xy."""
    for k in range(n):
        a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        p = [(cx + r0 * math.cos(a0), cy + r0 * math.sin(a0)), (cx + r1 * math.cos(a0), cy + r1 * math.sin(a0)),
             (cx + r1 * math.cos(a1), cy + r1 * math.sin(a1)), (cx + r0 * math.cos(a1), cy + r0 * math.sin(a1))]
        if r0 < 1e-3:
            p = p[1:]
        m.cara([(x, y, z) for x, y in p], [(x, y) for x, y in p], mat, color=color)


def perfil_revolucion(m, cx, cy, perfil, mat, n=48, uv_v=None):
    """Superficie de revolución: perfil = [(r, z), ...] de abajo hacia arriba (cara hacia afuera si r crece
    hacia afuera en el sentido del recorrido). UV u = arco (m) en el radio medio; v = z o el valor dado."""
    for j in range(len(perfil) - 1):
        (r0, z0), (r1, z1) = perfil[j], perfil[j + 1]
        rm = (r0 + r1) / 2
        v0, v1 = (z0, z1) if uv_v is None else uv_v[j:j + 2]
        for k in range(n):
            a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
            u0, u1 = rm * a0, rm * a1
            m.cara([(cx + r0 * math.cos(a0), cy + r0 * math.sin(a0), z0), (cx + r0 * math.cos(a1), cy + r0 * math.sin(a1), z0),
                    (cx + r1 * math.cos(a1), cy + r1 * math.sin(a1), z1), (cx + r1 * math.cos(a0), cy + r1 * math.sin(a0), z1)],
                   [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], mat)


def tubo(m, puntos, radio, mat, lados=4):
    """Tubo fino a lo largo de una polilínea 3D (chorros de agua). UV v = 0..1 a lo largo."""
    n = len(puntos)
    anillos = []
    for i, p in enumerate(puntos):
        q0, q1 = puntos[max(i - 1, 0)], puntos[min(i + 1, n - 1)]
        d = [q1[k] - q0[k] for k in range(3)]
        L = math.sqrt(sum(x * x for x in d)) or 1.0
        d = [x / L for x in d]
        ref = (0, 0, 1) if abs(d[2]) < 0.9 else (1, 0, 0)
        a = (d[1] * ref[2] - d[2] * ref[1], d[2] * ref[0] - d[0] * ref[2], d[0] * ref[1] - d[1] * ref[0])
        La = math.sqrt(sum(x * x for x in a)) or 1.0
        a = [x / La for x in a]
        b = (d[1] * a[2] - d[2] * a[1], d[2] * a[0] - d[0] * a[2], d[0] * a[1] - d[1] * a[0])
        anillos.append([tuple(p[k] + radio * (math.cos(2 * math.pi * j / lados) * a[k] + math.sin(2 * math.pi * j / lados) * b[k])
                              for k in range(3)) for j in range(lados)])
    for i in range(n - 1):
        for j in range(lados):
            j2 = (j + 1) % lados
            m.cara([anillos[i][j], anillos[i][j2], anillos[i + 1][j2], anillos[i + 1][j]],
                   [(j / lados, i / (n - 1)), ((j + 1) / lados, i / (n - 1)), ((j + 1) / lados, (i + 1) / (n - 1)),
                    (j / lados, (i + 1) / (n - 1))], mat)


def fuente_escalonada(m, cx, cy, z0, R, n=64):
    """Fuente circular del Obelisco de Plaza Francia: pileta exterior con borde de azulejo turquesa,
    8 jardineras radiales, 3 platos escalonados de piedra que rebosan agua (cortinas) y chorros en arco
    desde el borde. Devuelve la z del agua del plato superior."""
    borde = 0.55
    # pileta exterior
    perfil_revolucion(m, cx, cy, [(R, z0 - 0.2), (R, z0 + borde)], "M_Azulejo", n)
    anillo_plano(m, cx, cy, R - 0.4, R, z0 + borde, "M_Brocal", n)
    perfil_revolucion(m, cx, cy, [(R - 0.4, z0 + borde), (R - 0.4, z0 + 0.05)], "M_Azulejo", n)
    platos = [(0.6 * R, 1.5), (0.44 * R, 3.2), (0.31 * R, 4.9)]  # (radio, altura del borde)
    z_agua = z0 + borde - 0.12
    anillo_plano(m, cx, cy, platos[0][0], R - 0.4, z_agua, "M_Agua_Fuente", n)
    # jardineras radiales (cuñas de 22°) dentro de la pileta
    ra, rb = platos[0][0] + 0.9, R - 1.3
    for k in range(8):
        a_c = math.radians(22.5 + 45 * k)
        angs = [a_c + math.radians(11) * s for s in (-1, -0.5, 0, 0.5, 1)]
        exterior = [(cx + rb * math.cos(a), cy + rb * math.sin(a)) for a in angs]
        interior = [(cx + ra * math.cos(a), cy + ra * math.sin(a)) for a in reversed(angs)]
        cuna = exterior + interior  # antihorario
        zt = z0 + 0.8
        for p, q in zip(cuna, cuna[1:] + cuna[:1]):
            L = math.dist(p, q)
            m.cara([(*p, z0), (*q, z0), (*q, zt), (*p, zt)], [(0, 0), (L, 0), (L, zt - z0), (0, zt - z0)], "M_Azulejo")
        for i in range(4):
            pts = [exterior[i], exterior[i + 1], interior[3 - i], interior[4 - i]]
            m.cara([(x, y, zt) for x, y in pts], [(x, y) for x, y in pts], "M_Seto")
    # platos escalonados con labio y cortina de agua que cae al nivel de abajo
    z_abajo = z_agua
    for r, h in platos:
        zb = z0 + h
        perfil_revolucion(m, cx, cy, [(r - 0.35, z0), (r - 0.35, zb - 0.45), (r + 0.25, zb - 0.1), (r + 0.25, zb)],
                          "M_Piedra_Fuente", n)
        anillo_plano(m, cx, cy, r - 0.1, r + 0.25, zb, "M_Piedra_Fuente", n)
        anillo_plano(m, cx, cy, 0.0, r - 0.1, zb - 0.06, "M_Agua_Fuente", n)
        perfil_revolucion(m, cx, cy, [(r + 0.42, z_abajo + 0.01), (r + 0.3, zb - 0.03)], "M_Cortina_Agua", n,
                          uv_v=[1.0, 0.0])
        z_abajo = zb - 0.06
    # chorros en arco desde el borde de la pileta hacia el primer plato
    for k in range(32):
        a = 2 * math.pi * (k + 0.5) / 32
        r_ini, r_fin, alto = R - 0.3, platos[0][0] + 0.6, 2.6
        pts = []
        for i in range(13):
            t = i / 12
            r = r_ini + (r_fin - r_ini) * t
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a), z0 + borde + 4 * alto * t * (1 - t) - (borde - 0.12) * t))
        tubo(m, pts, 0.03, "M_Chorro")
    return z_abajo


# ---------------------------------------------------------------- Plaza Francia: bajada al Metro (sur)

def caja_xy(m, x0, x1, y0, y1, z0, z1, mat, caras="nsoet", color=(1, 1, 1, 1)):
    """Bloque alineado con los ejes. caras: n/s/o/e = paredes norte/sur/oeste/este, t = tapa.
    UV de paredes: (metros a lo largo, z - z0); tapa: xy."""
    if z1 - z0 < 1e-3:
        return
    h = z1 - z0
    if "s" in caras:
        m.cara([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], [(x0, 0), (x1, 0), (x1, h), (x0, h)], mat, color=color)
    if "n" in caras:
        m.cara([(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)], [(-x1, 0), (-x0, 0), (-x0, h), (-x1, h)], mat, color=color)
    if "e" in caras:
        m.cara([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], [(y0, 0), (y1, 0), (y1, h), (y0, h)], mat, color=color)
    if "o" in caras:
        m.cara([(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)], [(-y1, 0), (-y0, 0), (-y0, h), (-y1, h)], mat, color=color)
    if "t" in caras:
        m.cara([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], mat, color=color)


def baranda(m, puntos, alto=1.0, paso_poste=1.5, mat="M_Pintura_Verde"):
    """Baranda de tubo (pasamanos + travesaño medio + postes) sobre una polilínea 3D (z = piso)."""
    tubo(m, [(x, y, z + alto) for x, y, z in puntos], 0.03, mat, lados=6)
    tubo(m, [(x, y, z + alto * 0.5) for x, y, z in puntos], 0.018, mat, lados=4)
    s, sig = 0.0, 0.0
    for a, b in zip(puntos, puntos[1:]):
        L = math.dist(a[:2], b[:2])
        while sig <= s + L + 1e-6:
            t = (sig - s) / L if L else 0.0
            p = [a[k] + (b[k] - a[k]) * t for k in range(3)]
            tubo(m, [(p[0], p[1], p[2]), (p[0], p[1], p[2] + alto)], 0.025, mat, lados=4)
            sig += paso_poste
        s += L


def plaza_hundida(m, cfg, A, props, rnd, flores=None, A_sur=None):
    """Bajada al Metro de Plaza Francia: cascada desde el espejo de agua, escaleras a ambos lados, puente,
    foso con estanque y bocas del Metro, jardineras escalonadas de muros blancos con remate verde y barandas.
    A = piso de la plaza en el borde norte (arriba de la cascada); A_sur = en el borde sur (la plaza baja
    hacia la Av. Francisco de Miranda). Los niveles del puente y del foso se miden desde A_sur.
    Todas las coordenadas vienen de zonas.json ("plaza_hundida")."""
    hx0, hx1, hy0, hy1 = cfg["hueco"]
    yt, yb = cfg["y_cascada"]                       # arriba (norte) y abajo (sur) de la cascada
    cx0, cx1 = cfg["x_cascada"]
    (eo0, eo1), (ee0, ee1) = cfg["escaleras_x"]     # escalera oeste y este
    (to0, to1), (te0, te1) = cfg["terrazas_x"]
    py0, py1 = cfg["puente_y"]                      # norte y sur del puente
    fy0, fy1 = cfg["foso_y"]
    A_s = A if A_sur is None else A_sur
    B, C = A_s + cfg["nivel_puente"], A_s + cfg["nivel_foso"]
    blanco, verde = "M_Muro_Blanco", "M_Pintura_Verde"

    def nivel(y):  # piso de la plaza a los lados del hueco (interpolado entre el borde norte y el sur)
        return A + (A_s - A) * (yt - y) / (yt - hy0)

    # cascada: rampa de azulejo claro con lámina de agua y bordillos blancos
    m.cara([(cx0, yb, B), (cx1, yb, B), (cx1, yt, A), (cx0, yt, A)],
           [(cx0, yb), (cx1, yb), (cx1, yt), (cx0, yt)], "M_Azulejo_Claro")
    m.cara([(cx0, yb, B + 0.03), (cx1, yb, B + 0.03), (cx1, yt, A + 0.03), (cx0, yt, A + 0.03)],
           [(0, 0), (cx1 - cx0, 0), (cx1 - cx0, yt - yb), (0, yt - yb)], "M_Lamina_Agua")
    for x in (cx0, cx1):
        for lado in (-1, 1):
            xx = x + lado * 0.06
            m.cara([(xx, yb, B), (xx, yt, A), (xx, yt, A + 0.35), (xx, yb, B + 0.35)][::lado],
                   [(0, 0), (yt - yb, 0), (yt - yb, 0.35), (0, 0.35)][::lado], blanco)
    # escaleras de la plaza al puente (huella de ~0,7 m, contrahuella ~0,17 m)
    n = max(1, round((A - B) / 0.17))
    paso_y, paso_z = (yt - yb) / n, (A - B) / n
    for x0, x1 in ((eo0, eo1), (ee0, ee1)):
        for k in range(n):
            ya, yb_k = yt - k * paso_y, yt - (k + 1) * paso_y
            caja_xy(m, x0, x1, yb_k, ya, C, A - (k + 1) * paso_z, "M_Escalera", caras="st")
    # puente (losa de 0,6 m) entre las dos escaleras, al pie de la cascada
    caja_xy(m, eo0, ee1, py1, py0, B - 0.6, B, "M_Acera", caras="st")
    m.cara([(eo0, py0, B - 0.6), (ee1, py0, B - 0.6), (ee1, py1, B - 0.6), (eo0, py1, B - 0.6)],
           [(0, 0), (1, 0), (1, 1), (0, 1)], blanco)  # cara inferior
    # pared bajo el puente con las bocas del Metro
    yw = py0 - 1.0
    m.cara([(eo0, yw, C), (ee1, yw, C), (ee1, yw, B - 0.6), (eo0, yw, B - 0.6)],
           [(eo0, 0), (ee1, 0), (ee1, B - 0.6 - C), (eo0, B - 0.6 - C)], blanco)
    for xm in ((eo0 + cx0) / 2 + 1.0, (cx1 + ee1) / 2 - 1.0):
        m.cara([(xm - 1.5, yw - 0.02, C), (xm + 1.5, yw - 0.02, C), (xm + 1.5, yw - 0.02, C + 2.6), (xm - 1.5, yw - 0.02, C + 2.6)],
               [(0, 0), (1, 0), (1, 1), (0, 1)], "M_Metro_Boca")
    # foso: piso, estanque y escaleras del puente al foso
    arco = [(eo0 + (ee1 - eo0) * t, fy1 - 2.0 * math.sin(math.pi * t)) for t in [i / 16 for i in range(17)]]
    piso = [(eo0, yw), (ee1, yw)] + arco[::-1]
    for i in range(1, len(piso) - 1):  # abanico (el polígono es convexo)
        tri = [piso[0], piso[i + 1], piso[i]]
        m.cara([(x, y, C) for x, y in tri], [(x, y) for x, y in tri], "M_Acera")
    ex0, ex1, ey0, ey1 = cfg["estanque"]
    anillo = [(ex0, ey0), (ex1, ey0), (ex1, ey1), (ex0, ey1)]
    interior = borde_fuente(m, anillo, C, 0.55, 0.3, "M_Azulejo")
    m.cara([(x, y, C + 0.43) for x, y in interior], [(x, y) for x, y in interior], "M_Agua_Fuente")
    n2 = max(1, round((B - C) / 0.17))
    for x0, x1 in ((eo0, ex0 - 0.2), (ex1 + 0.6, ee1)):
        for k in range(n2):
            caja_xy(m, x0, x1, py1 - (k + 1) * 0.3, py1 - k * 0.3, C, B - (k + 1) * (B - C) / n2, "M_Escalera", caras="st")
    # muro curvo del sur (antepecho de 1 m sobre la plaza) con remate redondo verde
    tope = A_s + 1.0  # antepecho de 1 m sobre la acera del lado sur
    for (xa, ya), (xb, yb2) in zip(arco, arco[1:]):
        L = math.dist((xa, ya), (xb, yb2))
        m.cara([(xb, yb2, C), (xa, ya, C), (xa, ya, tope), (xb, yb2, tope)], [(0, 0), (L, 0), (L, tope - C), (0, tope - C)], blanco)
        m.cara([(xa, ya - 0.3, A_s - 0.3), (xb, yb2 - 0.3, A_s - 0.3), (xb, yb2 - 0.3, tope), (xa, ya - 0.3, tope)],
               [(0, 0), (L, 0), (L, 1.3), (0, 1.3)], blanco)
        m.cara([(xa, ya, tope), (xb, yb2, tope), (xb, yb2 - 0.3, tope), (xa, ya - 0.3, tope)][::-1], [(0, 0), (1, 0), (1, 1), (0, 1)], blanco)
    tubo(m, [(x, y - 0.15, tope + 0.05) for x, y in arco], 0.2, verde, lados=8)
    # piso de plaza entre el muro curvo y el borde sur del hueco
    for (xa, ya), (xb, yb2) in zip(arco, arco[1:]):
        q = [(xa, ya - 0.3), (xa, hy0), (xb, hy0), (xb, yb2 - 0.3)]
        m.cara([(x, y, A_s) for x, y in q], [(x, y) for x, y in q], "M_Plaza")
    # jardineras escalonadas a los lados (bajan hacia el sur siguiendo las escaleras), siempre por debajo
    # del piso de la plaza que las rodea
    cortes = [yt, yt - 7.0, yb, yb - 7.0, hy0]
    escalones = [(cortes[k], cortes[k + 1], nivel(cortes[k + 1]) - (0.4 + 0.55 * k)) for k in range(4)]
    for x0, x1, interior_x in ((to0, to1, to1), (te0, te1, te0)):
        z_ant = A
        for ya, yb3, zt in escalones:
            caja_xy(m, x0, x1, yb3, ya, C, zt, "M_Tierra_Jardin", caras="t")
            # muros: hacia el centro (escaleras/foso), escalón norte y borde exterior contra la plaza (en pendiente)
            if interior_x == to1:
                caja_xy(m, x0, x1, yb3, ya, C, zt, blanco, caras="e")
                m.cara([(x0, yb3, zt), (x0, ya, zt), (x0, ya, nivel(ya)), (x0, yb3, nivel(yb3))], [(0, 0), (1, 0), (1, 1), (0, 1)], blanco)
            else:
                caja_xy(m, x0, x1, yb3, ya, C, zt, blanco, caras="o")
                m.cara([(x1, ya, zt), (x1, yb3, zt), (x1, yb3, nivel(yb3)), (x1, ya, nivel(ya))], [(0, 0), (1, 0), (1, 1), (0, 1)], blanco)
            m.cara([(x0, ya, zt), (x1, ya, zt), (x1, ya, z_ant), (x0, ya, z_ant)], [(0, 0), (x1 - x0, 0), (x1 - x0, z_ant - zt), (0, z_ant - zt)], blanco)
            tubo(m, [(interior_x, ya, zt + 0.1), (interior_x, yb3, zt + 0.1)], 0.15, verde, lados=8)
            tubo(m, [(x0, ya, z_ant + 0.1), (x1, ya, z_ant + 0.1)], 0.15, verde, lados=8)
            if flores:
                densidad = flores.get("densidad_m2", 2.0)
                cant = int((x1 - x0 - 0.6) * (ya - yb3 - 0.6) * densidad)
                for _ in range(max(cant, 0)):
                    r, acum, tipo = rnd.random(), 0.0, None
                    for t, peso in flores["tipos"]:
                        acum += peso
                        if r <= acum:
                            tipo = t
                            break
                    props.append({"tipo": tipo or "canna_hojas", "x": round(rnd.uniform(x0 + 0.3, x1 - 0.3), 2),
                                  "y": round(rnd.uniform(yb3 + 0.3, ya - 0.3), 2), "z": round(zt, 2),
                                  "rumbo": round(rnd.uniform(0, 360), 1), "escala": round(rnd.uniform(0.8, 1.25), 2)})
            z_ant = zt
        # borde sur de la jardinera contra la plaza
        m.cara([(x1, hy0, zt), (x0, hy0, zt), (x0, hy0, A_s), (x1, hy0, A_s)], [(0, 0), (1, 0), (1, 1), (0, 1)], blanco)
    # barandas verdes: junto a la cascada (en la pendiente), en el borde sur del puente y en las escaleras al foso
    for x in (cx0 - 0.15, cx1 + 0.15):
        baranda(m, [(x, yt - 0.3, A - 0.05), (x, yb + 0.3, B - 0.05)])
    baranda(m, [(ex0 - 0.2, py1 + 0.1, B), (ex1 + 0.6, py1 + 0.1, B)])
    for x in (ex0 - 0.25, ex1 + 0.65):
        baranda(m, [(x, py1, B), (x, py1 - n2 * 0.3, C)])
    return B, C


# ---------------------------------------------------------------- edificios emblemáticos (hitos)

def ejes_hacia(anillo, destino):
    """Rectángulo orientado del polígono con sus ejes reordenados: e_fondo apunta hacia 'destino'
    (p. ej. la plaza) y e_ancho = e_fondo girado 90° a la derecha, de modo que (e_ancho, e_fondo) es antihorario.
    Devuelve (centro, e_ancho, e_fondo, medio_ancho, medio_fondo)."""
    c, eu, ev, hu, hv = rectangulo_orientado(anillo)
    d = (destino[0] - c[0], destino[1] - c[1])
    opciones = [(eu, hu, hv), (ev, hv, hu), ((-eu[0], -eu[1]), hu, hv), ((-ev[0], -ev[1]), hv, hu)]
    e_fondo, medio_fondo, medio_ancho = max(opciones, key=lambda o: o[0][0] * d[0] + o[0][1] * d[1])
    e_ancho = (e_fondo[1], -e_fondo[0])
    return c, e_ancho, e_fondo, medio_ancho, medio_fondo


def rect_redondeado(c, ea, ef, ha, hf, radio, seg=6):
    """Anillo antihorario de un rectángulo de esquinas redondeadas (semilados ha, hf en los ejes ea, ef)."""
    r = max(0.0, min(radio, ha * 0.999, hf * 0.999))
    pts = []
    for (sa, sf), a0 in (((1, -1), -90), ((1, 1), 0), ((-1, 1), 90), ((-1, -1), 180)):
        ca, cf = sa * (ha - r), sf * (hf - r)
        for k in range(seg + 1):
            a = math.radians(a0 + 90 * k / seg)
            u, v = ca + r * math.cos(a), cf + r * math.sin(a)
            p = (c[0] + ea[0] * u + ef[0] * v, c[1] + ea[1] * u + ef[1] * v)
            if not pts or math.dist(p, pts[-1]) > 1e-4:
                pts.append(p)
    if math.dist(pts[0], pts[-1]) < 1e-4:
        pts.pop()
    return pts


def prisma_anillo(m, anillo, z0, z1, mat, color=(1, 1, 1, 1), tapa=None, z_uv=None):
    """Paredes de un anillo antihorario entre z0 y z1 (UV: metros a lo largo, z - z_uv) y tapa convexa opcional."""
    zb = z0 if z_uv is None else z_uv
    u = 0.0
    for a, b in zip(anillo, anillo[1:] + anillo[:1]):
        L = math.dist(a, b)
        m.cara([(*a, z0), (*b, z0), (*b, z1), (*a, z1)], [(u, z0 - zb), (u + L, z0 - zb), (u + L, z1 - zb), (u, z1 - zb)],
               mat, color=color)
        u += L
    if tapa:
        cx = sum(p[0] for p in anillo) / len(anillo)
        cy = sum(p[1] for p in anillo) / len(anillo)
        for a, b in zip(anillo, anillo[1:] + anillo[:1]):
            m.cara([(cx, cy, z1), (*a, z1), (*b, z1)], [(cx, cy), a, b], tapa, color=color)


def losa_volada(m, anillo, z, vuelo, grosor, mat):
    """Losa de entrepiso que sobresale 'vuelo' metros de la fachada (aleta horizontal), con cara superior,
    inferior y canto."""
    afuera = offset_anillo(anillo, -vuelo)
    for (a, b), (a2, b2) in zip(zip(anillo, anillo[1:] + anillo[:1]), zip(afuera, afuera[1:] + afuera[:1])):
        L = math.dist(a2, b2)
        m.cara([(*a, z), (*a2, z), (*b2, z), (*b, z)], [a, a2, b2, b], mat)                                # arriba
        m.cara([(*a, z - grosor), (*b, z - grosor), (*b2, z - grosor), (*a2, z - grosor)], [a, b, b2, a2], mat)  # abajo
        m.cara([(*a2, z - grosor), (*b2, z - grosor), (*b2, z), (*a2, z)], [(0, 0), (L, 0), (L, grosor), (0, grosor)], mat)


def torre_escalonada(m, anillo, base, plaza, escalones, mat, color, aletas=None, terraza="M_Seto"):
    """Edificio de volúmenes de esquinas redondeadas que se escalonan (Hotel Caracas Palace, Torre Delta).
    escalones: [ancho (fracción), fondo (fracción), desplazamiento hacia la plaza (-1..1), z tope (m), radio (m)].
    aletas: {"piso": m, "vuelo": m} para losas voladas en cada piso. Las azoteas intermedias llevan jardinera."""
    c, ea, ef, ha, hf = ejes_hacia(anillo, plaza)
    z_ant = base
    anillos = []
    for k, (fa, ff, des, z_tope, radio) in enumerate(escalones):
        cc = (c[0] + ef[0] * des * hf, c[1] + ef[1] * des * hf)
        an = rect_redondeado(cc, ea, ef, ha * fa, hf * ff, radio)
        z0 = base if k == 0 else anillos[-1][1] - 0.5  # cada volumen arranca dentro del anterior
        ultimo = k == len(escalones) - 1
        prisma_anillo(m, an, z0, base + z_tope, mat, color, tapa="M_Techo_Concreto" if ultimo else terraza, z_uv=base)
        if aletas:
            z = z0 + aletas["piso"]
            while z < base + z_tope - 0.5:
                if z > z_ant + 0.3:
                    losa_volada(m, an, z, aletas["vuelo"], 0.25, "M_Losa_Blanca")
                z += aletas["piso"]
        anillos.append((an, base + z_tope))
        z_ant = base + z_tope
    return c, ef, ha, hf, anillos


def torre_marco(m, anillo, base, techo, plaza, color):
    """Torre Británica: prisma de vidrio oscuro metido dentro de un gran marco de concreto claro
    (dos pilares laterales y una viga de coronación), con una ranura vertical en el centro del remate."""
    c, ea, ef, ha, hf = ejes_hacia(anillo, plaza)
    pil = 0.16 * ha * 2          # ancho de cada pilar
    viga = 6.0
    retiro = 1.6                 # el vidrio está metido respecto del marco

    def P(a, f):
        return (c[0] + ea[0] * a + ef[0] * f, c[1] + ea[1] * a + ef[1] * f)

    def caja_local(a0, a1, f0, f1, z0, z1, mat):
        anillo_l = [P(a0, f0), P(a1, f0), P(a1, f1), P(a0, f1)]
        prisma_anillo(m, anillo_l, z0, z1, mat, color, tapa=mat, z_uv=base)
    for s in (-1, 1):  # pilares
        caja_local(*sorted((s * ha, s * (ha - pil))), -hf, hf, base, techo, "M_Concreto_Claro")
    # viga de coronación con ranura central
    ranura = 0.06 * ha * 2
    caja_local(-ha + pil, -ranura / 2, -hf, hf, techo - viga, techo, "M_Concreto_Claro")
    caja_local(ranura / 2, ha - pil, -hf, hf, techo - viga, techo, "M_Concreto_Claro")
    # cuerpo de vidrio retirado (muro cortina)
    caja_local(-ha + pil, ha - pil, -hf + retiro, hf - retiro, base, techo - viga + 0.01, "M_Muro_Cortina")
    caja_local(-ranura / 2, ranura / 2, -hf + retiro, hf - retiro, techo - viga, techo - 1.5, "M_Muro_Cortina")
    return P(0, hf + 0.05), ef, techo - viga / 2


def torre_arcos(m, anillo, base, techo, plaza, color, alto_corona=8.0, arcos=3):
    """Torre Adriática: cuerpo de oficinas con ventanas verticales y una corona hueca de arcos de medio punto."""
    c, ea, ef, ha, hf = ejes_hacia(anillo, plaza)
    an = rect_redondeado(c, ea, ef, ha, hf, 0.0)
    z_c = techo - alto_corona
    prisma_anillo(m, an, base, z_c, "M_Fachada_Beige", color, tapa="M_Techo_Concreto", z_uv=base)
    # corona: en cada cara, pilares + enjutas sobre arcos (huecos abiertos), por fuera y por dentro
    grosor = 0.6
    color = (*color[:3], 1.0)  # la corona no lleva ventanas dibujadas
    for i in range(4):
        a, b = an[i], an[(i + 1) % 4]
        L = math.dist(a, b)
        d = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        n_in = (-d[1], d[0])
        w = L / (arcos * 1.6 + 0.6)   # ancho de cada arco; pilares de 0,6 w
        pil = 0.6 * w
        h_rect = alto_corona - w / 2 - 1.2
        for capa, p_off in (("ext", 0.0), ("int", grosor)):
            def Q(u, z):
                return (a[0] + d[0] * u + n_in[0] * p_off, a[1] + d[1] * u + n_in[1] * p_off, z)

            def cara(pts, uv):
                m.cara(pts if capa == "ext" else pts[::-1], uv if capa == "ext" else uv[::-1], "M_Fachada_Beige", color=color)
            u = 0.0
            for k in range(arcos + 1):
                cara([Q(u, z_c), Q(u + pil, z_c), Q(u + pil, z_c + h_rect), Q(u, z_c + h_rect)],
                     [(u, z_c - base), (u + pil, z_c - base), (u + pil, z_c + h_rect - base), (u, z_c + h_rect - base)])
                u += pil
                if k == arcos:
                    break
                # enjuta: entre el semicírculo del arco y el borde superior (abanico desde el centro de arriba)
                cxu = u + w / 2
                arco = [(cxu - w / 2 * math.cos(math.pi * t / 8), z_c + h_rect + w / 2 * math.sin(math.pi * t / 8)) for t in range(9)]
                arriba = (cxu, techo)
                puntos = [(u, techo)] + arco + [(u + w, techo)]
                for j in range(len(puntos) - 1):
                    tri = [puntos[j], puntos[j + 1], arriba]
                    cara([Q(x, z) for x, z in tri], [(x, z - base) for x, z in tri])
                u += w
            # franja continua sobre los pilares (los pilares llegan a z_c + h_rect)
            for k in range(arcos + 1):
                u0 = k * (pil + w)
                cara([Q(u0, z_c + h_rect), Q(u0 + pil, z_c + h_rect), Q(u0 + pil, techo), Q(u0, techo)],
                     [(u0, 0), (u0 + pil, 0), (u0 + pil, 1), (u0, 1)])
        # bordes superiores e inferiores de la corona (tapas del grosor)
        b_in = (b[0] + n_in[0] * grosor, b[1] + n_in[1] * grosor)
        a_in = (a[0] + n_in[0] * grosor, a[1] + n_in[1] * grosor)
        m.cara([(*a, techo), (*b, techo), (*b_in, techo), (*a_in, techo)], [a, b, b_in, a_in], "M_Fachada_Beige", color=color)
    return c, ef, hf, techo - 1.05  # base del letrero: franja sobre los arcos


def edificio_balcones(m, anillo, base, techo, color, piso=3.0, vuelo=1.3):
    """Edificio residencial con balcones corridos en cada piso (losa volada + antepecho blanco)."""
    prisma_anillo(m, anillo, base, techo, "M_Fachada_Gris", color, tapa=None, z_uv=base)
    afuera = offset_anillo(anillo, -vuelo)
    if area_firmada(afuera) * area_firmada(anillo) <= 0:
        return
    z = base + 3.6
    while z < techo - 1.0:
        losa_volada(m, anillo, z, vuelo, 0.2, "M_Losa_Blanca")
        u = 0.0
        for a, b in zip(afuera, afuera[1:] + afuera[:1]):  # antepecho del balcón
            L = math.dist(a, b)
            m.cara([(*a, z), (*b, z), (*b, z + 1.05), (*a, z + 1.05)], [(u, 0), (u + L, 0), (u + L, 1.05), (u, 1.05)], "M_Antepecho")
            u += L
        z += piso


# ---------------------------------------------------------------- Chuao: UNEFA, Cubo Negro, CCCT

def caja_local(m, c, ea, ef, a0, a1, f0, f1, z0, z1, mat, color=(1, 1, 1, 1), tapa=True, z_uv=None):
    """Prisma rectangular en los ejes locales (ea, ef) de un edificio: a = a lo ancho, f = hacia el frente."""
    def P(a, f):
        return (c[0] + ea[0] * a + ef[0] * f, c[1] + ea[1] * a + ef[1] * f)
    an = [P(a0, f0), P(a1, f0), P(a1, f1), P(a0, f1)]
    prisma_anillo(m, an, z0, z1, mat, color, tapa=mat if tapa is True else tapa, z_uv=z_uv)
    return an


def unefa(m, anillo, base, techo, frente, color, piso=3.3, prof_torre=21.0, modulo=2.7, retiro_atras=0.0):
    """Sede UNEFA (Av. La Estancia, Chuao): torre-placa de ~19 pisos con fachada de quiebrasoles de concreto
    (aletas verticales cada 2,7 m + losas voladas en cada piso), muros de vidrio verdoso detrás, balcones en
    las culatas, y un pabellón de un piso al frente con techo plegado en zigzag y el nombre en letras."""
    c, ea, ef, ha, hf = ejes_hacia(anillo, frente)
    largo = 2 * ha * 0.96
    hl = largo / 2
    f_atras = -hf + retiro_atras        # la torre ocupa el fondo del terreno
    f_frente = f_atras + prof_torre
    z_torre0 = base + 5.5               # sobre el pabellón
    # cuerpo de la torre (vidrio y antepechos) y azotea
    caja_local(m, c, ea, ef, -hl, hl, f_atras, f_frente, base, techo, "M_Franjas_Verde", color, tapa="M_Techo_Concreto", z_uv=base)
    # losas voladas en cada piso (todo el perímetro) y aletas verticales en las dos fachadas largas
    an = [(c[0] + ea[0] * a + ef[0] * f, c[1] + ea[1] * a + ef[1] * f)
          for a, f in ((-hl, f_atras), (hl, f_atras), (hl, f_frente), (-hl, f_frente))]
    z = z_torre0
    while z < techo - 0.5:
        losa_volada(m, an, z, 1.0, 0.22, "M_Quiebrasol")
        z += piso
    losa_volada(m, an, techo, 1.0, 0.5, "M_Quiebrasol")  # cornisa
    n = int(largo / modulo)
    for k in range(n + 1):
        a = -hl + k * largo / n
        for f_cara, signo in ((f_frente, 1), (f_atras, -1)):
            f_a, f_b = sorted((f_cara, f_cara + signo * 1.0))
            caja_local(m, c, ea, ef, a - 0.12, a + 0.12, f_a, f_b, z_torre0, techo, "M_Quiebrasol", tapa=False)
    # balcones con baranda en las culatas (fachadas cortas)
    z = z_torre0
    while z < techo - 1.0:
        for a_cara, signo in ((hl, 1), (-hl, -1)):
            p0 = (c[0] + ea[0] * (a_cara + signo * 1.4) + ef[0] * f_atras, c[1] + ea[1] * (a_cara + signo * 1.4) + ef[1] * f_atras)
            p1 = (c[0] + ea[0] * (a_cara + signo * 1.4) + ef[0] * f_frente, c[1] + ea[1] * (a_cara + signo * 1.4) + ef[1] * f_frente)
            tubo(m, [(*p0, z + 1.0), (*p1, z + 1.0)], 0.03, "M_Metal_Oscuro", lados=4)
        z += piso
    # pabellón al frente: muro de vidrio bajo un techo plegado (dientes de sierra a lo largo de la fachada)
    f0, f1 = f_frente, min(hf, f_frente + 11.0)
    caja_local(m, c, ea, ef, -hl + 2, hl - 2, f0, f1 - 2.5, base, base + 4.2, "M_Vidrio_Local", tapa=False, z_uv=base)
    paso = 9.0
    k_max = int((largo - 4) / paso)
    z_alero, z_cumbre = base + 4.4, base + 6.4
    for k in range(k_max):
        a0 = -hl + 2 + k * (largo - 4) / k_max
        a1 = a0 + (largo - 4) / k_max
        am = (a0 + a1) / 2

        def P(a, f, zz):
            return (c[0] + ea[0] * a + ef[0] * f, c[1] + ea[1] * a + ef[1] * f, zz)
        for (aa, za), (ab, zb) in (((a0, z_alero), (am, z_cumbre)), ((am, z_cumbre), (a1, z_alero))):
            L = math.dist((aa, za), (ab, zb))
            m.cara([P(aa, f1, za), P(ab, f1, zb), P(ab, f0, zb), P(aa, f0, za)],
                   [(0, 0), (L, 0), (L, f1 - f0), (0, f1 - f0)], "M_Techo_Plegado")
            m.cara([P(aa, f1, za - 0.25), P(ab, f1, zb - 0.25), P(ab, f1, zb), P(aa, f1, za)],
                   [(0, 0), (L, 0), (L, 0.25), (0, 0.25)], "M_Techo_Plegado")
        # hastial triangular del frente (cierra el pliegue)
        m.cara([P(a0, f1, z_alero), P(a1, f1, z_alero), P(am, f1, z_cumbre)][::-1],
               [(0, 0), (1, 0), (0.5, 1)][::-1], "M_Techo_Plegado")
        # columnas bajo los valles
        q = P(a0, f1 - 1.0, base)
        tubo(m, [q, (q[0], q[1], z_alero)], 0.18, "M_Quiebrasol", lados=8)
    centro_frente = (c[0] + ef[0] * (f1 + 0.05), c[1] + ef[1] * (f1 + 0.05))
    esquina_techo = (c[0] + ea[0] * (-hl + 14) + ef[0] * (f_frente - 1.0), c[1] + ea[1] * (-hl + 14) + ef[1] * (f_frente - 1.0))
    return centro_frente, ef, z_alero - 0.1, esquina_techo, techo


def cubo_negro(m, anillo, base, techo, frente, color, retiro=4.0, alto_pb=7.0):
    """Centro Banaven (Cubo Negro): volumen de vidrio negro espejado sobre una planta baja retirada con
    columnas cilíndricas negras y una franja dentada en el borde del voladizo."""
    c, ea, ef, ha, hf = ejes_hacia(anillo, frente)
    caja_local(m, c, ea, ef, -ha, ha, -hf, hf, base + alto_pb, techo, "M_Vidrio_Negro", color, tapa="M_Techo_Concreto", z_uv=base)
    caja_local(m, c, ea, ef, -ha + retiro, ha - retiro, -hf + retiro, hf - retiro, base, base + alto_pb, "M_Vidrio_Negro", color,
               tapa=False, z_uv=base)
    # cara inferior del voladizo (plafón claro) y franja dentada oscura
    def P(a, f):
        return (c[0] + ea[0] * a + ef[0] * f, c[1] + ea[1] * a + ef[1] * f)
    m.cara([(*P(-ha, -hf), base + alto_pb), (*P(-ha, hf), base + alto_pb), (*P(ha, hf), base + alto_pb), (*P(ha, -hf), base + alto_pb)],
           [(0, 0), (0, 1), (1, 1), (1, 0)], "M_Antepecho")
    an = [P(-ha, -hf), P(ha, -hf), P(ha, hf), P(-ha, hf)]
    losa_volada(m, an, base + alto_pb + 0.9, 0.35, 0.9, "M_Metal_Oscuro")
    # columnas cilíndricas en el retiro
    for lado_a in (-1, 1):
        for k in range(7):
            f = -hf + retiro / 2 + k * (2 * hf - retiro) / 6
            q = P(lado_a * (ha - retiro / 2), f)
            tubo(m, [(q[0], q[1], base), (q[0], q[1], base + alto_pb)], 0.55, "M_Metal_Oscuro", lados=12)
    for lado_f in (-1, 1):
        for k in range(1, 6):
            a = -ha + retiro / 2 + k * (2 * ha - retiro) / 6
            q = P(a, lado_f * (hf - retiro / 2))
            tubo(m, [(q[0], q[1], base), (q[0], q[1], base + alto_pb)], 0.55, "M_Metal_Oscuro", lados=12)


def piramide_invertida(m, anillo, base, techo, color, abajo=0.62):
    """Pirámide Invertida del CCCT: volumen que se ensancha hacia arriba (base reducida al 62 %)."""
    c, eu, ev, hu, hv = rectangulo_orientado(anillo)
    def P(a, f, s):
        return (c[0] + (eu[0] * a + ev[0] * f) * s, c[1] + (eu[1] * a + ev[1] * f) * s)
    esquinas = [(-hu, -hv), (hu, -hv), (hu, hv), (-hu, hv)]
    z_quiebre = base + 4.0
    abajo_an = [P(a, f, abajo) for a, f in esquinas]
    arriba_an = [P(a, f, 1.0) for a, f in esquinas]
    prisma_anillo(m, abajo_an, base, z_quiebre, "M_Vidrio_Local", color, z_uv=base)
    for (a, b), (a2, b2) in zip(zip(abajo_an, abajo_an[1:] + abajo_an[:1]), zip(arriba_an, arriba_an[1:] + arriba_an[:1])):
        L = math.dist(a2, b2)
        m.cara([(*a, z_quiebre), (*b, z_quiebre), (*b2, techo), (*a2, techo)],
               [(0, 0), (L, 0), (L, techo - z_quiebre), (0, techo - z_quiebre)], "M_Vidrio_Oficina", color=color)
    m.cara([(*p, z_quiebre) for p in abajo_an][::-1], [p for p in abajo_an][::-1], "M_Concreto_Claro", color=color)
    cx, cy = c
    for a, b in zip(arriba_an, arriba_an[1:] + arriba_an[:1]):
        m.cara([(cx, cy, techo), (*a, techo), (*b, techo)], [(cx, cy), a, b], "M_Techo_Concreto", color=color)


def torre_escalera(m, x, y, z0, z1, eje, mat="M_Concreto_Claro"):
    """Torre de escalera/rampa de concreto en el extremo de una pasarela (5 × 7 m, con ventanas ranura)."""
    a, b = (eje[0] * 2.5, eje[1] * 2.5), (-eje[1] * 3.5, eje[0] * 3.5)
    an = [(x - a[0] - b[0], y - a[1] - b[1]), (x + a[0] - b[0], y + a[1] - b[1]),
          (x + a[0] + b[0], y + a[1] + b[1]), (x - a[0] + b[0], y - a[1] + b[1])]
    prisma_anillo(m, an, z0 - 0.3, z1 + 1.2, mat, tapa=mat, z_uv=z0)


def torre_control(m, anillo, base, alto, mat_fuste):
    """Fuste de concreto + cabina de vidrio volada 1 m + losa de techo."""
    z_cab = base + alto - 5.0
    z_techo = base + alto - 1.2
    cabina = offset_anillo(anillo, -1.0)  # hacia afuera
    n = len(anillo)
    u = 0.0
    for i in range(n):
        a, b = anillo[i], anillo[(i + 1) % n]
        L = math.dist(a, b)
        Pared(a, b).quad(m, 0, L, base, z_cab, 0, mat_fuste, u, base, (1, 1, 1, 1))
        u += L
    for i in range(n):
        a, b = cabina[i], cabina[(i + 1) % n]
        L = math.dist(a, b)
        if L < 0.05:
            continue
        p = Pared(a, b)
        p.quad(m, 0, L, z_cab, z_cab + 0.9, 0, "M_Fachada_Concreto", 0, z_cab, (1, 1, 1, 1))
        p.quad(m, 0, L, z_cab + 0.9, z_techo, 0, "M_Vidrio_Oficina", 0, 0, (1, 1, 1, 1), uv01=True)
        p.quad(m, 0, L, z_techo, base + alto, 0, "M_Fachada_Concreto", 0, z_techo, (1, 1, 1, 1))
    # piso volado de la cabina (mira hacia abajo) y techo
    m.cara([(x, y, z_cab) for x, y in reversed(cabina)], [(x, y) for x, y in reversed(cabina)], "M_Fachada_Concreto")
    return cabina, base + alto


# ---------------------------------------------------------------- elementos lineales y fuentes

def extruir_polilinea(m, puntos, normales, zs_suelo, ancho, alto, mat, color=(1, 1, 1, 1)):
    """Prisma a lo largo de una polilínea (setos, muros). zs_suelo = terreno en cada punto."""
    h = ancho / 2
    izq = [(p[0] + n[0] * h, p[1] + n[1] * h) for p, n in zip(puntos, normales)]
    der = [(p[0] - n[0] * h, p[1] - n[1] * h) for p, n in zip(puntos, normales)]
    s = 0.0
    for i in range(len(puntos) - 1):
        L = math.dist(puntos[i], puntos[i + 1])
        z0a, z0b = zs_suelo[i] - 0.1, zs_suelo[i + 1] - 0.1
        za, zb = zs_suelo[i] + alto, zs_suelo[i + 1] + alto
        uv = [(s, 0), (s + L, 0), (s + L, alto), (s, alto)]
        m.cara([(*der[i], z0a), (*der[i + 1], z0b), (*der[i + 1], zb), (*der[i], za)], uv, mat, color=color)
        m.cara([(*izq[i + 1], z0b), (*izq[i], z0a), (*izq[i], za), (*izq[i + 1], zb)], uv, mat, color=color)
        m.cara([(*der[i], za), (*der[i + 1], zb), (*izq[i + 1], zb), (*izq[i], za)],
               [(s, 0), (s + L, 0), (s + L, ancho), (s, ancho)], mat, color=color)
        s += L
    for k, sentido in ((0, 1), (len(puntos) - 1, -1)):
        a, b = (izq[k], der[k]) if sentido > 0 else (der[k], izq[k])
        z0, z1 = zs_suelo[k] - 0.1, zs_suelo[k] + alto
        m.cara([(*a, z0), (*b, z0), (*b, z1), (*a, z1)], [(0, 0), (ancho, 0), (ancho, alto), (0, alto)], mat, color=color)


def borde_fuente(m, anillo, z_suelo, alto, grosor, mat_borde, z_fondo=None):
    """Muro perimetral de una fuente o espejo de agua. Devuelve el anillo interior.
    z_fondo: hasta dónde baja la cara exterior (por defecto 20 cm bajo el piso)."""
    interior = offset_anillo(anillo, grosor)
    if not offset_valido(anillo, interior):
        interior = offset_anillo(anillo, grosor * 0.3)
        if not offset_valido(anillo, interior):
            return anillo
    zt = z_suelo + alto
    zf = z_suelo - 0.2 if z_fondo is None else z_fondo
    n = len(anillo)
    for i in range(n):
        a, b = anillo[i], anillo[(i + 1) % n]
        ai, bi = interior[i], interior[(i + 1) % n]
        L = math.dist(a, b)
        m.cara([(a[0], a[1], zf), (b[0], b[1], zf), (b[0], b[1], zt), (a[0], a[1], zt)],
               [(0, zf - zt + alto), (L, zf - zt + alto), (L, alto), (0, alto)], mat_borde)
        m.cara([(bi[0], bi[1], z_suelo - 0.3), (ai[0], ai[1], z_suelo - 0.3), (ai[0], ai[1], zt), (bi[0], bi[1], zt)],
               [(0, 0), (L, 0), (L, alto), (0, alto)], mat_borde)
        m.cara([(a[0], a[1], zt), (b[0], b[1], zt), (bi[0], bi[1], zt), (ai[0], ai[1], zt)],
               [(a[0], a[1]), (b[0], b[1]), (bi[0], bi[1]), (ai[0], ai[1])], mat_borde)
    return interior
