#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Black Triangle and contributors. See LICENSE and NOTICE.
// Port of Rezmason bloomPass.highPass.frag.glsl.

uniform sampler2D tex;
uniform float highPassThreshold;

in vec2 vUV;
out vec4 fragColor;

void main() {
    vec4 color = texture(tex, vUV);
    if (color.r < highPassThreshold) color.r = 0.0;
    if (color.g < highPassThreshold) color.g = 0.0;
    if (color.b < highPassThreshold) color.b = 0.0;
    fragColor = color;
}
