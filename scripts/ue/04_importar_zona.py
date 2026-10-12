"""Paso 04 (dentro de Unreal Engine): importa la maqueta de una zona al nivel abierto.

Uso, desde la consola de Unreal (tecla ` ) o Tools > Execute Python Script:
    py "C:/Users/Dixon/OneDrive/Documentos/Escenarios 3D/scripts/ue/04_importar_zona.py" altamira
Opciones:
    --sin-props      no coloca árboles/farolas/tanques provisionales
    --solo-props     no reimporta las mallas, solo vuelve a colocar los props

Requisitos: plugin "Python Editor Script Plugin" activo (viene con UE5) y haber corrido el paso 03.
Se puede volver a ejecutar: borra y recrea solo lo que está en la carpeta del Outliner "Caracas/<zona>".

Qué hace:
  1. Importa las celdas FBX en /Game/Venezuela/<Zona>/Mallas (colisión = malla compleja).
  2. Crea un material maestro simple y una instancia por material (colores base realistas).
  3. Coloca las celdas en (0,0,0), los props provisionales y un PlayerStart en la plaza.
  4. Si Cesium for Unreal está instalado, ajusta el CesiumGeoreference al origen de la zona.
  5. Imprime los valores para importar el Landscape (heightmap) a mano.
"""

import json
import math
import sys
from pathlib import Path

import unreal

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
from comun import cargar_zona  # noqa: E402

herramientas = unreal.AssetToolsHelpers.get_asset_tools()
actores = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MEL = unreal.MaterialEditingLibrary

