"""Repinta la textura de una aeronave según una configuración JSON (esquema de colores + marcas).

Flujo completo (ver README en esta carpeta):
    blender -b --factory-startup -P scripts/repintar/repintar_blender.py -- preparar scripts/repintar/<cfg>.json
    .venv/Scripts/python -I scripts/repintar/repintar.py scripts/repintar/<cfg>.json
    blender -b --factory-startup -P scripts/repintar/repintar_blender.py -- exportar scripts/repintar/<cfg>.json

Este paso lee lo horneado en "trabajo" (color original, posición y normal de cada texel), aplica las capas
de "pintura" en orden, proyecta las "marcas" desde los costados y guarda tex_<lado>.png. También deja
guia_der.png / guia_izq.png: vistas laterales con cuadrícula (1 unidad del modelo) para ubicar marcas.

Coordenadas: modelo ya girado, largo en Y (nariz hacia +Y), alto en Z, costado derecho en +X.
Una marca se define por su centro [y, z], su tamaño [ancho, alto] en unidades del modelo y "giro" en grados.
"""
import json
import math
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

conf_ruta = Path(sys.argv[1])
conf = json.loads(conf_ruta.read_text(encoding="utf-8-sig"))  # tolera BOM (Bloc de notas)
trabajo = Path(conf["trabajo"])
LADOS = ["der", "izq"] if conf.get("dividir") else ["unico"]
FUENTE = conf.get("fuente", "C:/Windows/Fonts/arialbd.ttf")
LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)


def srgb(c):
    return np.array(c, np.float32) / 255


def a_lineal(x):
    return np.clip(x, 0, None) ** 2.2


def a_srgb(x):
    return np.clip(x, 0, 1) ** (1 / 2.2)


# ------------------------------------------------------------------------------------- criterios
def hsv_de(rgb):
    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).convert("HSV")
    a = np.asarray(img).astype(np.float32) / 255
    return a[..., 0] * 360, a[..., 1], a[..., 2]


def mascara(crit, orig, pos, nor):
    """Criterio de selección de texeles (todas las condiciones dadas deben cumplirse)."""
    m = np.ones(orig.shape[:2], bool)
    if "cerca_de" in crit:
        d = np.linalg.norm(orig - srgb(crit["cerca_de"]), axis=-1) * 255
        m &= d < crit.get("tolerancia", 40)
    if "tono" in crit:
        h, s, v = hsv_de(orig)
        h0, h1 = crit["tono"]
        m &= ((h >= h0) & (h <= h1)) if h0 <= h1 else ((h >= h0) | (h <= h1))
        m &= s >= crit.get("sat_min", 0.0)
        m &= v >= crit.get("val_min", 0.0)
    if "brillo_min" in crit:
        m &= orig @ LUM >= crit["brillo_min"]
    if "brillo_max" in crit:
        m &= orig @ LUM <= crit["brillo_max"]
    if "caja" in crit:
        (x0, y0, z0), (x1, y1, z1) = crit["caja"]
        m &= (pos[..., 0] >= x0) & (pos[..., 0] <= x1) & (pos[..., 1] >= y0) & (pos[..., 1] <= y1) & \
             (pos[..., 2] >= z0) & (pos[..., 2] <= z1)
    if "caja_simetrica" in crit:  # igual a "caja" pero en |x| (ambos costados)
        (x0, y0, z0), (x1, y1, z1) = crit["caja_simetrica"]
        ax = np.abs(pos[..., 0])
        m &= (ax >= x0) & (ax <= x1) & (pos[..., 1] >= y0) & (pos[..., 1] <= y1) & \
             (pos[..., 2] >= z0) & (pos[..., 2] <= z1)
    for caja in crit.get("excluir_cajas_simetricas", []):  # zonas a dejar fuera (en |x|)
        (x0, y0, z0), (x1, y1, z1) = caja
        ax = np.abs(pos[..., 0])
        m &= ~((ax >= x0) & (ax <= x1) & (pos[..., 1] >= y0) & (pos[..., 1] <= y1) &
               (pos[..., 2] >= z0) & (pos[..., 2] <= z1))
    if crit.get("no", False):
        m = ~m
    return m


