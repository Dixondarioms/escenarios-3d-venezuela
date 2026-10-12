# 2. Flujo de trabajo: de los datos a Unreal

Ejemplo con la zona `altamira` (centro en el Obelisco de Plaza Francia, cuadrado de 2016 × 2016 m).
Todos los comandos se corren desde la carpeta `Escenarios 3D`.

## Paso 01 — Datos de OpenStreetMap

```bash
.venv\Scripts\python scripts\01_descargar_osm.py altamira
```

Descarga edificios, calles (carriles, sentido, puentes), plazas, parques, árboles, semáforos, paradas,
entradas de Metro, etc. y los pasa a metros locales. Muestra un resumen como:

```
Edificios: 1300  (altura real: ~800, estimada: ~500)
```

Los edificios sin altura en OSM reciben una **estimada** según su tipo y tamaño (marcada con
`altura_estimada: true`). Para mejorarlos, lo ideal es **agregar `building:levels` en OpenStreetMap**
(openstreetmap.org → Editar) contando pisos con Street View o en persona: se beneficia todo el mundo
y la próxima descarga ya los trae.

Si Overpass falla por saturación, el script reintenta en otros servidores. Para reprocesar sin
descargar de nuevo: `--sin-descarga`.

## Paso 02 — Relieve

```bash
.venv\Scripts\python scripts\02_descargar_dem.py altamira
```

Descarga el tile Copernicus de 30 m (una sola vez, ~28 MB, queda en `datos/_dem_cache`), quita los
bultos de edificios/árboles, lo suaviza y genera la rejilla de 2 m. Revisa `terreno/vista_relieve.png`:
debe verse la pendiente subiendo hacia el norte (hacia El Ávila) y ningún "grano" de edificios.

## Paso 03 — Maqueta en Blender

```powershell
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup -P scripts/blender/03_construir_zona.py -- altamira
```

Tarda ~1 minuto. Vistas previas de referencia en `datos/caracas/altamira/vistas/`. Genera `datos/caracas/altamira/altamira.blend` y `export/` con las celdas FBX.
**Revísalo en Blender** (abre el .blend): con vista superior (numpad 7) el Obelisco está en el origen,
la Av. Francisco de Miranda corre de oeste a este al sur de la plaza, y la Av. Luis Roche sube hacia
el norte. Los colores son solo de vista previa.

Opcional: `-- altamira --exportar-terreno` exporta el terreno como malla (si no quieres usar Landscape).

## Paso 04 — Importar en Unreal

1. Abre `C:\UE\CaracasSim`. **File → New Level → Empty Open World** (o *Basic*), guárdalo como
   `/Game/Venezuela/Altamira/L_Altamira`.
