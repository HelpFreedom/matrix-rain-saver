# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""TextLayer: turns Message state machines into the world-grid textState texture.

Texture layout (grid_h x grid_w x RGBA, float16), row 0 = world BOTTOM row:
  R: glyph index / 255
  G: kind level — 1.0 settled text, 0.55 scramble head, 0.25 fading scramble
  B: occlusion — 1.0 suppresses rain inside the message's pocket

Placement: a message lies entirely inside ONE monitor's rectangle — physically
misaligned monitors would visually break a phrase crossing a border — and phrases
never spawn before the intro rain has covered the field.
"""

import random

import numpy as np

from .feed import Feed
from .layout import prepare_lines
from .message import DONE, DWELL, FADE, SCRAMBLE, TEXT, Message

KIND_LEVEL = {TEXT: 1.0, SCRAMBLE: 0.55, FADE: 0.25}
SCRAMBLE_FPS = 12.0  # how often flicker cells re-randomize


class TextLayer:
    def __init__(self, cfg, grid_w: int, grid_h: int, char_map: dict,
                 rain_sequence_length: int, coverage=None):
        """coverage: monitor rects in world CELL coords [(cx0, cy0, cx1, cy1)), rows top-down."""
        self.cfg = cfg
        self.cols = grid_w
        self.rows = grid_h
        self.char_map = char_map
        self.rain_len = max(1, int(rain_sequence_length))
        self.feed = Feed(cfg)
        self.messages: list[Message] = []
        self.max_concurrent = int(cfg.get("text.max_concurrent", 2))
        self.interval = (float(cfg.get("text.interval_min", 4.0)),
                         float(cfg.get("text.interval_max", 10.0)))
        self.max_length = int(cfg.get("text.max_length", 72))
        self._spawn_in = random.uniform(1.0, self.interval[1] / 2)
        self._scramble_in = 0.0
        self._array = np.zeros((grid_h, grid_w, 4), dtype="f2")
        # Messages stay inside ONE monitor's rect: physically misaligned monitors
        # would visually break a phrase that crosses a border.
        self._rects = coverage or [(0, 0, grid_w, grid_h)]
        self._skip_intro = bool(cfg.get("rain.skip_intro", False))
        self._horizontal = str(cfg.get("rain.direction", "horizontal")) != "vertical"
        self._fall_speed = max(1e-3, float(cfg.get("rain.fall_speed", 0.3)))
        self._aspeed = max(1e-3, float(cfg.get("rain.animation_speed", 1.0)))

    # --- placement ---

    def _activation_time(self, row: int, col: int, length: int) -> float:
        """Earliest sim time t at which the intro rain has certainly drawn every
        cell of a message at (row, col..col+length) — phrases must be drawn BY the
        rain, never appear on a blank screen.

        From intro.frag: a cell activates once (t*aspeed + offset) * fallSpeed
        / simRows * 100 >= cellsFromStreamStart / simRows, with the per-stream
        offset as low as -8.5 (random*-4 plus the sine dip -2.5..-4.5).
        """
        if self._skip_intro:
            return 0.0
        cells = (col + length) if self._horizontal else (row + 1)
        return (cells / (100.0 * self._fall_speed) + 8.5) / self._aspeed + 0.5

    def _place(self, t: float, block_w: int, n_lines: int):
        """Pick the top-left (row, col) of the block: 2-cell side margins, entirely
        inside one monitor rect, only where the intro rain has already passed."""
        need = block_w + 4
        candidates = [r for r in self._rects
                      if r[2] - r[0] >= need and r[3] - r[1] >= n_lines + 2]
        if not candidates:
            return None
        weights = [(r[2] - r[0]) * (r[3] - r[1]) for r in candidates]
        occupied = [(m.row, m.row + len(m.lines) - 1) for m in self.messages]
        for _ in range(32):
            cx0, cy0, cx1, cy1 = random.choices(candidates, weights=weights)[0]
            margin_rows = max(1, (cy1 - cy0) // 12)
            if cy1 - margin_rows - n_lines < cy0 + margin_rows:
                continue
            row = random.randrange(cy0 + margin_rows, cy1 - margin_rows - n_lines + 1)
            # Keep 2 clear rows between message blocks.
            if any(row - 2 <= hi and row + n_lines + 1 >= lo for lo, hi in occupied):
                continue
            col = random.randrange(cx0 + 2, cx1 - block_w - 2 + 1)
            if t < self._activation_time(row + n_lines - 1, col, block_w):
                continue
            return row, col
        return None

    def _spawn(self, t: float):
        widest = max((r[2] - r[0] for r in self._rects), default=0)
        lines = prepare_lines(self.feed.next(), self.char_map,
                              min(self.max_length, widest - 6))
        if not lines:
            return
        block_w = max(len(line) for line in lines)
        placed = self._place(t, block_w, len(lines))
        if placed is None:
            return
        row, col = placed
        self.messages.append(Message(lines, row, col, self.cfg))

    # --- per-frame update ---

    def tick(self, t: float, dt: float):
        """Advance to sim time t; returns the texture array when it changed, else None."""
        dirty = False

        self._spawn_in -= dt
        if self._spawn_in <= 0 and len(self.messages) < self.max_concurrent:
            self._spawn(t)  # no-op while the intro rain hasn't drawn a spot yet
            self._spawn_in = random.uniform(*self.interval)
            dirty = True

        for m in self.messages:
            if m.tick(dt):
                dirty = True
        self.messages = [m for m in self.messages if m.state != DONE]

        if any(m.state != DWELL for m in self.messages):
            self._scramble_in -= dt
            if self._scramble_in <= 0:
                self._scramble_in = 1.0 / SCRAMBLE_FPS
                dirty = True

        if not dirty:
            return None

        arr = self._array
        arr[:] = 0
        for m in self.messages:
            for row, a, b in m.occlusion_spans():
                if not (0 <= row < self.rows):
                    continue
                a, b = max(0, a), min(self.cols, b)
                if a < b:
                    arr[self.rows - 1 - row, a:b, 2] = 1.0  # array row 0 = world bottom
            for row, col, kind, value in m.cells(self.rain_len):
                if not (0 <= row < self.rows and 0 <= col < self.cols):
                    continue
                if kind == TEXT:
                    index = self.char_map.get(value)
                    if index is None:
                        continue
                else:
                    index = value
                arr[self.rows - 1 - row, col, 0] = index / 255.0
                arr[self.rows - 1 - row, col, 1] = KIND_LEVEL[kind]
        return arr
