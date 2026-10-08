"""Tests for UUIDv7 generation."""

import time
import uuid

from app.ids import uuid7


def test_version_is_seven() -> None:
    """The version nibble is 7."""
    assert uuid7().version == 7


def test_variant_is_rfc_4122() -> None:
    """The variant bits are 10."""
    value = uuid7()
    assert value.variant == uuid.RFC_4122
    assert (value.bytes[8] & 0xC0) == 0x80


def test_timestamp_is_current_unix_ms() -> None:
    """The first 48 bits hold the current unix time in milliseconds."""
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000
    stamp = int.from_bytes(value.bytes[:6], "big")
    assert before <= stamp <= after


def test_ordering_follows_time() -> None:
    """A UUID made later in time sorts after an earlier one."""
    first = uuid7()
    time.sleep(0.005)
    second = uuid7()
    assert first.bytes[:6] < second.bytes[:6]
    assert first < second


def test_values_are_unique() -> None:
    """Many generated values do not collide."""
    values = {uuid7() for _ in range(2000)}
    assert len(values) == 2000
