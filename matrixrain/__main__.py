# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Entry point.

Modes:
  --standalone                supervisor: one renderer per monitor, exits on any input
  --geometry WxH+X+Y          single renderer window at the given geometry
  --embed-window ID           render into a child of the given window (xsecurelock)

Multi-monitor children also receive --world (the monitors' bounding box) and --t0
(shared wall-clock time base): the simulation is a pure function of world-grid
coordinates and t, so separate processes draw one continuous rain.

Renderer processes handle SIGTERM for clean shutdown; --timeout N is for testing.
"""

import argparse
import math
import os
import re
import signal
import sys
import time


def parse_geometry(s: str) -> tuple[int, int, int, int]:
    m = re.fullmatch(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", s)
    if not m:
        raise argparse.ArgumentTypeError(f"bad geometry {s!r}, expected WxH+X+Y")
    w, h, x, y = (int(g) for g in m.groups())
    return w, h, x, y


def parse_window_id(s: str) -> int:
    return int(s, 0)  # accepts decimal and 0x…


def _coverage_cells(mons, wx, wy, grid_w, grid_h, cell):
    """Monitor rects -> world cell rects, clamped to the grid."""
    rects = []
    for m in mons:
        cx0 = max(0, round((m.x - wx) / cell))
        cy0 = max(0, round((m.y - wy) / cell))
        cx1 = min(grid_w, round((m.x - wx + m.width) / cell))
        cy1 = min(grid_h, round((m.y - wy + m.height) / cell))
        if cx0 < cx1 and cy0 < cy1:
            rects.append((cx0, cy0, cx1, cy1))
    return rects


def run_renderer(cfg, *, geometry=None, embed=None, monitor_name=None, timeout=None,
                 world=None, t0=None):
    import moderngl

    from .glx import GLWindow
    from .renderer.engine import Engine
    from .text.share import TextShare
    from .xwindow import monitors, window_root_position, world_bbox

    if monitor_name:
        cfg = cfg.for_monitor(monitor_name)

    if embed is not None:
        ex, ey, ew, eh = window_root_position(embed)
        win = GLWindow(0, 0, ew, eh, parent=embed, override_redirect=False)
        own_rect = (ex, ey, ew, eh)
        if t0 is None:
            # No launcher under xsecurelock: all children derive the same base from
            # the wall clock (they start within the same 5-minute window).
            t0 = math.floor(time.time() / 300) * 300
    else:
        w, h, x, y = geometry
        win = GLWindow(x, y, w, h, override_redirect=True)
        own_rect = (x, y, w, h)

    shared_world = world is not None or embed is not None
    if world is not None:
        ww, wh, wx, wy = world
    elif embed is not None:
        wx, wy, ww, wh = world_bbox(monitors())
    else:
        # Single-window debug: the window is its own world.
        wx, wy = own_rect[0], own_rect[1]
        ww, wh = own_rect[2], own_rect[3]
    viewport = (own_rect[0] - wx, own_rect[1] - wy, own_rect[2], own_rect[3])

    ctx = moderngl.create_context()
    engine = Engine(ctx, (win.width, win.height), cfg, world=(ww, wh), viewport=viewport)

    cell = int(cfg.get("glyphs.cell_size", 20))
    coverage = (_coverage_cells(monitors(), wx, wy, engine.grid_w, engine.grid_h, cell)
                if shared_world else None)
    text_share = TextShare(cfg, engine.grid_w, engine.grid_h, engine.char_map,
                           int(engine.glyph_sequence_length), coverage)

    running = True
    # When frozen (under the xsecurelock locker), sim time pins to the freeze moment
    # while the frame keeps being re-rendered, so the window repairs itself after the
    # password dialog is unmapped over it.
    paused = {"flag": False}

    def stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    # Under xsecurelock the auth module cannot signal us (no parent/child path), so
    # an embedded saver freezes via the shared flag file. xsecurelock itself may send
    # the saver SIGUSR1 (RESET_ON_AUTH_CLOSE) — ignore it so it isn't misread.
    freeze_poll = None
    saver_reg = None
    if embed is not None:
        from .lock.freeze import is_frozen
        from .lock.savermap import SaverRegistration
        freeze_poll = is_frozen
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        signal.signal(signal.SIGUSR2, signal.SIG_IGN)
        # Publish this saver window so the auth dialog can be drawn as its child
        # (same composited layer -> guaranteed visible under a compositor).
        # Register the actual rain GL window (not the outer $XSCREENSAVER_WINDOW):
        # the auth dialog is then drawn INSIDE it, not as a sibling — otherwise the
        # compositor arbitrarily picks which of the two siblings to show on top.
        saver_reg = SaverRegistration(win.win, own_rect)

    fps = float(cfg.get("display.fps", 60))
    frame_budget = 1.0 / fps if fps > 0 else 0.0
    start_mono = last = time.monotonic()
    pause_offset = 0.0
    pause_started = None  # (wall, mono) at the freeze moment
    try:
        while running:
            now = time.monotonic()
            dt = now - last
            last = now
            if freeze_poll is not None:
                paused["flag"] = freeze_poll()
            if paused["flag"] and pause_started is None:
                pause_started = (time.time(), now)
            elif not paused["flag"] and pause_started is not None:
                pause_offset += time.time() - pause_started[0]
                pause_started = None
            # Shared wall-clock time base keeps separate processes in sync;
            # while frozen, t stays pinned at the freeze moment.
            wall = pause_started[0] if pause_started else time.time()
            mono = pause_started[1] if pause_started else now
            t = (wall - t0 - pause_offset) if t0 is not None else (mono - start_mono - pause_offset)
            if timeout is not None and now - start_mono > timeout:
                break
            resized = win.poll_resize()
            if resized:
                if embed is not None:
                    ex, ey, ew, eh = window_root_position(embed)
                    engine.resize(resized, (ex - wx, ey - wy, resized[0], resized[1]))
                else:
                    engine.resize(resized)
            if not paused["flag"]:
                text_array = text_share.tick(t, dt)
                if text_array is not None:
                    engine.set_text_state(text_array)
            if saver_reg is not None:
                saver_reg.refresh()
            engine.render(t, 0.0 if paused["flag"] else dt)
            win.swap()
            elapsed = time.monotonic() - now
            if frame_budget and elapsed < frame_budget:
                time.sleep(frame_budget - elapsed)
    finally:
        if saver_reg is not None:
            saver_reg.close()
        text_share.close()
        win.close()


def run_standalone(cfg, timeout=None, config_path=None):
    from .launcher import run

    run(cfg, timeout=timeout, config_path=config_path)


def main():
    from . import config as config_mod

    ap = argparse.ArgumentParser(prog="matrixrain")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--standalone", action="store_true", help="cover all monitors, exit on input")
    mode.add_argument("--geometry", type=parse_geometry, help="single window at WxH+X+Y")
    mode.add_argument("--embed-window", type=parse_window_id, help="render into this window (xsecurelock)")
    ap.add_argument("--monitor", help="monitor name for per-monitor config overrides")
    ap.add_argument("--config", type=str, help="path to config.toml (default: ~/.config/matrix-rain/)")
    ap.add_argument("--world", type=parse_geometry, help="world bounding box WxH+X+Y (set by the launcher)")
    ap.add_argument("--t0", type=float, help="shared wall-clock time base (set by the launcher)")
    ap.add_argument("--timeout", type=float, help="exit after N seconds (testing)")
    args = ap.parse_args()

    from pathlib import Path

    cfg = config_mod.load(Path(args.config) if args.config else None)

    for key, value in cfg.get("display.env", {}).items():
        os.environ.setdefault(key, str(value))

    if args.standalone:
        run_standalone(cfg, timeout=args.timeout, config_path=args.config)
    elif args.embed_window is not None:
        run_renderer(cfg, embed=args.embed_window, monitor_name=args.monitor,
                     timeout=args.timeout, world=args.world, t0=args.t0)
    else:
        run_renderer(cfg, geometry=args.geometry, monitor_name=args.monitor,
                     timeout=args.timeout, world=args.world, t0=args.t0)


if __name__ == "__main__":
    main()
