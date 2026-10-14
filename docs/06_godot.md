# 6. Usar los escenarios en Godot 4.4

El proyecto de Godot está en la carpeta `godot/` del repositorio. Trae las zonas de Altamira y La Carlota
exportadas desde Blender, con los mismos materiales (reescritos como shaders de Godot), el cielo con nubes,
las luces de mañana / mediodía / tarde / nublado, el pasto 3D, los árboles, carros y aeronaves, y un jugador
que camina o vuela.

## Abrirlo en otra PC

1. Instala **Godot 4.4** (versión estándar, no .NET).
2. Clona el repositorio con Git LFS (`git lfs install`, luego `git clone ...`), o copia la carpeta `godot/`.
3. En Godot: **Importar** → elige `godot/project.godot`. La primera vez importa todos los modelos y texturas
   (varios minutos; queda guardado en `godot/.godot/`).
4. **F5** (Ejecutar). Empieza en La Carlota a pie.

## Controles

| Tecla | Acción |
|---|---|
| W A S D / ratón | Caminar y mirar |
| Shift | Correr (o ir más rápido volando) |
| Espacio | Saltar |
| F | Volar / caminar (al volar: E sube, Q baja) |
| 1 – 9 | Ir a las cámaras que se usaron en los renders de Blender |
| L | Cambiar la luz: mediodía → mañana → tarde → nublado |
| C | Calidad gráfica: baja → media → alta |
| Tab | Cambiar de zona (La Carlota ↔ Altamira) |
| H | Mostrar u ocultar la ayuda |
| Esc | Soltar el ratón |

También se puede abrir directo en un lugar: `Godot_v4.4.1-stable_win64.exe --path godot -- --zona=altamira --camara=Cam_Metro --luz=tarde`

## Calidad para una GeForce GT 750

La calidad **baja** es la de inicio: sombras de 2048 px a 250 m, sin SSAO, render al 75 % con FSR, pasto hasta
45 m y la ciudad cargada a 600 m. Si va fluido, sube a **media** con la tecla C. La **alta** (SSIL, reflejos SSR,
TAA, pasto a 100 m) es para una tarjeta más moderna.

Medido en la laptop de desarrollo (Radeon Vega 7 integrada, calidad media, 1600 × 900): unos **30 FPS** en
La Carlota, con ~550 MB de memoria de video. La GT 750 debería andar parecido o algo mejor.

Lo que hace que alcance:
- **Texturas comprimidas** (VRAM Compressed + mipmaps): sin esto la memoria de video pasa de 1,5 GB y el FPS
  cae a 10.
- **Dos versiones de cada objeto repetido**: detallada de cerca (carros a 90 m, árboles a 160 m) y una versión
  lejana muy simple (envolvente o árbol de pocas hojas) hasta 600–2400 m.
- **El árbol** (jacarandá de Poly Haven, 3,9 millones de triángulos) se reemplaza por tronco, ramas grandes y
  ~380 tarjetas de hojas: 4.300 triángulos.
- **El pasto** solo existe en las celdas cercanas y se dibuja hasta 45–100 m.

## Cómo se genera (si cambias algo en Blender)

```
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b datos/caracas/lacarlota/lacarlota_realista.blend -P scripts/godot/05_exportar_godot.py -- lacarlota
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b datos/caracas/altamira/altamira_realista.blend -P scripts/godot/05_exportar_godot.py -- altamira
.venv\Scripts\python scripts\godot\06_preparar_texturas.py
Godot_v4.4.1-stable_win64_console.exe --headless --path godot --import
.venv\Scripts\python scripts\godot\07_ajustar_importacion.py
Godot_v4.4.1-stable_win64_console.exe --headless --path godot --import
```

(El paso 07 comprime las texturas y quita el LOD automático de las celdas; solo hace falta la primera vez que
aparecen archivos nuevos. Los `.import` quedan en el repositorio.)

- `05_exportar_godot.py` escribe `godot/zonas/<zona>/`: las celdas de 252 m (`celdas/celda_I_J.glb`), los objetos
  repetidos en `biblioteca.glb` (farolas, tanques, árboles, carros, aeronaves...), sus posiciones por celda
  (`celda_I_J.json`), los puntos del pasto (`pasto_I_J.bin`), el relieve lejano (`fondo.glb`) y `zona.json`
  (cámaras, luces, materiales simples, imagen satelital y créditos).
- `06_preparar_texturas.py` copia las texturas de Poly Haven a `godot/texturas/` (color a 2048 px, normal y
  rugosidad a 1024 px por la poca memoria de video de la GT 750).
- Los materiales de Blender no pasan a Godot: cada malla lleva solo el **nombre** del material (M_Asfalto,
  M_Fachada_Friso...) y `godot/scripts/materiales.gd` lo cambia por el shader equivalente de `godot/shaders/`.
  Si agregas un material nuevo en Blender, agrégalo también en la tabla `ESPEC` de `materiales.gd` (si no, se ve
  con su color plano).

## Créditos obligatorios dentro del juego

Igual que en Unreal: «© OpenStreetMap contributors», Copernicus (DEM y Sentinel-2) y los autores CC BY de los
modelos de Sketchfab (`docs/creditos_modelos.md`). La lista está en `zona.json` → `creditos`. Los modelos con
licencia *Sketchfab Standard* se pueden usar dentro del juego pero no repartir sueltos.
