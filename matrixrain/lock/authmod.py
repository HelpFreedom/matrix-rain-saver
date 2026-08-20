# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""xsecurelock AUTH module: renders the SYSTEM FAILURE dialog and authenticates
via the bundled authproto_pam helper (real PAM, system password).

Contract with xsecurelock (verified against README + helpers/authproto.h):
  - $XSCREENSAVER_WINDOW: we draw a child window centered inside it.
  - keystrokes arrive on OUR stdin as a UTF-8 byte stream (xsecurelock forwards
    them; we do NOT grab the keyboard — the main process holds the grab).
  - we spawn the AUTHPROTO helper and relay its prompts / our responses.
  - exit status 0 == authenticated (unlock). Any other status == keep locked.

The AUTHPROTO helper's EXIT STATUS is the only truth for success — never a message.
"""

import os
import select
import shutil
import subprocess
import sys
import time

from . import authproto as ap

# Keystroke bytes.
_ENTER = {0x0A, 0x0D}
_BACKSPACE = {0x08, 0x7F}
_ESCAPE = 0x1B
_CTRL_U = 0x15

# xsecurelock installs its helpers into a per-distro directory. Debian/Ubuntu use
# /usr/libexec/xsecurelock/, others /usr/lib/xsecurelock/ (sometimes a helpers/
# subdir). Cover them all; XSECURELOCK_AUTHPROTO_HELPER overrides with a full path.
AUTHPROTO_DIRS = [
    "/usr/libexec/xsecurelock",
    "/usr/lib/xsecurelock",
    "/usr/lib/xsecurelock/helpers",
    "/usr/local/libexec/xsecurelock",
    "/usr/local/lib/xsecurelock",
]


def find_authproto() -> str:
    env = os.environ.get("XSECURELOCK_AUTHPROTO_HELPER")
    if env and os.path.isfile(env):
        return env
    # An authproto name (not a path) selected via XSECURELOCK_AUTHPROTO, default pam.
    name = os.environ.get("XSECURELOCK_AUTHPROTO", "authproto_pam")
    if "/" in name and os.path.isfile(name):
        return name
    for directory in AUTHPROTO_DIRS:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit(
        f"auth_matrixrain: {name} helper not found in "
        f"{', '.join(AUTHPROTO_DIRS)} — set XSECURELOCK_AUTHPROTO_HELPER to its path")


_CONTROL = {
    **{b: "submit" for b in _ENTER},
    **{b: "backspace" for b in _BACKSPACE},
    _ESCAPE: "cancel",
    _CTRL_U: "clear",
}


class KeyStream:
    """Decode the UTF-8 keystroke byte stream from a file descriptor into events."""

    def __init__(self, fd: int):
        self.fd = fd
        self._pending = bytearray()  # incomplete trailing multibyte char

    def read_events(self):
        """Read available bytes (call only when the fd is select-readable) and
        return a list of ('submit'|'backspace'|'cancel'|'clear'|'char'|'eof', value)."""
        chunk = os.read(self.fd, 1024)
        if not chunk:
            return [("eof", None)]

        events = []
        text = bytearray(self._pending)  # text bytes accumulated since last control
        self._pending = bytearray()

        def flush():
            if not text:
                return
            try:
                decoded = text.decode("utf-8")
                text.clear()
            except UnicodeDecodeError as e:
                # Keep a trailing partial character for the next read; drop true junk.
                if e.reason == "unexpected end of data":
                    self._pending = bytearray(text[e.start:])
                    decoded = text[: e.start].decode("utf-8")
                else:
                    decoded = text.decode("utf-8", "ignore")
                text.clear()
            for ch in decoded:
                events.append(("char", ch))

        for b in chunk:
            control = _CONTROL.get(b)
            if control is not None:
                flush()
                events.append((control, None))
            else:
                text.append(b)
        flush()
        return events


class AuthProtoSession:
    """One PAM attempt: spawns the helper, relays prompts, collects one response."""

    def __init__(self, helper_path: str):
        self.helper_path = helper_path
        self.proc = subprocess.Popen(
            [helper_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        self.reader = ap.PacketReader(self.proc.stdout.fileno())
        self.expecting = None   # 'password' | 'username' | None
        self.error = ""

    @property
    def out_fd(self) -> int:
        return self.proc.stdout.fileno()

    def pump(self) -> None:
        """Drain all packets currently available from the helper (call when its
        fd is select-readable, or opportunistically each frame)."""
        for ptype, message in self.reader.poll():
            if ptype == ap.PTYPE_PROMPT_LIKE_PASSWORD:
                self.expecting = "password"
            elif ptype == ap.PTYPE_PROMPT_LIKE_USERNAME:
                # Answer immediately from the environment; PAM rarely asks this.
                user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
                ap.write_packet(self.proc.stdin.fileno(), ap.PTYPE_RESPONSE_LIKE_USERNAME, user)
            elif ptype == ap.PTYPE_ERROR_MESSAGE:
                self.error = message
            # INFO messages are ignored (our dialog has its own fixed title).

    def send_response(self, password):
        """password is a bytes-like (bytearray) written straight to the helper."""
        ap.write_packet(self.proc.stdin.fileno(), ap.PTYPE_RESPONSE_LIKE_PASSWORD, password)
        self.expecting = None

    def cancel(self):
        try:
            ap.write_packet(self.proc.stdin.fileno(), ap.PTYPE_RESPONSE_CANCELLED)
        except OSError:
            pass

    def poll_result(self):
        """None while running, else True (authenticated) / False (denied)."""
        rc = self.proc.poll()
        if rc is None:
            return None
        return rc == 0

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except OSError:
                pass


def _wipe(buf: bytearray) -> None:
    """Best-effort scrub of a password buffer. Python can't guarantee no copies
    lingered (bytes are immutable), but zeroing the mutable original keeps the
    plaintext from sitting in the heap after use — the str approach never could."""
    for i in range(len(buf)):
        buf[i] = 0
    del buf[:]


def _utf8_backspace(buf: bytearray) -> None:
    """Remove the last whole UTF-8 character (not just one byte)."""
    i = len(buf)
    while i > 0:
        i -= 1
        if (buf[i] & 0xC0) != 0x80:  # lead byte (not a continuation byte)
            break
    del buf[i:]


def _wait_for_key(keys: "KeyStream", idle_exit: float):
    """Block (drawing nothing, rain running) until the user starts typing.

    Returns the first batch of decoded key events, or None on timeout / stdin EOF.

    xsecurelock spawns this auth module on ANY input — a key OR mere mouse motion —
    but it only forwards the *waking* keystroke to a freshly-started child when that
    keystroke is a PRINTABLE character (auth_child.c: ContainsNonControl). Control
    keys, Escape included, and mouse motion leave our stdin empty. So an empty stdin
    means "woken by the mouse / a control key" → we time out and leave the rain
    untouched; the first bytes arriving mean "the user is typing their password" →
    we open the dialog and those bytes become the start of the password.

    Esc (cancel) is dropped here, never opening the dialog: while this gate waits,
    a *previously* spawned child may still be alive within idle_exit, so a stray Esc
    would actually reach us — but opening the dialog on it would immediately hand the
    same cancel to handle_events and close it again (open-and-instantly-close). Esc
    only means "close" once the dialog is already up.
    """
    deadline = time.monotonic() + idle_exit
    stdin_fd = sys.stdin.fileno()
    while time.monotonic() < deadline:
        readable, _, _ = select.select([stdin_fd], [], [], 0.2)
        if stdin_fd not in readable:
            continue
        events = keys.read_events()
        if events and events[0][0] == "eof":
            return None
        events = [e for e in events if e[0] != "cancel"]  # Esc never opens the dialog
        if events:
            return events
    return None


def run(cfg, parent_window, center_rect, freeze=None, wake_on_key=True,
        idle_exit=45.0) -> int:
    """Drive the dialog + PAM loop. Returns process exit code (0 == unlock).

    parent_window / center_rect: where to draw the dialog (from run_auth._placement,
    chosen at spawn time).
    freeze: optional FreezeWriter; held while the dialog is open so the saver
    renderers pause the rain, released on exit.
    wake_on_key: if True, keep showing only the rain until the user starts typing
    (see _wait_for_key); mouse motion never opens the dialog. If no key arrives
    within idle_exit seconds we return 1, leaving the saver untouched. If False,
    the dialog opens immediately on any wake-up.
    """
    from ..lockui import LockDialog

    helper_path = find_authproto()
    keys = KeyStream(sys.stdin.fileno())

    initial_events = []
    if wake_on_key:
        initial_events = _wait_for_key(keys, idle_exit)
        if initial_events is None:
            return 1  # only mouse / no typing before the timeout — saver unchanged

    dialog = LockDialog(cfg, center_rect, parent=parent_window)
    if freeze:
        freeze.set()

    session = AuthProtoSession(helper_path)
    password = bytearray()  # mutable so it can be wiped after use
    result = None  # final exit decision

    def handle_events(events) -> None:
        """Apply a batch of key events to the password / dialog. Sets `result`
        (via nonlocal) when the user submits nothing further is needed / cancels."""
        nonlocal result, password
        for kind, value in events:
            if kind == "eof":
                result = 1
                return
            if dialog.in_error:
                continue  # ignore input during the denial flash
            if kind == "char":
                password += value.encode("utf-8")
                dialog.add_char()
            elif kind == "backspace":
                _utf8_backspace(password)
                dialog.backspace()
            elif kind == "clear":
                _wipe(password)
                dialog.clear()
            elif kind == "cancel":  # Esc closes the dialog, back to bare rain
                result = 1
                return
            elif kind == "submit":
                if session is not None and session.expecting == "password":
                    session.send_response(password)  # writes the bytearray directly
                _wipe(password)

    try:
        # The printable key(s) that opened the dialog are the start of the password.
        handle_events(initial_events)

        while result is None:
            # Drive the current PAM attempt; a finished one is respawned unless the
            # user cancelled.
            fds = [sys.stdin.fileno()]
            if session is not None:
                fds.append(session.out_fd)
            readable, _, _ = select.select(fds, [], [], 1 / 60)

            if session is not None and session.out_fd in readable:
                session.pump()

            if sys.stdin.fileno() in readable:
                handle_events(keys.read_events())

            if session is not None and result is None:
                verdict = session.poll_result()
                if verdict is True:
                    result = 0
                elif verdict is False:
                    # Denied: flash red, drop the helper, start a fresh attempt.
                    dialog.set_error()
                    session.close()
                    session = None
                    _wipe(password)

            if session is None and result is None and not dialog.in_error:
                session = AuthProtoSession(helper_path)

            if freeze:
                freeze.refresh()
            dialog.raise_window()  # stay above the frozen saver / obscurer windows
            dialog.render()
    finally:
        _wipe(password)
        if session is not None:
            session.cancel()
            session.close()
        if freeze:
            freeze.clear()
        dialog.close()
    return result
