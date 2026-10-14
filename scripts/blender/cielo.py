"""Cielo, sol y nubes de la escena realista (lo usan 03b_realismo.py y render_camaras.py).

El cielo es físico (Nishita) con el sol en su posición real para la fecha y hora en Caracas, más una capa
de nubes procedural en el shader del mundo (no cuesta memoria ni geometría): cúmulos dispersos que se
espesan sobre El Ávila (al norte) y hacia el horizonte, como en el valle de Caracas.

Las "luces" (variantes de iluminación) se definen en zonas.json → "luces":
    "tarde": {"hora": "17:20", "nubes": 0.45, "exposicion": -0.2, "bruma": 0.4}
y se aplican sin reconstruir la escena:  render_camaras.py -- --luz tarde
"""

import math
from datetime import date

import bpy

TZ_CARACAS = -4.0

# Variantes por defecto (se pueden sobrescribir en zonas.json → "luces")
LUCES = {
    "mediodia": {"hora": "11:30", "nubes": 0.35, "exposicion": -1.3, "bruma": 0.32},
    "manana": {"hora": "08:30", "nubes": 0.3, "exposicion": -0.7, "bruma": 0.38},
    "tarde": {"hora": "17:55", "nubes": 0.45, "exposicion": 0.2, "bruma": 0.42},
    "nublado": {"hora": "13:00", "nubes": 0.85, "exposicion": -0.2, "bruma": 0.5, "sol": 0.12},
}


def posicion_solar(lat, lon, dia, hora_local, tz=TZ_CARACAS):
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


def variante(zona, nombre=None):
    """Mezcla la variante por defecto con la de zonas.json. Sin nombre: la luz base de "render"."""
    render = zona.get("render", {})
    luces = {**LUCES, **zona.get("luces", {})}
    if nombre in (None, "base"):
        base = {"hora": "09:30", "nubes": 0.35, "exposicion": -0.8, "bruma": 0.32}
        base.update({k: render[k] for k in ("hora", "exposicion") if k in render})
        base.update({k: v for k, v in render.items() if k in ("nubes", "bruma", "sol")})
        return "base", base
    if nombre not in luces:
        raise SystemExit(f"Luz '{nombre}' no definida. Opciones: {', '.join(luces)}")
    return nombre, {**LUCES.get(nombre, {}), **luces[nombre]}


def _n(nt, tipo, **props):
    n = nt.nodes.new(tipo)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def _math(nt, op, a, b=None, clamp=False):
    n = _n(nt, "ShaderNodeMath", operation=op, use_clamp=clamp)
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if hasattr(v, "is_output"):
            nt.links.new(v, n.inputs[i])
        else:
            n.inputs[i].default_value = v
    return n.outputs[0]


