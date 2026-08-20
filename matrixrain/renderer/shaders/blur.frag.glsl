#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Black Triangle and contributors. See LICENSE and NOTICE.
// Port of Rezmason bloomPass.blur.frag.glsl (1D gaussian approximation).

uniform float width, height;
uniform sampler2D tex;
uniform vec2 direction;

in vec2 vUV;
out vec4 fragColor;

void main() {
    vec2 size = width > height ? vec2(width / height, 1.) : vec2(1., height / width);
    fragColor =
        texture(tex, vUV) * 0.442 +
        (
            texture(tex, vUV + direction / max(width, height) * size) +
            texture(tex, vUV - direction / max(width, height) * size)
        ) * 0.279;
}
