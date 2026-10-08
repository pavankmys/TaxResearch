"""Session JWTs (HS256). Tokens carry only identity; roles are read from the database."""

import uuid
from datetime import UTC, datetime
from uuid import UUID

import jwt

from app.settings import Settings

ALGORITHM = "HS256"
REQUIRED_CLAIMS = ["sub", "exp", "iat"]


class InvalidTokenError(Exception):
    """Raised when a token is malformed, badly signed, expired or missing claims."""


def issue_token(user_id: UUID, settings: Settings) -> tuple[str, int]:
    """Issue a signed token for the user. Returns (token, expires_in_seconds)."""
    issued_at = int(datetime.now(UTC).timestamp())
    ttl_seconds = settings.jwt_ttl_minutes * 60
    claims = {
        "sub": str(user_id),
        "jti": uuid.uuid4().hex,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)
    return token, ttl_seconds


def decode_token(token: str, settings: Settings) -> UUID:
    """Verify a token and return the user id from its ``sub`` claim."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("invalid token") from exc

    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise InvalidTokenError("missing subject")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise InvalidTokenError("invalid subject") from exc
