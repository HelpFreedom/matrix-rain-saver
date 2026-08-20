#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Black Triangle and contributors. See LICENSE and NOTICE.
// Port of Rezmason rainPass.raindrop.frag.glsl (GLSL ES 1.0 -> 3.3 core).
// R: raindrop brightness  G: cursor flag  B: activated (intro)  A: intro progress

#define PI 3.14159265359
#define SQRT_2 1.4142135623730951
#define SQRT_5 2.23606797749979

uniform sampler2D previousRaindropState, introState;
uniform float numColumns, numRows;
uniform float time, tick;
uniform float animationSpeed, fallSpeed;
uniform bool loops, skipIntro;
uniform float brightnessDecay;
uniform float raindropLength;

out vec4 fragColor;

float randomFloat(const in vec2 uv) {
    const float a = 12.9898, b = 78.233, c = 43758.5453;
    float dt = dot(uv.xy, vec2(a, b)), sn = mod(dt, PI);
    return fract(sin(sn) * c);
}

float wobble(float x) {
    return x + 0.3 * sin(SQRT_2 * x) + 0.2 * sin(SQRT_5 * x);
}

float getRainBrightness(float simTime, vec2 glyphPos) {
    float columnTimeOffset = randomFloat(vec2(glyphPos.x, 0.)) * 1000.;
    float columnSpeedOffset = randomFloat(vec2(glyphPos.x + 0.1, 0.)) * 0.5 + 0.5;
    if (loops) {
        columnSpeedOffset = 0.5;
    }
    float columnTime = columnTimeOffset + simTime * fallSpeed * columnSpeedOffset;
    float rainTime = (glyphPos.y * 0.01 + columnTime) / raindropLength;
    if (!loops) {
        rainTime = wobble(rainTime);
    }
    return 1.0 - fract(rainTime);
}

vec4 computeResult(float simTime, bool isFirstFrame, vec2 glyphPos, vec4 previous, vec4 intro) {
    float brightness = getRainBrightness(simTime, glyphPos);
    float brightnessBelow = getRainBrightness(simTime, glyphPos + vec2(0., -1.));

    float introProgress = intro.r - (1. - glyphPos.y / numRows);
    float introProgressBelow = intro.r - (1. - (glyphPos.y - 1.) / numRows);

    bool activated = bool(previous.b) || skipIntro || introProgress > 0.;
    bool activatedBelow = skipIntro || introProgressBelow > 0.;

    bool cursor = brightness > brightnessBelow || (activated && !activatedBelow);

    // Blend with the previous brightness, so glyphs wink on and off organically.
    if (!isFirstFrame) {
        brightness = mix(previous.r, brightness, brightnessDecay);
    }

    return vec4(brightness, cursor, activated, introProgress);
}

void main() {
    float simTime = time * animationSpeed;
    bool isFirstFrame = tick <= 1.;
    vec2 glyphPos = gl_FragCoord.xy;
    vec2 screenPos = glyphPos / vec2(numColumns, numRows);
    vec4 previous = texture(previousRaindropState, screenPos);
    vec4 intro = texture(introState, vec2(screenPos.x, 0.));
    fragColor = computeResult(simTime, isFirstFrame, glyphPos, previous, intro);
}
