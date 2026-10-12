# 1. Instalación y preparación de la PC

Tu PC: Ryzen 5 5625U, gráficos integrados Radeon (Vega 7), **8 GB de RAM**.
Unreal Engine 5 recomienda 32 GB y una tarjeta gráfica dedicada. Con estos pasos funciona,
pero hay que trabajar con zonas pequeñas y calidad media.

> **La mejora más rentable:** pasar a **16 GB de RAM** (o más). Revisa si tu laptop tiene una
> ranura SO-DIMM libre (CPU-Z → pestaña *Memory/SPD*, o el manual del modelo). Una GPU dedicada
> (PC de escritorio o eGPU) permitiría después activar Lumen y Nanite para el fotorrealismo completo.

## 1.1 Windows

1. **Archivo de paginación** (memoria virtual): Configuración → Sistema → Información → Configuración avanzada
   del sistema → Rendimiento → Configuración → Opciones avanzadas → Memoria virtual → Cambiar.
   Desmarca "Administrar automáticamente", elige C:, **Tamaño personalizado: inicial 16384, máximo 24576** MB.
   Reinicia.
2. **Controladores AMD**: instala el último *AMD Software: Adrenalin Edition* desde amd.com.
3. **Energía**: laptop siempre conectada, modo de energía "Mejor rendimiento".
4. **Memoria de video**: en la BIOS/UEFI, si existe la opción *UMA Frame Buffer Size*, súbela a **2 GB**.
5. Cierra navegador y programas pesados mientras uses Unreal.

## 1.2 Programas

| Programa | Dónde | Notas |
|---|---|---|
| **Python 3.12** | ✅ ya instalado (`%LOCALAPPDATA%\Programs\Python\Python312`) y entorno `.venv` creado | — |
| **Blender 4.5 LTS** | ✅ ya instalado en `C:\Program Files\Blender Foundation\Blender 4.5` | Opcional: agregarlo al PATH (ver abajo). |
| **Epic Games Launcher** | epicgames.com | Desde ahí, Unreal Engine **5.6 o 5.7**. |
| **Git** (opcional) | git-scm.com | Para guardar versiones de los scripts. |

**Unreal Engine (ahorra espacio):** en el Launcher → Unreal Engine → Biblioteca → ▾ junto a la versión →
*Opciones* → deja solo **Starter Content** y **Templates and Feature Packs**; desmarca plataformas (Android,
iOS, Linux…) y *Editor symbols for debugging*. Ocupa unos 40–60 GB.

**Blender en el PATH:** Configuración de Windows → busca "variables de entorno" → Path → Nuevo →
`C:\Program Files\Blender Foundation\Blender 4.x` (ajusta la versión). Verifica en una terminal nueva:

```bash
blender --version
```

## 1.3 Entorno de Python del proyecto

Ya está creado. Si algún día hay que rehacerlo, desde la carpeta `Escenarios 3D`:

```bash
python -m venv .venv
```
```bash
.venv\Scripts\python -m pip install -r scripts/requirements.txt
```

Después, ejecuta los scripts con `.venv\Scripts\python scripts\01_descargar_osm.py altamira`, etc.
(OneDrive puede sincronizar la carpeta `.venv`; si molesta, clic derecho → *Liberar espacio* o muévela fuera).

## 1.4 Proyecto de Unreal

1. Crea la carpeta `C:\UE` (fuera de OneDrive: OneDrive sincroniza miles de archivos pesados y las rutas
   largas rompen Unreal).
2. Unreal → *Games* → **Blank**, sin Starter Content, Blueprint, Calidad **Scalable**, sin Ray Tracing.
   Ruta `C:\UE`, nombre `CaracasSim`.
3. Cierra el editor y copia el contenido de [`scripts/ue/DefaultEngine_iGPU.ini`](../scripts/ue/DefaultEngine_iGPU.ini)
   al final de `C:\UE\CaracasSim\Config\DefaultEngine.ini`.
4. Abre el proyecto. **Edit → Plugins**, activa:
   - **Python Editor Script Plugin** (y *Editor Scripting Utilities* si aparece)
   - **Cesium for Unreal** (instálalo antes desde fab.com → "Cesium for Unreal" → *Add to My Library*,
     y en el Launcher → Biblioteca → *Install to Engine*)
   Reinicia el editor.
5. **Edit → Editor Preferences**:
   - *General → Performance*: activa **Use Less CPU when in Background**.
   - *Level Editor → Viewports*: desactiva *Realtime* en los viewports que no uses.
6. En el viewport: **Settings (⚙) → Engine Scalability Settings → Medium** (o *Low* si va lento).
7. Agrega las plantillas de juego: **Add (botón verde) → Add Feature or Content Pack → First Person** y
   **Vehicle** (las usaremos para caminar y manejar).

## 1.5 Cuenta de Cesium ion

Crea una cuenta gratuita en ion.cesium.com (uso personal/no comercial). En Unreal, panel **Cesium** →
*Connect to Cesium ion*. Eso da acceso a *Cesium World Terrain*, imágenes Bing y *Cesium OSM Buildings*.

**Google Photorealistic 3D Tiles (opcional):** primero revisa en Google Earth (web) si Caracas se ve
en 3D fotorrealista. Si sí, puedes agregarlo en el panel Cesium (*Google Photorealistic 3D Tiles*) para el
modo vuelo. Ver restricciones en [licencias](licencias.md).
