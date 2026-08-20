#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Black Triangle and contributors. See LICENSE and NOTICE.
// Port of Rezmason rainPass.symbol.frag.glsl (GLSL ES 1.0 -> 3.3 core).
// R: glyph index  G: age

#define PI 3.14159265359

uniform sampler2D previousSymbolState, raindropState;
uniform float numColumns, numRows;
uniform float time, tick, cycleFrameSkip;
uniform float animationSpeed, cycleSpeed;
uniform bool loops;
uniform float glyphSequenceLength;

out vec4 fragColor;

float randomFloat(const in vec2 uv) {
    const float a = 12.9898, b = 78.233, c = 43758.5453;
    float dt = dot(uv.xy, vec2(a, b)), sn = mod(dt, PI);
    return fract(sin(sn) * c);
}

vec4 computeResult(float simTime, bool isFirstFrame, vec2 glyphPos, vec2 screenPos, vec4 previous, vec4 raindrop) {
    float previousSymbol = previous.r;
    float previousAge = previous.g;
    bool resetGlyph = isFirstFrame;
    if (loops) {
        resetGlyph = resetGlyph || raindrop.r <= 0.;
    }
    if (resetGlyph) {
        previousAge = randomFloat(screenPos + 0.5);
        previousSymbol = floor(glyphSequenceLength * randomFloat(screenPos));
    }
    float speed = animationSpeed * cycleSpeed;
    float age = previousAge;
    float symbol = previousSymbol;
    if (mod(tick, cycleFrameSkip) == 0.) {
        age += speed * cycleFrameSkip;
        if (age >= 1.) {
            symbol = floor(glyphSequenceLength * randomFloat(screenPos + simTime));
            age = fract(age);
        }
    }

    return vec4(symbol, age, 0., 0.);
}

void main() {
    float simTime = time * animationSpeed;
    bool isFirstFrame = tick <= 1.;
    vec2 glyphPos = gl_FragCoord.xy;
    vec2 screenPos = glyphPos / vec2(numColumns, numRows);
    vec4 previous = texture(previousSymbolState, screenPos);
    vec4 raindrop = texture(raindropState, screenPos);
    fragColor = computeResult(simTime, isFirstFrame, glyphPos, screenPos, previous, raindrop);
}