def suavizar(m, r=2):
    """Borde suave sin debilitar trazos finos: primero ensancha la máscara y luego la difumina."""
    img = Image.fromarray((m * 255).astype(np.uint8))
    if r >= 1:
        img = img.filter(ImageFilter.MaxFilter(2 * int(round(r)) + 1))
    img = img.filter(ImageFilter.GaussianBlur(r))
    return np.asarray(img).astype(np.float32) / 255


# ------------------------------------------------------------------------------------- ruido 3D
RNG = np.random.default_rng(conf.get("semilla", 61120))
RED = RNG.random((64, 64, 64)).astype(np.float32)


def ruido(p):
    i = np.floor(p).astype(int)
    f = p - i
    f = f * f * (3 - 2 * f)
    r = 0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (f[..., 0] if dx else 1 - f[..., 0]) * (f[..., 1] if dy else 1 - f[..., 1]) * \
                    (f[..., 2] if dz else 1 - f[..., 2])
                r = r + w * RED[(i[..., 0] + dx) % 64, (i[..., 1] + dy) % 64, (i[..., 2] + dz) % 64]
    return r


def fbm(p, escala, desfase=0.0, estirar=(1, 1, 1)):
    q = np.abs(p) * np.array(estirar, np.float32) / escala + desfase  # simétrico entre costados
    return ruido(q) * 0.7 + ruido(q * 3 + 17) * 0.3


def umbral(n, u, borde=0.03):
    return np.clip((n - u) / borde + 0.5, 0, 1)


# ------------------------------------------------------------------------------------- capas
def componentes(m):
    etiqueta = np.zeros(m.shape, np.int32)
    n, tam = 0, []
    for y0, x0 in zip(*np.nonzero(m)):
        if etiqueta[y0, x0]:
            continue
        n += 1
        q = deque([(y0, x0)])
        etiqueta[y0, x0] = n
        c = 0
        while q:
            y, x = q.popleft()
            c += 1
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < m.shape[0] and 0 <= xx < m.shape[1] and m[yy, xx] and not etiqueta[yy, xx]:
                    etiqueta[yy, xx] = n
                    q.append((yy, xx))
        tam.append(c)
    return etiqueta, tam


