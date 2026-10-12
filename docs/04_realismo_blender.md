# 4. Realismo en Blender

Blender es el taller principal: allí se construye y se revisa todo con calidad de render, y la misma
geometría (con UV en metros y colores de vértice) se exporta a Unreal.

## Pasos

| Paso | Comando | Qué hace |
|---|---|---|
| 00 (una vez) | `.venv\Scripts\python scripts\00_descargar_recursos.py` | Baja ~450 MB de texturas, modelos y cielo CC0 de Poly Haven a `C:\UE\Recursos` |
| 01 | `.venv\Scripts\python scripts\01_descargar_osm.py altamira` | Datos de OpenStreetMap (ahora también fuentes, setos, muros, pasos de cebra) |
| 01b | `.venv\Scripts\python scripts\01b_edificios_microsoft.py altamira` | Completa los edificios que faltan en OSM con las huellas de Microsoft (repetir siempre después de 01) |
| 02 | `.venv\Scripts\python scripts\02_descargar_dem.py altamira` | Terreno de la zona + relieve de fondo de 28 km (El Ávila, valle, costa) |
| 02c | `.venv\Scripts\python scripts\02c_ciudad_lejana.py altamira` | Ciudad alrededor de la zona (~55.000 edificios hasta 7 km, alturas del modelo de superficie) y relieve de fondo aplanado en zonas urbanas. Correr después de 02 |
| 02b | `.venv\Scripts\python scripts\02b_imagen_satelital.py altamira` | Imagen Sentinel-2 real (10 m) para El Ávila y el valle, NDVI de vegetación y ~7.600 árboles donde el satélite ve verde (~25 s). `--listar` muestra otras fechas; `--escena ID` elige una |
| 03 | `blender -b --factory-startup -P scripts/blender/03_construir_zona.py -- altamira` | Maqueta con fachadas detalladas cerca de Plaza Francia (~25 s) |
| 03b | `blender -b -P scripts/blender/03b_realismo.py -- altamira` | Materiales, cielo, sol, bruma, mobiliario, árboles y cámaras (~50 s) |
| render | `blender -b datos/caracas/altamira/altamira_realista.blend -P scripts/blender/render_camaras.py -- Cam_Plaza_Calle` | Renderiza cámaras (Cycles en CPU) |

(`blender` = `"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"`)

Para trabajar a mano, abre **`datos/caracas/altamira/altamira_realista.blend`**. No edites a mano
`altamira.blend`: los pasos 03/03b lo regeneran. Si haces cambios manuales que quieras conservar, guárdalos
en otro archivo o pídeme que los pase al script.

## Qué hay en la escena

- **Fachadas detalladas** (radio `detalle.radio_m` = 170 m alrededor del Obelisco, en `zonas.json`):
  ventanas hundidas con vidrio y marco, rejas en los primeros pisos, locales con santamaría o vidriera,
  muros cortina en oficinas, aires acondicionados de ventana, pretiles en las azoteas.
- **Resto de la zona**: ventanas dibujadas por el material (mismo módulo de 3 m), pretiles, tanques y
  casillas de ascensor en las azoteas.
- **Materiales** con texturas reales: paleta de colores típica de fachadas caraqueñas, manchas de humedad
  y zócalo sucio, asfalto oscuro con líneas de carril (blancas discontinuas, amarilla central en doble
  sentido) y pasos de cebra gastados, aceras de concreto, jardineras con brocal, espejos de agua.
- **Fondo**: El Ávila (hasta 2.746 m), el valle y la costa con la imagen satelital Sentinel-2 real del
  18-02-2024 (temporada seca), con la vegetación realzada y relieve de copas de árboles.
- **Suelo entre edificios** según el satélite: grama y tierra donde hay vegetación (NDVI), concreto y
  asfalto de estacionamientos donde no; ~7.600 árboles extra donde el satélite ve verde libre.
- **Cielo físico** (Nishita) con el sol en la posición real según `render.fecha`/`render.hora` y bruma
  de valle (perspectiva aérea en el compositor).
- **Vehículos** (Geometry Nodes, objeto `Vehiculos`): estacionados junto al brocal en calles locales y
  circulando por su carril en avenidas (se maneja por la derecha): sedanes, hatchbacks, camionetas,
  pickups, carritos por puesto y motos, con colores variados (atributo `col_auto` de cada instancia).
  Unos 3.300 en Altamira y 12.000 en La Carlota; en el viewport se ve solo el 10 %.
