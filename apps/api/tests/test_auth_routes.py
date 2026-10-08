"""Endpoint tests with dependency overrides. No database is used."""

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.auth.deps import CurrentUser, get_current_user
from app.auth.ratelimit import LoginRateLimiter, get_login_rate_limiter
from app.db import get_session
from fastapi import FastAPI
from fastapi.testclient import TestClient

ADMIN = CurrentUser(
    id=uuid.uuid4(),
    email="admin@example.com",
    display_name="Admin",
    tenant_id=None,
    roles=frozenset({"platform_admin"}),
)
PROFESSIONAL = CurrentUser(
    id=uuid.uuid4(),
    email="pro@example.com",
    display_name="Pro",
    tenant_id=None,
    roles=frozenset({"professional"}),
)


def _mock_session() -> AsyncMock:
    """A session whose execute() returns an empty result."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = 0
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    result.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


def _use_session(app: FastAPI, session: AsyncMock) -> None:
    async def _dep() -> AsyncGenerator[AsyncMock, None]:
        yield session

    app.dependency_overrides[get_session] = _dep


def _use_user(app: FastAPI, user: CurrentUser) -> None:
    async def _dep() -> CurrentUser:
        return user

    app.dependency_overrides[get_current_user] = _dep


def _use_limiter(app: FastAPI, limiter: Any) -> None:  # noqa: ANN401
    app.dependency_overrides[get_login_rate_limiter] = lambda: limiter


def test_me_without_token_is_401(client: TestClient) -> None:
    """No Authorization header gives 401 with a Bearer challenge."""
    _use_session(client.app, _mock_session())  # type: ignore[arg-type]
    response = client.get("/v1/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_with_user_returns_profile(client: TestClient) -> None:
    """An authenticated caller gets their profile, not cached."""
    _use_user(client.app, PROFESSIONAL)  # type: ignore[arg-type]
    response = client.get("/v1/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "pro@example.com"
    assert body["roles"] == ["professional"]
    assert response.headers["Cache-Control"] == "private, no-store"


def test_admin_users_forbidden_for_professional(client: TestClient) -> None:
    """A role without users.read gets 403."""
    _use_user(client.app, PROFESSIONAL)  # type: ignore[arg-type]
    _use_session(client.app, _mock_session())  # type: ignore[arg-type]
    response = client.get("/v1/admin/users")
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


def test_admin_users_list_for_platform_admin(client: TestClient) -> None:
    """platform_admin can list users; an empty result gives an empty page."""
    _use_user(client.app, ADMIN)  # type: ignore[arg-type]
    _use_session(client.app, _mock_session())  # type: ignore[arg-type]
    response = client.get("/v1/admin/users")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None, "total": 0}
    assert response.headers["Cache-Control"] == "private, no-store"


def test_login_blocked_returns_429(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A blocked key gets 429 and an auth.login_blocked audit row is written."""
    limiter = MagicMock()
    limiter.is_blocked.return_value = True
    audit = AsyncMock()
    monkeypatch.setattr("app.routers.auth.write_audit", audit)
    session = _mock_session()
    _use_limiter(client.app, limiter)
    _use_session(client.app, session)  # type: ignore[arg-type]

    response = client.post(
        "/v1/auth/login",
        json={"email": "user@example.com", "password": "correct horse battery"},
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many failed attempts. Try again later."}
    assert audit.call_args.kwargs["action"] == "auth.login_blocked"
    session.commit.assert_awaited()


def test_login_unknown_user_is_generic_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown email gets the generic 401 and an audit row with the reason."""
    audit = AsyncMock()
    monkeypatch.setattr("app.routers.auth.write_audit", audit)
    session = _mock_session()
    _use_limiter(client.app, LoginRateLimiter(max_failures=5, window_seconds=900))
    _use_session(client.app, session)  # type: ignore[arg-type]

    response = client.post(
        "/v1/auth/login",
        json={"email": "nobody@example.com", "password": "correct horse battery"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert audit.call_args.kwargs["action"] == "auth.login_failed"
    assert audit.call_args.kwargs["detail"] == {
        "email": "nobody@example.com",
        "reason": "unknown_user",
    }
    session.commit.assert_awaited()
