"""Paso 03b (Blender): convierte la maqueta del paso 03 en una escena realista.

Uso:
    blender -b -P scripts/blender/03b_realismo.py -- altamira [--render] [--camara NOMBRE]
            [--hora 08:30] [--fecha 2026-03-15] [--muestras 96] [--porcentaje 70]

Abre datos/<ciudad>/<zona>/<zona>.blend (del paso 03) y guarda <zona>_realista.blend con:
  * Materiales PBR con las texturas CC0 de Poly Haven (paso 00), tinte por edificio con la paleta
    típica caraqueña, suciedad/humedad, vidrios con marcos y cortinas, rejas, santamarías,
    líneas de carril y pasos de cebra pintados (todo con fórmulas sobre UV/colores de vértice,
    replicables en Unreal).
  * Relieve de fondo (El Ávila, el valle y la costa) con vegetación y ciudad procedurales.
  * Cielo físico (Nishita) con el sol en la posición real para la fecha y hora en Caracas,
    y bruma de valle en el compositor.
  * Mobiliario: farolas, semáforos, tanques, casillas, aires acondicionados, paradas, árboles
    (jacaranda de Poly Haven), papeleras, hidrantes y tapas, como instancias (poca memoria).
  * Cámaras de referencia en Plaza Francia.
Con --render renderiza la cámara activa (Cycles, CPU) en datos/<ciudad>/<zona>/renders/.
"""

import importlib.util
import json
import math
import random
import sys
from datetime import date, datetime
from pathlib import Path

import bpy
import numpy as np

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
from comun import RAIZ, cargar_zona, carpeta_zona  # noqa: E402

_spec = importlib.util.spec_from_file_location("construir", AQUI / "03_construir_zona.py")
construir = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(construir)

TZ_CARACAS = -4.0

# Paleta de fachadas pintadas de Caracas (se elige una por edificio con el color de vértice R)
PALETA = [(0.86, 0.79, 0.63), (0.93, 0.92, 0.89), (0.87, 0.64, 0.52), (0.91, 0.83, 0.57),
          (0.72, 0.45, 0.33), (0.77, 0.77, 0.75), (0.64, 0.74, 0.81), (0.72, 0.79, 0.64),
          (0.95, 0.90, 0.80), (0.84, 0.72, 0.60)]
TINTE_ASFALTO = (0.42, 0.42, 0.44, 1)  # la textura es de asfalto claro/gastado; Caracas lo tiene más oscuro
FACHADAS_PINTADAS = {"M_Fachada_Friso", "M_Fachada_Casa", "M_Fachada_Beige", "M_Fachada_Comercial", "M_Muro"}


# ======================================================================= nodos

class Nodos:
    """Ayudante para armar árboles de nodos de sombreado con poco código."""

    def __init__(self, mat):
        mat.use_nodes = True
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.x = 0

    def nuevo(self, tipo, **props):
        n = self.nt.nodes.new(tipo)
        n.location = (self.x, -len(self.nt.nodes) * 25)
        self.x -= 15
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def unir(self, salida, entrada):
        self.nt.links.new(salida, entrada)

    def valor(self, destino, v):
        """Conecta un socket o asigna un número/tupla a una entrada."""
        if hasattr(v, "is_output"):
            self.unir(v, destino)
        else:
            destino.default_value = v

    def math(self, op, a, b=None, clamp=False):
        n = self.nuevo("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.valor(n.inputs[0], a)
        if b is not None:
            self.valor(n.inputs[1], b)
        return n.outputs[0]

    def mezcla(self, fac, a, b, modo="MIX"):
        n = self.nuevo("ShaderNodeMix", data_type="RGBA", blend_type=modo)
        self.valor(n.inputs[0], fac)
        self.valor([s for s in n.inputs if s.name == "A" and s.type == "RGBA"][0], a)
        self.valor([s for s in n.inputs if s.name == "B" and s.type == "RGBA"][0], b)
        return [s for s in n.outputs if s.name == "Result" and s.type == "RGBA"][0]

    def mezcla_f(self, fac, a, b):
        n = self.nuevo("ShaderNodeMix", data_type="FLOAT")
        self.valor(n.inputs[0], fac)
        self.valor([s for s in n.inputs if s.name == "A" and s.type == "VALUE"][0], a)
        self.valor([s for s in n.inputs if s.name == "B" and s.type == "VALUE"][0], b)
        return [s for s in n.outputs if s.name == "Result" and s.type == "VALUE"][0]

    def uv(self, capa="UV0", escala=(1.0, 1.0)):
        n = self.nuevo("ShaderNodeUVMap", uv_map=capa)
        m = self.nuevo("ShaderNodeMapping")
        m.inputs["Scale"].default_value = (escala[0], escala[1], 1.0)
        self.unir(n.outputs["UV"], m.inputs["Vector"])
        return m.outputs["Vector"]

    def xyz(self, vector):
        n = self.nuevo("ShaderNodeSeparateXYZ")
        self.unir(vector, n.inputs[0])
        return n.outputs["X"], n.outputs["Y"], n.outputs["Z"]

    def color_vertice(self):
        n = self.nuevo("ShaderNodeVertexColor", layer_name="Col")
        s = self.nuevo("ShaderNodeSeparateColor")
        self.unir(n.outputs["Color"], s.inputs[0])
        return s.outputs[0], s.outputs[1], s.outputs[2], n.outputs["Alpha"]

    def ruido(self, vector, escala, detalle=4.0, rug=0.55):
        n = self.nuevo("ShaderNodeTexNoise")
        self.valor(n.inputs["Vector"], vector)
        n.inputs["Scale"].default_value = escala
        n.inputs["Detail"].default_value = detalle
        n.inputs["Roughness"].default_value = rug
        return n.outputs["Fac"]

    def imagen(self, ruta, vector, datos=False):
        img = bpy.data.images.load(ruta, check_existing=True)
        if datos:
            img.colorspace_settings.name = "Non-Color"
        n = self.nuevo("ShaderNodeTexImage", image=img)
        self.unir(vector, n.inputs["Vector"])
        return n.outputs["Color"]

    def principled(self):
        p = self.nuevo("ShaderNodeBsdfPrincipled")
        out = self.nuevo("ShaderNodeOutputMaterial")
        self.unir(p.outputs[0], out.inputs["Surface"])
        return p, out


class Texturas:
    def __init__(self, manifiesto):
        self.m = manifiesto["texturas"]
        self.por_material = {v["material"]: k for k, v in self.m.items()}

    def de(self, material):
        tid = self.por_material.get(material)
        return self.m[tid] if tid else None


def material(nombre):
    mat = bpy.data.materials.get(nombre) or bpy.data.materials.new(nombre)
    return mat


def pbr(nombre, tex, uv_capa="UV0", tinte=None, rug_mult=1.0, normal=1.0, macro=0.12, escala_extra=1.0):
    """Material con textura real + variación macro anti-repetición. Devuelve (Nodos, principled, color)."""
    mat = material(nombre)
    g = Nodos(mat)
    p, _ = g.principled()
    sx, sy = tex["tamano_m"]
    vec = g.uv(uv_capa, (1.0 / (sx * escala_extra), 1.0 / (sy * escala_extra)))
    color = g.imagen(tex["mapas"]["color"], vec)
    if "rugosidad" in tex["mapas"]:
        rug = g.imagen(tex["mapas"]["rugosidad"], vec, datos=True)
        g.valor(p.inputs["Roughness"], g.math("MULTIPLY", rug, rug_mult, clamp=True))
    if "normal" in tex["mapas"]:
        nm = g.nuevo("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = normal
        g.unir(g.imagen(tex["mapas"]["normal"], vec, datos=True), nm.inputs["Color"])
        g.unir(nm.outputs["Normal"], p.inputs["Normal"])
    if macro:
        n = g.ruido(g.uv(uv_capa, (0.06, 0.06)), 1.0, 3.0)
        f = g.mezcla_f(n, 1.0 - macro, 1.0 + macro)
        mult = g.nuevo("ShaderNodeVectorMath", operation="SCALE")
        g.unir(color, mult.inputs[0])
        g.unir(f, mult.inputs["Scale"])
        color = mult.outputs[0]
    if tinte is not None:
        color = g.mezcla(1.0, color, tinte, "MULTIPLY")
    return g, p, color


def suciedad_fachada(g, color):
    """Manchas de humedad que escurren y zócalo más sucio (UV0.y = metros desde la base)."""
    u, v, _ = g.xyz(g.uv("UV0"))
    estirado = g.nuevo("ShaderNodeCombineXYZ")
    g.unir(g.math("MULTIPLY", u, 1.6), estirado.inputs[0])
    g.unir(g.math("MULTIPLY", v, 0.12), estirado.inputs[1])
    chorreado = g.math("SUBTRACT", g.ruido(estirado.outputs[0], 1.0, 6.0, 0.6), 0.45)
    chorreado = g.math("MULTIPLY", chorreado, 1.6, clamp=True)
    zocalo = g.math("SUBTRACT", 1.0, g.math("DIVIDE", v, 1.4), clamp=True)
    sucio = g.math("MAXIMUM", g.math("MULTIPLY", chorreado, 0.2), g.math("MULTIPLY", zocalo, 0.4))
    return g.mezcla(sucio, color, (0.18, 0.16, 0.13, 1.0), "MULTIPLY")


# ======================================================================= materiales

def materiales_fachada(tx):
    for nombre in ("M_Fachada_Friso", "M_Fachada_Casa", "M_Fachada_Beige", "M_Fachada_Comercial",
                   "M_Fachada_Ladrillo", "M_Fachada_Ceramica", "M_Fachada_Concreto", "M_Muro"):
        tex = tx.de(nombre) or tx.de("M_Fachada_Friso")
        g, p, color = pbr(nombre, tex, macro=0.08)
        r, _, _, _ = g.color_vertice()
        if nombre in FACHADAS_PINTADAS:
            hs = g.nuevo("ShaderNodeHueSaturation")
            hs.inputs["Saturation"].default_value = 0.0
            hs.inputs["Value"].default_value = 1.25
            g.unir(color, hs.inputs["Color"])
            rampa = g.nuevo("ShaderNodeValToRGB")
            rampa.color_ramp.interpolation = "CONSTANT"
            els = rampa.color_ramp.elements
            for i, c in enumerate(PALETA):
                e = els[i] if i < 2 else els.new(0)
                e.position = i / len(PALETA)
                e.color = (*c, 1.0)
            g.unir(r, rampa.inputs["Fac"])
            color = g.mezcla(1.0, hs.outputs["Color"], rampa.outputs["Color"], "MULTIPLY")
        else:  # ladrillo, cerámica y concreto: solo varía el brillo por edificio
            f = g.mezcla_f(r, 0.82, 1.12)
            esc = g.nuevo("ShaderNodeVectorMath", operation="SCALE")
            g.unir(color, esc.inputs[0])
            g.unir(f, esc.inputs["Scale"])
            color = esc.outputs[0]
        color = suciedad_fachada(g, color)
        ventanas_pintadas(g, p, color)


def ventanas_pintadas(g, p, color):
    """Ventanas dibujadas en edificios SIN geometría de detalle (color de vértice A = 0).

    Módulo de 3 m × 2,8 m (oficinas: franjas de 1,5 m × 3,6 m), sin ventanas en la planta baja.
    """
    u, v, _ = g.xyz(g.uv("UV0"))
    _, G, _, A = g.color_vertice()
    oficina = g.math("COMPARE", G, 0.2)
    oficina.node.inputs[2].default_value = 0.03
    vano = g.mezcla_f(oficina, 3.0, 1.5)
    piso = g.mezcla_f(oficina, 2.8, 3.6)
    fu = g.math("FRACT", g.math("DIVIDE", u, vano))
    fv = g.math("FRACT", g.math("DIVIDE", g.math("SUBTRACT", v, 3.6), piso))
    ancho = g.mezcla_f(oficina, 0.27, 0.05)
    en_u = g.math("MULTIPLY", g.math("GREATER_THAN", fu, ancho), g.math("LESS_THAN", fu, g.math("SUBTRACT", 1.0, ancho)))
    en_v = g.math("MULTIPLY", g.math("GREATER_THAN", fv, g.mezcla_f(oficina, 0.33, 0.18)), g.math("LESS_THAN", fv, 0.82))
    ventana = g.math("MULTIPLY", g.math("MULTIPLY", en_u, en_v), g.math("GREATER_THAN", v, 3.9))
    ventana = g.math("MULTIPLY", ventana, g.math("LESS_THAN", A, 0.5))
    vidrio = g.mezcla(oficina, (0.02, 0.025, 0.03, 1), (0.03, 0.06, 0.07, 1))
    g.unir(g.mezcla(ventana, color, vidrio), p.inputs["Base Color"])
    rug = p.inputs["Roughness"].links[0].from_socket if p.inputs["Roughness"].links else 0.8
    g.unir(g.mezcla_f(ventana, rug, 0.06), p.inputs["Roughness"])


def material_vidrio(nombre, base, cortinas, marco_ancho, interior_brillo):
    mat = material(nombre)
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))
    # marco perimetral y parteluz central
    borde = g.math("MINIMUM", g.math("MINIMUM", u, g.math("SUBTRACT", 1.0, u)),
                   g.math("MINIMUM", v, g.math("SUBTRACT", 1.0, v)))
    es_marco = g.math("LESS_THAN", borde, marco_ancho)
    parteluz = g.math("LESS_THAN", g.math("ABSOLUTE", g.math("SUBTRACT", u, 0.5)), marco_ancho * 0.6)
    es_marco = g.math("MAXIMUM", es_marco, parteluz)
    # cortinas/interiores distintos por ventana (celdas de Voronoi en coordenadas del mundo)
    vor = g.nuevo("ShaderNodeTexVoronoi")
    vor.inputs["Scale"].default_value = 0.45
    geo = g.nuevo("ShaderNodeNewGeometry")
    g.unir(geo.outputs["Position"], vor.inputs["Vector"])
    azar = g.nuevo("ShaderNodeSeparateColor")
    g.unir(vor.outputs["Color"], azar.inputs[0])
    con_cortina = g.math("GREATER_THAN", azar.outputs[0], 1.0 - cortinas)
    tono = g.mezcla(azar.outputs[1], (0.55, 0.50, 0.42, 1), (0.75, 0.72, 0.66, 1))
    interior = g.mezcla(con_cortina, (interior_brillo,) * 3 + (1,), tono)
    vidrio = g.mezcla(0.35, base, interior)
    g.unir(g.mezcla(es_marco, vidrio, (0.62, 0.63, 0.65, 1)), p.inputs["Base Color"])
    g.unir(g.mezcla_f(es_marco, 0.04, 0.4), p.inputs["Roughness"])
    g.unir(g.mezcla_f(es_marco, 0.0, 1.0), p.inputs["Metallic"])
    p.inputs["IOR"].default_value = 1.52
    p.inputs["Specular IOR Level"].default_value = 0.6


def material_reja(nombre, barrotes_u, barrotes_v, uv_metros=False):
    mat = material(nombre)
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))
    bu = g.math("LESS_THAN", g.math("FRACT", g.math("MULTIPLY", u, barrotes_u)), 0.14)
    bv = g.math("LESS_THAN", g.math("FRACT", g.math("MULTIPLY", v, barrotes_v)), 0.08)
    borde = g.math("LESS_THAN", g.math("MINIMUM", g.math("MINIMUM", u, g.math("SUBTRACT", 1.0, u)),
                                       g.math("MINIMUM", v, g.math("SUBTRACT", 1.0, v))), 0.03)
    alfa = g.math("MAXIMUM", g.math("MAXIMUM", bu, bv), 0.0 if uv_metros else borde)
    g.unir(alfa, p.inputs["Alpha"])
    p.inputs["Base Color"].default_value = (0.03, 0.03, 0.03, 1)
    p.inputs["Metallic"].default_value = 0.7
    p.inputs["Roughness"].default_value = 0.55
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"


