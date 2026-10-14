# Escenarios 3D de Venezuela

Pipeline para crear escenarios 3D realistas de lugares reales de Venezuela en **Unreal Engine 5**,
para videojuegos y simuladores (a pie, en vehículo y en vuelo). Zonas: **Altamira / Chacao** y
**La Carlota y alrededores** (Caracas). Cambia `altamira` por `lacarlota` en los comandos.

## Cómo funciona

```
OpenStreetMap ──► 01_descargar_osm.py ──┐
                                        ├──► Blender: 03_construir_zona.py ──► celdas FBX ──► Unreal: 04_importar_zona.py
Copernicus DEM ─► 02_descargar_dem.py ──┘                                    heightmap ───► Landscape
                                                         Cesium for Unreal ──► ciudad lejana, El Ávila, vista aérea
```

Hay dos capas:
1. **Zona jugable** (~2 × 2 km): geometría propia con edificios, calles, aceras, plazas y props,
   sobre el relieve real. Tiene colisión para caminar y manejar, y se puede distribuir en un juego.
2. **Fondo y vuelo**: Cesium for Unreal transmite el terreno y las imágenes satelitales de todo el valle.

## Estructura

| Carpeta | Contenido |
|---|---|
| `scripts/config/zonas.json` | Zonas definidas (centro, tamaño, resolución). Agrega aquí nuevas zonas. |
| `scripts/00_descargar_recursos.py` | Texturas, modelos y cielo CC0 de Poly Haven → `C:\UE\Recursos` (una vez) |
| `scripts/01_descargar_osm.py` | Descarga edificios, vías, áreas, fuentes, setos y puntos de OSM → `osm_local.json` |
| `scripts/01b_edificios_microsoft.py` | Completa los edificios que faltan en OSM (Microsoft Global ML Building Footprints) |
| `scripts/02_descargar_dem.py` | Relieve de la zona + heightmap de Unreal + relieve de fondo (El Ávila) |
| `scripts/02c_ciudad_lejana.py` | Edificios de la ciudad alrededor de la zona (fondo con volumen) |
| `scripts/02b_imagen_satelital.py` | Imagen Sentinel-2 real, NDVI de vegetación y árboles según el satélite |
| `scripts/blender/03_construir_zona.py` | Construye la maqueta (fachadas detalladas en Plaza Francia) y la exporta en celdas FBX |
| `scripts/blender/detalle.py` | Ventanas, rejas, locales, pretiles, fuentes y setos (lo usa el paso 03) |
| `scripts/blender/03b_realismo.py` | Escena realista en Blender: materiales, cielo, sol, bruma, mobiliario, cámaras |
| `scripts/blender/render_camaras.py` | Renderiza cámaras de la escena realista |
| `scripts/ue/04_importar_zona.py` | Importa todo al nivel de Unreal, crea materiales y ajusta Cesium |
| `scripts/ue/DefaultEngine_iGPU.ini` | Ajustes de render para PCs con gráficos integrados |
| `datos/<ciudad>/<zona>/` | Datos descargados y resultados (se regeneran con los scripts) |
| `docs/` | Guías |

El **proyecto de Unreal** va fuera de OneDrive, en `C:\UE\CaracasSim`.

## Guías

1. [Instalación y preparación de la PC](docs/01_instalacion.md)
2. [Flujo de trabajo: de los datos a Unreal](docs/02_flujo_de_trabajo.md)
3. [Hoja de ruta hacia el realismo](docs/03_realismo.md)
4. [Realismo en Blender (escena de render)](docs/04_realismo_blender.md)
5. [Modelos realistas de aeronaves y carros (descargados por ti)](docs/05_modelos_realistas.md)
6. [Usar los escenarios en Godot 4.4](docs/06_godot.md) (proyecto listo en `godot/`)
7. [Licencias y atribuciones](docs/licencias.md)

## Usarlo desde otro proyecto

El repositorio guarda los scripts, la documentación y también los resultados pesados (`.blend`, celdas
FBX, relieve, imágenes) con **Git LFS**, para no tener que regenerarlos:

```
git lfs install
git clone https://github.com/<usuario>/escenarios-3d-venezuela.git
```

- Los `.blend` de `datos/caracas/<zona>/` abren directamente en Blender 4.5. Las escenas `*_realista.blend`
  ya incluyen los modelos descargados de Sketchfab (ver [créditos](docs/creditos_modelos.md)); dos de ellos
  tienen licencia *Sketchfab Standard*, que no permite redistribuir los archivos: mantén el repositorio
  **privado**.
- Las texturas de Poly Haven y los modelos originales no van en el repositorio: viven en `C:\UE\Recursos`
  y las escenas las leen desde esa ruta. En otra PC, corre `scripts/00_descargar_recursos.py` para recrearla
  (los modelos de Sketchfab se descargan a mano, ver docs/05).
- No se suben `.venv/`, las copias `*.blend1` ni las cachés de descarga (`datos/_ms_cache`, `datos/_dem_cache`).

## Comandos rápidos

```
.venv\Scripts\python scripts\00_descargar_recursos.py
.venv\Scripts\python scripts\01_descargar_osm.py altamira
.venv\Scripts\python scripts\01b_edificios_microsoft.py altamira
.venv\Scripts\python scripts\02_descargar_dem.py altamira
.venv\Scripts\python scripts\02c_ciudad_lejana.py altamira
.venv\Scripts\python scripts\02b_imagen_satelital.py altamira
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup -P scripts/blender/03_construir_zona.py -- altamira
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b -P scripts/blender/03b_realismo.py -- altamira --render
```
y en la consola de Unreal:
```
py "C:/Users/Dixon/OneDrive/Documentos/Escenarios 3D/scripts/ue/04_importar_zona.py" altamira
```
