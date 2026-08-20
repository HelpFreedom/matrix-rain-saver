# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Expand axial skeletons into msdfgen shape descriptions.

Every stroke segment becomes a rectangle (square caps: endpoints extended by half a
stroke), joints are filled by the overlap; msdfgen's -overlap mode unions the contours.
Single-point strokes become enlarged square dots.

Em geometry matches Matrix-Code.ttf: unitsPerEm 1024, stroke 123, cap height 780.
"""

import math

UNITS_PER_EM = 1024
STROKE = 123.0
# 720 (not the matrix glyphs' ~780) leaves ~150 units of headroom above and below
# the cap box so diacritics (Ё dots, Й breve) and descenders (Ц/Щ tails, comma)
# stay inside the 64px atlas cell instead of being clipped at its edge.
CAP_HEIGHT = 720.0
CAP_TOP = (UNITS_PER_EM + CAP_HEIGHT) / 2  # 902 (em y-up)
BASE_WIDTH = 540.0  # letter box width at width factor 1.0
DOT_SCALE = 1.5  # dots (periods etc.) are slightly heavier than the stroke


def _to_em(pt, width):
    x, y = pt
    return (UNITS_PER_EM / 2 + (x - 0.5) * width, CAP_TOP - y * CAP_HEIGHT)


def _segment_contour(p1, p2):
    """Rectangle with square caps around segment p1->p2 (em coords, y-up), CCW."""
    h = STROKE / 2
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        h *= DOT_SCALE
        x, y = p1
        return [(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)]
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux  # left normal
    a = (p1[0] - ux * h, p1[1] - uy * h)
    b = (p2[0] + ux * h, p2[1] + uy * h)
    return [
        (a[0] - nx * h, a[1] - ny * h),
        (b[0] - nx * h, b[1] - ny * h),
        (b[0] + nx * h, b[1] + ny * h),
        (a[0] + nx * h, a[1] + ny * h),
    ]


def glyph_contours(glyph: dict) -> list[list[tuple[float, float]]]:
    width = BASE_WIDTH * glyph.get("w", 1.0)
    contours = []
    for stroke in glyph["strokes"]:
        pts = [_to_em(p, width) for p in stroke]
        if len(pts) == 1:
            contours.append(_segment_contour(pts[0], pts[0]))
        else:
            for p1, p2 in zip(pts, pts[1:]):
                contours.append(_segment_contour(p1, p2))
    return contours


def shape_description(glyph: dict) -> str:
    parts = []
    for contour in glyph_contours(glyph):
        pts = "; ".join(f"{x:.2f}, {y:.2f}" for x, y in contour)
        parts.append("{ " + pts + "; # }")
    return "\n".join(parts)
