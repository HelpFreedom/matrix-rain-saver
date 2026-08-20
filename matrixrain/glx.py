# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""ctypes Xlib + GLX shim.

Creates the render window and a GL 3.3 core context in one of two modes:
  - standalone: fullscreen override-redirect window on top of everything (WM ignores it)
  - embedded:   child window filling a foreign parent (xsecurelock's $XSCREENSAVER_WINDOW)

Both modes create OUR OWN window with a GLX-capable visual — rendering directly into a
foreign window is unreliable because its visual may not match any GL config.

moderngl attaches to whatever context is current via moderngl.create_context().
"""

import ctypes
import ctypes.util
import os


def _lib(name, fallback):
    path = ctypes.util.find_library(name)
    return ctypes.CDLL(path or fallback)

_x = _lib("X11", "libX11.so.6")
_gl = _lib("GL", "libGL.so.1")

# --- Xlib types & constants ---
Display_p = ctypes.c_void_p
XID = ctypes.c_ulong
Window = XID
Colormap = XID
VisualID = ctypes.c_ulong
Bool = ctypes.c_int

InputOutput = 1
AllocNone = 0
CWBackPixel = 1 << 1
CWBorderPixel = 1 << 3
CWEventMask = 1 << 11
CWColormap = 1 << 13
CWOverrideRedirect = 1 << 9
StructureNotifyMask = 1 << 17
ConfigureNotify = 22
MapNotify = 19


class XSetWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("background_pixmap", XID),
        ("background_pixel", ctypes.c_ulong),
        ("border_pixmap", XID),
        ("border_pixel", ctypes.c_ulong),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", Bool),
        ("event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", Bool),
        ("colormap", Colormap),
        ("cursor", XID),
    ]


class XVisualInfo(ctypes.Structure):
    _fields_ = [
        ("visual", ctypes.c_void_p),
        ("visualid", VisualID),
        ("screen", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("c_class", ctypes.c_int),
        ("red_mask", ctypes.c_ulong),
        ("green_mask", ctypes.c_ulong),
        ("blue_mask", ctypes.c_ulong),
        ("colormap_size", ctypes.c_int),
        ("bits_per_rgb", ctypes.c_int),
    ]


class XColor(ctypes.Structure):
    _fields_ = [
        ("pixel", ctypes.c_ulong),
        ("red", ctypes.c_ushort),
        ("green", ctypes.c_ushort),
        ("blue", ctypes.c_ushort),
        ("flags", ctypes.c_char),
        ("pad", ctypes.c_char),
    ]


class XConfigureEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", Bool),
        ("display", Display_p),
        ("event", Window),
        ("window", Window),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("above", Window),
        ("override_redirect", Bool),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("xconfigure", XConfigureEvent),
        ("pad", ctypes.c_long * 24),
    ]


_x.XOpenDisplay.restype = Display_p
_x.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x.XDefaultScreen.argtypes = [Display_p]
_x.XRootWindow.restype = Window
_x.XRootWindow.argtypes = [Display_p, ctypes.c_int]
_x.XCreateColormap.restype = Colormap
_x.XCreateColormap.argtypes = [Display_p, Window, ctypes.c_void_p, ctypes.c_int]
_x.XCreateWindow.restype = Window
_x.XCreateWindow.argtypes = [
    Display_p, Window,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
    ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p,
    ctypes.c_ulong, ctypes.POINTER(XSetWindowAttributes),
]
_x.XMapRaised.argtypes = [Display_p, Window]
_x.XRaiseWindow.argtypes = [Display_p, Window]
_x.XDestroyWindow.argtypes = [Display_p, Window]
_x.XCloseDisplay.argtypes = [Display_p]
_x.XFlush.argtypes = [Display_p]
_x.XSync.argtypes = [Display_p, Bool]
_x.XPending.argtypes = [Display_p]
_x.XNextEvent.argtypes = [Display_p, ctypes.POINTER(XEvent)]
_x.XSelectInput.argtypes = [Display_p, Window, ctypes.c_long]
_x.XFree.argtypes = [ctypes.c_void_p]
_x.XStoreName.argtypes = [Display_p, Window, ctypes.c_char_p]
_x.XCreateBitmapFromData.restype = XID
_x.XCreateBitmapFromData.argtypes = [Display_p, XID, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint]
_x.XCreatePixmapCursor.restype = XID
_x.XCreatePixmapCursor.argtypes = [Display_p, XID, XID, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_uint, ctypes.c_uint]
_x.XDefineCursor.argtypes = [Display_p, Window, XID]
_x.XFreePixmap.argtypes = [Display_p, XID]

# --- GLX constants ---
GLX_DOUBLEBUFFER = 5
GLX_RED_SIZE = 8
GLX_GREEN_SIZE = 9
GLX_BLUE_SIZE = 10
GLX_ALPHA_SIZE = 11
GLX_DEPTH_SIZE = 12
GLX_STENCIL_SIZE = 13
GLX_DRAWABLE_TYPE = 0x8010
GLX_RENDER_TYPE = 0x8011
GLX_X_RENDERABLE = 0x8012
GLX_WINDOW_BIT = 0x00000001
GLX_RGBA_BIT = 0x00000001
GLX_X_VISUAL_TYPE = 0x22
GLX_TRUE_COLOR = 0x8002

GLX_CONTEXT_MAJOR_VERSION_ARB = 0x2091
GLX_CONTEXT_MINOR_VERSION_ARB = 0x2092
GLX_CONTEXT_PROFILE_MASK_ARB = 0x9126
GLX_CONTEXT_CORE_PROFILE_BIT_ARB = 0x00000001

GLXFBConfig = ctypes.c_void_p
GLXContext = ctypes.c_void_p
GLXDrawable = XID

_gl.glXChooseFBConfig.restype = ctypes.POINTER(GLXFBConfig)
_gl.glXChooseFBConfig.argtypes = [Display_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
_gl.glXGetVisualFromFBConfig.restype = ctypes.POINTER(XVisualInfo)
_gl.glXGetVisualFromFBConfig.argtypes = [Display_p, GLXFBConfig]
_gl.glXMakeCurrent.restype = Bool
_gl.glXMakeCurrent.argtypes = [Display_p, GLXDrawable, GLXContext]
_gl.glXSwapBuffers.argtypes = [Display_p, GLXDrawable]
_gl.glXDestroyContext.argtypes = [Display_p, GLXContext]
_gl.glXGetProcAddressARB.restype = ctypes.c_void_p
_gl.glXGetProcAddressARB.argtypes = [ctypes.c_char_p]


def _proc(name, restype, argtypes):
    addr = _gl.glXGetProcAddressARB(name)
    if not addr:
        return None
    return ctypes.CFUNCTYPE(restype, *argtypes)(addr)


class GLWindow:
    """An X window with a current GL 3.3 core context."""

    def __init__(self, x, y, width, height, parent=None, override_redirect=True,
                 title="matrix-rain", argb=False, fill_parent=True):
        self.width, self.height = width, height
        self.dpy = _x.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("cannot open X display (is DISPLAY set?)")
        screen = _x.XDefaultScreen(self.dpy)
        root = _x.XRootWindow(self.dpy, screen)

        attribs = (ctypes.c_int * 25)(
            GLX_X_RENDERABLE, 1,
            GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
            GLX_RENDER_TYPE, GLX_RGBA_BIT,
            GLX_X_VISUAL_TYPE, GLX_TRUE_COLOR,
            GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
            GLX_ALPHA_SIZE, 8 if argb else 0,
            GLX_DEPTH_SIZE, 0, GLX_STENCIL_SIZE, 0,
            GLX_DOUBLEBUFFER, 1,
            0,
        )
        count = ctypes.c_int(0)
        configs = _gl.glXChooseFBConfig(self.dpy, screen, attribs, ctypes.byref(count))
        if not configs or count.value == 0:
            raise RuntimeError("no matching GLXFBConfig")
        # For an ARGB window we need a config whose X visual is 32-bit deep, so a
        # compositor treats the alpha channel as transparency.
        fbconfig = vi = None
        for i in range(count.value):
            candidate = _gl.glXGetVisualFromFBConfig(self.dpy, configs[i])
            if not candidate:
                continue
            if not argb or candidate.contents.depth == 32:
                fbconfig, vi = configs[i], candidate
                break
            _x.XFree(candidate)
        if vi is None:  # no 32-bit visual — fall back to opaque
            fbconfig = configs[0]
            vi = _gl.glXGetVisualFromFBConfig(self.dpy, fbconfig)
        _x.XFree(configs)
        if not vi:
            raise RuntimeError("no XVisualInfo for chosen FBConfig")
        self.argb = bool(argb) and vi.contents.depth == 32

        cmap = _x.XCreateColormap(self.dpy, root, vi.contents.visual, AllocNone)
        swa = XSetWindowAttributes()
        swa.colormap = cmap
        swa.background_pixel = 0
        swa.border_pixel = 0
        swa.override_redirect = 1 if override_redirect else 0
        swa.event_mask = StructureNotifyMask
        mask = CWColormap | CWBackPixel | CWBorderPixel | CWEventMask
        if override_redirect:
            mask |= CWOverrideRedirect

        win_parent = parent if parent is not None else root
        # Embedded saver fills the parent from its origin; an embedded dialog
        # (fill_parent=False) sits at (x, y) inside the parent instead.
        wx, wy = (0, 0) if (parent is not None and fill_parent) else (x, y)
        self.win = _x.XCreateWindow(
            self.dpy, win_parent, wx, wy, width, height, 0,
            vi.contents.depth, InputOutput, vi.contents.visual, mask, ctypes.byref(swa),
        )
        _x.XFree(vi)
        _x.XStoreName(self.dpy, self.win, title.encode())
        self._hide_cursor()
        _x.XMapRaised(self.dpy, self.win)
        _x.XSync(self.dpy, 0)

        create_ctx = _proc(
            b"glXCreateContextAttribsARB", GLXContext,
            [Display_p, GLXFBConfig, GLXContext, Bool, ctypes.POINTER(ctypes.c_int)],
        )
        if create_ctx is None:
            raise RuntimeError("glXCreateContextAttribsARB unavailable")
        ctx_attribs = (ctypes.c_int * 7)(
            GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
            GLX_CONTEXT_MINOR_VERSION_ARB, 3,
            GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
            0,
        )
        self.ctx = create_ctx(self.dpy, fbconfig, None, 1, ctx_attribs)
        if not self.ctx:
            raise RuntimeError("failed to create GL 3.3 core context")
        if not _gl.glXMakeCurrent(self.dpy, self.win, self.ctx):
            raise RuntimeError("glXMakeCurrent failed")

        # vsync (best effort)
        swap_interval = _proc(b"glXSwapIntervalEXT", None, [Display_p, GLXDrawable, ctypes.c_int])
        if swap_interval:
            swap_interval(self.dpy, self.win, 1)

    def _hide_cursor(self):
        """Blank cursor over the render window (a screensaver shows no pointer).

        Classic trick: a 1x1 all-zero bitmap as both cursor source and mask —
        the zero mask makes every pixel transparent.
        """
        blank = _x.XCreateBitmapFromData(self.dpy, self.win, b"\x00", 1, 1)
        color = XColor()
        cursor = _x.XCreatePixmapCursor(self.dpy, blank, blank,
                                        ctypes.byref(color), ctypes.byref(color), 0, 0)
        _x.XDefineCursor(self.dpy, self.win, cursor)
        _x.XFreePixmap(self.dpy, blank)

    def raise_(self):
        """Raise this window above its siblings (keeps a dialog on top of the saver)."""
        _x.XRaiseWindow(self.dpy, self.win)

    def swap(self):
        _gl.glXSwapBuffers(self.dpy, self.win)

    def poll_resize(self):
        """Drain pending events; return (w, h) if the window was resized, else None."""
        resized = None
        ev = XEvent()
        while _x.XPending(self.dpy):
            _x.XNextEvent(self.dpy, ctypes.byref(ev))
            if ev.type == ConfigureNotify and ev.xconfigure.window == self.win:
                w, h = ev.xconfigure.width, ev.xconfigure.height
                if (w, h) != (self.width, self.height):
                    self.width, self.height = w, h
                    resized = (w, h)
        return resized

    def close(self):
        if getattr(self, "ctx", None):
            _gl.glXMakeCurrent(self.dpy, 0, None)
            _gl.glXDestroyContext(self.dpy, self.ctx)
            self.ctx = None
        if getattr(self, "win", None):
            _x.XDestroyWindow(self.dpy, self.win)
            self.win = None
        if getattr(self, "dpy", None):
            _x.XCloseDisplay(self.dpy)
            self.dpy = None