def rampa_constante(g, fac, colores):
    rampa = g.nuevo("ShaderNodeValToRGB")
    rampa.color_ramp.interpolation = "CONSTANT"
    els = rampa.color_ramp.elements
    for i, c in enumerate(colores):
        e = els[i] if i < 2 else els.new(0)
        e.position = i / len(colores)
        e.color = (*c, 1.0)
    g.unir(fac, rampa.inputs["Fac"])
    return rampa.outputs["Color"]


def material_zinc(tx):
    """Láminas de zinc: galvanizado (la mayoría) o pintado de blanco, rojo óxido, verde o gris azulado,
    según el color de vértice R de cada edificio (como los techos de los hangares de La Carlota)."""
    g, p, color = pbr("M_Zinc", tx.de("M_Zinc"), macro=0.12)
    r, _, _, _ = g.color_vertice()
    hs = g.nuevo("ShaderNodeHueSaturation")
    hs.inputs["Saturation"].default_value = 0.0
    hs.inputs["Value"].default_value = 1.3
    g.unir(color, hs.inputs["Color"])
    pintura = g.mezcla(1.0, hs.outputs["Color"],
                       rampa_constante(g, g.math("MULTIPLY", g.math("SUBTRACT", r, 0.6), 2.45),
                                       [(0.95, 0.95, 0.93), (0.95, 0.95, 0.93), (0.62, 0.24, 0.17),
                                        (0.95, 0.95, 0.93), (0.58, 0.66, 0.76)]), "MULTIPLY")
    # R = 1 (color por defecto, sin edificio) se queda galvanizado
    pintado = g.math("MULTIPLY", g.math("GREATER_THAN", r, 0.6), g.math("LESS_THAN", r, 0.995))
    g.unir(g.mezcla(pintado, color, pintura), p.inputs["Base Color"])
    p.inputs["Metallic"].default_value = 0.0
    rug = p.inputs["Roughness"].links[0].from_socket if p.inputs["Roughness"].links else 0.5
    g.unir(g.mezcla_f(pintado, rug, 0.6), p.inputs["Roughness"])


def material_hangar_pared(tx):
    """Paredes de lámina ondulada pintada (blanco, crema o gris claro) con chorreado de suciedad."""
    g, p, color = pbr("M_Hangar_Pared", tx.de("M_Zinc"), macro=0.08)
    r, _, _, _ = g.color_vertice()
    hs = g.nuevo("ShaderNodeHueSaturation")
    hs.inputs["Saturation"].default_value = 0.0
    hs.inputs["Value"].default_value = 1.3
    g.unir(color, hs.inputs["Color"])
    tono = rampa_constante(g, r, [(0.95, 0.94, 0.9), (0.92, 0.87, 0.76), (0.82, 0.84, 0.83), (0.97, 0.96, 0.94)])
    color = suciedad_fachada(g, g.mezcla(1.0, hs.outputs["Color"], tono, "MULTIPLY"))
    g.unir(color, p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.6
    if p.inputs["Roughness"].links:
        g.nt.links.remove(p.inputs["Roughness"].links[0])


def material_muro_cerca(tx):
    """Muro bajo de concreto de la cerca: manchas de humedad, zócalo sucio y grafitis desteñidos."""
    g, p, color = pbr("M_Muro_Cerca", tx.de("M_Brocal"), macro=0.15)
    color = suciedad_fachada(g, color)
    u, v, _ = g.xyz(g.uv("UV0"))
    tramo = g.math("GREATER_THAN", g.ruido(g.uv("UV0", (0.04, 0.0)), 1.0, 2.0), 0.6)  # tramos con grafiti
    trazo = g.math("LESS_THAN", g.math("ABSOLUTE", g.math("SUBTRACT", g.ruido(g.uv("UV0", (1.0, 1.0)), 1.6, 3.0), 0.5)), 0.035)
    relleno = g.math("GREATER_THAN", g.ruido(g.uv("UV0", (0.7, 1.0)), 1.2, 2.0), 0.6)
    en_altura = g.math("MULTIPLY", g.math("GREATER_THAN", v, 0.12), g.math("LESS_THAN", v, 0.82))
    grafiti = g.math("MULTIPLY", g.math("MULTIPLY", tramo, en_altura), g.math("MAXIMUM", trazo, g.math("MULTIPLY", relleno, 0.6)))
    tinta = rampa_constante(g, g.ruido(g.uv("UV0", (0.03, 0.0)), 1.0, 1.0),
                            [(0.12, 0.35, 0.7), (0.15, 0.55, 0.55), (0.2, 0.45, 0.2), (0.05, 0.05, 0.05), (0.85, 0.85, 0.85)])
    g.unir(g.mezcla(g.math("MULTIPLY", grafiti, 0.65), color, tinta), p.inputs["Base Color"])


def material_barrotes(nombre="M_Barrotes", por_metro=7.0, rieles=((0.0, 0.05), (1.32, 1.37))):
    """Reja de barrotes verticales negros (UV en metros: u a lo largo, v a lo alto) con rieles horizontales."""
    mat = material(nombre)
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))
    alfa = g.math("LESS_THAN", g.math("FRACT", g.math("MULTIPLY", u, por_metro)), 0.17)
    for v0, v1 in rieles:
        riel = g.math("MULTIPLY", g.math("GREATER_THAN", v, v0 - 0.001), g.math("LESS_THAN", v, v1))
        alfa = g.math("MAXIMUM", alfa, riel)
    g.unir(alfa, p.inputs["Alpha"])
    p.inputs["Base Color"].default_value = (0.02, 0.02, 0.022, 1)
    p.inputs["Metallic"].default_value = 0.3
    p.inputs["Roughness"].default_value = 0.5
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"


def materiales_plaza_francia(tx):
    """Obelisco de piedra arenisca, relieves, placa de bronce, fuente (piedra, azulejo turquesa, agua,
    chorros y cortinas) y letras corpóreas."""
    # pared beige lisa (no el yeso descascarado de M_Monumento, que a 1 m se repite como cuadritos)
    tex = tx.de("M_Fachada_Beige") or tx.de("M_Monumento") or tx.de("M_Brocal")
    # piedra arenisca con hiladas cada 1,2 m (UV v = z en metros) y chorreado vertical suave
    g, p, color = pbr("M_Monumento", tex, macro=0.08, escala_extra=3.0, tinte=(1.0, 0.86, 0.66, 1))
    u, v, _ = g.xyz(g.uv("UV0"))
    junta = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", v, 1.2)), 0.01)
    estirado = g.nuevo("ShaderNodeCombineXYZ")
    g.unir(g.math("MULTIPLY", u, 0.7), estirado.inputs[0])
    g.unir(g.math("MULTIPLY", v, 0.04), estirado.inputs[1])
    chorreado = g.math("MULTIPLY", g.math("SUBTRACT", g.ruido(estirado.outputs[0], 1.0, 3.0), 0.5), 1.5, clamp=True)
    color = g.mezcla(g.math("MULTIPLY", chorreado, 0.15), color, (0.5, 0.44, 0.36, 1), "MULTIPLY")
    g.unir(g.mezcla(g.math("MULTIPLY", junta, 0.45), color, (0.4, 0.34, 0.26, 1)), p.inputs["Base Color"])
    # relieves tallados: misma piedra con mucho relieve (escudo, guirnaldas)
    g, p, color = pbr("M_Relieve", tex, macro=0.06, escala_extra=3.0, tinte=(0.92, 0.78, 0.6, 1))
    u, v, _ = g.xyz(g.uv("UV0"))
    vor = g.nuevo("ShaderNodeTexVoronoi", feature="SMOOTH_F1")
    vor.inputs["Scale"].default_value = 9.0
    g.unir(g.uv("UV0", (1.0, 1.3)), vor.inputs["Vector"])
    golpe = g.nuevo("ShaderNodeBump")
    golpe.inputs["Strength"].default_value = 0.9
    g.unir(g.math("ADD", vor.outputs["Distance"], g.math("MULTIPLY", g.ruido(g.uv("UV0", (3, 3)), 4.0, 6.0), 0.5)), golpe.inputs["Height"])
    g.unir(golpe.outputs["Normal"], p.inputs["Normal"])
    oscuro = g.math("MULTIPLY", g.math("SUBTRACT", 0.35, vor.outputs["Distance"]), 2.0, clamp=True)
    g.unir(g.mezcla(oscuro, color, (0.25, 0.2, 0.15, 1), "MULTIPLY"), p.inputs["Base Color"])
    material_simple("M_Placa", (0.22, 0.14, 0.07), 0.4, 0.85)
    # piedra de los platos: arenisca más oscura y húmeda
    g, p, color = pbr("M_Piedra_Fuente", tx.de("M_Brocal"), macro=0.1, tinte=(0.55, 0.43, 0.32, 1))
    g.unir(color, p.inputs["Base Color"])
    if p.inputs["Roughness"].links:
        g.nt.links.remove(p.inputs["Roughness"].links[0])
    p.inputs["Roughness"].default_value = 0.35
    # azulejo turquesa 15 cm con junta blanca (UV en metros)
    mat = material("M_Azulejo")
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))
    ju = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", u, 0.15)), 0.06)
    jv = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", v, 0.15)), 0.06)
    tono = g.mezcla(g.ruido(g.uv("UV0", (6.0, 6.0)), 1.0, 1.0), (0.04, 0.42, 0.45, 1), (0.08, 0.52, 0.52, 1))
    g.unir(g.mezcla(g.math("MAXIMUM", ju, jv), tono, (0.75, 0.75, 0.72, 1)), p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.15
    # agua de fuente: turquesa clara (fondo de azulejo) con ondas
    mat = material("M_Agua_Fuente")
    g = Nodos(mat)
    p, _ = g.principled()
    p.inputs["Base Color"].default_value = (0.05, 0.36, 0.40, 1)
    p.inputs["Roughness"].default_value = 0.03
    p.inputs["Coat Weight"].default_value = 0.5
    golpe = g.nuevo("ShaderNodeBump")
    golpe.inputs["Strength"].default_value = 0.15
    g.unir(g.ruido(g.uv("UV0", (1.0, 1.0)), 2.5, 4.0), golpe.inputs["Height"])
    g.unir(golpe.outputs["Normal"], p.inputs["Normal"])
    # chorros y cortinas: agua blanca translúcida con vetas
    for nombre, vetas in (("M_Chorro", 1.0), ("M_Cortina_Agua", 0.0)):
        mat = material(nombre)
        g = Nodos(mat)
        p, _ = g.principled()
        p.inputs["Base Color"].default_value = (0.85, 0.92, 0.95, 1)
        p.inputs["Roughness"].default_value = 0.1
        p.inputs["Transmission Weight"].default_value = 0.6
        p.inputs["IOR"].default_value = 1.33
        if vetas:
            p.inputs["Alpha"].default_value = 0.75
        else:
            estirado = g.nuevo("ShaderNodeCombineXYZ")
            u, v, _ = g.xyz(g.uv("UV0"))
            g.unir(g.math("MULTIPLY", u, 9.0), estirado.inputs[0])
            g.unir(g.math("MULTIPLY", v, 0.6), estirado.inputs[1])
            g.unir(g.mezcla_f(g.ruido(estirado.outputs[0], 1.0, 4.0), 0.15, 0.95), p.inputs["Alpha"])
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "DITHERED"
    material_simple("M_Letras", (0.86, 0.86, 0.84), 0.3)
    material_simple("M_Corazon", (0.72, 0.02, 0.03), 0.3)


def materiales_plaza_altamira(tx):
    """Bajada al Metro y jardines de Plaza Francia: muros blancos, pintura verde de barandas y remates,
    rampa de azulejo claro con lámina de agua, bocas del Metro, tierra de jardín, cannas y banderas."""
    tex = tx.de("M_Fachada_Casa") or tx.de("M_Brocal")
    g, p, color = pbr("M_Muro_Blanco", tex, macro=0.06, tinte=(1.0, 1.0, 0.97, 1))
    g.unir(suciedad_fachada(g, color), p.inputs["Base Color"])
    material_simple("M_Pintura_Verde", (0.03, 0.30, 0.20), 0.35)
    # azulejo claro (blanco azulado) de la rampa de la cascada
    mat = material("M_Azulejo_Claro")
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))
    ju = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", u, 0.2)), 0.05)
    jv = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", v, 0.2)), 0.05)
    g.unir(g.mezcla(g.math("MAXIMUM", ju, jv), (0.62, 0.78, 0.82, 1), (0.85, 0.87, 0.86, 1)), p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.12
    # lámina de agua que baja por la rampa: espuma blanca en vetas a lo largo de la pendiente
    mat = material("M_Lamina_Agua")
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))
    estirado = g.nuevo("ShaderNodeCombineXYZ")
    g.unir(g.math("MULTIPLY", u, 6.0), estirado.inputs[0])
    g.unir(g.math("MULTIPLY", v, 0.4), estirado.inputs[1])
    espuma = g.math("MULTIPLY", g.math("SUBTRACT", g.ruido(estirado.outputs[0], 1.0, 5.0), 0.42), 3.0, clamp=True)
    p.inputs["Base Color"].default_value = (0.9, 0.95, 0.97, 1)
    p.inputs["Roughness"].default_value = 0.05
    p.inputs["Transmission Weight"].default_value = 0.4
    g.unir(g.mezcla_f(espuma, 0.25, 0.9), p.inputs["Alpha"])
    golpe = g.nuevo("ShaderNodeBump")
    golpe.inputs["Strength"].default_value = 0.3
    g.unir(g.ruido(estirado.outputs[0], 3.0, 4.0), golpe.inputs["Height"])
    g.unir(golpe.outputs["Normal"], p.inputs["Normal"])
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    material_simple("M_Metro_Boca", (0.012, 0.012, 0.014), 0.8)
    tierra = tx.de("M_Terreno")
    if tierra:
        g, p, color = pbr("M_Tierra_Jardin", tierra, macro=0.2, tinte=(0.45, 0.38, 0.3, 1))
        g.unir(color, p.inputs["Base Color"])
    else:
        material_simple("M_Tierra_Jardin", (0.12, 0.09, 0.06), 0.9)
    hoja = material_simple("M_Hoja", (0.05, 0.2, 0.04), 0.45)
    principled_de(hoja).inputs["Subsurface Weight"].default_value = 0.15
    principled_de(hoja).inputs["Sheen Weight"].default_value = 0.3
    material_simple("M_Flor_Roja", (0.75, 0.04, 0.02), 0.5)
    material_simple("M_Flor_Amarilla", (0.88, 0.62, 0.03), 0.5)
    for nombre, c in (("M_Bandera_Verde", (0.02, 0.35, 0.08)), ("M_Bandera_Amarilla", (0.85, 0.7, 0.02)),
                      ("M_Bandera_Roja", (0.65, 0.03, 0.03))):
        b = material_simple(nombre, c, 0.8)
        principled_de(b).inputs["Sheen Weight"].default_value = 0.4


def material_franjas(nombre, vidrio, antepecho, piso, banda, modulo=1.5):
    """Fachada de franjas horizontales continuas (vidrio / antepecho), como el Hotel Caracas Palace o la
    Torre Delta. UV0 = (metros a lo largo, metros desde la base)."""
    mat = material(nombre)
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))
    f = g.math("FRACT", g.math("DIVIDE", v, piso))
    en_vidrio = g.math("MULTIPLY", g.math("GREATER_THAN", f, 0.22), g.math("LESS_THAN", f, 0.22 + banda))
    parteluz = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", u, modulo)), 0.035)
    vidrio_final = g.math("MULTIPLY", en_vidrio, g.math("SUBTRACT", 1.0, parteluz))
    # reflejos que cambian de una ventana a otra (vidrio no perfectamente plano)
    var = g.ruido(g.uv("UV0", (0.25, 0.6)), 1.0, 2.0)
    tono = g.mezcla(var, (vidrio[0] * 0.7, vidrio[1] * 0.7, vidrio[2] * 0.7, 1), (*vidrio, 1))
    marco = (antepecho[0] * 0.55, antepecho[1] * 0.55, antepecho[2] * 0.55, 1)
    color = g.mezcla(en_vidrio, (*antepecho, 1), marco)
    color = g.mezcla(vidrio_final, color, tono)
    g.unir(color, p.inputs["Base Color"])
    g.unir(g.mezcla_f(vidrio_final, 0.55, 0.04), p.inputs["Roughness"])
    g.unir(g.mezcla_f(vidrio_final, 0.0, 0.35), p.inputs["Metallic"])


