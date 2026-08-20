#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
# One-shot setup: venv (python3.11+), dependencies, msdfgen binary, upstream assets, glyph atlas.
# Safe to re-run — every step is idempotent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "error: $*" >&2; exit 1; }

# --- python 3.11+ ---
PY=""
for c in python3.13 python3.12 python3.11; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
done
if [[ -z "$PY" ]]; then
    v="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
    case "$v" in 3.1[1-9]) PY=python3 ;; esac
fi
[[ -n "$PY" ]] || die "python 3.11+ not found (try: sudo apt install python3.11 или python.org build)"
echo "using $PY ($($PY --version))"

# --- system prerequisites ---
for t in cmake g++ make curl git; do
    command -v "$t" >/dev/null 2>&1 || die "$t not found (sudo apt install cmake g++ make curl git)"
done

# --- venv + python deps ---
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    "$PY" -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/pip" install --quiet --upgrade pip
"$ROOT/.venv/bin/pip" install --quiet -r "$ROOT/requirements.txt"
echo "venv ready: .venv"

# --- msdfgen (core-only: no Skia, no FreeType — we feed it shape descriptions) ---
MSDFGEN="$ROOT/build/msdfgen/bin/msdfgen"
if [[ ! -x "$MSDFGEN" ]]; then
    mkdir -p "$ROOT/build"
    if [[ ! -d "$ROOT/build/msdfgen-src" ]]; then
        git clone --depth 1 https://github.com/Chlumsky/msdfgen.git "$ROOT/build/msdfgen-src"
    fi
    cmake -S "$ROOT/build/msdfgen-src" -B "$ROOT/build/msdfgen-build" \
        -DCMAKE_BUILD_TYPE=Release \
        -DMSDFGEN_CORE_ONLY=ON \
        -DMSDFGEN_BUILD_STANDALONE=ON \
        -DMSDFGEN_USE_VCPKG=OFF \
        -DMSDFGEN_USE_SKIA=OFF \
        -DMSDFGEN_DISABLE_SVG=ON \
        -DMSDFGEN_DISABLE_PNG=OFF \
        -DMSDFGEN_INSTALL=OFF >/dev/null
    cmake --build "$ROOT/build/msdfgen-build" -j"$(nproc)" >/dev/null
    mkdir -p "$ROOT/build/msdfgen/bin"
    find "$ROOT/build/msdfgen-build" -maxdepth 2 -type f -name msdfgen -perm -u+x \
        -exec cp {} "$MSDFGEN" \; -quit
    [[ -x "$MSDFGEN" ]] || die "msdfgen build produced no binary (see build/msdfgen-build)"
fi
echo "msdfgen: $("$MSDFGEN" --version 2>/dev/null | head -1 || echo ok)"

# --- upstream assets (Rezmason atlas + reference shaders) ---
bash "$ROOT/atlas/fetch_assets.sh"

# --- combined glyph atlas (matrix glyphs + generated Cyrillic) ---
if [[ -f "$ROOT/atlas/build_atlas.py" ]]; then
    "$ROOT/.venv/bin/python" "$ROOT/atlas/build_atlas.py"
else
    echo "atlas/build_atlas.py not present yet — skipping atlas build"
fi

echo
echo "install complete. Run: .venv/bin/python -m matrixrain --standalone"
