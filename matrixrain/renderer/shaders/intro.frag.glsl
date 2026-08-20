#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Black Triangle and contributors. See LICENSE and NOTICE.
// Port of Rezmason rainPass.intro.frag.glsl (GLSL ES 1.0 -> 3.3 core).
// R: raindrop length of the initial stream from a blank screen.

#define PI 3.14159265359

uniform sampler2D previousIntroState;
uniform float numColumns, numRows;
uniform float time, tick;
uniform float animationSpeed, fallSpeed;
uniform bool skipIntro;

out vec4 fragColor;

float randomFloat(const in vec2 uv) {
    const float a = 12.9898, b = 78.233, c = 43758.5453;
    float dt = dot(uv.xy, vec2(a, b)), sn = mod(dt, PI);
    return fract(sin(sn) * c);
}

vec4 computeResult(float simTime, vec2 glyphPos) {
    if (skipIntro) {
        return vec4(2., 0., 0., 0.);
    }

    float columnTimeOffset;
    int column = int(glyphPos.x);
    if (column == int(numColumns / 2.)) {
        columnTimeOffset = -1.;
    } else if (column == int(numColumns * 0.75)) {
        columnTimeOffset = -2.;
    } else {
        columnTimeOffset = randomFloat(vec2(glyphPos.x, 0.)) * -4.;
        columnTimeOffset += (sin(glyphPos.x / numColumns * PI) - 1.) * 2. - 2.5;
    }
    float introTime = (simTime + columnTimeOffset) * fallSpeed / numRows * 100.;

    return vec4(introTime, 0., 0., 0.);
}

void main() {
    float simTime = time * animationSpeed;
    vec2 glyphPos = gl_FragCoord.xy;
    fragColor = computeResult(simTime, glyphPos);
}