def materiales_hitos(tx):
    material_franjas("M_Franjas_Azul", (0.07, 0.17, 0.38), (0.86, 0.87, 0.88), 3.4, 0.55)
    material_franjas("M_Franjas_Blanca", (0.03, 0.05, 0.06), (0.88, 0.88, 0.86), 3.3, 0.5)
    # muro cortina oscuro con retícula de perfiles (Torre Británica)
    mat = material("M_Muro_Cortina")
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))
    perfil = g.math("MAXIMUM", g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", u, 1.5)), 0.04),
                    g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", v, 3.6)), 0.03))
    var = g.ruido(g.uv("UV0", (0.3, 0.25)), 1.0, 2.0)
    vidrio = g.mezcla(var, (0.015, 0.02, 0.025, 1), (0.03, 0.04, 0.05, 1))
    g.unir(g.mezcla(perfil, vidrio, (0.08, 0.08, 0.085, 1)), p.inputs["Base Color"])
    g.unir(g.mezcla_f(perfil, 0.03, 0.4), p.inputs["Roughness"])
    g.unir(g.mezcla_f(perfil, 0.4, 0.8), p.inputs["Metallic"])
    tex = tx.de("M_Fachada_Concreto") or tx.de("M_Brocal")
    g, p, color = pbr("M_Concreto_Claro", tex, macro=0.06, tinte=(1.1, 1.08, 1.02, 1))
    g.unir(suciedad_fachada(g, color), p.inputs["Base Color"])
    tex = tx.de("M_Fachada_Comercial") or tex
    g, p, color = pbr("M_Fachada_Gris", tex, macro=0.06, tinte=(0.82, 0.83, 0.84, 1))
    color = suciedad_fachada(g, color)
    ventanas_pintadas(g, p, color)
    # Chuao: UNEFA, Cubo Negro, CCCT
    material_franjas("M_Franjas_Verde", (0.10, 0.17, 0.15), (0.70, 0.71, 0.68), 3.3, 0.62, modulo=1.35)
    material_franjas("M_Franjas_Gris", (0.03, 0.04, 0.045), (0.62, 0.61, 0.58), 3.4, 0.42)
    g, p, color = pbr("M_Quiebrasol", tex, macro=0.1, tinte=(1.05, 1.04, 1.0, 1))
    g.unir(suciedad_fachada(g, color), p.inputs["Base Color"])
    g, p, color = pbr("M_Techo_Plegado", tex, macro=0.25, tinte=(0.62, 0.68, 0.55, 1))  # concreto con moho verdoso
    g.unir(color, p.inputs["Base Color"])
    mat = material("M_Vidrio_Negro")
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))
    junta = g.math("MAXIMUM", g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", u, 1.6)), 0.02),
                   g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", v, 1.6)), 0.02))
    g.unir(g.mezcla(junta, (0.008, 0.008, 0.01, 1), (0.05, 0.05, 0.055, 1)), p.inputs["Base Color"])
    p.inputs["Metallic"].default_value = 0.9
    g.unir(g.mezcla_f(junta, 0.02, 0.4), p.inputs["Roughness"])
    # concreto gris del CCCT con el mural geométrico (amarillo, azul, rojo, blanco) en la parte baja
    tex_c = tx.de("M_Fachada_Concreto") or tex
    g, p, color = pbr("M_Mural_CCCT", tex_c, macro=0.1, tinte=(0.95, 0.94, 0.9, 1))
    color = suciedad_fachada(g, color)
    u, v, _ = g.xyz(g.uv("UV0"))
    celdas_mural = g.nuevo("ShaderNodeTexVoronoi", distance="CHEBYCHEV")
    celdas_mural.inputs["Scale"].default_value = 0.12
    g.unir(g.uv("UV0", (1.0, 1.0)), celdas_mural.inputs["Vector"])
    tono = rampa_constante(g, g.xyz(celdas_mural.outputs["Color"])[0],
                           [(0.92, 0.72, 0.05), (0.05, 0.22, 0.6), (0.92, 0.92, 0.9), (0.75, 0.12, 0.08), (0.1, 0.45, 0.75)])
    en_mural = g.math("MULTIPLY", g.math("GREATER_THAN", v, 2.5), g.math("LESS_THAN", v, 14.0))
    g.unir(g.mezcla(en_mural, color, tono), p.inputs["Base Color"])
    material_simple("M_Losa_Blanca", (0.84, 0.84, 0.82), 0.6)
    material_simple("M_Antepecho", (0.9, 0.9, 0.88), 0.45)
    material_simple("M_Letrero_Rojo", (0.7, 0.03, 0.03), 0.4)
    material_simple("M_Letrero_Azul", (0.06, 0.2, 0.52), 0.4)


def material_plaza_bandas(tx, cfg):
    """Losas de concreto beige con bandas de ladrillo rojo cada 'modulo_m' (UV = xy en metros)."""
    g, p, concreto = pbr("M_Plaza", tx.de("M_Acera") or tx.de("M_Plaza"), macro=0.12, tinte=(1.08, 0.98, 0.85, 1))
    ladrillo_tex = tx.de("M_Fachada_Ladrillo")
    mod, banda = cfg.get("modulo_m", 6.0), cfg.get("banda_m", 0.65)
    u, v, _ = g.xyz(g.uv("UV0"))
    en_u = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", u, mod)), banda / mod)
    en_v = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", v, mod)), banda / mod)
    es_banda = g.math("MAXIMUM", en_u, en_v)
    if ladrillo_tex:
        sx, sy = ladrillo_tex["tamano_m"]
        ladrillo = g.imagen(ladrillo_tex["mapas"]["color"], g.uv("UV0", (2.5 / sx, 2.5 / sy)))
        ladrillo = g.mezcla(1.0, ladrillo, (0.95, 0.7, 0.6, 1), "MULTIPLY")
    else:
        ladrillo = (0.45, 0.15, 0.09, 1)
    g.unir(g.mezcla(es_banda, concreto, ladrillo), p.inputs["Base Color"])


def material_asfalto(tx, nombre="M_Asfalto", con_lineas=True):
    g, p, color = pbr(nombre, tx.de("M_Asfalto"), macro=0.15, normal=0.6, tinte=TINTE_ASFALTO)
    rug_base = p.inputs["Roughness"].links[0].from_socket if p.inputs["Roughness"].links else 0.85
    if not con_lineas:
        g.unir(color, p.inputs["Base Color"])
        return
    u, v, _ = g.xyz(g.uv("UV1"))
    R, G, B, A = g.color_vertice()
    carriles = g.math("MAXIMUM", g.math("ROUND", g.math("MULTIPLY", R, 8.0)), 1.0)
    ancho = g.math("MULTIPLY", A, 30.0)
    marcada = g.math("GREATER_THAN", B, 0.55)
    doble = g.math("SUBTRACT", 1.0, G)  # doble sentido
    x = g.math("MULTIPLY", u, carriles)
    d = g.math("ABSOLUTE", g.math("SUBTRACT", g.math("FRACT", g.math("ADD", x, 0.5)), 0.5))
    d_m = g.math("DIVIDE", g.math("MULTIPLY", d, ancho), carriles)
    linea = g.math("LESS_THAN", d_m, 0.06)
    linea = g.math("MULTIPLY", linea, g.math("GREATER_THAN", x, 0.5))
    linea = g.math("MULTIPLY", linea, g.math("LESS_THAN", x, g.math("SUBTRACT", carriles, 0.5)))
    centro_m = g.math("MULTIPLY", g.math("ABSOLUTE", g.math("SUBTRACT", u, 0.5)), ancho)
    en_centro = g.math("MULTIPLY", doble, g.math("LESS_THAN", centro_m, 0.3))
    linea = g.math("MULTIPLY", linea, g.math("SUBTRACT", 1.0, en_centro))
    discontinua = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", v, 9.0)), 0.35)
    blanca = g.math("MULTIPLY", linea, discontinua)
    borde_m = g.math("MINIMUM", g.math("MULTIPLY", u, ancho), g.math("MULTIPLY", g.math("SUBTRACT", 1.0, u), ancho))
    orilla = g.math("MULTIPLY", g.math("GREATER_THAN", borde_m, 0.25), g.math("LESS_THAN", borde_m, 0.38))
    orilla = g.math("MULTIPLY", orilla, g.math("GREATER_THAN", B, 0.7))
    blanca = g.math("MAXIMUM", blanca, orilla)
    amarilla = g.math("MULTIPLY", g.math("MULTIPLY", doble, g.math("GREATER_THAN", carriles, 1.5)),
                      g.math("LESS_THAN", centro_m, 0.07))
    desgaste = g.math("GREATER_THAN", g.ruido(g.uv("UV0", (0.7, 0.7)), 1.0, 5.0), 0.36)
    pintura = g.math("MULTIPLY", marcada, desgaste)
    blanca = g.math("MULTIPLY", blanca, pintura)
    amarilla = g.math("MULTIPLY", amarilla, pintura)
    color = g.mezcla(blanca, color, (0.78, 0.78, 0.74, 1))
    color = g.mezcla(amarilla, color, (0.80, 0.58, 0.08, 1))
    g.unir(color, p.inputs["Base Color"])
    g.unir(g.mezcla_f(g.math("MAXIMUM", blanca, amarilla), rug_base, 0.55), p.inputs["Roughness"])


def material_cebra(tx):
    g, p, color = pbr("M_Cebra", tx.de("M_Asfalto"), macro=0.15, normal=0.6, tinte=TINTE_ASFALTO)
    u, _, _ = g.xyz(g.uv("UV0"))
    franja = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", u, 1.0)), 0.5)
    desgaste = g.math("GREATER_THAN", g.ruido(g.uv("UV0", (0.9, 0.9)), 1.0, 5.0), 0.33)
    g.unir(g.mezcla(g.math("MULTIPLY", franja, desgaste), color, (0.8, 0.8, 0.77, 1)), p.inputs["Base Color"])


def material_pista(tx):
    """Pista con marcas OACI: umbral (barras), eje discontinuo, zona de toma de contacto, punto de mira,
    bordes y desgaste de caucho. UV1 = (0..1 a lo ancho, m a lo largo); color de vértice R = ancho/80, A = largo/4000."""
    g, p, color = pbr("M_Pista", tx.de("M_Asfalto"), macro=0.12, normal=0.5, tinte=(0.34, 0.34, 0.36, 1))
    u, v, _ = g.xyz(g.uv("UV1"))
    R, _, _, A = g.color_vertice()
    W = g.math("MULTIPLY", R, 80.0)
    L = g.math("MULTIPLY", A, 4000.0)
    x = g.math("ABSOLUTE", g.math("MULTIPLY", g.math("SUBTRACT", u, 0.5), W))   # m desde el eje
    d = g.math("MINIMUM", v, g.math("SUBTRACT", L, v))                           # m desde el umbral más cercano

    def entre(a, lo, hi):
        return g.math("MULTIPLY", g.math("GREATER_THAN", a, lo), g.math("LESS_THAN", a, hi))

    borde_lateral = g.math("SUBTRACT", g.math("DIVIDE", W, 2.0), 1.5)
    umbral = g.math("MULTIPLY", entre(d, 6.0, 36.0),
                    g.math("MULTIPLY", g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", g.math("SUBTRACT", x, 0.9), 3.6)), 0.5),
                           g.math("MULTIPLY", g.math("GREATER_THAN", x, 1.8), g.math("LESS_THAN", x, borde_lateral))))
    eje = g.math("MULTIPLY", g.math("LESS_THAN", x, 0.45),
                 g.math("MULTIPLY", g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", v, 50.0)), 0.6), entre(d, 110.0, 1e5)))
    mira = g.math("MULTIPLY", entre(d, 400.0, 445.0), entre(x, 5.0, 9.0))
    toma = g.math("MULTIPLY", g.math("MAXIMUM", entre(d, 150.0, 172.5), entre(d, 300.0, 322.5)), entre(x, 5.5, 7.3))
    lado = entre(x, g.math("SUBTRACT", g.math("DIVIDE", W, 2.0), 1.0), g.math("SUBTRACT", g.math("DIVIDE", W, 2.0), 0.1))
    pintura = g.math("MAXIMUM", g.math("MAXIMUM", umbral, eje), g.math("MAXIMUM", g.math("MAXIMUM", mira, toma), lado))
    pintura = g.math("MULTIPLY", pintura, g.math("GREATER_THAN", g.ruido(g.uv("UV0", (0.5, 0.5)), 1.0, 5.0), 0.25))
    # caucho de las ruedas en la zona de toma de contacto
    caucho = g.math("MULTIPLY", g.math("MULTIPLY", entre(d, 120.0, 800.0), g.math("LESS_THAN", x, 9.0)),
                    g.math("MULTIPLY", g.ruido(g.uv("UV1", (2.0, 0.05)), 1.0, 4.0), 0.9))
    color = g.mezcla(caucho, color, (0.01, 0.01, 0.01, 1))
    color = g.mezcla(pintura, color, (0.75, 0.75, 0.72, 1))
    g.unir(color, p.inputs["Base Color"])


def material_rodaje(tx):
    """Calle de rodaje: asfalto con eje amarillo continuo (UV1.x = 0..1 a lo ancho)."""
    g, p, color = pbr("M_Rodaje", tx.de("M_Asfalto"), macro=0.12, normal=0.5, tinte=(0.4, 0.4, 0.42, 1))
    u, _, _ = g.xyz(g.uv("UV1"))
    R, _, _, _ = g.color_vertice()
    x = g.math("ABSOLUTE", g.math("MULTIPLY", g.math("SUBTRACT", u, 0.5), g.math("MULTIPLY", R, 80.0)))
    eje = g.math("MULTIPLY", g.math("LESS_THAN", x, 0.08),
                 g.math("GREATER_THAN", g.ruido(g.uv("UV0", (0.5, 0.5)), 1.0, 5.0), 0.3))
    g.unir(g.mezcla(eje, color, (0.78, 0.55, 0.06, 1)), p.inputs["Base Color"])


def material_plataforma(tx):
    """Plataforma de concreto en losas de 5 m con juntas oscuras."""
    g, p, color = pbr("M_Plataforma", tx.de("M_Techo_Concreto"), macro=0.18, tinte=(0.6, 0.63, 0.68, 1))  # neutraliza el tono cálido
    x, y, _ = g.xyz(g.uv("UV0"))
    jx = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", x, 5.0)), 0.006)
    jy = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", y, 5.0)), 0.006)
    color = g.mezcla(g.math("MAXIMUM", jx, jy), color, (0.06, 0.06, 0.06, 1))
    # manchas de aceite y combustible
    mancha = g.math("MULTIPLY", g.math("SUBTRACT", g.ruido(g.uv("UV0", (0.25, 0.25)), 1.0, 5.0), 0.6), 3.0, clamp=True)
    g.unir(g.mezcla(g.math("MULTIPLY", mancha, 0.55), color, (0.03, 0.03, 0.028, 1)), p.inputs["Base Color"])


def coordenadas_objeto(g):
    tc = g.nuevo("ShaderNodeTexCoord")
    return g.xyz(tc.outputs["Object"])


def material_bandera():
    """Bandera de Venezuela 3:2 (amarillo, azul, rojo; 8 estrellas blancas en arco). Coordenadas del objeto."""
    mat = material("M_Bandera")
    g = Nodos(mat)
    p, _ = g.principled()
    x, _, z = coordenadas_objeto(g)
    u = g.math("SUBTRACT", x, 0.05)            # 0..3 m desde el asta
    v = g.math("SUBTRACT", z, 9.8)             # 0..2 m desde abajo
    color = g.mezcla(g.math("GREATER_THAN", v, 4 / 3), (0.62, 0.02, 0.04, 1), (0.88, 0.70, 0.02, 1))
    color = g.mezcla(g.math("MULTIPLY", g.math("GREATER_THAN", v, 2 / 3), g.math("LESS_THAN", v, 4 / 3)),
                     g.mezcla(g.math("LESS_THAN", v, 2 / 3), color, (0.62, 0.02, 0.04, 1)), (0.01, 0.06, 0.32, 1))
    estrellas = None
    for k in range(8):
        ang = math.radians(160 - k * 140 / 7)
        sx, sy = 1.5 + 0.42 * math.cos(ang), 0.78 + 0.42 * math.sin(ang)
        d = g.math("SQRT", g.math("ADD", g.math("POWER", g.math("SUBTRACT", u, sx), 2.0),
                                  g.math("POWER", g.math("SUBTRACT", v, sy), 2.0)))
        e = g.math("LESS_THAN", d, 0.055)
        estrellas = e if estrellas is None else g.math("MAXIMUM", estrellas, e)
    g.unir(g.mezcla(estrellas, color, (0.9, 0.9, 0.9, 1)), p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.8
    p.inputs["Sheen Weight"].default_value = 0.4


def material_letrero():
    """Letrero de rodaje: parte roja (designación de pista, obligatorio) y amarilla (dirección) con 'texto'."""
    mat = material("M_Letrero")
    g = Nodos(mat)
    p, _ = g.principled()
    _, y, z = coordenadas_objeto(g)
    u = g.math("DIVIDE", g.math("ADD", y, 1.2), 2.4)
    v = g.math("SUBTRACT", z, 0.4)
    rojo = g.math("LESS_THAN", u, 0.45)
    fondo = g.mezcla(rojo, (0.85, 0.62, 0.03, 1), (0.6, 0.02, 0.02, 1))
    # trazos de "caracteres" en la franja central
    trazo = g.math("MULTIPLY", g.math("LESS_THAN", g.math("FRACT", g.math("MULTIPLY", u, 14.0)), 0.55),
                   g.math("MULTIPLY", g.math("GREATER_THAN", v, 0.3), g.math("LESS_THAN", v, 0.7)))
    trazo = g.math("MULTIPLY", trazo, g.math("GREATER_THAN", g.math("FRACT", g.math("MULTIPLY", u, 2.22)), 0.15))
    texto = g.mezcla(rojo, (0.02, 0.02, 0.02, 1), (0.9, 0.9, 0.9, 1))
    g.unir(g.mezcla(trazo, fondo, texto), p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.5


def material_marca_espera():
    """Marca de punto de espera: 2 líneas amarillas continuas (lado rodaje) y 2 discontinuas (lado pista)."""
    mat = material("M_Marca_Espera")
    g = Nodos(mat)
    p, _ = g.principled()
    u, v, _ = g.xyz(g.uv("UV0"))

    def banda(a, b):
        return g.math("MULTIPLY", g.math("GREATER_THAN", v, a), g.math("LESS_THAN", v, b))
    continuas = g.math("MAXIMUM", banda(0.0, 0.1), banda(0.2, 0.3))
    discontinuas = g.math("MULTIPLY", g.math("MAXIMUM", banda(0.55, 0.65), banda(0.8, 0.9)),
                          g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", u, 1.8)), 0.5))
    pintura = g.math("MAXIMUM", continuas, discontinuas)
    g.unir(pintura, p.inputs["Alpha"])
    p.inputs["Base Color"].default_value = (0.8, 0.56, 0.04, 1)
    p.inputs["Roughness"].default_value = 0.6
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"


def material_agua():
    mat = material("M_Agua")
    g = Nodos(mat)
    p, _ = g.principled()
    p.inputs["Base Color"].default_value = (0.02, 0.07, 0.07, 1)
    p.inputs["Roughness"].default_value = 0.03
    p.inputs["IOR"].default_value = 1.33
    p.inputs["Specular IOR Level"].default_value = 0.7
    bump = g.nuevo("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    g.unir(g.ruido(g.uv("UV0", (1.5, 1.5)), 1.0, 3.0), bump.inputs["Height"])
    g.unir(bump.outputs["Normal"], p.inputs["Normal"])


def material_suelo(tx, ndvi=None, satelite=None):
    """Suelo entre edificios. Con NDVI satelital: grama y tierra donde el satélite ve vegetación,
    concreto y asfalto de estacionamientos donde no. Sin NDVI: mezcla por ruido.
    Con 'satelite' (ruta, extensión) el color general sale de la imagen real (grama seca, tierra, concreto)
    y las texturas solo aportan el detalle fino."""
    mat = material("M_Terreno")
    g = Nodos(mat)
    p, _ = g.principled()
    capas = []
    for clave in ("M_Techo_Concreto", "M_Grama", "M_Terreno", "M_Asfalto"):
        tex = tx.de(clave)
        sx, sy = tex["tamano_m"]
        vec = g.uv("UV0", (1 / sx, 1 / sy))
        capas.append((g.imagen(tex["mapas"]["color"], vec), g.imagen(tex["mapas"]["rugosidad"], vec, datos=True)))
    ruido_borde = g.math("MULTIPLY", g.math("SUBTRACT", g.ruido(g.uv("UV0", (0.3, 0.3)), 1.0, 5.0), 0.5), 0.25)
    if ndvi:
        img = g.imagen(str(ndvi[0]), coordenadas_imagen(g, g.uv("UV0"), ndvi[1]), datos=True)
        img.node.interpolation = "Cubic"
        img.node.extension = "EXTEND"
        verde = g.math("GREATER_THAN", g.math("ADD", img, ruido_borde), 0.42)
    else:
        verde = g.math("GREATER_THAN", g.ruido(g.uv("UV0", (0.05, 0.05)), 1.0, 4.0), 0.52)
    tierra = g.math("GREATER_THAN", g.ruido(g.uv("UV0", (0.11, 0.11)), 1.0, 4.0), 0.6)
    asfalto = g.math("GREATER_THAN", g.ruido(g.uv("UV0", (0.025, 0.025)), 1.0, 3.0), 0.55)
    gris = g.mezcla(1.0, capas[0][0], (0.62, 0.62, 0.61, 1), "MULTIPLY")
    duro = g.mezcla(asfalto, gris, g.mezcla(1.0, capas[3][0], TINTE_ASFALTO, "MULTIPLY"))
    blando = g.mezcla(tierra, g.mezcla(1.0, capas[1][0], (0.8, 0.85, 0.7, 1), "MULTIPLY"),
                      g.mezcla(1.0, capas[2][0], (0.55, 0.45, 0.38, 1), "MULTIPLY"))
    color = g.mezcla(verde, duro, blando)
    if satelite:
        sat = g.imagen(str(satelite[0]), coordenadas_imagen(g, g.uv("UV0"), satelite[1]))
        sat.node.interpolation = "Cubic"
        gamma = g.nuevo("ShaderNodeGamma")  # el concreto urbano sale casi blanco en la imagen
        gamma.inputs["Gamma"].default_value = 1.4
        g.unir(sat, gamma.inputs["Color"])
        sat = gamma.outputs[0]
        detalle_gris = g.nuevo("ShaderNodeHueSaturation")
        detalle_gris.inputs["Saturation"].default_value = 0.0
        g.unir(color, detalle_gris.inputs["Color"])
        tono = g.mezcla(1.0, sat, (0.75, 0.75, 0.75, 1), "MULTIPLY")  # albedo urbano real ~0,2–0,3
        color = g.mezcla(0.7, color, g.mezcla(1.0, detalle_gris.outputs["Color"], tono, "MULTIPLY"))
    g.unir(color, p.inputs["Base Color"])
    g.unir(g.mezcla_f(verde, capas[0][1], capas[1][1]), p.inputs["Roughness"])


def material_grama_verde(tx):
    """Grama de parques y jardines: la textura 'leafy_grass' trae hojas secas; se lleva a verde tropical."""
    g, p, color = pbr("M_Grama", tx.de("M_Grama"), macro=0.25, normal=1.5)
    gris = g.nuevo("ShaderNodeHueSaturation")
    gris.inputs["Saturation"].default_value = 0.0
    g.unir(color, gris.inputs["Color"])
    n1 = g.ruido(g.uv("UV0", (0.08, 0.08)), 1.0, 3.0)
    tono = g.mezcla(n1, (0.05, 0.14, 0.02, 1), (0.10, 0.20, 0.035, 1))
    color = g.mezcla(1.0, gris.outputs["Color"], tono, "MULTIPLY")
    g.unir(g.mezcla(1.0, color, (2.5, 2.5, 2.5, 1), "MULTIPLY"), p.inputs["Base Color"])


def material_pasto(tx, satelite=None, cfg=None):
    """Grama de la franja de pista: verde y bien mantenida (riego), con franjas de corte paralelas a la pista.
    cfg (zonas.json → 'pasto'): {'color': 'verde'|'seco', 'rayas_angulo': grados desde el Este}."""
    cfg = cfg or {}
    g, p, color = pbr("M_Pasto", tx.de("M_Grama"), macro=0.12, normal=1.8)
    gris = g.nuevo("ShaderNodeHueSaturation")
    gris.inputs["Saturation"].default_value = 0.0
    g.unir(color, gris.inputs["Color"])
    n1 = g.ruido(g.uv("UV0", (0.04, 0.04)), 1.0, 3.0)
    n2 = g.ruido(g.uv("UV0", (0.15, 0.15)), 1.0, 4.0)
    if cfg.get("color", "verde") == "verde":
        tono = g.mezcla(n1, (0.05, 0.11, 0.025, 1), (0.085, 0.15, 0.035, 1))
        tono = g.mezcla(g.math("MULTIPLY", g.math("GREATER_THAN", n2, 0.62), 0.6), tono, (0.12, 0.15, 0.05, 1))
    else:  # temporada seca sin riego
        tono = g.mezcla(n1, (0.40, 0.34, 0.15, 1), (0.20, 0.25, 0.09, 1))
        tono = g.mezcla(g.math("MULTIPLY", g.math("GREATER_THAN", n2, 0.6), 0.7), tono, (0.50, 0.42, 0.22, 1))
    color = g.mezcla(1.0, gris.outputs["Color"], tono, "MULTIPLY")
    color = g.mezcla(1.0, color, (2.0, 2.0, 2.0, 1), "MULTIPLY")
    # franjas de corte (cortadora en ida y vuelta, ~10 m de ancho) paralelas a la pista
    ang = math.radians(cfg.get("rayas_angulo", 0.0))
    x, y, _ = g.xyz(g.uv("UV0"))
    perp = g.math("SUBTRACT", g.math("MULTIPLY", y, math.cos(ang)), g.math("MULTIPLY", x, math.sin(ang)))
    franja = g.math("LESS_THAN", g.math("FRACT", g.math("DIVIDE", perp, 20.0)), 0.5)
    color = g.mezcla(1.0, color, g.mezcla(franja, (0.88, 0.88, 0.88, 1), (1.12, 1.15, 1.08, 1)), "MULTIPLY")
    g.unir(color, p.inputs["Base Color"])
    g.unir(g.mezcla_f(franja, 0.85, 0.7), p.inputs["Roughness"])


def principled_de(mat):
    """Nodo Principled por tipo (su nombre cambia si Blender está en otro idioma)."""
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def material_simple(nombre, color, rug=0.6, metal=0.0, emision=None):
    mat = material(nombre)
    g = Nodos(mat)
    p, _ = g.principled()
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = rug
    p.inputs["Metallic"].default_value = metal
    if emision:
        p.inputs["Emission Color"].default_value = (*emision[0], 1)
        p.inputs["Emission Strength"].default_value = emision[1]
    return mat


def coordenadas_imagen(g, vector, extension):
    """Coordenadas locales (m) -> UV de una imagen que cubre 'extension' (norte arriba)."""
    xmin, ymin, xmax, ymax = extension
    m = g.nuevo("ShaderNodeMapping")
    m.inputs["Location"].default_value = (-xmin / (xmax - xmin), -ymin / (ymax - ymin), 0)
    m.inputs["Scale"].default_value = (1 / (xmax - xmin), 1 / (ymax - ymin), 1)
    g.unir(vector, m.inputs["Vector"])
    return m.outputs["Vector"]


def material_fondo_satelite(ruta_img, extension):
    """Relieve lejano con la imagen Sentinel-2 real + relieve de copas de árboles."""
    mat = material("M_Fondo")
    g = Nodos(mat)
    p, _ = g.principled()
    geo = g.nuevo("ShaderNodeNewGeometry")
    pos = geo.outputs["Position"]
    _, _, z = g.xyz(pos)
    color = g.imagen(str(ruta_img), coordenadas_imagen(g, pos, extension))
    color.node.interpolation = "Cubic"
    color.node.extension = "EXTEND"
    # el color satelital incluye bruma y sombras; se baja un poco el brillo y la saturación
    # Vegetación (verde domina) más viva; ciudad (concreto, techos) más apagada y sin blancos quemados
    rgb = g.nuevo("ShaderNodeSeparateColor")
    g.unir(color, rgb.inputs[0])
    dom = g.math("SUBTRACT", rgb.outputs[1], g.math("MAXIMUM", rgb.outputs[0], rgb.outputs[2]))
    es_veg = g.math("MULTIPLY", g.math("ADD", dom, 0.004), 120.0, clamp=True)
    veg = g.nuevo("ShaderNodeHueSaturation")
    veg.inputs["Saturation"].default_value = 1.35
    veg.inputs["Value"].default_value = 1.15
    g.unir(color, veg.inputs["Color"])
    gamma = g.nuevo("ShaderNodeGamma")
    gamma.inputs["Gamma"].default_value = 1.4
    g.unir(color, gamma.inputs["Color"])
    urb = g.nuevo("ShaderNodeHueSaturation")
    urb.inputs["Saturation"].default_value = 0.5
    urb.inputs["Value"].default_value = 0.6
    g.unir(gamma.outputs[0], urb.inputs["Color"])
    ajustado = g.mezcla(es_veg, urb.outputs[0], veg.outputs[0])
    copas = g.ruido(pos, 0.04, 3.0, 0.7)
    bump = g.nuevo("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.5
    bump.inputs["Distance"].default_value = 8.0
    g.unir(copas, bump.inputs["Height"])
    g.unir(bump.outputs["Normal"], p.inputs["Normal"])
    color = g.mezcla(g.math("MULTIPLY", copas, 0.35), ajustado, (0.0, 0.0, 0.0, 1), "MULTIPLY")
    g.unir(color, p.inputs["Base Color"])
    mar = g.math("LESS_THAN", z, -872.0)
    g.unir(g.mezcla_f(mar, 0.92, 0.05), p.inputs["Roughness"])


def material_fondo():
    """Relieve lejano: bosque del Ávila, sabana en laderas secas, ciudad en el valle y mar."""
    mat = material("M_Fondo")
    g = Nodos(mat)
    p, _ = g.principled()
    p.inputs["Roughness"].default_value = 0.9
    geo = g.nuevo("ShaderNodeNewGeometry")
    _, _, z = g.xyz(geo.outputs["Position"])
    _, _, nz = g.xyz(geo.outputs["Normal"])
    pos = geo.outputs["Position"]
    r1 = g.ruido(pos, 0.0012, 6.0, 0.6)
    r2 = g.ruido(pos, 0.006, 4.0, 0.5)
    copas = g.ruido(pos, 0.04, 3.0, 0.7)  # textura de copas de árboles (~25 m)
    bosque = g.mezcla(r1, (0.012, 0.036, 0.011, 1), (0.036, 0.075, 0.02, 1))
    bosque = g.mezcla(g.math("MULTIPLY", copas, 0.6), bosque, (0.006, 0.02, 0.006, 1))
    bump = g.nuevo("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 8.0
    g.unir(copas, bump.inputs["Height"])
    g.unir(bump.outputs["Normal"], p.inputs["Normal"])
    sabana = g.mezcla(r2, (0.09, 0.10, 0.04, 1), (0.14, 0.14, 0.07, 1))
    seco = g.math("MULTIPLY", g.math("GREATER_THAN", r1, 0.66), g.math("LESS_THAN", nz, 0.85))
    vegetacion = g.mezcla(seco, bosque, sabana)
    # ciudad: zonas planas del valle (entre -150 y +250 m respecto al origen) y de la costa
    plano = g.math("GREATER_THAN", nz, 0.965)
    valle = g.math("MULTIPLY", g.math("GREATER_THAN", z, -150.0), g.math("LESS_THAN", z, 250.0))
    costa = g.math("MULTIPLY", g.math("GREATER_THAN", z, -872.0), g.math("LESS_THAN", z, -780.0))
    ciudad = g.math("MULTIPLY", plano, g.math("MAXIMUM", valle, costa))
    ciudad = g.math("MULTIPLY", ciudad, g.math("GREATER_THAN", r2, 0.3))
    vor = g.nuevo("ShaderNodeTexVoronoi")
    vor.inputs["Scale"].default_value = 0.03
    g.unir(pos, vor.inputs["Vector"])
    tono = g.nuevo("ShaderNodeSeparateColor")
    g.unir(vor.outputs["Color"], tono.inputs[0])
    manzanas = g.mezcla(tono.outputs[0], (0.05, 0.048, 0.045, 1), (0.17, 0.16, 0.145, 1))
    manzanas = g.mezcla(g.math("GREATER_THAN", tono.outputs[1], 0.8), manzanas, (0.16, 0.08, 0.055, 1))  # techos rojizos
    arboles_ciudad = g.math("GREATER_THAN", copas, 0.52)
    manzanas = g.mezcla(arboles_ciudad, manzanas, (0.02, 0.045, 0.018, 1))  # árboles entre edificios
    color = g.mezcla(ciudad, vegetacion, manzanas)
    mar = g.math("LESS_THAN", z, -872.0)
    color = g.mezcla(mar, color, (0.01, 0.05, 0.08, 1))
    g.unir(color, p.inputs["Base Color"])
    g.unir(g.mezcla_f(mar, 0.9, 0.05), p.inputs["Roughness"])


def crear_materiales(tx, carpeta, zona):
    materiales_fachada(tx)
    material_vidrio("M_Vidrio", (0.015, 0.02, 0.025, 1), 0.55, 0.06, 0.05)
    material_vidrio("M_Vidrio_Oficina", (0.03, 0.07, 0.08, 1), 0.15, 0.025, 0.03)
    material_vidrio("M_Vidrio_Local", (0.02, 0.02, 0.02, 1), 0.3, 0.03, 0.18)
    material_reja("M_Reja", 9.0, 2.0)
    material_reja("M_Cerca", 8.0, 0.55, uv_metros=True)
    material_barrotes()
    if tx.de("M_Zinc"):
        material_zinc(tx)
        material_hangar_pared(tx)
    if tx.de("M_Brocal"):
        material_muro_cerca(tx)
        materiales_plaza_francia(tx)
        materiales_plaza_altamira(tx)
        materiales_hitos(tx)
    material_simple("M_Marco", (0.62, 0.63, 0.65), 0.35, 1.0)
    material_asfalto(tx)
    material_cebra(tx)
    material_grama_verde(tx)
    material_pista(tx)
    material_rodaje(tx)
    material_plataforma(tx)
    material_simple("M_Pintura_Blanca", (0.75, 0.75, 0.72), 0.6)
    material_simple("M_Pintura_Amarilla", (0.8, 0.56, 0.04), 0.6)
    material_simple("M_Luz_Pista", (0.9, 0.9, 0.85), 0.1, emision=((1.0, 0.95, 0.8), 3.0))
    material_simple("M_Luz_Umbral", (0.1, 0.6, 0.2), 0.1, emision=((0.1, 1.0, 0.3), 3.0))
    material_simple("M_Luz_Rodaje", (0.05, 0.15, 0.7), 0.1, emision=((0.1, 0.3, 1.0), 3.0))
    material_bandera()
    material_letrero()
    material_marca_espera()
    material_simple("M_Manga", (0.85, 0.22, 0.02), 0.7)
    avion = material_simple("M_Avion", (0.82, 0.82, 0.8), 0.25)
    principled_de(avion).inputs["Coat Weight"].default_value = 0.6
    material_simple("M_Avion_Franja", (0.03, 0.10, 0.35), 0.3)
    material_simple("M_Helicoptero", (0.10, 0.12, 0.06), 0.55)
    # vehículos: el color de la pintura viene de cada instancia (atributo 'col_auto')
    pintura = material("M_Carro_Pintura")
    g = Nodos(pintura)
    p, _ = g.principled()
    attr = g.nuevo("ShaderNodeAttribute", attribute_type="INSTANCER", attribute_name="col_auto")
    g.unir(attr.outputs["Color"], p.inputs["Base Color"])
    p.inputs["Metallic"].default_value = 0.45
    p.inputs["Roughness"].default_value = 0.28
    p.inputs["Coat Weight"].default_value = 1.0
    material_simple("M_Vidrio_Auto", (0.01, 0.012, 0.015), 0.05)
    caucho = material_simple("M_Caucho", (0.012, 0.012, 0.012), 0.92)
    principled_de(caucho).inputs["Specular IOR Level"].default_value = 0.2
    material_simple("M_Rin", (0.6, 0.6, 0.62), 0.3, 1.0)
    material_simple("M_Faros", (0.8, 0.8, 0.75), 0.1, 0.6)
    material_simple("M_Stop", (0.35, 0.01, 0.01), 0.3)
    material_agua()
    sat_meta = carpeta / "terreno" / "satelite_meta.json"
    if sat_meta.exists():  # paso 02b: imagen Sentinel-2 real
        with open(sat_meta, encoding="utf-8") as f:
            sat = json.load(f)
        material_fondo_satelite(carpeta / "terreno" / "satelite_fondo.jpg", sat["fondo_extension"])
        material_suelo(tx, (carpeta / "terreno" / "ndvi_zona.png", sat["zona_extension"]),
                       (carpeta / "terreno" / "satelite_fondo.jpg", sat["fondo_extension"]))
        material_pasto(tx, (carpeta / "terreno" / "satelite_fondo.jpg", sat["fondo_extension"]), zona.get("pasto"))
        print(f"  Imagen satelital: {sat['escena']} ({sat['fecha']})")
    else:
        material_fondo()
        material_suelo(tx)
        material_pasto(tx, cfg=zona.get("pasto"))
    for nombre, kw in {
        "M_Acera": dict(macro=0.18), "M_Brocal": dict(macro=0.1), "M_Sendero": dict(macro=0.12),
        "M_Escalera": dict(macro=0.1),
        "M_Plaza": dict(macro=0.1, tinte=(*zona["plaza"]["tinte"], 1)) if zona.get("plaza", {}).get("tinte") else dict(macro=0.1),
        "M_Cancha": dict(macro=0.1, tinte=(0.55, 0.75, 0.62, 1)),
        "M_Techo": dict(macro=0.2), "M_Techo_Concreto": dict(macro=0.2),
        "M_Santamaria": dict(uv_capa="UV0", macro=0.05, escala_extra=0.5),
        "M_Seto": dict(macro=0.3, tinte=(0.35, 0.55, 0.3, 1), normal=2.0),
    }.items():
        clave = "M_Escalera" if nombre == "M_Escalera" else nombre
        tex = tx.de({"M_Escalera": "M_Brocal", "M_Seto": "M_Grama"}.get(clave, clave))
        if tex is None:
            continue
        g, p, color = pbr(nombre, tex, **kw)
        g.unir(color, p.inputs["Base Color"])
    if zona.get("plaza", {}).get("patron") == "bandas_ladrillo":
        material_plaza_bandas(tx, zona["plaza"])
    # props
    material_simple("M_Metal_Galvanizado", (0.55, 0.56, 0.57), 0.45, 1.0)
    material_simple("M_Metal_Oscuro", (0.04, 0.045, 0.05), 0.5, 0.6)
    material_simple("M_Tanque", (0.02, 0.02, 0.022), 0.45)
    material_simple("M_Tanque_Azul", (0.03, 0.10, 0.25), 0.4)
    material_simple("M_Aire", (0.78, 0.77, 0.72), 0.5)
    material_simple("M_Luminaria", (0.9, 0.85, 0.7), 0.2, emision=((1.0, 0.75, 0.45), 0.0))
    material_simple("M_Luz_Roja", (0.6, 0.02, 0.01), 0.2, emision=((1, 0.05, 0.02), 1.5))
    material_simple("M_Luz_Verde", (0.02, 0.4, 0.15), 0.2, emision=((0.05, 1, 0.4), 0.0))


# ======================================================================= fondo

def crear_fondo(carpeta, coleccion, zona):
    ruta = carpeta / "terreno" / "fondo_altura.npy"
    if not ruta.exists():
        print("  (sin relieve de fondo: corre el paso 02 con 'fondo' en zonas.json)")
        return
    h = np.load(ruta)
    with open(carpeta / "terreno" / "fondo_meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    n, res = h.shape[0], meta["resolucion_m"]
    xmin, _, _, ymax = meta["extension_local"]
    mitad_zona = zona["tamano_m"] / 2
    xs = xmin + np.arange(n) * res
    ys = ymax - np.arange(n) * res
    X, Y = np.meshgrid(xs, ys)
    Z = h.copy()
    cerca = (np.abs(X) < mitad_zona + 150) & (np.abs(Y) < mitad_zona + 150)
    Z[cerca] -= 4.0  # queda por debajo del terreno detallado
    verts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    idx = np.arange(n * n).reshape(n, n)
    a, b, c, d = idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:], idx[:-1, :-1]  # SO, SE, NE, NO
    dentro = (np.abs(X[:-1, :-1] + res / 2) < mitad_zona - res) & (np.abs(Y[:-1, :-1] - res / 2) < mitad_zona - res)
    caras = np.stack([a[~dentro], b[~dentro], c[~dentro], d[~dentro]], axis=1)
    me = bpy.data.meshes.new("Fondo_Relieve")
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.astype(np.float32).ravel())
    me.loops.add(caras.size)
    me.loops.foreach_set("vertex_index", caras.astype(np.int32).ravel())
    me.polygons.add(len(caras))
    me.polygons.foreach_set("loop_start", (np.arange(len(caras)) * 4).astype(np.int32))
    me.polygons.foreach_set("loop_total", np.full(len(caras), 4, np.int32))
    me.update(calc_edges=True)
    try:
        me.shade_smooth()
    except AttributeError:
        me.polygons.foreach_set("use_smooth", np.ones(len(caras), bool))
    me.materials.append(bpy.data.materials["M_Fondo"])
    obj = bpy.data.objects.new("Fondo_Relieve", me)
    coleccion.objects.link(obj)
    print(f"  Fondo: {len(caras):,} caras, hasta {meta['max_msnm']:.0f} m s.n.m.")


# ======================================================================= props

def canna(material_flor):
    """Planta de canna (platanillo de jardín): 7 hojas anchas inclinadas, tallo y racimo de flores."""
    partes = []
    for k in range(7):
        rz = k * 51.4 + (k % 3) * 9
        rx = 16 + (k % 3) * 9
        largo = 0.75 + (k % 2) * 0.15
        eje = (math.sin(math.radians(rz)) * math.sin(math.radians(rx)), -math.cos(math.radians(rz)) * math.sin(math.radians(rx)),
               math.cos(math.radians(rx)))
        centro = tuple(c * largo / 2 for c in eje)
        partes.append(("caja", (0.17, 0.012, largo), (centro[0], centro[1], centro[2] + 0.05), (rx, 0, rz), "M_Hoja"))
    if material_flor:
        partes.append(("cil", (0.012, 0.009, 1.15), (0, 0, 0.58), 0, "M_Hoja"))
        for k in range(4):
            a = math.radians(k * 90 + 20)
            partes.append(("esfera", (0.05, 0.035, 0.11), (0.05 * math.cos(a), 0.05 * math.sin(a), 1.17 + 0.04 * k),
                           (25 * math.sin(a), 25 * math.cos(a), 0), material_flor))
    return partes


def malla_de_partes(nombre, partes):
    """Crea un objeto a partir de primitivas: (tipo, tamaño, posición, rotación, material).
    tipo: caja (tamaño = lados), cil (radio abajo, radio arriba, alto), esfera (semiejes).
    rotación: grados alrededor de Y, o (rx, ry, rz) en grados."""
    import bmesh
    from mathutils import Euler, Matrix
    bm = bmesh.new()
    mats = []
    for tipo, tam, pos, rot, mat in partes:
        if mat not in mats:
            mats.append(mat)
        antes = set(bm.verts)
        if tipo in ("caja", "cabina", "carroceria"):
            g = bmesh.ops.create_cube(bm, size=1.0)
            vs = g["verts"]
            if tipo == "cabina":  # techo más corto y angosto: parabrisas y luneta inclinados
                for v in vs:
                    if v.co.z > 0:
                        v.co.x = v.co.x * 0.62 - 0.06
                        v.co.y *= 0.84
            elif tipo == "carroceria":  # capó y maletero más bajos que el centro
                largas = [e for e in bm.edges if e.verts[0] in vs and e.verts[1] in vs
                          and abs(e.verts[0].co.x - e.verts[1].co.x) > 0.5]
                bmesh.ops.subdivide_edges(bm, edges=largas, cuts=2, use_grid_fill=True)
                vs = [v for v in bm.verts if v not in antes]
                for v in vs:
                    if v.co.z > 0 and abs(v.co.x) > 0.3:
                        v.co.z -= 0.25
            bmesh.ops.scale(bm, vec=tam, verts=vs)
            if tipo != "caja":  # bordes redondeados (el bisel crea vértices nuevos)
                aristas = list({e for v in vs for e in v.link_edges})
                bmesh.ops.bevel(bm, geom=aristas, offset=min(0.08, min(tam) * 0.2), segments=2,
                                affect="EDGES", profile=0.6)
                vs = [v for v in bm.verts if v not in antes]
        elif tipo == "esfera":
            g = bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=1.0)
            vs = g["verts"]
            bmesh.ops.scale(bm, vec=tam, verts=vs)
        else:  # cilindro: tam = (radio_abajo, radio_arriba, alto)
            g = bmesh.ops.create_cone(bm, cap_ends=True, segments=12 if max(tam[0], tam[1]) < 0.3 else 24,
                                      radius1=tam[0], radius2=tam[1], depth=tam[2])
            vs = g["verts"]
        if isinstance(rot, (tuple, list)):
            matriz = Euler([math.radians(a) for a in rot], "XYZ").to_matrix()
            bmesh.ops.rotate(bm, verts=vs, cent=(0, 0, 0), matrix=matriz)
        elif rot:
            bmesh.ops.rotate(bm, verts=vs, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(rot), 3, "Y"))
        bmesh.ops.translate(bm, vec=pos, verts=vs)
        caras = {f for v in vs for f in v.link_faces}
        for f in caras:
            f.material_index = mats.index(mat)
    me = bpy.data.meshes.new(nombre)
    bm.to_mesh(me)
    bm.free()
    try:  # cilindros y esferas suaves, aristas de cajas marcadas
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(40))
    except AttributeError:
        pass
    for m in mats:
        me.materials.append(bpy.data.materials[m])
    return bpy.data.objects.new(nombre, me)


def tren(x, y, z_eje, alto_pata):
    return [("cil", (0.32, 0.32, 0.22), (x, y, 0.32), (90, 0, 0), "M_Metal_Oscuro"),
            ("caja", (0.12, 0.12, alto_pata), (x, y, 0.32 + alto_pata / 2), 0, "M_Metal_Galvanizado")]


def aeronave_turbohelice():
    """Bimotor turbohélice tipo King Air 350 (14,2 m de largo, 17,6 m de envergadura). Nariz hacia +X."""
    p = [("cil", (0.85, 0.85, 9.0), (0.3, 0, 1.95), (0, 90, 0), "M_Avion"),
         ("esfera", (2.0, 0.85, 0.8), (4.8, 0, 1.92), 0, "M_Avion"),
         ("esfera", (0.95, 0.7, 0.38), (4.4, 0, 2.45), 0, "M_Vidrio_Oficina"),
         ("cil", (0.85, 0.22, 4.2), (-6.2, 0, 2.15), (0, -90, 0), "M_Avion"),
         ("caja", (6.0, 1.72, 0.26), (0.4, 0, 2.2), 0, "M_Vidrio_Oficina"),
         ("caja", (13.0, 1.73, 0.12), (-0.4, 0, 1.72), 0, "M_Avion_Franja"),
         ("caja", (2.0, 17.6, 0.25), (0.6, 0, 1.25), 0, "M_Avion"),
         ("caja", (2.5, 0.22, 2.5), (-7.0, 0, 3.3), 0, "M_Avion"),
         ("caja", (1.4, 5.6, 0.14), (-7.7, 0, 4.5), 0, "M_Avion")]
    for y in (2.7, -2.7):
        p += [("cil", (0.42, 0.34, 3.2), (1.7, y, 1.35), (0, 90, 0), "M_Avion"),
              ("caja", (0.06, 2.5, 0.18), (3.35, y, 1.35), (35, 0, 0), "M_Metal_Oscuro")]
        p += tren(1.6, y, 0.32, 0.9)
    p += tren(4.0, 0, 0.32, 0.8)
    return p


def aeronave_jet():
    """Jet ejecutivo tipo Citation (15 m de largo, 15 m de envergadura, motores traseros). Nariz hacia +X."""
    p = [("cil", (0.95, 0.95, 10.0), (0.0, 0, 2.0), (0, 90, 0), "M_Avion"),
         ("esfera", (2.6, 0.95, 0.9), (5.0, 0, 1.95), 0, "M_Avion"),
         ("esfera", (1.0, 0.75, 0.42), (4.6, 0, 2.55), 0, "M_Vidrio_Oficina"),
         ("cil", (0.95, 0.3, 4.5), (-7.2, 0, 2.2), (0, -90, 0), "M_Avion"),
         ("caja", (6.0, 1.92, 0.3), (0.3, 0, 2.25), 0, "M_Vidrio_Oficina"),
         ("caja", (14.0, 1.93, 0.14), (-0.6, 0, 1.75), 0, "M_Avion_Franja"),
         ("caja", (2.6, 7.2, 0.22), (-0.9, 3.9, 1.25), (0, 0, 25), "M_Avion"),
         ("caja", (2.6, 7.2, 0.22), (-0.9, -3.9, 1.25), (0, 0, -25), "M_Avion"),
         ("caja", (2.8, 0.22, 2.8), (-7.4, 0, 3.8), 0, "M_Avion"),
         ("caja", (1.4, 5.2, 0.14), (-8.1, 0, 5.15), 0, "M_Avion")]
    for y in (1.75, -1.75):
        p += [("cil", (0.6, 0.5, 3.0), (-4.4, y, 2.65), (0, 90, 0), "M_Avion"),
              ("caja", (1.2, 0.8, 0.15), (-4.4, y * 0.7, 2.55), 0, "M_Avion")]
        p += tren(-0.6, y * 0.95, 0.32, 0.9)
    p += tren(4.4, 0, 0.32, 0.8)
    return p


def aeronave_helicoptero():
    """Helicóptero utilitario militar tipo Bell 412 (rotor de 14 m), verde oliva. Nariz hacia +X."""
    p = [("esfera", (2.4, 1.25, 1.25), (0.8, 0, 1.6), 0, "M_Helicoptero"),
         ("caja", (3.4, 2.3, 2.0), (-0.9, 0, 1.6), 0, "M_Helicoptero"),
         ("esfera", (1.3, 1.05, 0.8), (1.9, 0, 1.95), 0, "M_Vidrio_Oficina"),
         ("caja", (2.6, 1.4, 0.7), (-0.6, 0, 2.85), 0, "M_Helicoptero"),
         ("cil", (0.5, 0.22, 7.0), (-6.0, 0, 2.2), (0, -90, 0), "M_Helicoptero"),
         ("caja", (1.1, 0.15, 1.8), (-9.3, 0, 3.0), 0, "M_Helicoptero"),
         ("caja", (0.7, 2.6, 0.08), (-8.0, 0, 2.3), 0, "M_Helicoptero"),
         ("caja", (0.25, 0.05, 2.6), (-9.4, 0.3, 3.0), 0, "M_Metal_Oscuro"),
         ("caja", (0.25, 0.05, 2.6), (-9.4, 0.3, 3.0), (90, 0, 0), "M_Metal_Oscuro"),
         ("cil", (0.14, 0.14, 0.6), (-0.5, 0, 3.45), 0, "M_Metal_Oscuro"),
         ("caja", (14.0, 0.4, 0.05), (-0.5, 0, 3.8), (0, 0, 20), "M_Metal_Oscuro"),
         ("caja", (14.0, 0.4, 0.05), (-0.5, 0, 3.8), (0, 0, 110), "M_Metal_Oscuro")]
    for y in (1.2, -1.2):
        p += [("caja", (3.8, 0.1, 0.1), (-0.6, y, 0.08), 0, "M_Metal_Oscuro"),
              ("caja", (0.1, 0.1, 0.75), (0.4, y * 0.95, 0.45), 0, "M_Metal_Oscuro"),
              ("caja", (0.1, 0.1, 0.75), (-1.6, y * 0.95, 0.45), 0, "M_Metal_Oscuro")]
    return p


def ruedas(xs, y, r=0.32, ancho=0.22):
    """Cauchos con rin metálico (el rin sobresale un poco para que la rueda se lea desde lejos)."""
    return ([("cil", (r, r, ancho), (x, s * y, r), (90, 0, 0), "M_Caucho") for x in xs for s in (1, -1)]
            + [("cil", (r * 0.62, r * 0.62, ancho + 0.02), (x, s * y, r), (90, 0, 0), "M_Rin") for x in xs for s in (1, -1)])


def carro(largo, ancho, alto_carroceria, cabina, despeje=0.18, radio_rueda=0.32):
    """Vehículo genérico: carrocería + cabina de vidrio con techo pintado + ruedas + luces. Frente hacia +X.
    cabina = (largo, desplazamiento x, alto)."""
    z_c = despeje + alto_carroceria / 2
    lc, xc, hc = cabina
    z_cab = despeje + alto_carroceria + hc / 2
    dx = largo / 2 - 0.75
    return ([("carroceria", (largo, ancho, alto_carroceria), (0, 0, z_c), 0, "M_Carro_Pintura"),
             ("cabina", (lc, ancho - 0.1, hc), (xc, 0, z_cab - 0.05), 0, "M_Vidrio_Auto"),
             ("cabina", (lc * 0.66, ancho * 0.82, 0.07), (xc - 0.06 * lc, 0, z_cab + hc / 2 - 0.05), 0, "M_Carro_Pintura"),
             ("caja", (0.05, 0.32, 0.12), (largo / 2, ancho * 0.33, z_c + 0.12), 0, "M_Faros"),
             ("caja", (0.05, 0.32, 0.12), (largo / 2, -ancho * 0.33, z_c + 0.12), 0, "M_Faros"),
             ("caja", (0.05, 0.3, 0.12), (-largo / 2, ancho * 0.33, z_c + 0.15), 0, "M_Stop"),
             ("caja", (0.05, 0.3, 0.12), (-largo / 2, -ancho * 0.33, z_c + 0.15), 0, "M_Stop")]
            + ruedas((dx, -dx), ancho / 2 - 0.08, radio_rueda))


def vehiculos_procedurales():
    """Modelos simples con medidas reales de los vehículos más comunes en Caracas."""
    return {
        "sedan": carro(4.5, 1.76, 0.72, (2.3, -0.25, 0.52)),
        "hatchback": carro(3.9, 1.7, 0.78, (2.1, -0.35, 0.55)),
        "camioneta": carro(4.75, 1.9, 0.95, (2.9, -0.35, 0.62), despeje=0.25, radio_rueda=0.38),
        "pickup": carro(5.3, 1.86, 0.9, (1.7, 0.45, 0.6), despeje=0.26, radio_rueda=0.38)
        + [("caja", (2.0, 1.86, 0.45), (-1.6, 0, 1.38), 0, "M_Carro_Pintura")],
        "por_puesto": carro(6.6, 2.1, 1.25, (5.4, -0.3, 0.85), despeje=0.3, radio_rueda=0.42)
        + [("caja", (6.4, 2.12, 0.12), (0, 0, 1.6), 0, "M_Avion_Franja")],
        "moto": [("caja", (1.5, 0.28, 0.45), (0, 0, 0.62), 0, "M_Carro_Pintura"),
                 ("caja", (0.5, 0.3, 0.12), (-0.25, 0, 0.92), 0, "M_Caucho"),
                 ("cil", (0.3, 0.3, 0.09), (0.68, 0, 0.3), (90, 0, 0), "M_Caucho"),
                 ("cil", (0.3, 0.3, 0.09), (-0.68, 0, 0.3), (90, 0, 0), "M_Caucho"),
                 ("cil", (0.025, 0.025, 0.65), (0.55, 0, 0.98), (0, 25, 0), "M_Metal_Galvanizado")],
    }


def biblioteca_procedural():
    """Modelos simples con medidas reales (pivote en la base; +X = hacia la calle/frente)."""
    return {
        "farola": [("cil", (0.11, 0.065, 9.0), (0, 0, 4.5), 0, "M_Metal_Galvanizado"),
                   ("cil", (0.045, 0.045, 1.9), (0.95, 0, 8.95), 90, "M_Metal_Galvanizado"),
                   ("caja", (0.75, 0.3, 0.14), (2.05, 0, 8.9), 0, "M_Metal_Galvanizado"),
                   ("caja", (0.6, 0.22, 0.02), (2.05, 0, 8.82), 0, "M_Luminaria")],
        "semaforo": [("cil", (0.08, 0.07, 4.4), (0, 0, 2.2), 0, "M_Metal_Oscuro"),
                     ("caja", (0.3, 0.34, 1.0), (0.18, 0, 3.8), 0, "M_Metal_Oscuro"),
                     ("cil", (0.1, 0.1, 0.06), (0.35, 0, 4.1), 90, "M_Luz_Roja"),
                     ("cil", (0.1, 0.1, 0.06), (0.35, 0, 3.8), 90, "M_Metal_Oscuro"),
                     ("cil", (0.1, 0.1, 0.06), (0.35, 0, 3.5), 90, "M_Luz_Verde")],
        "tanque": [("cil", (1.0, 1.0, 1.55), (0, 0, 0.78), 0, "M_Tanque"),
                   ("cil", (0.32, 0.32, 0.12), (0, 0, 1.6), 0, "M_Tanque")],
        "casilla": [("caja", (3.2, 4.0, 2.8), (0, 0, 1.4), 0, "M_Muro"),
                    ("caja", (3.4, 4.2, 0.15), (0, 0, 2.87), 0, "M_Techo_Concreto")],
        "aire": [("caja", (0.45, 0.72, 0.5), (0, 0, 0.25), 0, "M_Aire"),
                 ("caja", (0.02, 0.5, 0.36), (0.23, 0, 0.25), 0, "M_Metal_Oscuro")],
        "parada": [("caja", (1.7, 3.4, 0.08), (0, 0, 2.55), 0, "M_Metal_Galvanizado"),
                   ("caja", (0.08, 0.08, 2.5), (-0.7, 1.6, 1.25), 0, "M_Metal_Galvanizado"),
                   ("caja", (0.08, 0.08, 2.5), (-0.7, -1.6, 1.25), 0, "M_Metal_Galvanizado"),
                   ("caja", (0.03, 3.2, 1.8), (-0.75, 0, 1.3), 0, "M_Vidrio_Local"),
                   ("caja", (0.45, 2.4, 0.06), (-0.45, 0, 0.45), 0, "M_Metal_Galvanizado")],
        "metro": [("caja", (6.0, 3.2, 1.05), (0, 0, 0.52), 0, "M_Brocal"),
                  ("cil", (0.06, 0.06, 2.6), (2.6, 1.8, 1.3), 0, "M_Metal_Oscuro"),
                  ("caja", (0.06, 0.7, 0.7), (2.6, 1.8, 2.75), 0, "M_Luz_Roja")],
        "manga": [("cil", (0.06, 0.05, 6.0), (0, 0, 3.0), 0, "M_Metal_Galvanizado"),
                  ("cil", (0.45, 0.22, 3.6), (1.85, 0, 5.75), 90, "M_Manga")],
        "avion_turbohelice": aeronave_turbohelice(),
        "avion_jet": aeronave_jet(),
        "helicoptero": aeronave_helicoptero(),
        "luz_pista": [("cil", (0.09, 0.07, 0.32), (0, 0, 0.16), 0, "M_Metal_Galvanizado"),
                      ("cil", (0.1, 0.1, 0.08), (0, 0, 0.36), 0, "M_Luz_Pista")],
        "luz_umbral": [("cil", (0.09, 0.07, 0.32), (0, 0, 0.16), 0, "M_Metal_Galvanizado"),
                       ("cil", (0.1, 0.1, 0.08), (0, 0, 0.36), 0, "M_Luz_Umbral")],
        "luz_rodaje": [("cil", (0.08, 0.06, 0.3), (0, 0, 0.15), 0, "M_Metal_Galvanizado"),
                       ("cil", (0.09, 0.09, 0.08), (0, 0, 0.34), 0, "M_Luz_Rodaje")],
        "letrero_rodaje": [("caja", (0.25, 2.4, 1.0), (0, 0, 0.9), 0, "M_Letrero"),
                           ("caja", (0.08, 0.08, 0.45), (0, 0.9, 0.22), 0, "M_Metal_Galvanizado"),
                           ("caja", (0.08, 0.08, 0.45), (0, -0.9, 0.22), 0, "M_Metal_Galvanizado")],
        "bandera": [("cil", (0.07, 0.045, 12.0), (0, 0, 6.0), 0, "M_Metal_Galvanizado"),
                    ("esfera", (0.12, 0.12, 0.12), (0, 0, 12.05), 0, "M_Metal_Galvanizado"),
                    ("caja", (3.0, 0.02, 2.0), (1.55, 0, 10.8), 0, "M_Bandera")],
        **{f"bandera_{c}": [("cil", (0.07, 0.045, 12.0), (0, 0, 6.0), 0, "M_Pintura_Verde"),
                            ("esfera", (0.12, 0.12, 0.12), (0, 0, 12.05), 0, "M_Metal_Galvanizado"),
                            ("caja", (3.0, 0.02, 2.0), (1.55, 0, 10.8), 0, f"M_Bandera_{c.capitalize()}")]
           for c in ("verde", "amarilla", "roja")},
        **{nombre: canna(flor) for nombre, flor in (("canna_roja", "M_Flor_Roja"), ("canna_amarilla", "M_Flor_Amarilla"),
                                                     ("canna_hojas", None))},
        "banco": [("caja", (0.5, 1.8, 0.08), (0, 0, 0.45), 0, "M_Brocal"),
                  ("caja", (0.4, 0.15, 0.42), (0, 0.75, 0.21), 0, "M_Brocal"),
                  ("caja", (0.4, 0.15, 0.42), (0, -0.75, 0.21), 0, "M_Brocal")],
    }


def importar_gltf(ruta, nombre, coleccion, altura=None):
    """Importa un modelo glTF de Poly Haven en su propia colección (pivote en la base)."""
    col = bpy.data.collections.new(f"Lib_{nombre}")
    coleccion.children.link(col)
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ruta))
    nuevos = [o for o in bpy.data.objects if o not in antes]
    for o in nuevos:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        col.objects.link(o)
    bpy.context.view_layer.update()
    if altura:
        mallas = [o for o in nuevos if o.type == "MESH"]
        from mathutils import Vector
        zs = [(o.matrix_world @ Vector(c)).z for o in mallas for c in o.bound_box]
        alto = max(zs) - min(zs) if zs else 1.0
        raices = [o for o in nuevos if o.parent is None]
        for o in raices:
            o.scale = [s * altura / alto for s in o.scale]
    for o in nuevos:
        if o.type == "MESH" and nombre == "arbol":
            o.display_type = "BOUNDS"  # el viewport de una iGPU no aguanta 470 árboles completos
    return col


def arboles_geometry_nodes(arboles, col_arbol, coleccion, fraccion_viewport=0.04):
    """Todos los árboles en un solo objeto: puntos + Geometry Nodes 'Instance on Points'.
    Es mucho más liviano que miles de objetos; en el viewport solo se muestra una fracción."""
    me = bpy.data.meshes.new("Arboles_Puntos")
    me.vertices.add(len(arboles))
    me.vertices.foreach_set("co", [c for a in arboles for c in (a["x"], a["y"], a["z"])])
    rot = me.attributes.new("rot", "FLOAT_VECTOR", "POINT")
    rot.data.foreach_set("vector", [c for a in arboles for c in (0.0, 0.0, math.radians(a.get("rumbo", 0.0)))])
    esc = me.attributes.new("esc", "FLOAT", "POINT")
    esc.data.foreach_set("value", [a.get("escala") or 1.0 for a in arboles])
    obj = bpy.data.objects.new("Arboles", me)
    coleccion.objects.link(obj)

    ng = bpy.data.node_groups.new("GN_Arboles", "GeometryNodeTree")
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N = ng.nodes
    ent, sal = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    vista = N.new("GeometryNodeIsViewport")
    azar = N.new("FunctionNodeRandomValue")
    azar.data_type = "BOOLEAN"
    azar.inputs["Probability"].default_value = 1.0 - fraccion_viewport
    y_logico = N.new("FunctionNodeBooleanMath")
    y_logico.operation = "AND"
    borrar = N.new("GeometryNodeDeleteGeometry")
    borrar.domain = "POINT"
    info = N.new("GeometryNodeCollectionInfo")
    info.inputs["Collection"].default_value = col_arbol
    info.transform_space = "ORIGINAL"
    instanciar = N.new("GeometryNodeInstanceOnPoints")
    a_rot = N.new("GeometryNodeInputNamedAttribute")
    a_rot.data_type = "FLOAT_VECTOR"
    a_rot.inputs["Name"].default_value = "rot"
    a_esc = N.new("GeometryNodeInputNamedAttribute")
    a_esc.data_type = "FLOAT"
    a_esc.inputs["Name"].default_value = "esc"
    L = ng.links
    L.new(vista.outputs[0], y_logico.inputs[0])
    L.new([s for s in azar.outputs if s.type == "BOOLEAN"][0], y_logico.inputs[1])
    L.new(ent.outputs[0], borrar.inputs["Geometry"])
    L.new(y_logico.outputs[0], borrar.inputs["Selection"])
    L.new(borrar.outputs[0], instanciar.inputs["Points"])
    L.new(info.outputs[0], instanciar.inputs["Instance"])
    L.new(a_rot.outputs["Attribute"], instanciar.inputs["Rotation"])
    L.new(a_esc.outputs["Attribute"], instanciar.inputs["Scale"])
    L.new(instanciar.outputs[0], sal.inputs[0])
    mod = obj.modifiers.new("Arboles", "NODES")
    mod.node_group = ng
    return len(arboles)


def pasto_3d(col_superficies, cols_pavimento, col_grama, cfg, coleccion):
    """Matas de grama 3D (modelos de Poly Haven) sobre las caras con material de pasto/grama, densas cerca de
    la CÁMARA ACTIVA y desvaneciéndose con la distancia. Se descartan las que tienen pavimento o edificios
    encima (rayo hacia arriba). Un solo objeto 'Pasto_3D'; solo en el render (no en el viewport)."""
    densidad = cfg.get("densidad", 30.0)
    r0, r1 = cfg.get("radio_pleno", 25.0), cfg.get("radio_max", 90.0)
    ng = bpy.data.node_groups.new("GN_Pasto3D", "GeometryNodeTree")
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    ent, sal = N.new("NodeGroupInput"), N.new("NodeGroupOutput")

    def geometria_de(col):
        ci = N.new("GeometryNodeCollectionInfo")
        ci.inputs["Collection"].default_value = col
        ci.transform_space = "ORIGINAL"
        real = N.new("GeometryNodeRealizeInstances")
        L.new(ci.outputs[0], real.inputs[0])
        return real.outputs[0]
    superficie = geometria_de(col_superficies)
    obstaculos = N.new("GeometryNodeJoinGeometry")
    for col in cols_pavimento:
        L.new(geometria_de(col), obstaculos.inputs[0])
    seleccion = None
    for nombre in ("M_Pasto", "M_Grama"):
        if nombre not in bpy.data.materials:
            continue
        ms = N.new("GeometryNodeMaterialSelection")
        ms.inputs["Material"].default_value = bpy.data.materials[nombre]
        if seleccion is None:
            seleccion = ms.outputs[0]
        else:
            o = N.new("FunctionNodeBooleanMath")
            o.operation = "OR"
            L.new(seleccion, o.inputs[0])
            L.new(ms.outputs[0], o.inputs[1])
            seleccion = o.outputs[0]
    cam = N.new("GeometryNodeInputActiveCamera")
    info_cam = N.new("GeometryNodeObjectInfo")
    L.new(cam.outputs[0], info_cam.inputs["Object"])
    pos = N.new("GeometryNodeInputPosition")
    dist = N.new("ShaderNodeVectorMath")
    dist.operation = "DISTANCE"
    L.new(pos.outputs[0], dist.inputs[0])
    L.new(info_cam.outputs["Location"], dist.inputs[1])
    rango = N.new("ShaderNodeMapRange")
    rango.inputs["From Min"].default_value = r0
    rango.inputs["From Max"].default_value = r1
    rango.inputs["To Min"].default_value = 1.0
    rango.inputs["To Max"].default_value = 0.0
    rango.clamp = True
    L.new(dist.outputs["Value"], rango.inputs["Value"])
    repartir = N.new("GeometryNodeDistributePointsOnFaces")  # modo aleatorio: 'Density' acepta un campo
    por = N.new("ShaderNodeMath")
    por.operation = "MULTIPLY"
    por.inputs[1].default_value = densidad
    L.new(rango.outputs["Result"], por.inputs[0])
    L.new(superficie, repartir.inputs["Mesh"])
    if seleccion is not None:
        L.new(seleccion, repartir.inputs["Selection"])
    L.new(por.outputs[0], repartir.inputs["Density"])
    # rayo hacia arriba: si hay pista, calle, plataforma o edificio encima, no hay grama
    rayo = N.new("GeometryNodeRaycast")
    L.new(obstaculos.outputs[0], rayo.inputs["Target Geometry"])
    origen = N.new("ShaderNodeVectorMath")  # 1 cm arriba: el rayo no choca con su propia superficie
    origen.operation = "ADD"
    origen.inputs[1].default_value = (0, 0, 0.01)
    L.new(N.new("GeometryNodeInputPosition").outputs[0], origen.inputs[0])
    L.new(origen.outputs[0], rayo.inputs["Source Position"])
    rayo.inputs["Ray Direction"].default_value = (0, 0, 1)
    rayo.inputs["Ray Length"].default_value = 3.0
    borrar = N.new("GeometryNodeDeleteGeometry")
    borrar.domain = "POINT"
    L.new(repartir.outputs["Points"], borrar.inputs["Geometry"])
    L.new(rayo.outputs["Is Hit"], borrar.inputs["Selection"])
    info = N.new("GeometryNodeCollectionInfo")
    info.inputs["Collection"].default_value = col_grama
    info.inputs["Separate Children"].default_value = True
    info.inputs["Reset Children"].default_value = True
    info.transform_space = "ORIGINAL"
    giro = N.new("FunctionNodeRandomValue")
    giro.data_type = "FLOAT_VECTOR"
    giro.inputs[0].default_value = (0, 0, 0)          # Min (vector)
    giro.inputs[1].default_value = (0, 0, 6.2832)     # Max (vector)
    escala = N.new("FunctionNodeRandomValue")
    escala.data_type = "FLOAT"
    escala.inputs[2].default_value = cfg.get("escala_min", 0.6)  # Min (float)
    escala.inputs[3].default_value = cfg.get("escala_max", 1.2)  # Max (float)
    cual = N.new("FunctionNodeRandomValue")
    cual.data_type = "INT"
    cual.inputs[4].default_value = 0     # Min (int)
    cual.inputs[5].default_value = 50    # Max (int); Pick Instance usa el módulo del número de modelos
    inst = N.new("GeometryNodeInstanceOnPoints")
    inst.inputs["Pick Instance"].default_value = True
    L.new(borrar.outputs[0], inst.inputs["Points"])
    L.new(info.outputs[0], inst.inputs["Instance"])
    L.new([s for s in cual.outputs if s.type == "INT"][0], inst.inputs["Instance Index"])
    L.new([s for s in giro.outputs if s.type == "VECTOR"][0], inst.inputs["Rotation"])
    L.new([s for s in escala.outputs if s.type == "VALUE"][0], inst.inputs["Scale"])
    L.new(inst.outputs[0], sal.inputs[0])
    obj = bpy.data.objects.new("Pasto_3D", bpy.data.meshes.new("Pasto_3D"))
    coleccion.objects.link(obj)
    mod = obj.modifiers.new("Pasto3D", "NODES")
    mod.node_group = ng
    mod.show_viewport = False  # la iGPU no aguanta el pasto en el viewport
    return len(col_superficies.objects)


def vehiculos_geometry_nodes(vehiculos, cols_modelo, coleccion, fraccion_viewport=0.1):
    """Todos los vehículos en un objeto: puntos con atributos (modelo, rumbo, color) + Instance on Points
    eligiendo el modelo por índice. cols_modelo = {tipo: [colección, ...]} (varias = variantes al azar).
    El material de pintura de los modelos procedurales lee el color de cada instancia."""
    variantes = [(t, c) for t, cols in cols_modelo.items() for c in cols]
    indices = {t: [i for i, (tt, _) in enumerate(variantes) if tt == t] for t in cols_modelo}
    padre = bpy.data.collections.new("Lib_Vehiculos")
    for _, c in variantes:  # el orden de las hijas define el índice de cada modelo
        padre.children.link(c)
    rnd = random.Random(4)
    me = bpy.data.meshes.new("Vehiculos_Puntos")
    me.vertices.add(len(vehiculos))
    me.vertices.foreach_set("co", [c for v in vehiculos for c in (v["x"], v["y"], v["z"])])
    for nombre, tipo, dominio, datos, campo in (
            ("rot", "FLOAT_VECTOR", "POINT", [c for v in vehiculos for c in (0.0, 0.0, math.radians(v["rumbo"]))], "vector"),
            ("idx", "INT", "POINT", [rnd.choice(indices[v["tipo"]]) for v in vehiculos], "value"),
            ("col_auto", "FLOAT_COLOR", "POINT", [c for v in vehiculos for c in (*v.get("color", (0.5, 0.5, 0.5)), 1.0)], "color")):
        a = me.attributes.new(nombre, tipo, dominio)
        a.data.foreach_set(campo, datos)
    obj = bpy.data.objects.new("Vehiculos", me)
    coleccion.objects.link(obj)

    ng = bpy.data.node_groups.new("GN_Vehiculos", "GeometryNodeTree")
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    ent, sal = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    vista = N.new("GeometryNodeIsViewport")
    azar = N.new("FunctionNodeRandomValue")
    azar.data_type = "BOOLEAN"
    azar.inputs["Probability"].default_value = 1.0 - fraccion_viewport
    y_logico = N.new("FunctionNodeBooleanMath")
    y_logico.operation = "AND"
    borrar = N.new("GeometryNodeDeleteGeometry")
    borrar.domain = "POINT"
    info = N.new("GeometryNodeCollectionInfo")
    info.inputs["Collection"].default_value = padre
    info.inputs["Separate Children"].default_value = True
    info.inputs["Reset Children"].default_value = True
    info.transform_space = "ORIGINAL"
    inst = N.new("GeometryNodeInstanceOnPoints")
    inst.inputs["Pick Instance"].default_value = True
    atributos = {}
    for nombre, tipo in (("rot", "FLOAT_VECTOR"), ("idx", "INT")):
        n = N.new("GeometryNodeInputNamedAttribute")
        n.data_type = tipo
        n.inputs["Name"].default_value = nombre
        atributos[nombre] = n.outputs["Attribute"]
    L.new(vista.outputs[0], y_logico.inputs[0])
    L.new([s for s in azar.outputs if s.type == "BOOLEAN"][0], y_logico.inputs[1])
    L.new(ent.outputs[0], borrar.inputs["Geometry"])
    L.new(y_logico.outputs[0], borrar.inputs["Selection"])
    L.new(borrar.outputs[0], inst.inputs["Points"])
    L.new(info.outputs[0], inst.inputs["Instance"])
    L.new(atributos["idx"], inst.inputs["Instance Index"])
    L.new(atributos["rot"], inst.inputs["Rotation"])
    L.new(inst.outputs[0], sal.inputs[0])
    obj.modifiers.new("Vehiculos", "NODES").node_group = ng
    return len(vehiculos)


def crear_ciudad_lejana(carpeta, coleccion, rnd):
    """Edificios simples (paredes con ventanas pintadas por el material + techo) alrededor de la zona."""
    ruta = carpeta / "terreno" / "ciudad_lejana.json"
    if not ruta.exists():
        return 0
    with open(ruta, encoding="utf-8") as f:
        edificios = json.load(f)
    m = construir.Malla()
    fachadas = [("M_Fachada_Friso", 0.4), ("M_Fachada_Beige", 0.2), ("M_Fachada_Ladrillo", 0.15),
                ("M_Fachada_Ceramica", 0.1), ("M_Fachada_Concreto", 0.15)]
    Pared = construir.detalle.Pared
    for x, y, z, h, anillo in edificios:
        if len(anillo) < 3:
            continue
        base, tope = z - 1.0, z + h
        mat = "M_Fachada_Concreto" if h > 35 and rnd.random() < 0.5 else construir.elegir(fachadas, rnd)
        color = (rnd.random(), 0.2 if h > 35 else 0.1, min(h / 150.0, 1.0), 0.0)  # A = 0: ventanas pintadas
        u = 0.0
        for a, b in zip(anillo, anillo[1:] + anillo[:1]):
            L = math.dist(a, b)
            if L < 0.3:
                continue
            Pared(a, b).quad(m, 0, L, base, tope, 0, mat, u, base, color)
            u += L
        planos, tris = construir.triangular(anillo)
        techo = "M_Techo" if rnd.random() < 0.5 else "M_Techo_Concreto"
        for i, j, k in tris:
            pts = [planos[i], planos[j], planos[k]]
            m.cara([(px, py, tope) for px, py in pts], [(px, py) for px, py in pts], techo, color=color)
    if not m.vacia():
        m.crear_objeto("Ciudad_Lejana", coleccion)
    return len(edificios)


def colocar_instancias(props, bibliotecas, coleccion):
    conteo = {}
    rnd = random.Random(6)
    for i, p in enumerate(props):
        col = bibliotecas.get(p["tipo"])
        if col is None or p["tipo"] == "arbol":  # los árboles van con Geometry Nodes
            continue
        if isinstance(col, list):  # varias variantes (modelos del usuario): una al azar
            col = rnd.choice(col)
        e = bpy.data.objects.new(f"{p['tipo']}_{i}", None)
        e.instance_type = "COLLECTION"
        e.instance_collection = col
        e.location = (p["x"], p["y"], p["z"])
        e.rotation_euler = (0, 0, math.radians(p.get("rumbo", 0.0)))
        s = p.get("escala") or 1.0
        e.scale = (s, s, s)
        e.empty_display_size = 0.5
        coleccion.objects.link(e)
        conteo[p["tipo"]] = conteo.get(p["tipo"], 0) + 1
    return conteo


def props_extra(props, osm, terreno, zona_detalle, rnd):
    """Papeleras, hidrantes y tapas de alcantarilla en la zona de detalle."""
    cx, cy = zona_detalle["centro"]
    radio = zona_detalle["radio_m"]
    extra = []
    for p in props:
        if p["tipo"] != "farola" or math.hypot(p["x"] - cx, p["y"] - cy) > radio:
            continue
        ang = math.radians(p["rumbo"] + 90)  # a lo largo de la acera
        if rnd.random() < 0.4:
            x, y = p["x"] + math.cos(ang) * 1.4, p["y"] + math.sin(ang) * 1.4
            extra.append({"tipo": "papelera", "x": x, "y": y, "z": p["z"], "rumbo": rnd.uniform(0, 360)})
        elif rnd.random() < 0.12:
            x, y = p["x"] - math.cos(ang) * 1.8, p["y"] - math.sin(ang) * 1.8
            extra.append({"tipo": "hidrante", "x": x, "y": y, "z": p["z"], "rumbo": rnd.uniform(0, 360)})
    for v in osm["vias"]:
        if v["tipo"] in construir.TIPOS_SENDERO or v["tunel"] or v["puente"]:
            continue
        pts = construir.densificar(v["puntos"], 2.0)
        s = construir.longitudes(pts)
        t = rnd.uniform(5, 30)
        for i in range(len(pts) - 1):
            while t <= s[i + 1]:
                f = (t - s[i]) / ((s[i + 1] - s[i]) or 1)
                x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f
                y = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f
                if math.hypot(x - cx, y - cy) < radio:
                    off = construir.Z_CALLE.get(v["tipo"].replace("_link", ""), construir.Z_CALLE_DEFECTO)
                    extra.append({"tipo": "tapa", "x": x, "y": y, "z": terreno.z(x, y) + off + 0.005,
                                  "rumbo": rnd.uniform(0, 360)})
                t += rnd.uniform(25, 45)
    return extra


# ======================================================================= sol y cielo

def posicion_solar(lat, lon, dia, hora_local, tz):
    """Elevación y azimut (grados, azimut desde el Norte en sentido horario). Algoritmo NOAA."""
    n = dia.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1 + (hora_local - 12) / 24)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    t_solar = hora_local * 60 + eqt + 4 * lon - 60 * tz
    ha = math.radians(t_solar / 4 - 180)
    phi = math.radians(lat)
    cos_z = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(ha)
    zen = math.acos(max(-1, min(1, cos_z)))
    az = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(phi) - math.tan(decl) * math.cos(phi))) + 180
    return 90 - math.degrees(zen), az % 360


