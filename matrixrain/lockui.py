# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""The lock-screen dialog: the film's SYSTEM FAILURE box.

A thin near-white border tight around glowing green "SYSTEM FAILURE", the password
input (masked with random matrix glyphs) beneath it — nothing else. The glow is the
same bloom pipeline the rain uses (highPass -> blur pyramid -> combine), rendered
over a small override-redirect window so the frozen rain stays visible around it.
A wrong password flashes the whole box red for a moment.
"""

import json
import random
import time
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image

from .config import PROJECT_ROOT
from .glx import GLWindow
from .renderer.buffers import PassFBO

SHADER_DIR = Path(__file__).parent / "renderer" / "shaders"
MSDF_PX_RANGE = 4.0
PYRAMID_HEIGHT = 5
BLOOM_SIZE = 0.5
BLOOM_STRENGTH = 0.9

TITLE = "SYSTEM FAILURE"
TITLE_CELL = 44
TITLE_SPACING = 1.15
INPUT_CELL = 30
MAX_MASK = 16
ERROR_SECONDS = 1.2

FRAME_INSET = 60    # window edge -> outline: room for the glow to fade out softly
PAD = 104           # window edge -> content (box)
BOX_PAD_X = 34      # border-to-text padding inside the box
BOX_PAD_Y = 22
BORDER_PX = 3.0
INPUT_GAP = 46      # box bottom -> input row center
FRAME_PX = 2.5

TEXT_GREEN = (0.55, 1.0, 0.6)
FRAME_BRIGHT = (0.82, 1.0, 0.86)  # like the letters at the peak of their glow
BORDER_WHITE = (0.92, 1.0, 0.94)
MASK_GREEN = (0.35, 1.0, 0.45)
CURSOR = (0.756, 1.0, 0.46)
ERROR_RED = (1.0, 0.2, 0.1)

_TEXT_VERT = """
#version 330 core
in vec2 aPos;   // pixels, y down
in vec2 aUV;    // atlas uv
uniform vec2 resolution;
out vec2 vUV;
void main() {
    vUV = aUV;
    gl_Position = vec4(aPos.x * 2.0 / resolution.x - 1.0,
                       1.0 - aPos.y * 2.0 / resolution.y, 0.0, 1.0);
}
"""

_TEXT_FRAG = """
#version 330 core
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D glyphMSDF;
uniform vec2 glyphMSDFSize;
uniform float msdfPxRange;
uniform vec3 color;
uniform bool solid;   // plain rect (border, cursor) instead of a glyph

float median3(vec3 i) {
    return max(min(i.r, i.g), min(max(i.r, i.g), i.b));
}