def difundir(campo, conocido, pasos=400):
    def caja(a):
        return (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5
    k = conocido.astype(np.float32)
    c, w = campo * k, k.copy()
    for _ in range(pasos):
        c, w = caja(c), caja(w)
        c = np.where(conocido, campo, c)
        w = np.where(conocido, 1.0, w)
    return np.where(conocido, campo, c / np.maximum(w, 1e-6))


def capa_camuflaje_remapeo(capa, orig, pos, nor, sal):
    """Camuflaje de dos tonos existente (base clara + manchas oscuras) -> esquema nuevo de tres tonos,
    conservando sombreado, desgaste y líneas de paneles del original."""
    h, s, v = hsv_de(orig)
    es_a = (h > 25) & (h < 50) & (s > 0.3) & (v > 0.45)
    es_b = (h > 70) & (h < 170) & (s > 0.15) & (v < 0.45) & (v > 0.12)
    ma, mb = orig[es_a].mean(0), orig[es_b].mean(0)
    eje = mb - ma
    t = np.clip(((orig - ma) @ eje) / (eje @ eje), -0.3, 1.3)
    proy = ma + t[..., None] * eje
    resid = np.linalg.norm(orig - proy, axis=-1) / (proy @ LUM + 0.05)
    peso = np.clip(1.6 - resid / 0.25, 0, 1)
    sombra = (orig @ LUM) / np.maximum(np.clip(proy, 0.02, 1) @ LUM, 0.02)
    sombra = np.clip(sombra / np.median(sombra[peso > 0.8]), 0.25, 1.6)
    if capa.get("borrar_rojo"):  # insignias rojas pintadas sobre el camuflaje
        # "borrar_rojo": criterio 3D (p. ej. {"caja_simetrica": ...}) de la zona donde están las insignias;
        # se borra cada mancha roja cuyo centro cae dentro (las luces y piezas rojas de otras zonas se respetan)
        zona = mascara(capa["borrar_rojo"], orig, pos, nor) if isinstance(capa["borrar_rojo"], dict) else None
        rojo = (orig[..., 0] > 2.5 * np.maximum(orig[..., 1], orig[..., 2])) & (orig[..., 0] > 0.22)
        zonas = np.asarray(Image.fromarray((rojo * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))) > 0
        etq, tams = componentes(zonas)
        relleno = np.zeros_like(zonas)
        for i, c in enumerate(tams, 1):
            m = etq == i
            if zona is not None:
                if zona[m].mean() > 0.5:
                    relleno |= m
                continue
            borde = (np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))) > 0) & ~m
            if borde.any() and peso[borde].mean() > 0.6 and es_a[borde].mean() + es_b[borde].mean() > 0.35:
                relleno |= m
        relleno = np.asarray(Image.fromarray((relleno * 255).astype(np.uint8)).filter(
            ImageFilter.MaxFilter(capa.get("dilatar_borrado", 21)))) > 0
        t, sombra = difundir(t, ~relleno), difundir(sombra, ~relleno)
        peso = np.where(relleno, 1.0, peso)
        print(f"  insignias rojas borradas: {int(relleno.sum())} texeles")
    ar = umbral(fbm(pos, capa["arena_escala"]), capa["arena_umbral"], 0.04)[..., None]
    base = a_lineal(srgb(capa["salvia"])) * (1 - ar) + a_lineal(srgb(capa["arena"])) * ar
    tt = np.clip((t - 0.15) / 0.7, 0, 1)
    tt = (tt * tt * (3 - 2 * tt))[..., None]
    pintura = (base * (1 - tt) + a_lineal(srgb(capa["verde_oscuro"])) * tt) * (sombra[..., None] ** 2.2)
    w = peso[..., None]
    return sal * (1 - w) + pintura * w


def capa_camuflaje_procedural(capa, orig, pos, nor, sal):
    """Camuflaje nuevo de 2–4 tonos a partir de ruido 3D, solo sobre los texeles elegidos por 'donde'."""
    m = suavizar(mascara(capa.get("donde", {}), orig, pos, nor), 1.5)[..., None]
    cols = [a_lineal(srgb(c)) for c in capa["colores"]]
    pint = np.broadcast_to(cols[0], sal.shape).copy()
    for k, (c, u) in enumerate(zip(cols[1:], capa["umbrales"])):
        n = fbm(pos, capa["escala"], desfase=31.7 * (k + 1), estirar=capa.get("estirar", (1, 1, 1)))
        a = umbral(n, u, capa.get("borde", 0.03))[..., None]
        pint = pint * (1 - a) + c * a
    if capa.get("suciedad", 0):  # variación suave de tono y manchas de uso
        s = fbm(pos, capa["escala"] / 6, desfase=5.3)
        pint = pint * (1 + (s[..., None] - 0.5) * capa["suciedad"])
    return sal * (1 - m) + pint * m


def capa_color(capa, orig, pos, nor, sal):
    """Pinta los texeles elegidos de un color; con 'conservar_sombreado' mantiene la luz/sombra original."""
    m = suavizar(mascara(capa["donde"], orig, pos, nor), capa.get("suave", 1.0))[..., None]
    c = a_lineal(srgb(capa["color"]))
    if capa.get("conservar_sombreado"):
        l = orig @ LUM
        ref = np.median(l[m[..., 0] > 0.5]) if (m > 0.5).any() else 1
        c = c * np.clip(l / max(ref, 1e-3), 0.5, 1.2)[..., None] ** 2.2
    return sal * (1 - m) + c * m


