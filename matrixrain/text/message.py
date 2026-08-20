# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""One headline (one or two lines) on the grid: reveal -> dwell -> erase.

Meanwhile-style: a flickering scramble head sweeps left-to-right, settled characters
lock in behind it. On a two-line message the sweep finishes line one and flows onto
line two; erasing follows the same path. Lines are centered within the block.
While alive, the message occupies a "pocket" where rain is suppressed.
"""

import random

REVEAL, DWELL, ERASE, DONE = range(4)

# Cell kinds yielded to the texture builder.
TEXT, SCRAMBLE, FADE = "text", "scramble", "fade"


class Message:
    def __init__(self, lines: list[str], row: int, col: int, cfg):
        self.lines = lines
        self.row = row  # top row of the block
        self.col = col  # left column of the block
        self.block_width = max(len(line) for line in lines)
        # Each line is centered within the block.
        self.line_cols = [col + (self.block_width - len(line)) // 2 for line in lines]
        self._starts = []
        total = 0
        for line in lines:
            self._starts.append(total)
            total += len(line)
        self.total = total

        self.state = REVEAL
        self.head = 0.0  # reveal/erase sweep position over the concatenated lines
        self.dwell_left = float(cfg.get("text.dwell", 6.0)) + 0.055 * total
        self.reveal_rate = float(cfg.get("text.reveal_rate", 20.0))
        self.erase_rate = float(cfg.get("text.erase_rate", 40.0))
        self.scramble_width = int(cfg.get("text.scramble_width", 6))

    @property
    def rows(self) -> range:
        return range(self.row, self.row + len(self.lines))

    def tick(self, dt: float) -> bool:
        """Advance; returns True if the visible state changed."""
        if self.state == REVEAL:
            self.head += self.reveal_rate * dt
            if self.head >= self.total + self.scramble_width:
                self.state = DWELL
            return True
        if self.state == DWELL:
            self.dwell_left -= dt
            if self.dwell_left <= 0:
                self.state = ERASE
                self.head = 0.0
                return True
            return False
        if self.state == ERASE:
            self.head += self.erase_rate * dt
            if self.head >= self.total + self.scramble_width:
                self.state = DONE
            return True
        return False

    def _ranges(self):
        """(settled_lo, settled_hi), (head_lo, head_hi), head_kind — in global cells."""
        n, h = self.total, int(self.head)
        if self.state == DWELL:
            return (0, n), (0, 0), SCRAMBLE
        if self.state == REVEAL:
            settled_hi = max(0, min(n, h - self.scramble_width))
            return (0, settled_hi), (settled_hi, min(n, h)), SCRAMBLE
        if self.state == ERASE:
            gone = max(0, min(n, h - self.scramble_width))
            return (min(n, h), n), (gone, min(n, h)), FADE
        return (0, 0), (0, 0), SCRAMBLE

    def cells(self, rain_sequence_length: int):
        """Yield (row, col, kind, glyph_index_or_char) for currently visible cells."""
        (s_lo, s_hi), (h_lo, h_hi), head_kind = self._ranges()
        for k, line in enumerate(self.lines):
            start = self._starts[k]
            row = self.row + k
            line_col = self.line_cols[k]
            for i, ch in enumerate(line):
                if ch == " ":
                    continue
                g = start + i
                if s_lo <= g < s_hi:
                    yield row, line_col + i, TEXT, ch
                elif h_lo <= g < h_hi:
                    yield row, line_col + i, head_kind, random.randrange(rain_sequence_length)

    def occlusion_spans(self):
        """Yield (row, col_start, col_end) exclusive ranges where rain is suppressed."""
        h = int(self.head)
        for k, line in enumerate(self.lines):
            start, length = self._starts[k], len(line)
            row = self.row + k
            line_col = self.line_cols[k]
            if self.state == DWELL:
                yield row, line_col - 1, line_col + length + 1
            elif self.state == REVEAL:
                visible = min(length, h - start)
                if visible > 0:
                    yield row, line_col - 1, line_col + visible + 1
            elif self.state == ERASE:
                gone = max(0, min(length, h - self.scramble_width - start))
                if gone < length:
                    left = line_col - 1 if gone == 0 else line_col + gone
                    yield row, left, line_col + length + 1
