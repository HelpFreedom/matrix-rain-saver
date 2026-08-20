# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Standalone supervisor for the plain saver: one renderer process per monitor,
exit on any input.

Mirrors xsecurelock's saver_multiplex model: children draw, the supervisor owns the
display-wide keyboard/pointer grabs and the lifecycle. This is NOT a locker — for a
real lock use bin/matrix-lock (xsecurelock + PAM).
"""

import select
import signal
import subprocess
import sys
import time

from .xwindow import InputWatcher, monitors, world_bbox


def _selected_monitors(cfg):
    all_monitors = monitors()
    if not all_monitors:
        raise SystemExit("no monitors reported by RandR")
    wanted = cfg.get("display.monitors", "all")
    if wanted == "all":
        return all_monitors
    by_name = {m.name: m for m in all_monitors}
    missing = [name for name in wanted if name not in by_name]
    if missing:
        print(f"warning: monitors not found: {', '.join(missing)}", file=sys.stderr)
    selected = [by_name[name] for name in wanted if name in by_name]
    return selected or all_monitors


def run(cfg, timeout=None, config_path=None):
    children = []
    watcher = None
    try:
        selected = _selected_monitors(cfg)
        # One shared world (bbox of ALL monitors, even unselected ones, so the
        # grid stays identical whichever subset is shown) and one time base.
        wx, wy, ww, wh = world_bbox(monitors())
        world = f"{ww}x{wh}+{wx}+{wy}"
        t0 = f"{time.time():.3f}"
        for mon in selected:
            cmd = [sys.executable, "-m", "matrixrain",
                   "--geometry", mon.geometry, "--monitor", mon.name,
                   "--world", world, "--t0", t0]
            if config_path:
                cmd += ["--config", str(config_path)]
            children.append(subprocess.Popen(cmd))

        # Children map their windows, then we take the grabs (retry loop inside).
        time.sleep(0.3)
        try:
            watcher = InputWatcher()
        except RuntimeError as e:
            print(f"warning: {e}; falling back to no-grab mode (exit via SIGTERM)",
                  file=sys.stderr)

        stop = {"flag": False}

        def on_term(signum, frame):
            stop["flag"] = True

        signal.signal(signal.SIGTERM, on_term)
        signal.signal(signal.SIGINT, on_term)

        deadline = time.monotonic() + timeout if timeout is not None else None
        if watcher is not None:
            _wait_for_input(watcher, stop, deadline, children)
        else:
            while not stop["flag"] and (deadline is None or time.monotonic() < deadline):
                if any(c.poll() is not None for c in children):
                    break
                time.sleep(0.2)
    finally:
        for c in children:
            if c.poll() is None:
                c.terminate()
        for c in children:
            try:
                c.wait(timeout=3)
            except subprocess.TimeoutExpired:
                c.kill()
        if watcher is not None:
            watcher.close()


def _wait_for_input(watcher, stop, deadline, children):
    """Block on the X connection until input, timeout, SIGTERM, or child death."""
    from Xlib import X

    d = watcher.d
    origin = None
    while not stop["flag"]:
        if deadline is not None and time.monotonic() >= deadline:
            return
        if any(c.poll() is not None for c in children):
            return
        wait = 0.25
        if deadline is not None:
            wait = min(wait, max(0.0, deadline - time.monotonic()))
        try:
            ready, _, _ = select.select([d.fileno()], [], [], wait)
        except InterruptedError:
            continue
        if not ready:
            continue
        while d.pending_events():
            ev = d.next_event()
            if ev.type in (X.KeyPress, X.ButtonPress):
                return
            if ev.type == X.MotionNotify:
                if origin is None:
                    origin = (ev.root_x, ev.root_y)
                elif abs(ev.root_x - origin[0]) > 10 or abs(ev.root_y - origin[1]) > 10:
                    return
