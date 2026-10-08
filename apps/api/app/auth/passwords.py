"""Password hashing with argon2id."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

# Verified against when the user does not exist, so unknown-user logins cost the same time.
DUMMY_HASH: str = _hasher.hash("timing-equalisation-only")


def hash_password(password: str) -> str:
    """Hash a password with argon2id."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return True if the password matches the hash. Never raises."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError, TypeError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Return True if the hash uses outdated parameters or is not a valid hash."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
