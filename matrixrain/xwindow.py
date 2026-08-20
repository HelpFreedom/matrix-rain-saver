# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""python-xlib helpers: RandR monitor enumeration and (for the supervisor) input grabs.

The render window itself is created in glx.py via ctypes — python-xlib's Display is a
pure-Python protocol client and cannot be handed to GLX. Mixing the two connections is
fine: XIDs are server-side and global.
"""

import time
from dataclasses import dataclass

from Xlib import X, display
from Xlib.ext import randr


@dataclass(frozen=True)
class Monitor:
    name: str
    x: int
    y: int
    width: int
    height: int

    @property
    def geometry(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


def monitors() -> list[Monitor]:
    d = display.Display()
    try:
        root = d.screen().root
        result = []
        for m in randr.get_monitors(root).monitors:
            name = d.get_atom_name(m.name)
            result.append(Monitor(name, m.x, m.y, m.width_in_pixels, m.height_in_pixels))
        return result
    finally:
        d.close()


def world_bbox(mons: list[Monitor]) -> tuple[int, int, int, int]:
    """Bounding box (x, y, w, h) of all monitors — the shared rain's world."""
    x0 = min(m.x for m in mons)
    y0 = min(m.y for m in mons)
    x1 = max(m.x + m.width for m in mons)
    y1 = max(m.y + m.height for m in mons)
    return x0, y0, x1 - x0, y1 - y0


def window_root_position(window_id: int) -> tuple[int, int, int, int]:
    """Absolute (x, y, w, h) of an arbitrary window in root coordinates."""
    d = display.Display()
    try:
        win = d.create_resource_object("window", window_id)
        geo = win.get_geometry()
        translated = d.screen().root.translate_coords(win, 0, 0)
        return translated.x, translated.y, geo.width, geo.height
    finally:
        d.close()


class InputWatcher:
    """Supervisor-side: grab keyboard+pointer display-wide, report the first input event.

    Grabs can fail while another client holds them (e.g. a popup) — retried for a while,
    like every screen locker does.
    """

    def __init__(self, retries: int = 25, retry_delay: float = 0.1):
        self.d = display.Display()
        self.root = self.d.screen().root
        self._grab(retries, retry_delay)

    def _grab(self, retries, retry_delay):
        for attempt in range(retries):
            kb = self.root.grab_keyboard(True, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
            ptr = self.root.grab_pointer(
                True,
                X.ButtonPressMask | X.PointerMotionMask,
                X.GrabModeAsync, X.GrabModeAsync, 0, 0, X.CurrentTime,
            )
            self.d.sync()
            if kb == X.GrabSuccess and ptr == X.GrabSuccess:
                return
            self.d.ungrab_keyboard(X.CurrentTime)
            self.d.ungrab_pointer(X.CurrentTime)
            time.sleep(retry_delay)
        raise RuntimeError("could not grab keyboard/pointer (another client holds a grab)")

    def wait_for_input(self, ignore_motion_pixels: int = 10) -> None:
        """Block until a key press, button press, or noticeable pointer motion."""
        origin = None
        while True:
            ev = self.d.next_event()
            if ev.type in (X.KeyPress, X.ButtonPress):
                return
            if ev.type == X.MotionNotify:
                if origin is None:
                    origin = (ev.root_x, ev.root_y)
                elif (
                    abs(ev.root_x - origin[0]) > ignore_motion_pixels
                    or abs(ev.root_y - origin[1]) > ignore_motion_pixels
                ):
                    return

    def close(self):
        self.d.ungrab_keyboard(X.CurrentTime)
        self.d.ungrab_pointer(X.CurrentTime)
        self.d.sync()
        self.d.close()
