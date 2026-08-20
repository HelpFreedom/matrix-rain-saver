# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Render the atlas glyphs as large bitmaps (CPU MSDF decode) for visual inspection.

Usage: python atlas/preview.py [text]  ->  assets/atlas_preview.png
Without arguments renders the whole generated set.
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCALE = 2  # 64px cell -> 128px preview


def decode_msdf(cell: np.ndarray, scale: int) -> np.ndarray:
    """Median-of-RGB MSDF decode with bilinear upsampling -> alpha 0..255."""
    img = Image.fromarray(cell, "RGB").resize(
        (cell.shape[1] * scale, cell.shape[0] * scale), Image.BILINEAR
    )
    a = np.asarray(img).astype(np.float32) / 255.0
    median = np.median(a, axis=2)
    # Approximate screenPxRange for the preview scale.
    px_range = 4.0 * scale
    alpha = np.clip((median - 0.5) * px_range * 0.5 + 0.5, 0, 1)
    return (alpha * 255).astype(np.uint8)


def main():
    atlas = np.asarray(Image.open(ROOT / "assets" / "atlas_combined.png").convert("RGB"))
    meta = json.loads((ROOT / "assets" / "atlas.json").read_text())
    grid_w = meta["grid"][0]
    char_map = meta["char_map"]

    text = sys.argv[1] if len(sys.argv) > 1 else "".join(char_map)
    chars = [c for c in text if c.upper() in char_map or c in char_map]

    cols = 16
    rows = (len(chars) + cols - 1) // cols
    cell_px = 64 * SCALE
    out = np.zeros((rows * cell_px, cols * cell_px), dtype=np.uint8)
    for i, ch in enumerate(chars):
        index = char_map.get(ch, char_map.get(ch.upper()))
        cx, cy = index % grid_w, index // grid_w
        cell = atlas[cy * 64:(cy + 1) * 64, cx * 64:(cx + 1) * 64]
        ox, oy = (i % cols) * cell_px, (i // cols) * cell_px
        out[oy:oy + cell_px, ox:ox + cell_px] = decode_msdf(cell, SCALE)

    dest = ROOT / "assets" / "atlas_preview.png"
    Image.fromarray(255 - out, "L").save(dest)
    print("preview:", dest)


if __name__ == "__main__":
    main()