def capa_original(capa, orig, pos, nor, sal):
    """Devuelve el color original en los texeles elegidos (cristales, metal, ruedas...)."""
    m = suavizar(mascara(capa["donde"], orig, pos, nor), capa.get("suave", 1.0))[..., None]
    return sal * (1 - m) + a_lineal(orig) * m


CAPAS = {"camuflaje_remapeo": capa_camuflaje_remapeo, "camuflaje_procedural": capa_camuflaje_procedural,
         "color": capa_color, "original": capa_original}


# ------------------------------------------------------------------------------------- marcas
def fuente_que_quepa(d, texto, W, H, archivo):
    tam = int(H * 1.3)
    while tam > 4:
        f = ImageFont.truetype(archivo, tam)
        caja = d.textbbox((0, 0), texto, font=f)
        if (caja[2] - caja[0]) <= W * 0.96 and (caja[3] - caja[1]) <= H * 0.92:
            return f, caja
        tam -= 2
    return f, caja


def estrella(d, cx, cy, r, color):
    pts = []
    for j in range(10):
        rr = r if j % 2 == 0 else r * 0.4
        b = math.radians(-90 + 36 * j)
        pts.append((cx + rr * math.cos(b), cy + rr * math.sin(b)))
    d.polygon(pts, fill=color)


def imagen_marca(m):
    W, H = m["px"]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tipo = m["tipo"]
    if tipo == "texto":
        f, caja = fuente_que_quepa(d, m["texto"], W, H, m.get("fuente", FUENTE))
        x = (W - (caja[2] - caja[0])) / 2 - caja[0]
        y = (H - (caja[3] - caja[1])) / 2 - caja[1]
        d.text((x, y), m["texto"], font=f, fill=tuple(m["color"]) + (255,))
    elif tipo == "banda":
        d.rectangle([0, 0, W, H], fill=tuple(m["color"]) + (255,))
        if m.get("texto"):
            f, caja = fuente_que_quepa(d, m["texto"], W * 0.85, H * 0.7, m.get("fuente", FUENTE))
            x = (W - (caja[2] - caja[0])) / 2 - caja[0]
            y = (H - (caja[3] - caja[1])) / 2 - caja[1]
            d.text((x, y), m["texto"], font=f, fill=tuple(m["color_texto"]) + (255,))
    elif tipo == "bandera":  # Venezuela: amarillo, azul (8 estrellas en arco), rojo
        for k, c in enumerate(((255, 204, 0), (0, 36, 125), (207, 20, 43))):
            d.rectangle([0, k * H / 3, W, (k + 1) * H / 3], fill=c + (255,))
        if m.get("estrellas", True):  # arco de 8 estrellas dentro de la franja azul
            sh = H / 3
            rx = min(W * 0.36, sh * 0.9)
            ry = min(sh * 0.6, rx * 0.8)
            cx, cy = W / 2, H / 3 + sh * 0.5 + ry * 0.5
            r_est = min(rx, sh) * 0.15
            for k in range(8):
                a = math.radians(155 - 130 / 7 * k)
                estrella(d, cx + rx * math.cos(a), cy - ry * math.sin(a), r_est, (255, 255, 255, 255))
    elif tipo == "escarapela":  # círculo amarillo-azul-rojo concéntrico con estrella blanca (FANB)
        for k, (c, r) in enumerate((((207, 20, 43), 0.5), ((0, 36, 125), 0.36), ((255, 204, 0), 0.22))):
            d.ellipse([W / 2 - W * r, H / 2 - H * r, W / 2 + W * r, H / 2 + H * r], fill=c + (255,))
    elif tipo == "linea":  # franja lisa (por ejemplo la línea azul del fuselaje)
        d.rectangle([0, 0, W, H], fill=tuple(m["color"]) + (255,))
    return np.asarray(img).astype(np.float32) / 255