def configurar_cielo(escena, zona, dia, hora, terreno_meta):
    lat, lon = zona["centro"]["lat"], zona["centro"]["lon"]
    h, mnt = (int(x) for x in hora.split(":"))
    elev, az = posicion_solar(lat, lon, dia, h + mnt / 60, TZ_CARACAS)
    print(f"  Sol {dia} {hora}: elevación {elev:.1f}°, azimut {az:.1f}°")
    mundo = escena.world or bpy.data.worlds.new("Cielo")
    escena.world = mundo
    g = Nodos(mundo)
    cielo = g.nuevo("ShaderNodeTexSky", sky_type="NISHITA")
    cielo.sun_elevation = math.radians(max(elev, -5))
    # Rotación de Nishita = azimut (desde el Norte = +Y local, sentido horario). Verificado con las sombras:
    # a las 8:40 las caras al Este quedan iluminadas.
    cielo.sun_rotation = math.radians(az) % (2 * math.pi)
    cielo.altitude = terreno_meta["z_origen_msnm"]
    cielo.air_density = 1.0
    cielo.dust_density = 2.5  # bruma típica del valle
    cielo.ozone_density = 1.0
    cielo.sun_disc = True
    fondo = g.nuevo("ShaderNodeBackground")
    fondo.inputs["Strength"].default_value = 0.22
    salida = g.nuevo("ShaderNodeOutputWorld")
    g.unir(cielo.outputs["Color"], fondo.inputs["Color"])
    g.unir(fondo.outputs["Background"], salida.inputs["Surface"])
    mundo.mist_settings.start = 80
    mundo.mist_settings.depth = 9000
    mundo.mist_settings.falloff = "LINEAR"
    return elev, az