# Color base (sRGB lineal aprox.), rugosidad, metálico, variación por edificio
# (Versión base con colores planos; las texturas y fórmulas del paso 03b se portarán a Unreal después.)
MATERIALES = {
    "M_Fachada_Friso": ((0.62, 0.55, 0.43), 0.85, 0.0, 0.30),
    "M_Fachada_Beige": ((0.64, 0.56, 0.42), 0.85, 0.0, 0.25),
    "M_Fachada_Casa": ((0.70, 0.66, 0.58), 0.90, 0.0, 0.30),
    "M_Fachada_Ladrillo": ((0.42, 0.22, 0.15), 0.85, 0.0, 0.15),
    "M_Fachada_Ceramica": ((0.55, 0.53, 0.50), 0.50, 0.0, 0.15),
    "M_Fachada_Concreto": ((0.45, 0.45, 0.43), 0.85, 0.0, 0.15),
    "M_Fachada_Comercial": ((0.55, 0.52, 0.48), 0.80, 0.0, 0.25),
    "M_Muro": ((0.60, 0.56, 0.48), 0.85, 0.0, 0.20),
    "M_Techo": ((0.08, 0.075, 0.07), 0.90, 0.0, 0.20),
    "M_Techo_Concreto": ((0.40, 0.39, 0.37), 0.90, 0.0, 0.20),
    "M_Vidrio": ((0.02, 0.025, 0.03), 0.05, 0.0, 0.0),
    "M_Vidrio_Oficina": ((0.03, 0.06, 0.07), 0.04, 0.3, 0.0),
    "M_Vidrio_Local": ((0.03, 0.03, 0.03), 0.05, 0.0, 0.0),
    "M_Marco": ((0.62, 0.63, 0.65), 0.35, 1.0, 0.0),
    "M_Reja": ((0.03, 0.03, 0.03), 0.55, 0.7, 0.0),
    "M_Cerca": ((0.03, 0.03, 0.03), 0.55, 0.7, 0.0),
    "M_Santamaria": ((0.45, 0.47, 0.49), 0.5, 0.8, 0.0),
    "M_Cebra": ((0.6, 0.6, 0.58), 0.6, 0.0, 0.0),
    "M_Agua": ((0.02, 0.07, 0.07), 0.03, 0.0, 0.0),
    "M_Seto": ((0.03, 0.09, 0.02), 0.9, 0.0, 0.0),
    "M_Pista": ((0.03, 0.03, 0.032), 0.85, 0.0, 0.0),
    "M_Rodaje": ((0.035, 0.035, 0.037), 0.85, 0.0, 0.0),
    "M_Plataforma": ((0.35, 0.35, 0.34), 0.85, 0.0, 0.0),
    "M_Pintura_Blanca": ((0.75, 0.75, 0.72), 0.6, 0.0, 0.0),
    "M_Zinc": ((0.5, 0.52, 0.53), 0.45, 0.8, 0.1),
    # hangares y cerca de La Carlota (paredes de hangar con cara interior; barrotes: usar material Masked de dos caras)
    "M_Hangar_Pared": ((0.72, 0.70, 0.64), 0.6, 0.0, 0.0),
    "M_Muro_Cerca": ((0.45, 0.44, 0.41), 0.9, 0.0, 0.0),
    "M_Barrotes": ((0.02, 0.02, 0.022), 0.5, 0.3, 0.0),
    "M_Metal_Oscuro": ((0.04, 0.045, 0.05), 0.5, 0.6, 0.0),
    # Plaza Francia: obelisco, fuente escalonada y letrero (chorros y cortinas: Translucent en UE)
    "M_Relieve": ((0.55, 0.44, 0.31), 0.85, 0.0, 0.0),
    "M_Placa": ((0.22, 0.14, 0.07), 0.4, 0.85, 0.0),
    "M_Piedra_Fuente": ((0.33, 0.25, 0.18), 0.35, 0.0, 0.0),
    "M_Azulejo": ((0.04, 0.4, 0.42), 0.15, 0.0, 0.0),
    "M_Agua_Fuente": ((0.05, 0.36, 0.4), 0.03, 0.0, 0.0),
    "M_Chorro": ((0.85, 0.92, 0.95), 0.1, 0.0, 0.0),
    "M_Cortina_Agua": ((0.8, 0.88, 0.92), 0.1, 0.0, 0.0),
    "M_Letras": ((0.86, 0.86, 0.84), 0.3, 0.0, 0.0),
    "M_Corazon": ((0.72, 0.02, 0.03), 0.3, 0.0, 0.0),
    # bajada al Metro de Plaza Francia (M_Lamina_Agua: Translucent en UE)
    "M_Muro_Blanco": ((0.78, 0.78, 0.75), 0.85, 0.0, 0.0),
    "M_Pintura_Verde": ((0.03, 0.3, 0.2), 0.35, 0.0, 0.0),
    "M_Azulejo_Claro": ((0.65, 0.76, 0.78), 0.12, 0.0, 0.0),
    "M_Lamina_Agua": ((0.9, 0.95, 0.97), 0.05, 0.0, 0.0),
    "M_Metro_Boca": ((0.012, 0.012, 0.014), 0.8, 0.0, 0.0),
    "M_Tierra_Jardin": ((0.12, 0.09, 0.06), 0.9, 0.0, 0.0),
    # edificios emblemáticos (franjas: en UE conviene un material con máscara por UV como en Blender)
    "M_Franjas_Azul": ((0.3, 0.38, 0.52), 0.25, 0.2, 0.0),
    "M_Franjas_Blanca": ((0.55, 0.56, 0.56), 0.3, 0.15, 0.0),
    "M_Muro_Cortina": ((0.025, 0.035, 0.045), 0.04, 0.5, 0.0),
    "M_Concreto_Claro": ((0.7, 0.69, 0.66), 0.85, 0.0, 0.0),
    "M_Fachada_Gris": ((0.6, 0.61, 0.62), 0.85, 0.0, 0.0),
    "M_Losa_Blanca": ((0.84, 0.84, 0.82), 0.6, 0.0, 0.0),
    "M_Antepecho": ((0.9, 0.9, 0.88), 0.45, 0.0, 0.0),
    "M_Letrero_Rojo": ((0.7, 0.03, 0.03), 0.4, 0.0, 0.0),
    "M_Letrero_Azul": ((0.06, 0.2, 0.52), 0.4, 0.0, 0.0),
    "M_Asfalto": ((0.035, 0.035, 0.037), 0.80, 0.0, 0.0),
    "M_Acera": ((0.33, 0.32, 0.30), 0.90, 0.0, 0.0),
    "M_Brocal": ((0.55, 0.55, 0.52), 0.85, 0.0, 0.0),
    "M_Sendero": ((0.38, 0.35, 0.30), 0.90, 0.0, 0.0),
    "M_Escalera": ((0.40, 0.40, 0.40), 0.90, 0.0, 0.0),
    "M_Plaza": ((0.50, 0.44, 0.36), 0.85, 0.0, 0.0),
    "M_Grama": ((0.07, 0.16, 0.03), 0.95, 0.0, 0.0),
    "M_Cancha": ((0.08, 0.22, 0.12), 0.85, 0.0, 0.0),
    "M_Terreno": ((0.18, 0.15, 0.10), 0.95, 0.0, 0.0),
    "M_Monumento": ((0.66, 0.55, 0.40), 0.75, 0.0, 0.0),
}

