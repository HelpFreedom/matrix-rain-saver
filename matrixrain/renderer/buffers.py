# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""FBO plumbing: ping-pong double buffers for the GPGPU passes, single pass FBOs."""

import moderngl


def make_texture(ctx, size, dtype="f2", filter=moderngl.NEAREST):
    tex = ctx.texture(size, 4, dtype=dtype)
    tex.filter = (filter, filter)
    tex.repeat_x = False
    tex.repeat_y = False
    return tex


class PassFBO:
    """A texture + framebuffer pair, like Rezmason's makePassFBO."""

    def __init__(self, ctx, size, dtype="f2", filter=moderngl.LINEAR):
        self.texture = make_texture(ctx, size, dtype, filter)
        self.fbo = ctx.framebuffer(color_attachments=[self.texture])
        self.size = size

    def release(self):
        self.fbo.release()
        self.texture.release()


class PingPong:
    """Two FBO+texture pairs that trade places each frame (regl's makeDoubleBuffer).

    Render into .front_fbo while sampling .back_texture, then swap() once per frame.
    """

    def __init__(self, ctx, size, dtype="f2"):
        self._pairs = [PassFBO(ctx, size, dtype, moderngl.NEAREST) for _ in range(2)]
        self._front = 0
        self.size = size
        for pair in self._pairs:
            pair.fbo.clear(0.0, 0.0, 0.0, 0.0)

    @property
    def front_fbo(self):
        return self._pairs[self._front].fbo

    @property
    def front_texture(self):
        return self._pairs[self._front].texture

    @property
    def back_texture(self):
        return self._pairs[1 - self._front].texture

    def swap(self):
        self._front = 1 - self._front

    def release(self):
        for pair in self._pairs:
            pair.release()
