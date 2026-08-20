# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Entry point invoked as the xsecurelock AUTH module (via helpers/auth_matrixrain).

Reads $XSCREENSAVER_WINDOW, draws the SYSTEM FAILURE dialog over the saver on the
middle monitor, and runs the auth loop. Exit status 0 unlocks; anything else keeps
the screen locked.

xsecurelock discards our stderr, so a startup crash would be invisible (the lock
would just show the saver with no dialog). We therefore log any exception to a file
($XDG_RUNTIME_DIR/matrix-rain/auth.log, override with MATRIXRAIN_AUTH_LOG).
"""

import os
import sys
import traceback
from pathlib import Path


def _log_crash(msg: str) -> None:
    path = os.environ.get("MATRIXRAIN_AUTH_LOG")
    if not path:
        from ..text.share import _runtime_dir
        path = _runtime_dir() / "auth.log"
    try:
        with open(path, "a") as f:
            f.write(msg.rstrip() + "\n")
    except OSError:
        pass


def _middle_monitor():
    """(x, y, w, h) of the middle monitor in root coordinates, or None."""
    try:
        from ..xwindow import monitors
        mons = monitors()
    except Exception:
        return None
    if not mons:
        return None
    ordered = sorted(mons, key=lambda m: m.x + m.width / 2)
    m = ordered[len(ordered) // 2]
    return (m.x, m.y, m.width, m.height)


def _placement():
    """Where to draw the dialog.

    Preferred: as a CHILD of the saver window covering the middle monitor. Under a
    compositor (picom) a brand-new top-level window created during the lock may not
    be composited (invisible though X reports it viewable and on top), while the
    saver windows xsecurelock manages ARE composited — so a child of a saver window
    lands in the same visible layer. The saver renderers publish their windows via
    lock.savermap.

    Fallback (no saver registered): a top-level window centered on the middle
    monitor. The unmapped full-screen auth window is never used as parent — mapping
    it would blank the rain.

    Returns (parent_window_or_None, center_rect). center_rect is parent-relative for
    a child, root coords for a top-level.
    """
    import time as _time
    from .savermap import find_covering

    mon = _middle_monitor() or (0, 0, 1920, 1080)
    cx, cy = mon[0] + mon[2] // 2, mon[1] + mon[3] // 2

    # Retry briefly: right after a saver is (re)created there's a window where no
    # live registration covers the point yet. Waiting avoids the invisible top-level
    # fallback on the first lock and after xsecurelock recreates the saver.
    deadline = _time.monotonic() + 1.5
    while True:
        covering = find_covering(cx, cy)
        if covering is not None:
            win, (rx, ry, _rw, _rh) = covering
            # Middle-monitor rect expressed in the saver window's coordinate space.
            return win, (mon[0] - rx, mon[1] - ry, mon[2], mon[3])
        if _time.monotonic() >= deadline:
            return None, mon  # give up -> top-level (last resort)
        _time.sleep(0.05)


def main() -> int:
    win = os.environ.get("XSCREENSAVER_WINDOW")
    if not win:
        return 1
    try:
        from .. import config as config_mod
        from . import authmod
        from .freeze import FreezeWriter

        cfg_path = os.environ.get("MATRIXRAIN_CONFIG")
        cfg = config_mod.load(Path(cfg_path) if cfg_path else None)
        draw_parent, rect = _placement()

        # Open the dialog when the user starts typing; ignore mouse motion.
        wake_on_key = bool(cfg.get("lock.key_to_open", True))
        idle_exit = float(cfg.get("lock.idle_timeout", 45.0))
        return authmod.run(cfg, draw_parent, rect, freeze=FreezeWriter(),
                           wake_on_key=wake_on_key, idle_exit=idle_exit)
    except BaseException:
        _log_crash(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
