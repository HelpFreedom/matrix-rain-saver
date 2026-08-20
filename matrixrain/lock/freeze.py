# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Freeze flag shared between the auth module and the saver renderers.

Under xsecurelock the saver processes and the auth module are separate programs with
no parent/child signal path, so the auth module signals "freeze the rain" by creating
a flag file that every saver renderer polls. The flag is timestamped and treated as
stale after a few seconds, so a crashed auth module never leaves the rain frozen.
"""

import os
import time
from pathlib import Path

from ..text.share import _runtime_dir

FLAG = "freeze"
STALE_AFTER = 4.0
REFRESH = 1.0


def _path() -> Path:
    return _runtime_dir() / FLAG


class FreezeWriter:
    """Auth-module side: hold the freeze flag while the dialog is open."""

    def __init__(self):
        self._path = _path()
        self._last = 0.0

    def set(self):
        self._touch()

    def refresh(self):
        if time.monotonic() - self._last >= REFRESH:
            self._touch()

    def _touch(self):
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(str(time.time()))
        os.replace(tmp, self._path)
        self._last = time.monotonic()

    def clear(self):
        try:
            self._path.unlink()
        except OSError:
            pass


def is_frozen() -> bool:
    """Saver-renderer side: True while a fresh freeze flag exists."""
    try:
        mtime = _path().stat().st_mtime
    except OSError:
        return False
    return (time.time() - mtime) <= STALE_AFTER