# tipo -> (malla provisional, escala XYZ en metros, altura del centro sobre el suelo en metros)
PROPS = {
    "arbol": ("/Engine/BasicShapes/Sphere.Sphere", (5.0, 5.0, 4.0), 5.0),
    "farola": ("/Engine/BasicShapes/Cylinder.Cylinder", (0.18, 0.18, 9.0), 4.5),
    "semaforo": ("/Engine/BasicShapes/Cylinder.Cylinder", (0.2, 0.2, 4.5), 2.25),
    "parada": ("/Engine/BasicShapes/Cube.Cube", (3.0, 1.5, 2.6), 1.3),
    "tanque": ("/Engine/BasicShapes/Cylinder.Cylinder", (2.2, 2.2, 1.6), 0.8),
    "obelisco": ("/Engine/BasicShapes/Cube.Cube", (2.5, 2.5, 40.0), 20.0),
    "metro": ("/Engine/BasicShapes/Cube.Cube", (3.0, 6.0, 1.0), 0.5),
    "banco": ("/Engine/BasicShapes/Cube.Cube", (1.8, 0.5, 0.45), 0.225),
    "torre": ("/Engine/BasicShapes/Cylinder.Cylinder", (1.0, 1.0, 20.0), 10.0),
    "aire": ("/Engine/BasicShapes/Cube.Cube", (0.45, 0.72, 0.5), 0.25),
    "casilla": ("/Engine/BasicShapes/Cube.Cube", (3.2, 4.0, 2.8), 1.4),
    "manga": ("/Engine/BasicShapes/Cylinder.Cylinder", (0.12, 0.12, 6.0), 3.0),
    # aeronaves: cajas del tamaño real (largo × envergadura × alto) hasta portar los modelos de Blender
    "avion_turbohelice": ("/Engine/BasicShapes/Cube.Cube", (14.2, 17.6, 4.4), 2.2),
    "avion_jet": ("/Engine/BasicShapes/Cube.Cube", (15.0, 15.5, 4.6), 2.3),
    "helicoptero": ("/Engine/BasicShapes/Cube.Cube", (12.7, 14.0, 3.8), 1.9),
    "sedan": ("/Engine/BasicShapes/Cube.Cube", (4.5, 1.76, 1.45), 0.72),
    "hatchback": ("/Engine/BasicShapes/Cube.Cube", (3.9, 1.7, 1.5), 0.75),
    "camioneta": ("/Engine/BasicShapes/Cube.Cube", (4.75, 1.9, 1.8), 0.9),
    "pickup": ("/Engine/BasicShapes/Cube.Cube", (5.3, 1.86, 1.8), 0.9),
    "por_puesto": ("/Engine/BasicShapes/Cube.Cube", (6.6, 2.1, 2.4), 1.2),
    "moto": ("/Engine/BasicShapes/Cube.Cube", (2.0, 0.6, 1.1), 0.55),
}


def a_ue(x, y, z):
    """Local (m, X=Este, Y=Norte) -> Unreal (cm, X=Este, Y=Sur)."""
    return unreal.Vector(x * 100.0, -y * 100.0, z * 100.0)


# ---------------------------------------------------------------- materiales

