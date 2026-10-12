# 3. Hoja de ruta hacia el realismo

Los pasos 01–04 dan una **maqueta fiel en forma y escala**: calles, manzanas, alturas y relieve reales.
El realismo visual se construye encima, por capas, siempre comparando capturas contra fotos reales del
mismo punto. Orden recomendado (de mayor a menor impacto):

## A. Luz y atmósfera (impacto enorme, costo bajo)
- Cesium SunSky con hora y fecha reales; nubes volumétricas sobre El Ávila; bruma de valle.
- *Post Process Volume* global: exposición manual o rango acotado, *Bloom* suave, ligera aberración y viñeta.
- Noche: farolas de sodio (naranja ~2000 K) en vías secundarias y LED (blanco ~4000 K) en la Francisco de Miranda.

## B. Materiales (lo que más delata un escenario "de maqueta")
- Texturas **CC0** de Poly Haven y ambientCG: asfalto gastado, concreto, friso, granito, cerámica, grama tropical.
- Material maestro de fachada con: ventanas por módulo de 3 m (las UV de las paredes están en metros),
  manchas de humedad y escorrentía bajo ventanas, suciedad en la base y variación por edificio
  (color de vértice R).
- Asfalto con parches, grietas, tapas de alcantarilla y rayado (las calles tienen UV1 = 0..1 a lo ancho
  para las líneas).

## C. Kit de fachadas caraqueñas (Blender → Unreal)
Piezas modulares de 3 × 3 m: ventana con reja, ventana con aire acondicionado, balcón, local comercial
con santamaría, entrada de edificio con reja, planta baja de vidrio para oficinas. Luego un script que
reemplace las paredes de los edificios residenciales por estos módulos según su altura.

## D. Monumentos y lugares "héroe"
Modelados con detalle a partir de fotos y medidas: **Obelisco y fuente de Plaza Francia**, entradas del
**Metro Altamira**, **Torre Británica**, Hotel Caracas Palace, Centro Plaza, Sambil (fachada).
Con el celular: **RealityScan** (gratis) para escanear objetos pequeños (kioscos, bancos, bocas de Metro).

## E. Calles vivas (PCG)
Con *Procedural Content Generation* de Unreal a lo largo de las calles: postes con **cableado aéreo**,
kioscos, paradas, conos, bolsas de basura, motos estacionadas, avisos, rejas, señales venezolanas
(PARE, flechas, nomenclatura), huecos y parches.

## F. Vegetación tropical
Chaguaramos / palmas reales, samanes, araguaneyes, bucares, mangos y matorral del Ávila. En esta PC usar
vegetación con pocos polígonos y *impostores* a distancia.

## G. Tráfico y gente
Autos típicos (sedanes y camionetas de los 2000, camioneticas por puesto, motos), peatones con *Mass AI*
(solo con mejor hardware).

## Referencias visuales
Fotos propias (lo mejor), **Mapillary** (fotos libres a nivel de calle) y Street View **solo como
referencia** para mirar: no se pueden copiar sus imágenes como texturas.

## Cuando haya mejor PC
Activar **Lumen** (iluminación global) y **Nanite** (geometría masiva), Virtual Shadow Maps, resolución
100 %, más densidad de vegetación y props. Todo lo construido aquí se aprovecha sin rehacer nada.
