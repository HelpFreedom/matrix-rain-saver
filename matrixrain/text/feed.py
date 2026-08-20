# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Headline source: titles from a local SQLite database.

Reads distinct titles whose timestamp column falls within the last N hours,
re-running the query periodically so a saver running for hours keeps showing fresh
titles. The database is opened read-only and never written.

The database is entirely optional and is NOT part of this project: point
`[feed] db` at any SQLite file that has a title column and a timestamp column
(configure their names in `[feed]`). With no database configured — or when it is
empty, missing or unreadable — the configured fallback phrases are shown instead,
so the saver always works out of the box.

Used only by the text-master process (see text.share).
"""

import random
import re
import sqlite3
import time
from pathlib import Path

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RETRY_AFTER_ERROR = 60.0


class Feed:
    def __init__(self, cfg):
        # An empty feed.db means "no database" — run on fallback phrases only.
        configured = str(cfg.get("feed.db", "") or "").strip()
        self.db_path: Path | None = Path(cfg.path("feed.db")) if configured else None
        self.window_hours = float(cfg.get("feed.window_hours", 20))
        self.refresh_seconds = float(cfg.get("feed.refresh_seconds", 3600))
        self.table = str(cfg.get("feed.db_table", "posts"))
        self.title_col = str(cfg.get("feed.db_title_column", "title"))
        self.time_col = str(cfg.get("feed.db_time_column", "created_at"))
        for ident in (self.table, self.title_col, self.time_col):
            if not _IDENT.match(ident):
                raise SystemExit(f"config error: bad SQL identifier {ident!r} in [feed]")
        # Timestamps are treated as UTC; set feed.db_time_local = true for local time.
        self.time_local = bool(cfg.get("feed.db_time_local", False))
        self._exclude = [re.compile(p, re.IGNORECASE) for p in cfg.get("feed.exclude", [])]
        self.fallback = [str(s) for s in cfg.get("feed.fallback", [])] or ["WAKE UP"]

        self._items: list[str] = []
        self._queue: list[str] = []
        self._next_refresh = 0.0
        self._missing_warned = False
        self._refresh(force=True)

    def _load(self) -> list[str]:
        now_expr = "datetime('now', 'localtime')" if self.time_local else "datetime('now')"
        query = (
            f"SELECT DISTINCT {self.title_col} FROM {self.table} "
            f"WHERE {self.time_col} IS NOT NULL AND {self.time_col} != '' "
            f"AND datetime({self.time_col}) >= datetime({now_expr}, ?) "
            f"ORDER BY {self.time_col} DESC"
        )
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=2.0)
        try:
            rows = con.execute(query, (f"-{self.window_hours:g} hours",)).fetchall()
        finally:
            con.close()
        titles = []
        for (title,) in rows:
            title = (title or "").strip()
            if title and not any(p.search(title) for p in self._exclude):
                titles.append(title)
        return titles

    def _refresh(self, force: bool = False):
        now = time.monotonic()
        if not force and now < self._next_refresh:
            return
        if self.db_path is None:  # no database configured — fallback phrases only
            self._next_refresh = now + self.refresh_seconds
            return
        if not self.db_path.is_file():
            # Warn once, then keep retrying quietly: the database may appear later
            # (a parser writing it may simply not have started yet).
            if not self._missing_warned:
                print(f"feed: no database at {self.db_path} — "
                      f"showing fallback phrases", flush=True)
                self._missing_warned = True
            self._next_refresh = now + _RETRY_AFTER_ERROR
            return
        try:
            titles = self._load()
        except sqlite3.Error as e:
            print(f"feed: sqlite refresh failed ({e}); keeping "
                  f"{len(self._items)} titles, retrying soon", flush=True)
            self._next_refresh = now + _RETRY_AFTER_ERROR
            return
        self._missing_warned = False
        self._next_refresh = now + self.refresh_seconds
        if set(titles) != set(self._items):
            self._items = titles
            self._queue.clear()

    def next(self) -> str:
        """A headline, cycling through the source in shuffled order; fallback when empty."""
        self._refresh()
        source = self._items if self._items else self.fallback
        if not self._queue:
            self._queue = list(source)
            random.shuffle(self._queue)
        return self._queue.pop()
