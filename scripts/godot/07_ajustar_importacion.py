"""Ajusta los .import del proyecto de Godot para que quepa en una tarjeta de video modesta (GT 750, iGPU).

Uso (después de que Godot haya importado una zona nueva por primera vez):
    .venv\\Scripts\\python scripts\\godot\\07_ajustar_importacion.py
    Godot_v4.4.1-stable_win64_console.exe --headless --path godot --import

- Texturas: comprimidas en VRAM (BPTC/S3TC) con mipmaps; los mapas normales, como normales. Sin esto la
  memoria de video pasa de 1,5 GB y la imagen parpadea a lo lejos.
- Celdas: sin LOD automático ni mallas de sombra aparte (las celdas ya son simples y así importan más rápido).
Los .import se guardan en el repositorio: en otra PC no hace falta volver a correr esto.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comun import RAIZ  # noqa: E402


def main():
    godot = RAIZ / "godot"
    n_tex = n_esc = 0
    for f in list(godot.glob("texturas/*.import")) + list(godot.glob("zonas/*/*.import")) + list(godot.glob("zonas/*/celdas/*.import")):
        s = f.read_text(encoding="utf-8")
        nuevo = s
        if 'importer="texture"' in s:
            nuevo = re.sub(r"^compress/mode=\d", "compress/mode=2", nuevo, flags=re.M)
            nuevo = re.sub(r"^mipmaps/generate=\w+", "mipmaps/generate=true", nuevo, flags=re.M)
            if "normal" in f.name or "nor_gl" in f.name:
                nuevo = re.sub(r"^compress/normal_map=\d", "compress/normal_map=1", nuevo, flags=re.M)
            n_tex += nuevo != s
        elif 'importer="scene"' in s:
            nuevo = re.sub(r"^meshes/create_shadow_meshes=\w+", "meshes/create_shadow_meshes=false", nuevo, flags=re.M)
            if "/celdas/" in f.as_posix():
                nuevo = re.sub(r"^meshes/generate_lods=\w+", "meshes/generate_lods=false", nuevo, flags=re.M)
            n_esc += nuevo != s
        if nuevo != s:
            f.write_text(nuevo, encoding="utf-8")
    print(f"Ajustados: {n_tex} texturas y {n_esc} escenas. Reimporta con: godot --headless --path godot --import")


if __name__ == "__main__":
    main()
