# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Black Triangle and contributors. See LICENSE for terms.
"""xsecurelock authproto wire protocol (helpers/authproto.h).

An AUTH module spawns an AUTHPROTO helper (e.g. the bundled authproto_pam) and
exchanges length-prefixed packets with it over the helper's stdin/stdout. The helper
drives the real PAM conversation; the AUTH module only relays prompts to the user and
sends typed responses back. The helper's EXIT STATUS is the sole source of truth for
success — never any message type.

Packet wire format:  <ptype><SPC><decimal-len><NL><message bytes><NL>
"""

import errno
import fcntl
import os

# PAM -> user (the helper asks; uppercase = expects a reply).
PTYPE_INFO_MESSAGE = "i"
PTYPE_ERROR_MESSAGE = "e"
PTYPE_PROMPT_LIKE_USERNAME = "U"   # visible prompt
PTYPE_PROMPT_LIKE_PASSWORD = "P"   # hidden prompt

# user -> PAM (the AUTH module answers; lowercase = terminal for this exchange).
PTYPE_RESPONSE_LIKE_USERNAME = "u"
PTYPE_RESPONSE_LIKE_PASSWORD = "p"
PTYPE_RESPONSE_CANCELLED = "x"


def _write_all(fd: int, buf) -> None:
    mv = memoryview(buf)
    while mv:
        n = os.write(fd, mv)
        mv = mv[n:]


def write_packet(fd: int, ptype: str, message="") -> None:
    """Write one packet. message may be str (UTF-8 encoded) or bytes/bytearray.

    A bytes-like message (e.g. a password bytearray) is written straight through
    without an intermediate str/bytes copy, so the caller can wipe the original.
    """
    payload = message if isinstance(message, (bytes, bytearray)) else message.encode("utf-8")
    _write_all(fd, f"{ptype} {len(payload)}\n".encode("ascii"))
    _write_all(fd, payload)
    _write_all(fd, b"\n")


class PacketReader:
    """Non-blocking buffered packet reader for a select() loop.

    The fd is made non-blocking so buffered data never desynchronizes from what
    select() reports: poll() drains every byte currently available and returns all
    complete (ptype, message) packets, leaving any partial packet in the buffer for
    next time. `eof` is set once the peer closes its end.

    Also usable blockingly (tests, simple drivers) via read().
    """

    def __init__(self, fd: int, nonblocking: bool = True):
        self.fd = fd
        self._buf = bytearray()
        self.eof = False
        if nonblocking:
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            self._nonblocking = True
        else:
            self._nonblocking = False

    def _parse_one(self):
        """Pop one complete packet from the buffer, or None if incomplete."""
        nl = self._buf.find(b"\n")
        if nl < 0:
            return None
        header = bytes(self._buf[:nl])
        try:
            ptype_bytes, len_bytes = header.split(b" ", 1)
            ptype = ptype_bytes.decode("ascii")
            length = int(len_bytes)
        except (ValueError, UnicodeDecodeError):
            raise ValueError(f"malformed authproto header: {header!r}")
        if length < 0:
            raise ValueError(f"negative authproto length: {header!r}")
        # Need: header + NL + length bytes + trailing NL.
        total = nl + 1 + length + 1
        if len(self._buf) < total:
            return None
        message = bytes(self._buf[nl + 1: nl + 1 + length]).decode("utf-8", "replace")
        del self._buf[:total]
        return ptype, message

    def poll(self) -> list[tuple[str, str]]:
        """Drain available bytes; return all complete packets (may be empty)."""
        while True:
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                break
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    break
                raise
            if not chunk:
                self.eof = True
                break
            self._buf.extend(chunk)
        packets = []
        while (pkt := self._parse_one()) is not None:
            packets.append(pkt)
        return packets

    def read(self):
        """Blocking single-packet read (returns None on clean EOF). For tests."""
        while True:
            pkt = self._parse_one()
            if pkt is not None:
                return pkt
            if self.eof:
                return None
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                continue
            if not chunk:
                self.eof = True
                if not self._buf:
                    return None
                continue
            self._buf.extend(chunk)
