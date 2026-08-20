# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Shared text state across renderer processes.

Exactly one process per world grid becomes the text master (non-blocking flock);
it runs the TextLayer and publishes the texture array to a runtime file (atomic
rename). Replicas poll the file's mtime and upload the array when it changes, so a
headline spanning two monitors is pixel-identical in both processes.

Works the same under our standalone launcher and under xsecurelock's saver_multiplex —
whichever child wins the lock computes the text. If the master dies, the file goes
stale and a replica takes over. The master touches the file every second as a
heartbeat even when nothing changed.
"""

import fcntl
import os
import time
from pathlib import Path

import numpy as np

from .textstate import TextLayer

HEARTBEAT = 1.0
STALE_AFTER = 3.0


def _runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        path = Path(base) / "matrix-rain"
    else:
        path = Path(f"/tmp/matrix-rain-{os.getuid()}")
    path.mkdir(parents=True, exist_ok=True)
    return path


class TextShare:
    def __init__(self, cfg, grid_w: int, grid_h: int, char_map: dict,
                 rain_sequence_length: int, coverage=None):
        self._layer_args = (cfg, grid_w, grid_h, char_map, rain_sequence_length, coverage)
        self.shape = (grid_h, grid_w, 4)
        base = _runtime_dir()
        self.data_path = base / f"textstate-{grid_w}x{grid_h}.npy"
        self.lock_path = base / f"textstate-{grid_w}x{grid_h}.lock"
        self._lock_fd = None
        self._layer = None
        self._mtime = None
        self._heartbeat_in = 0.0
        self._try_become_master()

    @property
    def is_master(self) -> bool:
        return self._layer is not None

    def _try_become_master(self) -> bool:
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._lock_fd = fd  # held for the process lifetime
        self._layer = TextLayer(*self._layer_args)
        # Immediately overwrite whatever a PREVIOUS session left in the file —
        # otherwise replicas would show last session's phrases on a blank screen.
        self._publish(np.zeros(self.shape, dtype="f2"))
        return True

    def _publish(self, arr: np.ndarray):
        tmp = self.data_path.with_suffix(".tmp.npy")
        np.save(tmp, arr)
        os.replace(tmp, self.data_path)
        self._heartbeat_in = HEARTBEAT

    def tick(self, t: float, dt: float):
        """Returns the texture array when it changed, else None."""
        if self._layer is not None:
            arr = self._layer.tick(t, dt)
            if arr is not None:
                self._publish(arr)
                return arr
            self._heartbeat_in -= dt
            if self._heartbeat_in <= 0 and self.data_path.exists():
                os.utime(self.data_path)
                self._heartbeat_in = HEARTBEAT
            return None

        # Replica: follow the published file. A file with no fresh heartbeat is a
        # leftover of a previous session (or a dead master) — never display it.
        try:
            mtime = self.data_path.stat().st_mtime_ns
        except OSError:
            mtime = None
        stale = mtime is None or (time.time() - mtime / 1e9) > STALE_AFTER
        if not stale and mtime != self._mtime:
            self._mtime = mtime
            try:
                arr = np.load(self.data_path)
            except (OSError, ValueError):
                return None
            if arr.shape == self.shape:
                return arr
            return None
        if stale and self._try_become_master():
            return self._layer.tick(t, dt)
        return None

    def close(self):
        # NB: never unlink the lock file — a fresh process would lock a new inode
        # while a straggler still holds the old one, giving two masters.
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
