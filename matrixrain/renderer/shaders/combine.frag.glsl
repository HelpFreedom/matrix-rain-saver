#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Black Triangle and contributors. See LICENSE and NOTICE.
// Port of Rezmason bloomPass.combine.frag.glsl (sum of the blur pyramid).

uniform sampler2D pyr_0, pyr_1, pyr_2, pyr_3, pyr_4;
uniform float bloomStrength;

in vec2 vUV;
out vec4 fragColor;

void main() {
    vec4 total = vec4(0.);
    total += texture(pyr_0, vUV) * 0.96549;
    total += texture(pyr_1, vUV) * 0.92832;
    total += texture(pyr_2, vUV) * 0.88790;
    total += texture(pyr_3, vUV) * 0.84343;
    total += texture(pyr_4, vUV) * 0.79370;
    fragColor = total * bloomStrength;
}