mapa = np.load(trabajo / "mapa.npz")
PASO, MN = float(mapa["paso"]), mapa["mn"]


def visibles(lado_avion, p, n):
    signo = 1 if lado_avion == "der" else -1
    impacto = mapa["x_pos" if lado_avion == "der" else "x_neg"]
    iy = np.clip(((p[..., 1] - MN[1]) / PASO).round().astype(int), 0, impacto.shape[1] - 1)
    iz = np.clip(((p[..., 2] - MN[2]) / PASO).round().astype(int), 0, impacto.shape[0] - 1)
    hx = impacto[iz, iy]
    tol = conf.get("tolerancia", PASO * 8)
    return (signo * n[..., 0] > conf.get("coseno_min", 0.3)) & (signo * p[..., 0] > 0) & \
           (np.nan_to_num(signo * (hx - p[..., 0]), nan=1e9) < tol)


def proyectar(base, lado_tex, p, n, orig):
    lados_avion = ["der", "izq"] if lado_tex == "unico" else [lado_tex]
    sombra = np.clip((orig @ LUM) / max(np.median(orig @ LUM), 1e-3), 0.6, 1.2)
    for lado in lados_avion:
        signo = 1 if lado == "der" else -1
        vis = visibles(lado, p, n)
        for m in conf.get("marcas", []):
            if lado not in m.get("lados", ["der", "izq"]):
                continue
            img = imagen_marca(m)
            H, W = img.shape[:2]
            yc, zc = m["centro"]
            ancho, alto = m["tam"]
            a = math.radians(m.get("giro", 0.0))
            dy, dz = p[..., 1] - yc, p[..., 2] - zc
            # "giro" (antihorario, medido en la vista del costado derecho) se aplica en el plano (y, z) del
            # modelo, así la marca sigue la misma pieza en ambos costados; luego la lectura se orienta hacia
            # la nariz en el costado derecho y hacia la cola en el izquierdo (como la ve quien la mira)
            ry = dy * math.cos(a) + dz * math.sin(a)
            lz = -dy * math.sin(a) + dz * math.cos(a)
            ly = ry * signo
            u = ly / ancho + 0.5
            vv = 0.5 - lz / alto
            dentro = vis & (u >= 0) & (u < 1) & (vv >= 0) & (vv < 1)
            if not dentro.any():
                print(f"  ! marca sin texeles visibles: {m.get('texto', m['tipo'])} ({lado})")
                continue
            px = np.clip(u[dentro] * W, 0, W - 1.001)
            py = np.clip(vv[dentro] * H, 0, H - 1.001)
            x0, y0 = px.astype(int), py.astype(int)
            fx, fy = (px - x0)[:, None], (py - y0)[:, None]
            x1, y1 = np.minimum(x0 + 1, W - 1), np.minimum(y0 + 1, H - 1)
            mu = (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x1] * fx * (1 - fy) +
                  img[y1, x0] * (1 - fx) * fy + img[y1, x1] * fx * fy)
            c_lin = a_lineal(mu[:, :3]) * (sombra[dentro][:, None] ** 2.2 if m.get("sombreado", True) else 1)
            al = mu[:, 3:4] * conf.get("marca_opacidad", 0.94)
            base[dentro] = base[dentro] * (1 - al) + c_lin * al
            print(f"  marca {m.get('texto', m['tipo'])} ({lado}): {int(dentro.sum())} texeles")
    return base