def material_maestro(carpeta):
    ruta = f"{carpeta}/M_Maestro_Base"
    if unreal.EditorAssetLibrary.does_asset_exist(ruta):
        return unreal.load_asset(ruta)
    mat = herramientas.create_asset("M_Maestro_Base", carpeta, unreal.Material, unreal.MaterialFactoryNew())

    def parametro(clase, nombre, valor, x, y):
        e = MEL.create_material_expression(mat, clase, x, y)
        e.set_editor_property("parameter_name", nombre)
        e.set_editor_property("default_value", valor)
        return e

    color = parametro(unreal.MaterialExpressionVectorParameter, "Color", unreal.LinearColor(0.5, 0.5, 0.5, 1), -900, -200)
    variacion = parametro(unreal.MaterialExpressionScalarParameter, "Variacion", 0.2, -900, 0)
    rugosidad = parametro(unreal.MaterialExpressionScalarParameter, "Rugosidad", 0.85, -400, 200)
    metalico = parametro(unreal.MaterialExpressionScalarParameter, "Metalico", 0.0, -400, 300)
    vc = MEL.create_material_expression(mat, unreal.MaterialExpressionVertexColor, -900, 150)

    # factor = lerp(1 - Variacion, 1 + Variacion, VertexColor.R)  -> cada edificio con un tono distinto
    menos = MEL.create_material_expression(mat, unreal.MaterialExpressionSubtract, -650, -50)
    menos.set_editor_property("const_a", 1.0)
    MEL.connect_material_expressions(variacion, "", menos, "B")
    mas = MEL.create_material_expression(mat, unreal.MaterialExpressionAdd, -650, 50)
    mas.set_editor_property("const_a", 1.0)
    MEL.connect_material_expressions(variacion, "", mas, "B")
    lerp = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -450, 0)
    MEL.connect_material_expressions(menos, "", lerp, "A")
    MEL.connect_material_expressions(mas, "", lerp, "B")
    MEL.connect_material_expressions(vc, "R", lerp, "Alpha")
    mult = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -250, -100)
    MEL.connect_material_expressions(color, "", mult, "A")
    MEL.connect_material_expressions(lerp, "", mult, "B")

    MEL.connect_material_property(mult, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(rugosidad, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(metalico, "", unreal.MaterialProperty.MP_METALLIC)
    MEL.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat


def instancias_materiales(carpeta, maestro):
    instancias = {}
    for nombre, (rgb, rug, met, var) in MATERIALES.items():
        nombre_mi = "MI_" + nombre[2:]
        ruta = f"{carpeta}/{nombre_mi}"
        if unreal.EditorAssetLibrary.does_asset_exist(ruta):
            mi = unreal.load_asset(ruta)
        else:
            mi = herramientas.create_asset(nombre_mi, carpeta, unreal.MaterialInstanceConstant,
                                           unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, maestro)
        MEL.set_material_instance_vector_parameter_value(mi, "Color", unreal.LinearColor(*rgb, 1.0))
        MEL.set_material_instance_scalar_parameter_value(mi, "Rugosidad", rug)
        MEL.set_material_instance_scalar_parameter_value(mi, "Metalico", met)
        MEL.set_material_instance_scalar_parameter_value(mi, "Variacion", var)
        unreal.EditorAssetLibrary.save_loaded_asset(mi)
        instancias[nombre] = mi
    return instancias


# ---------------------------------------------------------------- importación

def importar_fbx(ruta, destino):
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_as_skeletal", False)
    ui.set_editor_property("import_materials", True)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("import_animations", False)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
    datos = ui.get_editor_property("static_mesh_import_data")
    datos.set_editor_property("combine_meshes", False)
    datos.set_editor_property("auto_generate_collision", False)
    datos.set_editor_property("generate_lightmap_u_vs", True)
    datos.set_editor_property("remove_degenerates", True)
    datos.set_editor_property("import_uniform_scale", 1.0)
    datos.set_editor_property("vertex_color_import_option", unreal.VertexColorImportOption.REPLACE)

    tarea = unreal.AssetImportTask()
    tarea.set_editor_property("filename", str(ruta))
    tarea.set_editor_property("destination_path", destino)
    tarea.set_editor_property("automated", True)
    tarea.set_editor_property("replace_existing", True)
    tarea.set_editor_property("save", True)
    tarea.set_editor_property("options", ui)
    herramientas.import_asset_tasks([tarea])
    return [unreal.load_asset(p) for p in tarea.get_editor_property("imported_object_paths")]


def preparar_malla(malla, instancias):
    for i, sm in enumerate(malla.get_editor_property("static_materials")):
        nombre = str(sm.get_editor_property("material_slot_name"))
        if nombre not in instancias and sm.get_editor_property("material_interface"):
            nombre = sm.get_editor_property("material_interface").get_name()
        if nombre in instancias:
            malla.set_material(i, instancias[nombre])
    cuerpo = malla.get_editor_property("body_setup")
    if cuerpo:
        cuerpo.set_editor_property("collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    unreal.EditorAssetLibrary.save_loaded_asset(malla)


# ---------------------------------------------------------------- nivel

def borrar_carpeta(carpeta):
    borrados = 0
    for a in actores.get_all_level_actors():
        if str(a.get_folder_path()).startswith(carpeta):
            actores.destroy_actor(a)
            borrados += 1
    return borrados


def colocar(objeto_o_clase, pos, rot, carpeta, etiqueta):
    if isinstance(objeto_o_clase, type):
        a = actores.spawn_actor_from_class(objeto_o_clase, pos, rot)
    else:
        a = actores.spawn_actor_from_object(objeto_o_clase, pos, rot)
    a.set_folder_path(carpeta)
    a.set_actor_label(etiqueta)
    return a


def transformacion_prop(p):
    _, (sx, sy, sz), centro = PROPS[p["tipo"]]
    esc = p.get("escala") or 1.0
    if p["tipo"] == "obelisco" and p.get("altura"):
        sz, centro = p["altura"], p["altura"] / 2.0
    return unreal.Transform(
        a_ue(p["x"], p["y"], p["z"] + centro * esc),
        unreal.Rotator(0.0, 0.0, -p.get("rumbo", 0.0)),  # roll, pitch, yaw (Y invertida -> yaw negado)
        unreal.Vector(sx * esc, sy * esc, sz * esc),
    )


def colocar_props_instanciados(tipo, malla, lista, carpeta):
    """Un actor por tipo con InstancedStaticMeshComponent (mucho más liviano que un actor por prop)."""
    host = colocar(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0), carpeta, f"Props_{tipo}")
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    raiz = sds.k2_gather_subobject_data_for_instance(host)[0]
    params = unreal.AddNewSubobjectParams(parent_handle=raiz, new_class=unreal.InstancedStaticMeshComponent)
    handle, error = sds.add_new_subobject(params)
    if not str(error) in ("", "None"):
        actores.destroy_actor(host)
        raise RuntimeError(error)
    biblioteca = unreal.SubobjectDataBlueprintFunctionLibrary
    ism = biblioteca.get_object(biblioteca.get_data(handle))
    ism.set_static_mesh(malla)
    ism.add_instances([transformacion_prop(p) for p in lista], False, True)
    return len(lista)


def colocar_props(props, carpeta):
    por_tipo = {}
    for p in props:
        if p["tipo"] in PROPS:
            por_tipo.setdefault(p["tipo"], []).append(p)
    for tipo, lista in por_tipo.items():
        malla = unreal.load_asset(PROPS[tipo][0])
        try:
            colocar_props_instanciados(tipo, malla, lista, f"{carpeta}/Props")
        except Exception as e:  # noqa: BLE001 - versión de UE sin esa API: un actor por prop
            unreal.log_warning(f"Instancias no disponibles ({e}); colocando {len(lista)} actores de '{tipo}'")
            for k, p in enumerate(lista):
                t = transformacion_prop(p)
                a = colocar(malla, t.translation, t.rotation.rotator(), f"{carpeta}/Props/{tipo}", f"{tipo}_{k}")
                a.set_actor_scale3d(t.scale3d)
        unreal.log(f"  {tipo}: {len(lista)}")


def ajustar_cesium(meta_terreno, centro):
    if not hasattr(unreal, "CesiumGeoreference"):
        unreal.log_warning("Cesium for Unreal no está activo: se omite la georreferencia.")
        return
    altura = meta_terreno.get("altura_elipsoidal_origen")
    if altura is None:
        altura = meta_terreno["z_origen_msnm"]
        unreal.log_warning("Sin ondulación del geoide: se usa la altura sobre el nivel del mar. "
                           "Ajusta 'Origin Height' comparando con Cesium World Terrain (ver docs).")
    geos = [a for a in actores.get_all_level_actors() if isinstance(a, unreal.CesiumGeoreference)]
    geo = geos[0] if geos else actores.spawn_actor_from_class(unreal.CesiumGeoreference, unreal.Vector(0, 0, 0))
    try:
        geo.set_origin_placement(unreal.OriginPlacement.CARTOGRAPHIC_ORIGIN)
    except Exception:  # noqa: BLE001 - versiones nuevas ya usan origen cartográfico por defecto
        pass
    geo.set_origin_longitude_latitude_height(unreal.Vector(centro["lon"], centro["lat"], altura))
    unreal.log(f"CesiumGeoreference -> lat {centro['lat']}, lon {centro['lon']}, altura {altura:.2f} m")


# ---------------------------------------------------------------- principal

def main():
    args = sys.argv[1:]
    nombres = [a for a in args if not a.startswith("--")]
    if not nombres:
        raise SystemExit("Uso: py 04_importar_zona.py <zona> [--sin-props] [--solo-props]")
    zona = cargar_zona(nombres[0])
    export = RAIZ / "datos" / zona["ciudad"] / zona["id"] / "export"
    with open(export / "meta_zona.json", encoding="utf-8") as f:
        meta = json.load(f)

    titulo = zona["id"].capitalize()
    raiz_ue = f"/Game/Venezuela/{titulo}"
    carpeta_nivel = f"Caracas/{titulo}" if zona["ciudad"] == "caracas" else f"{zona['ciudad'].capitalize()}/{titulo}"

    # Usar el importador FBX clásico (respeta FbxImportUI); en UE 5.5+ el nuevo es Interchange.
    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX False")

    if "--solo-props" in args:
        borrar_carpeta(f"{carpeta_nivel}/Props")
    else:
        n = borrar_carpeta(carpeta_nivel)
        unreal.log(f"Borrados {n} actores previos de '{carpeta_nivel}'")
        maestro = material_maestro(f"{raiz_ue}/Materiales")
        instancias = instancias_materiales(f"{raiz_ue}/Materiales", maestro)

        celdas = meta["celdas"]
        with unreal.ScopedSlowTask(len(celdas), f"Importando {meta['nombre']}") as tarea:
            tarea.make_dialog(True)
            for archivo in celdas:
                if tarea.should_cancel():
                    break
                tarea.enter_progress_frame(1, archivo)
                for malla in importar_fbx(export / archivo, f"{raiz_ue}/Mallas"):
                    if not isinstance(malla, unreal.StaticMesh):
                        continue
                    preparar_malla(malla, instancias)
                    capa = malla.get_name().split("_")[0]
                    colocar(malla, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0),
                            f"{carpeta_nivel}/{capa}", malla.get_name())

        ini = meta["inicio_jugador"]
        # Rotator(roll, pitch, yaw): yaw -90 = mirando al Norte (hacia el Obelisco y El Ávila)
        colocar(unreal.PlayerStart, a_ue(ini["x"], ini["y"], ini["z"]), unreal.Rotator(0, 0, -90),
                carpeta_nivel, "Inicio_PlazaFrancia")
        ajustar_cesium(meta["terreno"], meta["centro"])

    if "--sin-props" not in args:
        with open(export / "props.json", encoding="utf-8") as f:
            colocar_props(json.load(f), carpeta_nivel)

    lu = meta["terreno"]["unreal_landscape"]
    carpeta_terreno = (export.parent / "terreno").as_posix()
    unreal.log("=" * 70)
    unreal.log("LANDSCAPE (modo Landscape > Import from File):")
    unreal.log(f"  Archivo:   {carpeta_terreno}/{lu['archivo']}  ({lu['resolucion']})")
    unreal.log(f"  Location:  X={lu['ubicacion_cm'][0]}  Y={lu['ubicacion_cm'][1]}  Z={lu['ubicacion_cm'][2]}")
    unreal.log(f"  Scale:     X={lu['escala'][0]}  Y={lu['escala'][1]}  Z={lu['escala'][2]}")
    unreal.log("Guarda el nivel con Ctrl+S.")
    unreal.log("=" * 70)


main()
