#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Black Triangle and contributors. See LICENSE and NOTICE.
// Port of Rezmason palettePass.frag.glsl: brightness -> palette color, plus dither.

#define PI 3.14159265359

uniform sampler2D tex;
uniform sampler2D bloomTex;
uniform sampler2D paletteTex;
uniform float ditherMagnitude;
uniform float time;
uniform vec3 backgroundColor, cursorColor, textColor;
uniform float cursorIntensity, textIntensity;

in vec2 vUV;
out vec4 fragColor;

float rand(const in vec2 uv, const in float t) {
    const float a = 12.9898, b = 78.233, c = 43758.5453;
    float dt = dot(uv.xy, vec2(a, b)), sn = mod(dt, PI);
    return fract(sin(sn) * c + t);
}

void main() {
    vec4 brightness = texture(tex, vUV) + texture(bloomTex, vUV);

    // Dither: subtract a random value from the brightness to hide banding.
    brightness -= rand(gl_FragCoord.xy, time) * ditherMagnitude / 3.0;

    fragColor = vec4(
        texture(paletteTex, vec2(brightness.r, 0.0)).rgb
            + min(cursorColor * cursorIntensity * brightness.g, vec3(1.0))
            + min(textColor * textIntensity * brightness.b, vec3(1.0))
            + backgroundColor,
        1.0
    );
}
