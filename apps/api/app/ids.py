"""Identifier helpers."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Return a new RFC 9562 UUIDv7.

    Layout: 48-bit unix millisecond timestamp, 4-bit version (7), 2-bit variant (10),
    and 74 random bits from ``os.urandom``.
    """
    unix_ms = time.time_ns() // 1_000_000
    buf = bytearray(unix_ms.to_bytes(6, "big") + os.urandom(10))
    buf[6] = (buf[6] & 0x0F) | 0x70  # version 7
    buf[8] = (buf[8] & 0x3F) | 0x80  # variant 10
    return uuid.UUID(bytes=bytes(buf))
