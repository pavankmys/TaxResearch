"""Tests for password hashing."""

from app.auth.passwords import DUMMY_HASH, hash_password, needs_rehash, verify_password


def test_hash_and_verify_round_trip() -> None:
    """A password verifies against its own hash."""
    password_hash = hash_password("correct horse battery")
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "correct horse battery") is True


def test_wrong_password_fails() -> None:
    """A different password does not verify."""
    password_hash = hash_password("correct horse battery")
    assert verify_password(password_hash, "wrong horse battery") is False


def test_garbage_hash_returns_false() -> None:
    """A malformed stored hash is treated as a mismatch, not an error."""
    assert verify_password("not-a-hash", "anything") is False


def test_dummy_hash_never_matches() -> None:
    """The timing-equalisation hash does not match any real password."""
    assert verify_password(DUMMY_HASH, "password-1234") is False


def test_fresh_hash_does_not_need_rehash() -> None:
    """A hash made with current parameters needs no rehash."""
    assert needs_rehash(hash_password("correct horse battery")) is False


def test_garbage_hash_needs_rehash() -> None:
    """A malformed hash is reported as needing a rehash."""
    assert needs_rehash("not-a-hash") is True
