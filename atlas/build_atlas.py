# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Build the combined MSDF atlas: original matrix glyphs + generated text glyphs.

Layout: the original 512x512 matrixcode_msdf.png (8x8 grid, 64px cells, indices 0..63)
is extended downward; generated glyphs occupy indices 64+ in the same 8-wide grid.
The rain only ever draws indices < glyphSequenceLength (57), so it never reaches the
text glyphs; the text layer addresses them directly.

Outputs:
  assets/atlas_combined.png
  assets/atlas.json   {"grid": [8, rows], "char_map": {char: index}, "base_count": 64}
"""

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from skeletons import ALIASES, GLYPH_ORDER, GLYPHS  # noqa: E402
from stroke_expand import UNITS_PER_EM, shape_description  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MSDFGEN = ROOT / "build" / "msdfgen" / "bin" / "msdfgen"
BASE_ATLAS = ROOT / "assets" / "matrixcode_msdf.png"
OUT_PNG = ROOT / "assets" / "atlas_combined.png"
OUT_META = ROOT / "assets" / "atlas.json"

CELL = 64
GRID_W = 8
BASE_COUNT = 64
PX_RANGE = 4


def render_glyph(name: str, workdir: Path) -> Image.Image:
    desc = shape_description(GLYPHS[name])
    desc_file = workdir / "glyph.txt"
    out_file = workdir / "glyph.bmp"
    desc_file.write_text(desc)
    scale = CELL / UNITS_PER_EM
    subprocess.run(
        [
            str(MSDFGEN), "msdf",
            "-shapedesc", str(desc_file),
            "-o", str(out_file),
            "-size", str(CELL), str(CELL),
            "-pxrange", str(PX_RANGE),
            "-scale", f"{scale}",
            "-translate", "0", "0",
            "-overlap",
        ],
        check=True,
        capture_output=True,
    )
    return Image.open(out_file).convert("RGB")


def main():
    if not MSDFGEN.is_file():
        sys.exit(f"msdfgen not found at {MSDFGEN} — run install.sh first")
    if not BASE_ATLAS.is_file():
        sys.exit(f"{BASE_ATLAS} missing — run atlas/fetch_assets.sh first")

    total = BASE_COUNT + len(GLYPH_ORDER)
    grid_h = math.ceil(total / GRID_W)
    atlas = Image.new("RGB", (GRID_W * CELL, grid_h * CELL), (0, 0, 0))
    atlas.paste(Image.open(BASE_ATLAS).convert("RGB"), (0, 0))

    char_map = {}
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for i, ch in enumerate(GLYPH_ORDER):
            index = BASE_COUNT + i
            # msdfgen's BMP is bottom-up; Pillow already decodes it top-down upright.
            cell_img = render_glyph(ch, workdir)
            x = (index % GRID_W) * CELL
            y = (index // GRID_W) * CELL
            atlas.paste(cell_img, (x, y))
            char_map[ch] = index

    for latin, cyr in ALIASES.items():
        char_map[latin] = char_map[cyr]

    atlas.save(OUT_PNG)
    OUT_META.write_text(json.dumps(
        {"grid": [GRID_W, grid_h], "char_map": char_map, "base_count": BASE_COUNT},
        ensure_ascii=False, indent=1,
    ))
    print(f"atlas: {OUT_PNG} ({atlas.size[0]}x{atlas.size[1]}, {len(GLYPH_ORDER)} generated glyphs)")


if __name__ == "__main__":
    main()