- **Ciudad lejana** (objeto `Ciudad_Lejana`): edificios simples con ventanas pintadas hasta 7 km.
- **Mobiliario como instancias**: 1.078 farolas, 70 semáforos, 890 tanques, 474 casillas, 1.476 aires,
  ~8.000 árboles (jacaranda: 473 de OSM + los del satélite), paradas, entradas del Metro, papeleras, hidrantes y tapas de alcantarilla.

## Zonas disponibles

| Zona | Qué incluye |
|---|---|
| `altamira` | Plaza Francia y el Obelisco con detalle máximo, Chacao, La Castellana, Los Palos Grandes (2 × 2 km) |
| `lacarlota` | Base Aérea La Carlota (SVFM) con pista 11/29 de 1.963 × 30 m y sus marcas OACI, números de pista, calles de rodaje con eje amarillo, plataformas de losas, helipuertos, mangas de viento, hangares abovedados de zinc, torre de control con cabina de vidrio, edificios militares bajos y 32 aeronaves estacionadas (helicópteros tipo Bell 412, turbohélices tipo King Air y jets ejecutivos); Parque del Este, Los Ruices, Santa Cecilia, El Rosal, CCCT, Chuao (4 × 4 km) |

**Alturas de edificios:** las que no vienen en OSM se estiman por tipo y tamaño, y el paso 02 las corrige
con el modelo de superficie Copernicus (superficie − suelo), sobre todo en edificios grandes. Para fijar una
altura real a mano: `zonas.json` → `alturas_conocidas`.

Las cámaras de cada zona se definen en `zonas.json` → `camaras` (`"ojo": true` = altura sobre el piso real).
Para La Carlota la hora por defecto es 11:30 con exposición −1,5 (`render.exposicion`), para que ninguna
vista mire de frente al sol.

## Cámaras incluidas

| Cámara | Vista |
|---|---|
| `Cam_Plaza_Calle` | Desde la Av. Francisco de Miranda hacia el Obelisco y El Ávila |
| `Cam_Plaza_Fuente` | Dentro de la plaza, junto a las fuentes |
| `Cam_Plaza_Dron` | Dron a ~110 m sobre Altamira |
| `Cam_Avila` | Vista alta del valle con El Ávila |

Otra hora del día: `-- altamira --hora 17:50` (atardecer) o `--fecha 2026-07-01`.

## En esta PC (8 GB, gráficos integrados)

- **Render**: Cycles usa el procesador (la Radeon integrada no es compatible con Cycles). Una imagen
  1920×1080 a 96 muestras tarda varios minutos. Para pruebas: `--muestras 24 --porcentaje 40`.
- **Viewport**: usa *Solid* o *Material Preview*. Los árboles se muestran como cajas (*Bounds*) para que
  el viewport no se trabe; para verlos, selecciona el objeto del árbol en la colección *Biblioteca* →
  Object Properties → Viewport Display → Display As: *Textured*.
- **Memoria**: la escena usa ~3,7 GB al renderizar. Cierra el navegador mientras renderizas.

## Compatibilidad con Unreal

Todo lo que define el aspecto está en la geometría (UV en metros, colores de vértice) y en fórmulas de
material que se pueden replicar en Unreal (las líneas de carril, la cebra, las ventanas dibujadas y los
marcos usan solo UV y colores de vértice). Lo único exclusivo de Blender es el relieve de fondo y la bruma
del compositor: en Unreal los reemplazan Cesium y la niebla de altura.

Cámaras de La Carlota: `Cam_Cabecera_29`, `Cam_Aproximacion_11`, `Cam_Dron_Base`, `Cam_Plataforma`,
`Cam_Aeronaves`, `Cam_Torre`.

## Próximas mejoras posibles

- Palmas (chaguaramos) y samanes además de las jacarandas; arbustos y flores en las jardineras.
- Cableado eléctrico y telefónico entre postes; avisos comerciales; carros estacionados y tráfico.
- Detalle del Obelisco (base, escalinatas) y de las fuentes con chorros de agua.
- Extender el radio de detalle o crear zonas nuevas (Centro, Sabana Grande, UCV…).