# ------------------------------------------------------------------------------------- guía
def guia(color_srgb, pos, nor, lado_avion, ruta):
    """Vista lateral (proyección de los texeles que miran a ese costado) con cuadrícula de 1 unidad."""
    signo = 1 if lado_avion == "der" else -1
    sel = visibles(lado_avion, pos, nor) & (np.abs(pos).sum(-1) > 0)
    ys, zs, cs = pos[sel][:, 1], pos[sel][:, 2], color_srgb[sel]
    ly = (MN[1], float(mapa["mx"][1])) if "mx" in mapa else (ys.min(), ys.max())
    lz = (MN[2], float(mapa["mx"][2])) if "mx" in mapa else (zs.min(), zs.max())
    esc = 1600 / (ly[1] - ly[0])
    Wg, Hg = 1600, int((lz[1] - lz[0]) * esc) + 1
    img = np.full((Hg, Wg, 3), 70, np.uint8)
    gx = ((ys - ly[0]) * esc).astype(int).clip(0, Wg - 1)
    if signo < 0:
        gx = Wg - 1 - gx  # costado izquierdo: la nariz queda a la izquierda, como se ve de verdad
    gy = (Hg - 1 - (zs - lz[0]) * esc).astype(int).clip(0, Hg - 1)
    orden = np.argsort(pos[sel][:, 0] * signo)  # lo más cercano al observador se dibuja al final
    for oy, ox in ((0, 0), (1, 0), (0, 1), (1, 1)):  # cada texel como un punto de 2x2 (sin huecos)
        img[np.minimum(gy[orden] + oy, Hg - 1), np.minimum(gx[orden] + ox, Wg - 1)] = (cs[orden] * 255).astype(np.uint8)
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    paso_g = 10 ** math.floor(math.log10((ly[1] - ly[0]) / 10))
    for y in np.arange(math.ceil(ly[0] / paso_g) * paso_g, ly[1], paso_g):
        x = (y - ly[0]) * esc
        x = Wg - 1 - x if signo < 0 else x
        d.line([(x, 0), (x, Hg)], fill=(255, 255, 0) if round(y / paso_g) % 5 == 0 else (110, 110, 60))
        if round(y / paso_g) % 5 == 0:
            d.text((x + 2, 2), f"y={y:g}", fill=(255, 255, 0))
    for z in np.arange(math.ceil(lz[0] / paso_g) * paso_g, lz[1], paso_g):
        yy = Hg - 1 - (z - lz[0]) * esc
        d.line([(0, yy), (Wg, yy)], fill=(0, 255, 255) if round(z / paso_g) % 5 == 0 else (60, 110, 110))
        if round(z / paso_g) % 5 == 0:
            d.text((2, yy + 2), f"z={z:g}", fill=(0, 255, 255))
    pil.save(ruta)


# ------------------------------------------------------------------------------------- principal
pos = {l: np.load(trabajo / f"pos_{l}.npy") for l in LADOS}
nor = {l: np.load(trabajo / f"nor_{l}.npy") for l in LADOS}
col = {l: a_srgb(np.load(trabajo / f"color_{l}.npy")) for l in LADOS}
for lado in LADOS:
    p, n, orig = pos[lado].copy(), nor[lado], col[lado]
    if len(LADOS) == 2:  # texeles que solo usa el otro costado: posición del otro para que el ruido sea continuo
        otro = pos["izq" if lado == "der" else "der"]
        vacio = np.abs(p).sum(-1) == 0
        p[vacio] = otro[vacio]
    sal = a_lineal(orig)
    for capa in conf.get("pintura", []):
        print(f"[{lado}] capa {capa['tipo']}")
        sal = CAPAS[capa["tipo"]](capa, orig, p, n, sal)
    sal = proyectar(sal, lado, pos[lado], n, orig)
    out = (a_srgb(sal) * 255).round().astype(np.uint8)
    Image.fromarray(out).save(trabajo / f"tex_{lado}.png", optimize=True)
    print("GUARDADO", trabajo / f"tex_{lado}.png")
    for lado_avion in (["der", "izq"] if lado == "unico" else [lado]):
        guia(out.astype(np.float32) / 255, pos[lado], n, lado_avion, trabajo / f"guia_{lado_avion}.png")
