#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
# Downloads upstream assets from Rezmason/matrix (MIT):
#   - the original Matrix glyph MSDF atlas (base of our combined atlas)
#   - reference GLSL shaders + regl pass sources into vendor/rezmason for diffing during the port
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAW="https://raw.githubusercontent.com/Rezmason/matrix/master"
VENDOR="$ROOT/vendor/rezmason"
ASSETS="$ROOT/assets"

mkdir -p "$VENDOR/shaders" "$VENDOR/js" "$ASSETS"

fetch() { # fetch <url-path> <dest>
    local dest="$2"
    if [[ -s "$dest" ]]; then
        echo "  exists: ${dest#$ROOT/}"
    else
        echo "  fetch:  $1"
        curl -fsSL --retry 3 "$RAW/$1" -o "$dest"
    fi
}

echo "[assets]"
fetch "assets/matrixcode_msdf.png" "$ASSETS/matrixcode_msdf.png"
fetch "assets/msdf_command.txt" "$VENDOR/msdf_command.txt"
fetch "LICENSE" "$VENDOR/LICENSE"

echo "[vendor shaders]"
for f in \
    rainPass.vert.glsl rainPass.frag.glsl \
    rainPass.raindrop.frag.glsl rainPass.symbol.frag.glsl \
    rainPass.effect.frag.glsl rainPass.intro.frag.glsl \
    bloomPass.highPass.frag.glsl bloomPass.blur.frag.glsl bloomPass.combine.frag.glsl \
    palettePass.frag.glsl
do
    fetch "shaders/glsl/$f" "$VENDOR/shaders/$f"
done

echo "[vendor js]"
for f in rainPass.js bloomPass.js palettePass.js main.js utils.js; do
    fetch "js/regl/$f" "$VENDOR/js/$f"
done
fetch "js/config.js" "$VENDOR/js/config.js"
fetch "js/colorToRGB.js" "$VENDOR/js/colorToRGB.js"

echo "done."