def configurar_bruma(escena, intensidad=0.32):
    """Perspectiva aérea: mezcla cada píxel con el color del cielo según la distancia."""
    capa = escena.view_layers[0]
    capa.use_pass_mist = True
    capa.use_pass_environment = True
    escena.render.film_transparent = True
    escena.use_nodes = True
    nt = escena.node_tree
    nt.nodes.clear()
    rl = nt.nodes.new("CompositorNodeRLayers")
    env = next(s for s in rl.outputs if s.name in ("Env", "Environment"))
    mul = nt.nodes.new("CompositorNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = intensidad
    nt.links.new(rl.outputs["Mist"], mul.inputs[0])
    bruma = nt.nodes.new("CompositorNodeMixRGB")
    nt.links.new(mul.outputs[0], bruma.inputs[0])
    nt.links.new(rl.outputs["Image"], bruma.inputs[1])
    nt.links.new(env, bruma.inputs[2])
    sobre = nt.nodes.new("CompositorNodeAlphaOver")
    nt.links.new(env, sobre.inputs[1])
    nt.links.new(bruma.outputs[0], sobre.inputs[2])
    sobre.use_premultiply = False
    sal = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(sobre.outputs[0], sal.inputs["Image"])


def configurar_render(escena, muestras, porcentaje):
    escena.render.engine = "CYCLES"
    c = escena.cycles
    c.device = "CPU"  # la Radeon Vega integrada no es compatible con Cycles (HIP)
    c.samples = muestras
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.03
    c.use_denoising = True
    c.denoiser = "OPENIMAGEDENOISE"
    c.max_bounces = 6
    c.diffuse_bounces = 3
    c.glossy_bounces = 3
    c.transparent_max_bounces = 12
    c.caustics_reflective = False
    c.caustics_refractive = False
    escena.render.resolution_x, escena.render.resolution_y = 1920, 1080
    escena.render.resolution_percentage = porcentaje
    escena.render.use_persistent_data = True
    # Los modelos descargados traen texturas de 4K–8K: se limitan a 2K en el render para caber en 8 GB
    escena.render.use_simplify = True
    escena.cycles.texture_limit_render = "2048"
    escena.cycles.texture_limit = "1024"
    escena.view_settings.view_transform = "AgX"
    try:
        escena.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    escena.view_settings.exposure = -0.8
    escena.render.image_settings.file_format = "JPEG"
    escena.render.image_settings.quality = 92


def camara(nombre, pos, mira, lente, coleccion):
    from mathutils import Vector
    cam = bpy.data.cameras.new(nombre)
    cam.lens = lente
    cam.clip_start = 0.1
    cam.clip_end = 40000
    obj = bpy.data.objects.new(nombre, cam)
    coleccion.objects.link(obj)
    obj.location = pos
    obj.rotation_euler = (Vector(mira) - Vector(pos)).to_track_quat("-Z", "Y").to_euler()
    return obj


# ======================================================================= principal

def argumento(argv, nombre, defecto):
    return argv[argv.index(nombre) + 1] if nombre in argv else defecto


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("Uso: blender -b -P 03b_realismo.py -- <zona> [--render]")
    zona = cargar_zona(argv[0])
    carpeta = carpeta_zona(zona)
    cfg_render = zona.get("render", {})
    dia = date.fromisoformat(argumento(argv, "--fecha", cfg_render.get("fecha", "2026-03-15")))
    hora = argumento(argv, "--hora", cfg_render.get("hora", "08:40"))
    muestras = int(argumento(argv, "--muestras", cfg_render.get("muestras", 96)))
    porcentaje = int(argumento(argv, "--porcentaje", cfg_render.get("porcentaje", 70)))

    with open(RAIZ / "scripts" / "config" / "recursos.json", encoding="utf-8") as f:
        carpeta_recursos = Path(json.load(f)["carpeta"])
    with open(carpeta_recursos / "manifiesto.json", encoding="utf-8") as f:
        manifiesto = json.load(f)

    bpy.ops.wm.open_mainfile(filepath=str(carpeta / f"{zona['id']}.blend"))
    escena = bpy.context.scene
    print(f"Realismo para '{zona['nombre']}'")

    crear_materiales(Texturas(manifiesto), carpeta, zona)
    print(f"  Materiales: {len(bpy.data.materials)}")

    raiz = bpy.data.collections.new("Realismo")
    escena.collection.children.link(raiz)
    fondo_col = bpy.data.collections.new("Fondo")
    raiz.children.link(fondo_col)
    crear_fondo(carpeta, fondo_col, zona)
    n_lejana = crear_ciudad_lejana(carpeta, fondo_col, random.Random(13))
    if n_lejana:
        print(f"  Ciudad lejana: {n_lejana} edificios")

    # Biblioteca de modelos (excluida de la vista; se usa por instancias)
    lib = bpy.data.collections.new("Biblioteca")
    escena.collection.children.link(lib)
    bibliotecas = {}
    for nombre, partes in biblioteca_procedural().items():
        col = bpy.data.collections.new(f"Lib_{nombre}")
        lib.children.link(col)
        col.objects.link(malla_de_partes(f"Modelo_{nombre}", partes))
        bibliotecas[nombre] = col
    modelos = manifiesto["modelos"]
    for clave, mid, altura in (("arbol", "jacaranda_tree", 9.5), ("papelera", "metal_trash_can", None),
                               ("hidrante", "fire_hydrant", None), ("tapa", "water_manhole_cover", None)):
        if mid in modelos:
            bibliotecas[clave] = importar_gltf(modelos[mid], clave, lib, altura)
    col_grama = None
    for mid in ("grass_bermuda_01", "grass_medium_02"):
        if mid in modelos:
            col = importar_gltf(modelos[mid], mid, lib)
            if col_grama is None:
                col_grama = bpy.data.collections.new("Lib_Grama")
                lib.children.link(col_grama)
            for o in list(col.objects):  # todas las matas en una sola colección
                col.objects.unlink(o)
                col_grama.objects.link(o)
    import modelos_usuario  # carpeta C:/UE/Recursos/modelos_usuario/<tipo>/ (ver docs)
    usuario = modelos_usuario.cargar(carpeta_recursos, lib)
    for tipo in ("helicoptero", "avion_turbohelice", "avion_jet"):
        if tipo in usuario:
            bibliotecas[tipo] = usuario[tipo]
    capa_lib = [c for c in bpy.context.view_layer.layer_collection.children if c.collection == lib][0]
    capa_lib.exclude = True

    with open(carpeta / "export" / "props.json", encoding="utf-8") as f:
        props = json.load(f)
    with open(carpeta / "osm_local.json", encoding="utf-8") as f:
        osm = json.load(f)
    terreno = construir.Terreno(carpeta)
    zona_detalle = zona.get("detalle", {"centro": [0, 0], "radio_m": 0})
    props += props_extra(props, osm, terreno, zona_detalle, random.Random(5))
    ruta_arboles = carpeta / "terreno" / "arboles_satelite.json"
    if ruta_arboles.exists():  # paso 02b: árboles donde el satélite ve vegetación
        with open(ruta_arboles, encoding="utf-8") as f:
            props += json.load(f)
    props_col = bpy.data.collections.new("Mobiliario")
    raiz.children.link(props_col)
    print(f"  Instancias: {colocar_instancias(props, bibliotecas, props_col)}")
    arboles = [p for p in props if p["tipo"] == "arbol"]
    if arboles and "arbol" in bibliotecas:
        print(f"  Árboles (Geometry Nodes): {arboles_geometry_nodes(arboles, bibliotecas['arbol'], props_col)}")
    modelos_auto = vehiculos_procedurales()
    cols_auto = {}
    for nombre, partes in modelos_auto.items():
        if nombre in usuario:  # modelos realistas descargados por el usuario
            cols_auto[nombre] = usuario[nombre]
            continue
        col = bpy.data.collections.new(f"Lib_{nombre}")
        col.objects.link(malla_de_partes(f"Modelo_{nombre}", partes))
        cols_auto[nombre] = [col]
    vehiculos = [p for p in props if p["tipo"] in modelos_auto]
    if vehiculos:
        fraccion = 0.01 if any(t in usuario for t in modelos_auto) else 0.1
        n = vehiculos_geometry_nodes(vehiculos, cols_auto, props_col, fraccion)
        lib.children.link(bpy.data.collections["Lib_Vehiculos"])
        print(f"  Vehículos (Geometry Nodes): {n}")

    if col_grama is not None and zona.get("pasto_3d", {}).get("activo", True) and "Areas" in bpy.data.collections:
        obstaculos = [bpy.data.collections[n] for n in ("Aviacion", "Calles", "Senderos", "Aceras", "Areas", "Detalles")
                      if n in bpy.data.collections]
        n = pasto_3d(bpy.data.collections["Areas"], obstaculos, col_grama, zona.get("pasto_3d", {}), props_col)
        print(f"  Pasto 3D: sobre {n} superficies (solo en el render, cerca de la cámara)")

    # Terreno de vista previa visible con su material (suelo entre edificios)
    for o in bpy.data.objects:
        if o.name.startswith("Terreno_"):
            o.hide_render = False

    elev, az = configurar_cielo(escena, zona, dia, hora, terreno.meta)
    configurar_render(escena, muestras, porcentaje)
    escena.view_settings.exposure = float(cfg_render.get("exposicion", -0.8))  # mediodía: más luz, menos exposición
    configurar_bruma(escena)

    # Cámaras de referencia
    cams = bpy.data.collections.new("Camaras")
    raiz.children.link(cams)
    z = terreno.z
    dg = bpy.context.evaluated_depsgraph_get()

    def ojo(x, y, alto=1.65, en_azotea=False):
        """Altura de los ojos de un peatón sobre la superficie real (acera, plaza, calle) o, con en_azotea,
        sobre el techo del edificio que haya en ese punto."""
        from mathutils import Vector
        hit, loc, _, _, obj, _ = escena.ray_cast(dg, Vector((x, y, 3000.0)), Vector((0, 0, -1)))
        while hit and obj.name.startswith(("Edificios", "Fondo") if not en_azotea else ("Fondo",)):  # no pararse en techos
            hit, loc, _, _, obj, _ = escena.ray_cast(dg, loc - Vector((0, 0, 0.05)), Vector((0, 0, -1)))
        return (x, y, (loc.z if hit else z(x, y)) + alto)

    # Cámaras de zonas.json: alturas relativas al terreno del origen, o "ojo": altura sobre el piso real
    config_cams = zona.get("camaras") or {"Cam_General": {"pos": [0, -800, 250], "mira": [0, 0, 0], "lente": 24}}
    objetos_cam = {}
    for nombre, c in config_cams.items():
        x, y, h = c["pos"]
        pos = ojo(x, y, h, c.get("azotea", False)) if c.get("ojo") or c.get("azotea") else (x, y, z(0, 0) + h)
        mx, my, mh = c["mira"]
        mz = z(mx, my) + mh if c.get("mira_suelo") else z(0, 0) + mh  # "mira_suelo": altura sobre el terreno de ese punto
        objetos_cam[nombre] = camara(nombre, pos, (mx, my, mz), c.get("lente", 24), cams)
    primera = next(iter(objetos_cam))
    escena.camera = objetos_cam.get(argumento(argv, "--camara", primera), objetos_cam[primera])

    ruta = carpeta / f"{zona['id']}_realista.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(ruta), compress=True)
    print(f"  Escena guardada: {ruta}")

    if "--render" in argv:
        salida = carpeta / "renders"
        salida.mkdir(exist_ok=True)
        marca = datetime.now().strftime("%Y%m%d_%H%M")
        escena.render.filepath = str(salida / f"{escena.camera.name}_{hora.replace(':', '')}_{marca}.jpg")
        print(f"  Renderizando {escena.camera.name} ({muestras} muestras, {porcentaje}%)...")
        bpy.ops.render.render(write_still=True)
        print(f"  Render: {escena.render.filepath}")
    print("Listo.")


if __name__ == "__main__":
    main()
