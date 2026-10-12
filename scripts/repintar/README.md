# Repintar aeronaves (esquemas venezolanos)

Cambia la pintura y las marcas de un modelo `.glb` descargado sin tocar su forma.
Cada aeronave tiene su configuración `.json` en esta carpeta:

| Configuración | Resultado | Esquema |
|---|---|---|
| `mi17_fanb.json` | `helicoptero/mil_mi-17_fanb.glb` | FANB, camuflaje verde salvia / oliva / arena, 61120 |
| `citation_amb.json` | `avion_jet/cessna_citation_amb.glb` | Aviación Militar Bolivariana, blanco, timón tricolor, 0002 |
| `super_puma_fav.json` | `helicoptero/as332_super_puma_fav.glb` | FAV, camuflaje arena rosada / oliva / verde oscuro, banda roja 580 |

Los originales quedan en `C:/UE/Recursos/modelos_usuario/_originales/<tipo>/` y los archivos
intermedios en `C:/UE/Recursos/modelos_usuario/_repintar/<nombre>/` (fuera de OneDrive).

## Pasos

```
blender -b --factory-startup -P scripts/repintar/repintar_blender.py -- preparar scripts/repintar/<cfg>.json
.venv/Scripts/python -I scripts/repintar/repintar.py scripts/repintar/<cfg>.json
blender -b --factory-startup -P scripts/repintar/repintar_blender.py -- exportar scripts/repintar/<cfg>.json
```

1. **preparar** (lento, una sola vez por modelo): gira el modelo (largo en Y, nariz hacia +Y, costado
   derecho en +X), separa el costado izquierdo si la textura está en espejo (`"dividir"`), crea UV nuevas
   si las del modelo no sirven (`"uv_nuevas"`), y hornea color, posición y normal de cada píxel.
2. **repintar** (rápido): aplica las capas de `"pintura"` y las `"marcas"`. Deja `guia_der.png` y
   `guia_izq.png` en la carpeta de trabajo: vistas laterales con cuadrícula para medir dónde poner cada marca.
   Para cambiar un número, un texto o mover una marca basta con editar el `.json` y repetir este paso.
3. **exportar**: escribe el `.glb` final con los créditos del autor original (CC-BY) más la nota del cambio.

Después de exportar, `scripts/blender/revisar_modelos.py` reconstruye la caché y la hoja de revisión.

## Capas de pintura

- `camuflaje_remapeo`: convierte un camuflaje de dos tonos existente a tres tonos nuevos conservando
  sombras y desgaste; `borrar_rojo` borra insignias rojas dentro de una zona 3D.
- `camuflaje_procedural`: camuflaje nuevo con manchas de ruido 3D (continuo entre piezas).
- `color`: pinta de un color los píxeles elegidos (por color original, tono, brillo o caja 3D).
- `original`: devuelve el color original (cristales, mástil del rotor, ruedas...).

## Marcas

`texto`, `bandera` (Venezuela, con estrellas), `banda` (rectángulo de color con texto), `linea`, `escarapela`.
Cada una lleva `centro` [y, z], `tam` [ancho, alto] en unidades del modelo (léelas en la guía),
`px` (resolución de la imagen de la marca) y opcionalmente `giro` en grados y `lados` (`der`, `izq`).