def capa_nubes(nt, cobertura, elev_sol, semilla=3.0):
    """Devuelve (máscara 0..1, color) de las nubes según la dirección de la vista.
    Proyecta la dirección sobre un plano de nubes (dir.xy / dir.z) y usa ruido fBm; la cobertura sube
    hacia el norte cerca del horizonte (nubes que se arman sobre El Ávila)."""
    coord = _n(nt, "ShaderNodeTexCoord")
    sep = _n(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(coord.outputs["Generated"], sep.inputs[0])
    dx, dy, dz = sep.outputs
    dz_seguro = _math(nt, "MAXIMUM", dz, 0.035)
    u = _math(nt, "DIVIDE", dx, dz_seguro)
    v = _math(nt, "DIVIDE", dy, dz_seguro)
    vec = _n(nt, "ShaderNodeCombineXYZ")
    nt.links.new(_math(nt, "MULTIPLY", u, 0.9), vec.inputs[0])
    nt.links.new(_math(nt, "MULTIPLY", v, 0.9), vec.inputs[1])
    vec.inputs[2].default_value = semilla
    ruido = _n(nt, "ShaderNodeTexNoise", noise_dimensions="3D")
    ruido.inputs["Scale"].default_value = 1.6
    ruido.inputs["Detail"].default_value = 8.0
    ruido.inputs["Roughness"].default_value = 0.62
    ruido.inputs["Distortion"].default_value = 0.25
    nt.links.new(vec.outputs[0], ruido.inputs["Vector"])
    # más nubes hacia el norte y bajas en el horizonte (El Ávila retiene la nubosidad)
    norte = _math(nt, "MULTIPLY", _math(nt, "MAXIMUM", dy, 0.0), _math(nt, "SUBTRACT", 1.0, _math(nt, "MULTIPLY", dz, 3.0), clamp=True))
    # el fBm vale ~0.5 ± 0.12: cobertura 0.3 → cúmulos sueltos, 0.85 → casi cubierto
    umbral = _math(nt, "SUBTRACT", 0.62 - cobertura * 0.28, _math(nt, "MULTIPLY", norte, 0.08))
    dens = _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", ruido.outputs["Fac"], umbral), 9.0, clamp=True)
    # se desvanecen justo en el horizonte (bruma) y no hay nubes bajo él
    horiz = _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", dz, 0.015), 12.0, clamp=True)
    mascara = _math(nt, "MULTIPLY", dens, horiz)
    # sombreado: base gris (vientre de la nube), bordes iluminados; al atardecer, tono cálido
    calido = max(0.0, min(1.0, (20.0 - elev_sol) / 18.0))
    claro = (1.0, 0.97 - 0.12 * calido, 0.93 - 0.3 * calido, 1.0)
    oscuro = (0.55 + 0.15 * calido, 0.57, 0.62 - 0.1 * calido, 1.0)
    mezcla = _n(nt, "ShaderNodeMix", data_type="RGBA")
    nt.links.new(_math(nt, "POWER", ruido.outputs["Fac"], 2.2), mezcla.inputs[0])
    [s for s in mezcla.inputs if s.name == "A" and s.type == "RGBA"][0].default_value = oscuro
    [s for s in mezcla.inputs if s.name == "B" and s.type == "RGBA"][0].default_value = claro
    color = [s for s in mezcla.outputs if s.name == "Result" and s.type == "RGBA"][0]
    return mascara, color


def sombras_de_nubes(escena, cobertura, z_origen, altura=2400.0, lado=40000.0):
    """Plano invisible a 2.400 m sobre el valle (por encima de El Ávila) que solo proyecta sombra (manchas de nubes en el suelo).
    Solo lo ven los rayos de sombra: no tapa el cielo ni el reflejo."""
    obj = bpy.data.objects.get("Sombra_Nubes")
    if cobertura <= 0:
        if obj:
            obj.hide_render = True
        return
    if obj is None:
        me = bpy.data.meshes.new("Sombra_Nubes")
        h = lado / 2
        me.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
        obj = bpy.data.objects.new("Sombra_Nubes", me)
        escena.collection.objects.link(obj)
    obj.hide_render = False
    obj.location = (0, 0, altura)
    obj.visible_camera = False
    obj.visible_diffuse = False
    obj.visible_glossy = False
    obj.visible_transmission = False
    obj.visible_volume_scatter = False
    obj.visible_shadow = True
    mat = bpy.data.materials.get("M_Sombra_Nubes") or bpy.data.materials.new("M_Sombra_Nubes")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    coord = _n(nt, "ShaderNodeTexCoord")
    mapeo = _n(nt, "ShaderNodeMapping")
    mapeo.inputs["Scale"].default_value = (1 / 900.0, 1 / 900.0, 1.0)
    nt.links.new(coord.outputs["Object"], mapeo.inputs["Vector"])
    ruido = _n(nt, "ShaderNodeTexNoise")
    ruido.inputs["Scale"].default_value = 1.0
    ruido.inputs["Detail"].default_value = 6.0
    ruido.inputs["Roughness"].default_value = 0.6
    nt.links.new(mapeo.outputs["Vector"], ruido.inputs["Vector"])
    umbral = 0.62 - cobertura * 0.28
    dens = _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", ruido.outputs["Fac"], umbral), 6.0, clamp=True)
    opaco = _math(nt, "MULTIPLY", dens, 0.8)  # las nubes dejan pasar algo de luz
    mezcla = _n(nt, "ShaderNodeMixShader")
    nt.links.new(opaco, mezcla.inputs[0])
    nt.links.new(_n(nt, "ShaderNodeBsdfTransparent").outputs[0], mezcla.inputs[1])
    nt.links.new(_n(nt, "ShaderNodeBsdfDiffuse").outputs[0], mezcla.inputs[2])
    nt.links.new(mezcla.outputs[0], _n(nt, "ShaderNodeOutputMaterial").inputs["Surface"])
    if not obj.data.materials:
        obj.data.materials.append(mat)


def aplicar(escena, zona, nombre=None, z_origen=None):
    """Configura sol, cielo con nubes, exposición y bruma para una variante de luz. Devuelve la variante."""
    nombre, luz = variante(zona, nombre)
    lat, lon = zona["centro"]["lat"], zona["centro"]["lon"]
    fecha = luz.get("fecha") or zona.get("render", {}).get("fecha", "2026-03-15")
    dia = date.fromisoformat(fecha)
    h, mnt = (int(x) for x in luz["hora"].split(":"))
    elev, az = posicion_solar(lat, lon, dia, h + mnt / 60)
    print(f"  Luz '{nombre}': {fecha} {luz['hora']}, sol a {elev:.1f}° de elevación y {az:.1f}° de azimut, "
          f"nubes {luz.get('nubes', 0):.0%}")
    if z_origen is None:
        z_origen = escena.get("z_origen_msnm", 900.0)
    escena["z_origen_msnm"] = z_origen

    mundo = escena.world or bpy.data.worlds.new("Cielo")
    escena.world = mundo
    mundo.use_nodes = True
    nt = mundo.node_tree
    nt.nodes.clear()
    cielo = _n(nt, "ShaderNodeTexSky", sky_type="NISHITA")
    cielo.sun_elevation = math.radians(max(elev, -5))
    # Rotación de Nishita = azimut (desde el Norte = +Y local, sentido horario). Verificado con las sombras.
    cielo.sun_rotation = math.radians(az) % (2 * math.pi)
    cielo.altitude = z_origen
    cielo.air_density = 1.0
    cielo.dust_density = 2.5 + 2.0 * luz.get("nubes", 0)  # bruma típica del valle, más con nubes
    cielo.ozone_density = 1.0
    cielo.sun_disc = True
    cielo.sun_intensity = luz.get("sol", 1.0)
    color_cielo = cielo.outputs["Color"]
    if luz.get("nubes", 0) > 0:
        mascara, color_nube = capa_nubes(nt, luz["nubes"], elev)
        # las nubes toman la luz del cielo (más oscuras de día nublado, doradas al atardecer)
        brillo = _n(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        brillo.inputs[0].default_value = 1.0
        nt.links.new(color_nube, [s for s in brillo.inputs if s.name == "A" and s.type == "RGBA"][0])
        luz_cielo = _n(nt, "ShaderNodeTexSky", sky_type="NISHITA")
        for k in ("sun_elevation", "sun_rotation", "altitude", "air_density", "dust_density", "ozone_density"):
            setattr(luz_cielo, k, getattr(cielo, k))
        luz_cielo.sun_disc = False
        hsv = _n(nt, "ShaderNodeHueSaturation")
        hsv.inputs["Saturation"].default_value = 0.35
        hsv.inputs["Value"].default_value = 2.6
        nt.links.new(luz_cielo.outputs["Color"], hsv.inputs["Color"])
        nt.links.new(hsv.outputs["Color"], [s for s in brillo.inputs if s.name == "B" and s.type == "RGBA"][0])
        mezcla = _n(nt, "ShaderNodeMix", data_type="RGBA")
        nt.links.new(mascara, mezcla.inputs[0])
        nt.links.new(color_cielo, [s for s in mezcla.inputs if s.name == "A" and s.type == "RGBA"][0])
        nt.links.new([s for s in brillo.outputs if s.name == "Result" and s.type == "RGBA"][0],
                     [s for s in mezcla.inputs if s.name == "B" and s.type == "RGBA"][0])
        color_cielo = [s for s in mezcla.outputs if s.name == "Result" and s.type == "RGBA"][0]
    fondo = _n(nt, "ShaderNodeBackground")
    fondo.inputs["Strength"].default_value = 0.22
    nt.links.new(color_cielo, fondo.inputs["Color"])
    nt.links.new(fondo.outputs["Background"], _n(nt, "ShaderNodeOutputWorld").inputs["Surface"])
    mundo.mist_settings.start = 80
    mundo.mist_settings.depth = 9000
    mundo.mist_settings.falloff = "LINEAR"

    sombras_de_nubes(escena, luz.get("nubes", 0), z_origen)

    escena.view_settings.exposure = float(luz.get("exposicion", -0.8))
    if escena.node_tree:  # intensidad de la bruma del compositor (configurar_bruma en 03b)
        for n in escena.node_tree.nodes:
            if n.bl_idname == "CompositorNodeMath":
                n.inputs[1].default_value = float(luz.get("bruma", 0.32))
    escena["luz"] = nombre
    return nombre, luz, elev, az
