# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Registry of live saver windows, shared between saver and auth processes.

Under xsecurelock + a compositor (picom), a brand-new top-level window created by
the auth module during the lock is not always picked up by the compositor, so it
stays invisible even though X reports it viewable and on top. The saver windows,
created and managed by xsecurelock, ARE composited (the rain is visible). So the
auth module draws its dialog as a CHILD of a saver window — same composited layer,
guaranteed visible.

Each saver renderer registers its $XSCREENSAVER_WINDOW id and root-space rect in a
per-pid file; the auth module reads them and picks the one covering a target point.
Files are timestamped and ignored when stale, so a crashed saver leaves no ghost.
"""

import json
import os
import time
from pathlib import Path

from ..text.share import _runtime_dir

STALE_AFTER = 5.0
_PREFIX = "saverwin-"


def _dir() -> Path:
    d = _runtime_dir() / "savers"
    d.mkdir(parents=True, exist_ok=True)
    return d


class SaverRegistration:
    def __init__(self, window_id: int, rect):
        self._path = _dir() / f"{_PREFIX}{os.getpid()}.json"
        self._window = window_id
        self._rect = list(rect)
        self._last = 0.0
        self.refresh()

    def refresh(self):
        now = time.monotonic()
        if now - self._last < 1.0:
            return
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"window": self._window, "rect": self._rect,
                                   "ts": time.time()}))
        os.replace(tmp, self._path)
        self._last = now

    def close(self):
        try:
            self._path.unlink()
        except OSError:
            pass


def _window_alive(window_id: int) -> bool:
    """True if the X window still exists (a recreated saver leaves a dead file)."""
    try:
        from Xlib import display, error
    except Exception:
        return True  # can't check — assume alive
    d = display.Display()
    try:
        d.create_resource_object("window", window_id).get_attributes()
        return True
    except error.BadWindow:
        return False
    except Exception:
        return True
    finally:
        d.close()


def find_covering(x: int, y: int):
    """Return (window_id, rect) of the freshest LIVE saver window containing (x, y),
    or None. When the saver is recreated (e.g. on pointer motion under xsecurelock),
    a stale file with a dead window id may linger — we pick the newest registration
    and skip windows that no longer exist, so the dialog never becomes a child of a
    destroyed window (which would make it invisible)."""
    try:
        entries = list(_dir().glob(f"{_PREFIX}*.json"))
    except OSError:
        return None
    now = time.time()
    covering = []
    for path in entries:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        ts = data.get("ts", 0)
        if now - ts > STALE_AFTER:
            continue
        rx, ry, rw, rh = data["rect"]
        if rx <= x < rx + rw and ry <= y < ry + rh:
            covering.append((ts, int(data["window"]), (rx, ry, rw, rh)))
    covering.sort(reverse=True)  # newest registration first
    for _ts, win, rect in covering:
        if _window_alive(win):
            return win, rect
    return None
