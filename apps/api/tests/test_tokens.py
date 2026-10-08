"""Tests for session JWT issue and decode."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.auth.tokens import InvalidTokenError, decode_token, issue_token
from app.settings import Settings

SECRET = "test-only-jwt-secret-0123456789abcdefghi"
OTHER_SECRET = "another-test-secret-0123456789abcdefgh"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql://u:p@localhost/db",
        "jwt_secret": SECRET,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_round_trip_returns_user_id() -> None:
    """A freshly issued token decodes to the same user id."""
    user_id = uuid.uuid4()
    token, expires_in = issue_token(user_id, _settings())
    assert decode_token(token, _settings()) == user_id
    assert expires_in == 480 * 60


def test_token_carries_only_identity_claims() -> None:
    """Roles are never embedded in the token."""
    token, _ = issue_token(uuid.uuid4(), _settings())
    claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    assert set(claims) == {"sub", "jti", "iat", "exp"}


def test_expired_token_rejected() -> None:
    """A token whose exp is in the past is rejected."""
    settings = _settings()
    token, _ = issue_token(uuid.uuid4(), settings.model_copy(update={"jwt_ttl_minutes": -1}))
    with pytest.raises(InvalidTokenError):
        decode_token(token, settings)


def test_wrong_secret_rejected() -> None:
    """A token signed with another secret is rejected."""
    token, _ = issue_token(uuid.uuid4(), _settings())
    with pytest.raises(InvalidTokenError):
        decode_token(token, _settings(jwt_secret=OTHER_SECRET))


def test_tampered_payload_rejected() -> None:
    """Changing the subject invalidates the signature."""
    token, _ = issue_token(uuid.uuid4(), _settings())
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["sub"] = str(uuid.uuid4())
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(InvalidTokenError):
        decode_token(f"{header}.{forged}.{signature}", _settings())


def test_missing_subject_rejected() -> None:
    """A correctly signed token without sub is rejected."""
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        decode_token(token, _settings())


def test_missing_expiry_rejected() -> None:
    """A correctly signed token without exp is rejected."""
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "jti": uuid.uuid4().hex, "iat": 1_700_000_000},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        decode_token(token, _settings())


def test_garbage_token_rejected() -> None:
    """A string that is not a JWT is rejected."""
    with pytest.raises(InvalidTokenError):
        decode_token("not-a-jwt", _settings())


def test_non_uuid_subject_rejected() -> None:
    """A signed token whose sub is not a UUID is rejected."""
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {"sub": "not-a-uuid", "jti": uuid.uuid4().hex, "iat": now, "exp": now + 300},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        decode_token(token, _settings())