2. Abre la consola (tecla `` ` ``, la que está debajo de Esc) y ejecuta:
   ```
   py "C:/Users/Dixon/OneDrive/Documentos/Escenarios 3D/scripts/ue/04_importar_zona.py" altamira
   ```
3. Al terminar, el **Output Log** (Window → Output Log) muestra los números del Landscape.

### Landscape (terreno)

Modo **Landscape** (Shift+2) → *Manage* → **Import from File** → selecciona
`datos/caracas/altamira/terreno/heightmap_ue.png`. Usa exactamente la **Location** y **Scale** que imprimió
el script (también están en `terreno/meta.json` → `unreal_landscape`). Material: por ahora uno simple
de tierra/grama; las calles y aceras van encima como mallas.

## Cesium: ciudad lejana, El Ávila y vuelo

1. Panel **Cesium** (Window → Cesium) → *Quick Add Basic Actors* → **Cesium World Terrain + Bing Maps Aerial**
   y **Cesium OSM Buildings**. Agrega también **Cesium SunSky** y borra cualquier otra Directional Light /
   Sky Atmosphere / Sky Light del nivel.
2. El script ya configuró el **CesiumGeoreference** en el Obelisco. Verifica en sus propiedades:
   *Origin Latitude 10.4965344, Longitude -66.8489082* y la *Origin Height* que imprimió.
3. **Alineación vertical**: si el terreno de Cesium queda arriba o abajo de tu Landscape, cambia solo
   *Origin Height* del CesiumGeoreference hasta que coincidan (sube la altura → el mundo de Cesium baja).
   Luego anota ese valor en `zonas.json` → `ondulacion_geoide_m` = (altura final − `z_origen_msnm`).
4. **Recortar los tiles dentro de la zona jugable** (para que no se superpongan con tus edificios):
   - Cesium → *Cesium Cartographic Polygon*: colócalo y edita los puntos de su spline para formar el cuadrado
     (esquinas en X/Y = ±100800 cm).
   - En *Cesium World Terrain* y *Cesium OSM Buildings* → *Add Component* → **Cesium Polygon Raster Overlay**,
     asigna el polígono y activa **Exclude Selected Tiles** (en OSM Buildings) para ocultar los edificios de
     Cesium dentro de la zona.
5. **SunSky**: *Time Zone* = −4, la fecha y hora que quieras. Recuerda que Caracas está a ~10.5° N: a
   mediodía el sol está casi vertical. Para atardeceres dorados prueba 17:45–18:30.
6. Ambiente: agrega **Volumetric Cloud** y **Exponential Height Fog** (densidad baja, con
   *Volumetric Fog* apagado en esta PC) para la bruma típica del valle.

## Los tres modos

| Modo | Cómo probarlo ahora |
|---|---|
| **A pie** | World Settings → *GameMode Override* = `BP_FirstPersonGameMode`. Play (Alt+P): apareces en Plaza Francia. |
| **Vehículo** | Arrastra el auto de la plantilla *Vehicle* (`VehicleTemplate/Blueprints`) a la Av. Francisco de Miranda; en Details → *Auto Possess Player* = **Player 0**. |
| **Vuelo** | Cesium → *Quick Add* → **Dynamic Pawn**; *Auto Possess Player* = **Player 0**. Sube con E, baja con Q. |

Solo un actor debe tener *Auto Possess Player 0* a la vez. Más adelante se hará un selector con una tecla.

## Comprobaciones

- `stat fps` y `stat unit` en la consola: el objetivo en esta PC es ≥ 30 fps a nivel de calle.
  Si va lento: Scalability → Low, `r.ScreenPercentage 50`, oculta la carpeta *Props* o Cesium OSM Buildings.
- Compara con Google Earth desde el mismo punto: los edificios propios y el terreno de Cesium deben quedar
  alineados (< 2–3 m).
- Camina de Plaza Francia a la Av. Francisco de Miranda; maneja por la Luis Roche; despega y busca El Ávila.

## Problemas comunes

| Síntoma | Solución |
|---|---|
| La ciudad sale **en espejo** (norte y sur invertidos) respecto a Cesium | Reimporta con la opción *Force Front X Axis* desactivada (por defecto) y verifica que Blender exportó con `axis_forward=-Z, axis_up=Y`. Avísame y ajustamos el script. |
| Todo sale 100 veces más grande o pequeño | En el FBX import, *Import Uniform Scale* = 1 y *Convert Scene Unit* activo. |
| El editor se cierra por memoria | Archivo de paginación de 16–24 GB, cierra el navegador, usa Scalability Low, importa con `--sin-props`. |
| Calles que parpadean en los cruces | Normal en esta versión base (se superponen dos cintas). Se corrige en la fase de realismo con mallas de intersección. |
| Edificios flotando o enterrados | El terreno es aproximado (modelo de 30 m). Ajusta `filtro_dsm_px`/`suavizado_terreno_m` en `zonas.json` y repite 02 y 03. |

## Nuevas zonas

Agrega una entrada a `scripts/config/zonas.json` (copia `altamira`, cambia `centro` e `id`) y repite los
pasos 01→04. Ejemplos de próximos centros: Plaza Bolívar (10.5061, −66.9146), Sabana Grande / Chacaíto,
UCV, La Guaira.
