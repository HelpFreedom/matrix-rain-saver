# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""Layered configuration: built-in defaults <- user file <- [monitor.<name>] <- CLI overrides."""

import copy
import os
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "default.toml"
USER_CONFIG = Path("~/.config/matrix-rain/config.toml").expanduser()


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


class Config:
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, dotted: str):
        node = self._data
        for part in dotted.split("."):
            node = node[part]
        return node

    def get(self, dotted: str, default=None):
        try:
            return self[dotted]
        except KeyError:
            return default

    def section(self, name: str) -> dict:
        return copy.deepcopy(self._data.get(name, {}))

    def path(self, dotted: str) -> Path:
        """Resolve a config value as a path: ~ expanded, relative paths anchored at repo root."""
        p = Path(os.path.expanduser(str(self[dotted])))
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    def palette_stops(self) -> list:
        preset = self["palette.preset"]
        if preset == "custom":
            return self["palette.custom.stops"]
        try:
            return self[f"palette.presets.{preset}.stops"]
        except KeyError:
            raise SystemExit(f"config error: unknown palette preset {preset!r}")

    def for_monitor(self, name: str) -> "Config":
        override = self._data.get("monitor", {}).get(name)
        if not override:
            return self
        data = copy.deepcopy(self._data)
        # Monitor overrides are flat keys belonging to rain/glyphs/text sections.
        for key, value in override.items():
            placed = False
            for section in ("rain", "glyphs", "text", "display"):
                if key in data.get(section, {}):
                    data[section][key] = value
                    placed = True
                    break
            if not placed:
                data.setdefault("rain", {})[key] = value
        return Config(data)


def load(user_path: Path | None = None) -> Config:
    data = _load_toml(DEFAULT_CONFIG)
    user_file = user_path or USER_CONFIG
    if user_file.is_file():
        data = _deep_merge(data, _load_toml(user_file))
    return Config(data)
