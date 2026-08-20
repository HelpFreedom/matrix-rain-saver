# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Text normalization and line breaking for the glyph grid."""

import re

_WS = re.compile(r"\s+")

# Typography the atlas doesn't have, mapped to what it does.
_REPLACEMENTS = {
    "—": "-", "–": "-", "„": "«", "“": "»", "”": "»",
    "‘": "\"", "’": "\"", "×": "Х", "…": "…",
}


def _clean(text: str, char_map: dict) -> str:
    """Uppercase, map typography, silently drop characters without a glyph
    (emoji included — they simply have no atlas entry), collapse whitespace."""
    text = _WS.sub(" ", text).strip().upper()
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    kept = [ch for ch in text if ch == " " or ch in char_map]
    return _WS.sub(" ", "".join(kept)).strip()


def _trim(text: str, max_length: int) -> str:
    """Word-boundary trim with an ellipsis."""
    if len(text) <= max_length:
        return text
    cut = text.rfind(" ", 0, max_length - 1)
    if cut < max_length // 2:
        cut = max_length - 1
    return text[:cut].rstrip(" .,!?:-") + "…"


def prepare_lines(text: str, char_map: dict, max_length: int, max_lines: int = 2) -> list[str]:
    """Headline -> 1 or 2 display lines, each at most max_length cells.

    A long phrase is broken at the word boundary that balances the two lines best
    (slightly preferring a longer first line). When no boundary yields two lines
    within the limit, we still use TWO lines — the longest word-boundary prefix,
    then the rest trimmed with an ellipsis — never collapsing to a single trimmed
    line (that would silently drop half the phrase).
    """
    text = _clean(text, char_map)
    if not text:
        return []
    if len(text) <= max_length:
        return [text]
    if max_lines < 2:
        return [_trim(text, max_length)]

    best = None
    for i, ch in enumerate(text):
        if ch != " ":
            continue
        first, second = text[:i].rstrip(), text[i + 1:].lstrip()
        if not first or not second or len(first) > max_length or len(second) > max_length:
            continue
        # Balance the lines; break ties toward a longer first line.
        score = (max(len(first), len(second)), 0 if len(first) >= len(second) else 1)
        if best is None or score < best[0]:
            best = (score, [first, second])
    if best:
        return best[1]

    # No balanced break exists (the phrase slightly overflows two lines, or its
    # word boundaries fall badly). Show as much as possible on two lines.
    cut = text.rfind(" ", 0, max_length + 1)
    if cut > 0:
        first = text[:cut].rstrip()
        second = _trim(text[cut + 1:].lstrip(), max_length)
        return [first, second]
    return [_trim(text, max_length)]  # single giant unbreakable word