void main() {
    float alpha = 1.0;
    if (!solid) {
        vec2 unitRange = vec2(msdfPxRange) / glyphMSDFSize;
        vec2 screenTexSize = vec2(1.0) / fwidth(vUV);
        float screenPxRange = max(0.5 * dot(unitRange, screenTexSize), 1.0);
        float sd = median3(texture(glyphMSDF, vUV).rgb);
        alpha = clamp(screenPxRange * (sd - 0.5) + 0.5, 0.0, 1.0);
    }
    fragColor = vec4(color * alpha, alpha);
}
"""

_FINAL_FRAG = """
#version 330 core
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D scene;
uniform sampler2D bloomTex;
uniform bool opaqueBg;
void main() {
    vec4 s = texture(scene, vUV);   // premultiplied (blended over transparent black)
    vec3 glow = texture(bloomTex, vUV).rgb;
    // ARGB window under a compositor: color > alpha acts additively, so the glow
    // lays softly onto whatever is behind the window (the frozen rain).
    fragColor = vec4(s.rgb + glow, opaqueBg ? 1.0 : s.a);
}
"""


def _shader(name):
    return (SHADER_DIR / name).read_text()


def dialog_size() -> tuple[int, int]:
    """(width, height) in px of the dialog window — for placement decisions."""
    title_w = TITLE_CELL * TITLE_SPACING * (len(TITLE) - 1) + TITLE_CELL
    box_w = title_w + 2 * BOX_PAD_X
    box_h = TITLE_CELL + 2 * BOX_PAD_Y
    width = int(box_w + 2 * PAD)
    height = int(PAD + box_h + INPUT_GAP + INPUT_CELL + PAD)
    return width, height


class LockDialog:
    def __init__(self, cfg, center_rect, parent=None):
        """center_rect: (x, y, w, h) rect to center the dialog inside (screen
        coords). parent: window id to embed under ($XSCREENSAVER_WINDOW), or None
        for a standalone override-redirect window."""
        # Window geometry derives from the title box.
        title_w = TITLE_CELL * TITLE_SPACING * (len(TITLE) - 1) + TITLE_CELL
        self.box_w = title_w + 2 * BOX_PAD_X
        self.box_h = TITLE_CELL + 2 * BOX_PAD_Y
        self.width = int(self.box_w + 2 * PAD)
        self.height = int(PAD + self.box_h + INPUT_GAP + INPUT_CELL + PAD)
        self.box_x = PAD
        self.box_y = PAD
        self.input_cy = PAD + self.box_h + INPUT_GAP

        cx, cy, cw, ch = center_rect
        x = cx + (cw - self.width) // 2
        y = cy + (ch - self.height) // 2
        # Opaque window: solid black background, the glow fades out inside it.
        self.win = GLWindow(x, y, self.width, self.height, parent=parent,
                            override_redirect=True, title="matrix-rain-lock",
                            argb=False, fill_parent=False)
        self.ctx = moderngl.create_context()

        self._load_atlas(cfg)
        self._build_pipeline()

        self.rain_len = int(cfg.get("glyphs.rain_sequence_length", 57))
        self._mask: list[int] = []
        self._error_until = 0.0
        self._t0 = time.monotonic()

    def _load_atlas(self, cfg):
        atlas_path = cfg.path("glyphs.atlas")
        meta_path = cfg.path("glyphs.atlas_meta")
        if not atlas_path.is_file():
            atlas_path = PROJECT_ROOT / "assets" / "matrixcode_msdf.png"
        meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {"grid": [8, 8]}
        self.char_map = meta.get("char_map", {})
        self.atlas_grid = tuple(meta["grid"])
        image = Image.open(atlas_path).convert("RGBA").transpose(Image.FLIP_TOP_BOTTOM)
        self.atlas_size = image.size
        self.atlas_texture = self.ctx.texture(image.size, 4, image.tobytes())
        self.atlas_texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.atlas_texture.repeat_x = self.atlas_texture.repeat_y = False

    def _build_pipeline(self):
        ctx = self.ctx
        size = (self.width, self.height)
        fullscreen_vert = _shader("fullscreen.vert.glsl")

        self.text_prog = ctx.program(vertex_shader=_TEXT_VERT, fragment_shader=_TEXT_FRAG)
        self.text_prog["resolution"].value = (float(self.width), float(self.height))
        self.text_prog["glyphMSDFSize"].value = tuple(float(v) for v in self.atlas_size)
        self.text_prog["msdfPxRange"].value = MSDF_PX_RANGE
        self._text_buffer = ctx.buffer(reserve=64 * 6 * 16)
        self._text_vao = ctx.vertex_array(
            self.text_prog, [(self._text_buffer, "2f 2f", "aPos", "aUV")]
        )

        def make(frag_name):
            prog = ctx.program(vertex_shader=fullscreen_vert, fragment_shader=_shader(frag_name))
            vao = ctx.vertex_array(prog, [])
            vao.vertices = 3
            return prog, vao

        self.scene = PassFBO(ctx, size)
        self.highpass_prog, self.highpass_vao = make("highpass.frag.glsl")
        self.blur_prog, self.blur_vao = make("blur.frag.glsl")
        self.combine_prog, self.combine_vao = make("combine.frag.glsl")
        self.highpass_prog["highPassThreshold"].value = 0.15
        self.combine_prog["bloomStrength"].value = BLOOM_STRENGTH

        self.pyramid = []
        for i in range(PYRAMID_HEIGHT):
            pw = max(1, int(self.width * BLOOM_SIZE / 2**i))
            ph = max(1, int(self.height * BLOOM_SIZE / 2**i))
            self.pyramid.append((PassFBO(ctx, (pw, ph)), PassFBO(ctx, (pw, ph)),
                                 PassFBO(ctx, (pw, ph))))
        self.bloom_out = PassFBO(ctx, size)

        self.final_prog = ctx.program(vertex_shader=fullscreen_vert, fragment_shader=_FINAL_FRAG)
        self.final_vao = ctx.vertex_array(self.final_prog, [])
        self.final_vao.vertices = 3

    # --- input mask ---

    def add_char(self):
        if len(self._mask) < MAX_MASK:
            self._mask.append(random.randrange(self.rain_len))

    def backspace(self):
        if self._mask:
            self._mask.pop()

    def clear(self):
        self._mask.clear()

    def set_error(self):
        self._error_until = time.monotonic() + ERROR_SECONDS
        self.clear()

    @property
    def in_error(self) -> bool:
        return time.monotonic() < self._error_until

    # --- drawing ---

    def _glyph_uv(self, index):
        gw, gh = self.atlas_grid
        cx = index % gw
        cy_flipped = gh - 1 - index // gw
        u0, v0 = cx / gw, cy_flipped / gh
        return u0, v0, u0 + 1 / gw, v0 + 1 / gh

    def _draw_items(self, items, color, solid=False):
        """items: (x, y, w, h, glyph_index)."""
        if not items:
            return
        verts = np.empty((len(items) * 6, 4), dtype="f4")
        for n, (x, y, w, h, index) in enumerate(items):
            u0, v0, u1, v1 = self._glyph_uv(index)
            verts[n * 6:n * 6 + 6] = [
                (x, y, u0, v1), (x + w, y, u1, v1), (x + w, y + h, u1, v0),
                (x, y, u0, v1), (x + w, y + h, u1, v0), (x, y + h, u0, v0),
            ]
        self._text_buffer.orphan(verts.nbytes)
        self._text_buffer.write(verts.tobytes())
        self.text_prog["color"].value = color
        self.text_prog["solid"].value = solid
        self.atlas_texture.use(location=0)
        self.text_prog["glyphMSDF"].value = 0
        self._text_vao.render(moderngl.TRIANGLES, vertices=len(items) * 6)

    @staticmethod
    def _rect_outline(x, y, w, h, b):
        return [
            (x - b, y - b, w + 2 * b, b, 0),          # top
            (x - b, y + h, w + 2 * b, b, 0),          # bottom
            (x - b, y, b, h, 0),                      # left
            (x + w, y, b, h, 0),                      # right
        ]

    def _border_items(self):
        return self._rect_outline(self.box_x, self.box_y, self.box_w, self.box_h, BORDER_PX)

    def _frame_items(self):
        i = FRAME_INSET
        return self._rect_outline(i, i, self.width - 2 * i, self.height - 2 * i, FRAME_PX)

    def _title_items(self):
        step = TITLE_CELL * TITLE_SPACING
        x = self.box_x + BOX_PAD_X
        y = self.box_y + BOX_PAD_Y
        items = []
        for ch in TITLE:
            if ch != " ":
                index = self.char_map.get(ch)
                if index is not None:
                    items.append((x, y, TITLE_CELL, TITLE_CELL, index))
            x += step
        return items

    def render(self):
        ctx = self.ctx
        t = time.monotonic() - self._t0
        error = self.in_error
        text_color = ERROR_RED if error else TEXT_GREEN
        border_color = ERROR_RED if error else BORDER_WHITE
        mask_color = ERROR_RED if error else MASK_GREEN

        # Scene over transparent black; alpha accumulates coverage so the window
        # stays see-through everywhere except the drawn elements.
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA,
                          moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
        self.scene.fbo.use()
        self.scene.fbo.clear(0.0, 0.0, 0.0, 0.0)
        # Opaque black fill inside the title box (the film look) for readability.
        self._draw_items([(self.box_x, self.box_y, self.box_w, self.box_h, 0)],
                         (0.0, 0.0, 0.0), solid=True)
        self._draw_items(self._frame_items(), ERROR_RED if error else FRAME_BRIGHT, solid=True)
        self._draw_items(self._border_items(), border_color, solid=True)
        self._draw_items(self._title_items(), text_color)

        step = INPUT_CELL * 1.15
        width = step * len(self._mask) + INPUT_CELL * 0.45
        x = (self.width - width) / 2
        y = self.input_cy - INPUT_CELL / 2
        self._draw_items(
            [(x + i * step, y, INPUT_CELL, INPUT_CELL, g) for i, g in enumerate(self._mask)],
            mask_color)
        if not error and int(t * 2.4) % 2 == 0:
            cx = x + len(self._mask) * step
            self._draw_items([(cx, y, INPUT_CELL * 0.45, INPUT_CELL, 0)], CURSOR, solid=True)
        ctx.disable(moderngl.BLEND)

        # The same glow the rain has: highPass -> blur pyramid -> combine.
        for i, (hp, hb, vb) in enumerate(self.pyramid):
            src = self.scene.texture if i == 0 else self.pyramid[i - 1][0].texture
            src.use(location=0)
            self.highpass_prog["tex"].value = 0
            hp.fbo.use()
            self.highpass_vao.render(moderngl.TRIANGLES)
            vw, vh = hp.size
            for prog_dir, src_fbo, dst in ((1.0, hp, hb), (0.0, hb, vb)):
                src_fbo.texture.use(location=0)
                self.blur_prog["tex"].value = 0
                # width/height swapped exactly as in the original bloomPass.js.
                self.blur_prog["width"].value = float(vh)
                self.blur_prog["height"].value = float(vw)
                self.blur_prog["direction"].value = (prog_dir, 1.0 - prog_dir)
                dst.fbo.use()
                self.blur_vao.render(moderngl.TRIANGLES)
        for i, (_, _, vb) in enumerate(self.pyramid):
            vb.texture.use(location=i)
            self.combine_prog[f"pyr_{i}"].value = i
        self.bloom_out.fbo.use()
        self.combine_vao.render(moderngl.TRIANGLES)

        # Composite to the (ARGB) window.
        self.scene.texture.use(location=0)
        self.bloom_out.texture.use(location=1)
        self.final_prog["scene"].value = 0
        self.final_prog["bloomTex"].value = 1
        self.final_prog["opaqueBg"].value = not self.win.argb
        ctx.screen.use()
        ctx.viewport = (0, 0, self.width, self.height)
        self.final_vao.render(moderngl.TRIANGLES)
        self.win.swap()

    def raise_window(self):
        """Keep the dialog above the frozen saver / obscurer windows."""
        self.win.raise_()

    @property
    def window_id(self) -> int:
        return self.win.win

    def close(self):
        self.win.close()
