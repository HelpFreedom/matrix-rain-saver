#version 330 core
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Black Triangle and contributors. See LICENSE and NOTICE.
// Glyph render pass (ported from Rezmason rainPass.frag, non-volumetric path,
// reworked for world space, horizontal streams and a separate text channel).
//
// Primary FBO channels:
//   R: rain brightness (mapped through the palette gradient later)
//   G: cursor / scramble-head brightness (colored with cursorColor later)
//   B: settled headline brightness (colored with textColor later)
//
// The window shows a crop of the world: uvWorld = uvOffset + vUV * uvScale.
// The simulation is transposed in horizontal mode: sim "columns" are world rows,
// the stream head moves toward sim y=0, which maps to increasing world x
// (left -> right, meanwhile-style).
//
// textState (world grid): R = glyph index / 255, G = kind level
// (1.0 settled text, 0.55 scramble head, 0.25 fading scramble), B = occlusion.

#define PI 3.14159265359

uniform sampler2D raindropState, symbolState, effectState;
uniform sampler2D glyphMSDF;
uniform float msdfPxRange;
uniform vec2 glyphMSDFSize;
uniform float baseContrast, baseBrightness;
uniform vec2 glyphTextureGridSize;
uniform bool isolateCursor;
uniform vec2 worldGrid;      // world cells (x: columns, y: rows)
uniform vec2 uvOffset, uvScale;
uniform bool horizontal;

uniform bool hasText;
uniform sampler2D textState;
uniform float textBrightness, scrambleBrightness, fadeBrightness;

in vec2 vUV;
out vec4 fragColor;

float median3(vec3 i) {
    return max(min(i.r, i.g), min(max(i.r, i.g), i.b));
}

float modI(float a, float b) {
    float m = a - floor((a + 0.5) / b) * b;
    return floor(m + 0.5);
}

vec2 getSymbolUV(float index) {
    float symbolX = modI(index, glyphTextureGridSize.x);
    float symbolY = (index - symbolX) / glyphTextureGridSize.x;
    symbolY = glyphTextureGridSize.y - symbolY - 1.;
    return vec2(symbolX, symbolY);
}

float getSymbol(vec2 cellUV, float index) {
    vec2 uv = (cellUV + getSymbolUV(index)) / glyphTextureGridSize;

    // MSDF: brightness of the fragment from the distance to the shape.
    vec2 unitRange = vec2(msdfPxRange) / glyphMSDFSize;
    vec2 screenTexSize = vec2(1.0) / fwidth(uv);
    float screenPxRange = max(0.5 * dot(unitRange, screenTexSize), 1.0);

    float signedDistance = median3(texture(glyphMSDF, uv).rgb);
    float screenPxDistance = screenPxRange * (signedDistance - 0.5);
    return clamp(screenPxDistance + 0.5, 0.0, 1.0);
}

void main() {
    vec2 uvWorld = uvOffset + vUV * uvScale;
    vec2 simUV = horizontal ? vec2(uvWorld.y, 1.0 - uvWorld.x) : uvWorld;

    vec4 raindrop = texture(raindropState, simUV);
    vec4 symbolData = texture(symbolState, simUV);
    vec4 effectData = texture(effectState, simUV);

    float kind = 0.0;
    float occlusion = 0.0;
    float textGlyph = 0.0;
    if (hasText) {
        vec4 txt = texture(textState, uvWorld);
        kind = txt.g;
        occlusion = txt.b;
        textGlyph = floor(txt.r * 255. + 0.5);
    }

    // Glyph cells are anchored to the world grid, upright in both orientations.
    vec2 cellUV = fract(uvWorld * worldGrid);

    if (kind > 0.75) {
        // Settled headline character.
        fragColor = vec4(0., 0., textBrightness * getSymbol(cellUV, textGlyph), 0.);
        return;
    }
    if (kind > 0.4) {
        // Flickering scramble at the drawing head — cursor-colored.
        fragColor = vec4(0., scrambleBrightness * getSymbol(cellUV, textGlyph), 0., 0.);
        return;
    }
    if (kind > 0.1) {
        // Dim scramble left while a message dissolves — rain-colored.
        fragColor = vec4(fadeBrightness * getSymbol(cellUV, textGlyph), 0., 0., 0.);
        return;
    }

    // Plain rain cell (suppressed inside a message's pocket by occlusion).
    float base = raindrop.r + max(0., 1.0 - raindrop.a * 5.0);
    bool isCursor = bool(raindrop.g) && isolateCursor;
    base = base * baseContrast + baseBrightness;
    base = base * effectData.r + effectData.g;
    base *= raindrop.b * (1.0 - occlusion);

    float symbol = getSymbol(cellUV, symbolData.r);
    vec2 rainOut = (isCursor ? vec2(0.0, 1.0) : vec2(1.0, 0.0)) * base;
    fragColor = vec4(rainOut * symbol, 0., 0.);
}
