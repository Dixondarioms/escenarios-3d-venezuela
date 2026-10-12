# 5. Modelos realistas de aeronaves y carros

Los modelos que genera el código (aviones, helicópteros y carros hechos con primitivas) sirven a
distancia, pero de cerca se ven de juguete. Los modelos realistas gratuitos están en sitios que piden
una cuenta (gratis), así que los descargas tú y el pipeline hace el resto.

## Dónde ponerlos

```
C:\UE\Recursos\modelos_usuario\
    helicoptero\        avion_turbohelice\   avion_jet\
    sedan\              hatchback\           camioneta\
    pickup\             por_puesto\          moto\
```

- Formatos: **.glb** (preferido), .gltf (con su carpeta de texturas), .fbx u .obj.
- Puedes poner **varios modelos por carpeta**: se alternan al azar.
- Escribe un `credito.txt` en cada carpeta con el autor, el enlace y la licencia: el script lo copia a
  `docs/creditos_modelos.md` (las licencias CC BY exigen dar crédito).
- Después vuelve a correr el paso 03b de cada zona. El script escala cada modelo a su medida real, lo
  apoya en el suelo y lo orienta con el frente hacia adelante.

Si un modelo queda mirando hacia atrás o de lado, o con un tamaño raro, crea `ajustes.json` en su carpeta:

```json
{ "mi_helicoptero.glb": { "girar": 180, "largo_m": 25.3 } }
```

(`largo_m` = la dimensión horizontal más larga real: en helicópteros incluye el rotor y en aviones
puede ser la envergadura.) O avísame y lo ajusto yo viendo un render.

## Qué buscar (Sketchfab)

En sketchfab.com → buscar → filtros **Downloadable** y licencia **CC Attribution** (permite uso comercial
dando crédito; **evita las "NonCommercial"** si piensas vender el juego). Descarga en formato **glTF/GLB**.
Para que la escena siga funcionando en esta PC, prefiere modelos de **menos de ~150.000 triángulos**
(el número aparece en la página de cada modelo).

| Carpeta | Qué buscar (lo que se ve en La Carlota y Caracas) | Ejemplo verificado |
|---|---|---|
| `helicoptero` | "Mi-17", "Mi-8", "Bell 412", "Super Puma", "AS332" | [Mi-8 de manilov.ap](https://sketchfab.com/3d-models/mi8-1bc2f674ad8345648710f16df847599a) (CC BY, ~34.500 triángulos) |
| `avion_turbohelice` | "King Air", "Beechcraft 350", "Cessna 208 Caravan", "Casa C-212" | — |
| `avion_jet` | "Cessna Citation", "Falcon 50", "Learjet", "business jet" | — |
| `sedan` | "Toyota Corolla", "Chevrolet Aveo", "Ford Fiesta sedan" | — |
| `camioneta` | "Toyota Land Cruiser", "Toyota 4Runner", "Ford Explorer" | — |
| `pickup` | "Toyota Hilux", "Ford F-150", "Chevrolet Silverado" | — |
| `hatchback` | "Chevrolet Spark", "Fiat Uno", "hatchback" | — |
| `por_puesto` | "minibus", "Encava", "Toyota Coaster", "microbus" | — |
| `moto` | "motorcycle 150cc", "Honda CG", "scooter" | — |

Comprueba la licencia en la página de cada modelo antes de descargarlo: la búsqueda web no siempre la muestra.
Con 2–3 modelos por tipo es suficiente para que no se note la repetición.

## Modelos instalados (11-10-2026)

19 modelos de Sketchfab: helicópteros Mi-17 (repintado FANB) y Super Puma (repintado FAV), King Air,
Cessna Citation (repintado Aviación Militar Bolivariana), Corollas (2020,
KE80, AE92), Chevrolet Spark, Fiat Uno, Land Cruisers (FJ40, 100, 76), Hilux (2016, 2021, 2022),
minibuses (Peugeot J5 y otro) y dos motos. Créditos completos: [creditos_modelos.md](creditos_modelos.md).

- Se dejaron fuera dos con licencia **NoComercial** (`2005_toyota_corolla_luxel`, `toyota_land_cruiser` de
  Renafox) y el "S.I.A.M. Spirit" (objeto de 1 m, no es un vehículo).
- **Chevrolet Spark** y **King Air** tienen licencia *Sketchfab Standard*: se pueden usar dentro de un juego
  o render, pero no redistribuir los archivos del modelo por separado.
- Los de más de 200.000 triángulos se simplificaron (por ejemplo el Fiat Uno, de 4 millones a 200.000).

## Revisar la orientación

```powershell
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup -P scripts/blender/revisar_modelos.py
```

Genera `datos/modelos_revision_aeronaves.jpg` y `datos/modelos_revision_carros.jpg`: cada modelo con una
flecha roja hacia donde debe apuntar su frente. Si alguno queda al revés, agrega `"girar": 180` (o 90)
en el `ajustes.json` de su carpeta. La primera vez tarda ~15 minutos (simplifica y guarda en caché);
después, menos de un minuto.

## Pasto 3D

Las superficies de grama (franja de pista y parques) reciben matas de grama 3D de Poly Haven
(`grass_bermuda_01`, `grass_medium_02`, CC0) cerca de la cámara activa: densas hasta 25 m y
desvaneciéndose hasta 90 m. No se siembra donde hay pista, calle, plataforma o acera encima.
Ajustable en `zonas.json` → `"pasto_3d": {"densidad": 30, "radio_pleno": 25, "radio_max": 90}`.
Solo existe en el render (el objeto `Pasto_3D` no se calcula en el viewport).

## Rendimiento

En el viewport, los modelos descargados se muestran como cajas (*Bounds*) y solo aparece el 1 % de los
carros, para que la iGPU no se trabe. En el render (Cycles) se usan todos, como instancias (una sola
copia en memoria por modelo).
