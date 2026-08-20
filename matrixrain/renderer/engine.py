# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""The full render pipeline, ported from Rezmason/matrix (regl/WebGL -> moderngl/GL 3.3 core).

Frame graph (non-volumetric):
    intro -> raindrop -> symbol -> effect      (GPGPU ping-pong buffers, one texel per grid cell)
    -> rain render (MSDF glyphs, brightness)   -> primary FBO
    -> bloom (highPass -> blur pyramid -> combine)
    -> palette (primary + bloom -> gradient palette + dither) -> target framebuffer

World space: the glyph grid and the simulation cover the WHOLE multi-monitor bounding
box; each process simulates the full (tiny) grid deterministically from wall-clock time
and renders only its own monitor's crop (uvOffset/uvScale). Streams and headlines are
therefore continuous across monitor borders.

Orientation: "horizontal" (default) transposes the sim in the render pass so the
streams sweep left-to-right, meanwhile-style; "vertical" is the canonical fall.

The textState texture (set via set_text_state) pins glyphs for decoded headlines; zero
texture means pure rain.
"""

import json
import math
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image

from ..config import PROJECT_ROOT
from .buffers import PassFBO, PingPong, make_texture

SHADER_DIR = Path(__file__).parent / "shaders"
PYRAMID_HEIGHT = 5
MSDF_PX_RANGE = 4.0
PALETTE_SIZE = 2048


def _shader(name: str) -> str:
    return (SHADER_DIR / name).read_text()


def _set(prog, name, value):
    """Set a uniform if the shader kept it (moderngl drops unused uniforms)."""
    if name in prog:
        prog[name].value = value


def _build_palette(stops) -> np.ndarray:
    """Gradient stops [pos, r, g, b] -> PALETTE_SIZE x 1 RGBA8 lookup row."""
    stops = sorted(stops, key=lambda s: s[0])
    positions = np.array([s[0] for s in stops], dtype="f4")
    colors = np.array([s[1:4] for s in stops], dtype="f4")
    xs = np.linspace(0.0, 1.0, PALETTE_SIZE)
    out = np.empty((PALETTE_SIZE, 4), dtype="f4")
    for c in range(3):
        out[:, c] = np.interp(xs, positions, colors[:, c])
    out[:, 3] = 1.0
    return (out * 255).astype("u1")


class Engine:
    def __init__(self, ctx: moderngl.Context, size: tuple[int, int], cfg, target=None,
                 world: tuple[int, int] | None = None,
                 viewport: tuple[int, int, int, int] | None = None):
        """size: own window px; world: bounding box of all monitors in px;
        viewport: (x, y, w, h) of this window inside the world (X11 coords, y down)."""
        self.ctx = ctx
        self.cfg = cfg
        self.target = target if target is not None else ctx.screen
        self.tick = 0
        self.horizontal = str(cfg.get("rain.direction", "horizontal")) != "vertical"
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)

        self._load_atlas()
        self._build_programs()
        self._allocate(size, world or size, viewport or (0, 0, *size))

    # --- setup ---

    def _load_atlas(self):
        cfg = self.cfg
        atlas_path = cfg.path("glyphs.atlas")
        meta_path = cfg.path("glyphs.atlas_meta")
        if not atlas_path.is_file():
            # Combined atlas not built yet — fall back to the original matrix glyphs.
            atlas_path = PROJECT_ROOT / "assets" / "matrixcode_msdf.png"
            meta = {"grid": [8, 8]}
        else:
            meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {"grid": [8, 8]}
        self.char_map = meta.get("char_map", {})
        image = Image.open(atlas_path).convert("RGBA")
        self.atlas_size = image.size
        # regl loads textures with flipY: true; replicate so getSymbolUV addresses
        # the same cells (index 0 = top-left cell of the PNG).
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        self.atlas_texture = self.ctx.texture(image.size, 4, image.tobytes())
        self.atlas_texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.atlas_texture.repeat_x = False
        self.atlas_texture.repeat_y = False
        self.atlas_grid = tuple(meta["grid"])
        self.glyph_sequence_length = float(cfg.get("glyphs.rain_sequence_length", 57))

    def _build_programs(self):
        ctx = self.ctx
        vert = _shader("fullscreen.vert.glsl")

        def make(frag_name):
            prog = ctx.program(vertex_shader=vert, fragment_shader=_shader(frag_name))
            vao = ctx.vertex_array(prog, [])
            vao.vertices = 3
            return prog, vao

        self.intro_prog, self.intro_vao = make("intro.frag.glsl")
        self.raindrop_prog, self.raindrop_vao = make("raindrop.frag.glsl")
        self.symbol_prog, self.symbol_vao = make("symbol.frag.glsl")
        self.effect_prog, self.effect_vao = make("effect.frag.glsl")
        self.rain_prog, self.rain_vao = make("rain.frag.glsl")
        self.highpass_prog, self.highpass_vao = make("highpass.frag.glsl")
        self.blur_prog, self.blur_vao = make("blur.frag.glsl")
        self.combine_prog, self.combine_vao = make("combine.frag.glsl")
        self.palette_prog, self.palette_vao = make("palette.frag.glsl")

        palette_data = _build_palette(self.cfg.palette_stops())
        self.palette_texture = self.ctx.texture((PALETTE_SIZE, 1), 4, palette_data.tobytes())
        self.palette_texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.palette_texture.repeat_x = False
        self.palette_texture.repeat_y = False

    def _allocate(self, size, world, viewport):
        cfg = self.cfg
        self.size = size
        self.world = world
        self.viewport_rect = viewport
        cell = int(cfg.get("glyphs.cell_size", 20))
        # World glyph grid (shared by every process; cells are continuous across monitors).
        self.grid_w = max(1, round(world[0] / cell))
        self.grid_h = max(1, round(world[1] / cell))
        # Simulation dims: sim "columns" are the streams. Horizontal streams run along
        # world rows, so the sim is the transposed world grid.
        if self.horizontal:
            self.sim_columns, self.sim_rows = self.grid_h, self.grid_w
        else:
            self.sim_columns, self.sim_rows = self.grid_w, self.grid_h
        sim = (self.sim_columns, self.sim_rows)

        # Screen->world UV mapping (world v=0 is the world BOTTOM edge, GL convention).
        vx, vy, vw, vh = viewport
        ww, wh = world
        self.uv_scale = (vw / ww, vh / wh)
        self.uv_offset = (vx / ww, 1.0 - (vy + vh) / wh)

        self.intro_buf = PingPong(self.ctx, (self.sim_columns, 1))
        self.raindrop_buf = PingPong(self.ctx, sim)
        self.symbol_buf = PingPong(self.ctx, sim)
        self.effect_buf = PingPong(self.ctx, sim)

        self.primary = PassFBO(self.ctx, size)
        bloom_size = float(cfg.get("bloom.size", 0.4))
        self.bloom_enabled = bloom_size > 0 and float(cfg.get("bloom.strength", 0.7)) > 0
        self.highpass_pyramid = []
        self.hblur_pyramid = []
        self.vblur_pyramid = []
        if self.bloom_enabled:
            for i in range(PYRAMID_HEIGHT):
                pw = max(1, math.floor(size[0] * bloom_size / 2**i))
                ph = max(1, math.floor(size[1] * bloom_size / 2**i))
                self.highpass_pyramid.append(PassFBO(self.ctx, (pw, ph)))
                self.hblur_pyramid.append(PassFBO(self.ctx, (pw, ph)))
                self.vblur_pyramid.append(PassFBO(self.ctx, (pw, ph)))
        self.bloom_out = PassFBO(self.ctx, size)
        self.bloom_out.fbo.clear(0.0, 0.0, 0.0, 0.0)

        # Text layer over the WORLD grid: zero until a Message state machine writes it.
        self.text_texture = make_texture(self.ctx, (self.grid_w, self.grid_h), dtype="f2")
        self.text_texture.write(np.zeros((self.grid_h, self.grid_w, 4), dtype="f2").tobytes())
        self.has_text = False

        self._set_static_uniforms()

    def _set_static_uniforms(self):
        cfg = self.cfg
        common = {
            "numColumns": float(self.sim_columns),
            "numRows": float(self.sim_rows),
            "animationSpeed": float(cfg.get("rain.animation_speed", 1.0)),
        }
        rain = {
            "fallSpeed": float(cfg.get("rain.fall_speed", 0.3)),
            "raindropLength": float(cfg.get("rain.raindrop_length", 0.75)),
            "brightnessDecay": float(cfg.get("rain.brightness_decay", 1.0)),
            "cycleSpeed": float(cfg.get("rain.cycle_speed", 0.03)),
            "cycleFrameSkip": float(cfg.get("rain.cycle_frame_skip", 1)),
            "loops": False,
            "skipIntro": bool(cfg.get("rain.skip_intro", False)),
            "glyphSequenceLength": self.glyph_sequence_length,
        }
        for prog in (self.intro_prog, self.raindrop_prog, self.symbol_prog, self.effect_prog):
            for name, value in {**common, **rain}.items():
                _set(prog, name, value)

        _set(self.effect_prog, "hasThunder", False)
        _set(self.effect_prog, "rippleType", -1)
        _set(self.effect_prog, "rippleScale", 30.0)
        _set(self.effect_prog, "rippleSpeed", 0.2)
        _set(self.effect_prog, "rippleThickness", 0.2)
        _set(self.effect_prog, "glyphHeightToWidth", 1.0)

        p = self.rain_prog
        for name, value in common.items():
            _set(p, name, value)
        _set(p, "baseContrast", float(cfg.get("rain.base_contrast", 1.1)))
        _set(p, "baseBrightness", float(cfg.get("rain.base_brightness", -0.5)))
        _set(p, "glyphTextureGridSize", tuple(float(v) for v in self.atlas_grid))
        _set(p, "isolateCursor", True)
        _set(p, "msdfPxRange", MSDF_PX_RANGE)
        _set(p, "glyphMSDFSize", tuple(float(v) for v in self.atlas_size))
        _set(p, "worldGrid", (float(self.grid_w), float(self.grid_h)))
        _set(p, "uvOffset", self.uv_offset)
        _set(p, "uvScale", self.uv_scale)
        _set(p, "horizontal", self.horizontal)
        _set(p, "textBrightness", float(cfg.get("text.brightness", 0.9)))
        _set(p, "scrambleBrightness", float(cfg.get("text.scramble_brightness", 0.55)))
        _set(p, "fadeBrightness", float(cfg.get("text.fade_brightness", 0.3)))

        _set(self.highpass_prog, "highPassThreshold", float(cfg.get("bloom.high_pass_threshold", 0.1)))
        _set(self.combine_prog, "bloomStrength", float(cfg.get("bloom.strength", 0.7)))

        pal = self.palette_prog
        _set(pal, "ditherMagnitude", float(cfg.get("palette.dither_magnitude", 0.05)))
        _set(pal, "backgroundColor", tuple(cfg.get("palette.background_color", [0, 0, 0])))
        _set(pal, "cursorColor", tuple(cfg.get("palette.cursor_color", [0.756, 1.0, 0.46])))
        _set(pal, "cursorIntensity", float(cfg.get("palette.cursor_intensity", 2.0)))
        _set(pal, "textColor", tuple(cfg.get("palette.text_color", [0.85, 0.42, 0.05])))
        _set(pal, "textIntensity", float(cfg.get("palette.text_intensity", 1.0)))

    # --- runtime ---

    def set_text_state(self, data: np.ndarray):
        """Upload the world text layer: (grid_h, grid_w, 4) float16.

        R = glyph index / 255, G = kind level (1.0 settled text, 0.55 scramble head,
        0.25 fading scramble), B = occlusion (1 suppresses rain in the cell).
        Array row 0 is the world's BOTTOM row of cells.
        """
        if data.shape[:2] != (self.grid_h, self.grid_w):
            raise ValueError(f"text state shape {data.shape[:2]} != grid {(self.grid_h, self.grid_w)}")
        self.text_texture.write(data.astype("f2").tobytes())
        self.has_text = True

    def resize(self, size, viewport=None):
        if size == self.size and viewport in (None, self.viewport_rect):
            return
        for obj in (self.intro_buf, self.raindrop_buf, self.symbol_buf, self.effect_buf,
                    self.primary, self.bloom_out,
                    *self.highpass_pyramid, *self.hblur_pyramid, *self.vblur_pyramid):
            obj.release()
        self.text_texture.release()
        self.tick = 0
        self._allocate(size, self.world, viewport or self.viewport_rect)

    def _run(self, prog, vao, fbo, samplers, time, extra=None):
        for unit, (name, texture) in enumerate(samplers.items()):
            texture.use(location=unit)
            _set(prog, name, unit)
        _set(prog, "time", time)
        _set(prog, "tick", float(self.tick))
        for name, value in (extra or {}).items():
            _set(prog, name, value)
        fbo.use()
        vao.render(moderngl.TRIANGLES)

    def render(self, t: float, dt: float):
        ctx = self.ctx
        self.tick += 1

        # GPGPU passes (each writes its front buffer, sampling the previous frame's back).
        self._run(self.intro_prog, self.intro_vao, self.intro_buf.front_fbo,
                  {"previousIntroState": self.intro_buf.back_texture}, t)
        self._run(self.raindrop_prog, self.raindrop_vao, self.raindrop_buf.front_fbo,
                  {"previousRaindropState": self.raindrop_buf.back_texture,
                   "introState": self.intro_buf.front_texture}, t)
        self._run(self.symbol_prog, self.symbol_vao, self.symbol_buf.front_fbo,
                  {"previousSymbolState": self.symbol_buf.back_texture,
                   "raindropState": self.raindrop_buf.front_texture}, t)
        self._run(self.effect_prog, self.effect_vao, self.effect_buf.front_fbo,
                  {"previousEffectState": self.effect_buf.back_texture,
                   "raindropState": self.raindrop_buf.front_texture}, t)

        # Glyph render into the primary FBO.
        self.primary.fbo.clear(0.0, 0.0, 0.0, 1.0)
        self._run(self.rain_prog, self.rain_vao, self.primary.fbo,
                  {"raindropState": self.raindrop_buf.front_texture,
                   "symbolState": self.symbol_buf.front_texture,
                   "effectState": self.effect_buf.front_texture,
                   "glyphMSDF": self.atlas_texture,
                   "textState": self.text_texture}, t,
                  extra={"hasText": self.has_text})

        # Bloom: highPass -> h/v blur per pyramid level -> combine.
        if self.bloom_enabled:
            for i in range(PYRAMID_HEIGHT):
                src = self.primary.texture if i == 0 else self.highpass_pyramid[i - 1].texture
                self._run(self.highpass_prog, self.highpass_vao, self.highpass_pyramid[i].fbo,
                          {"tex": src}, t)
                vw, vh = self.highpass_pyramid[i].size
                # NB: width/height are swapped exactly as in the original bloomPass.js.
                blur_dims = {"width": float(vh), "height": float(vw)}
                self._run(self.blur_prog, self.blur_vao, self.hblur_pyramid[i].fbo,
                          {"tex": self.highpass_pyramid[i].texture}, t,
                          extra={**blur_dims, "direction": (1.0, 0.0)})
                self._run(self.blur_prog, self.blur_vao, self.vblur_pyramid[i].fbo,
                          {"tex": self.hblur_pyramid[i].texture}, t,
                          extra={**blur_dims, "direction": (0.0, 1.0)})
            self._run(self.combine_prog, self.combine_vao, self.bloom_out.fbo,
                      {f"pyr_{i}": self.vblur_pyramid[i].texture for i in range(PYRAMID_HEIGHT)}, t)

        # Palette pass to the target framebuffer.
        for unit, (name, texture) in enumerate(
            {"tex": self.primary.texture, "bloomTex": self.bloom_out.texture,
             "paletteTex": self.palette_texture}.items()
        ):
            texture.use(location=unit)
            _set(self.palette_prog, name, unit)
        _set(self.palette_prog, "time", t)
        self.target.use()
        ctx.viewport = (0, 0, *self.size)
        self.palette_vao.render(moderngl.TRIANGLES)

        # End of frame: all ping-pong buffers trade places.
        for buf in (self.intro_buf, self.raindrop_buf, self.symbol_buf, self.effect_buf):
            buf.swap()
