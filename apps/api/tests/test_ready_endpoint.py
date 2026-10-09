"""Tests for /ready endpoint."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

from app.db import get_session
from fastapi.testclient import TestClient


def test_ready_ok(client: TestClient) -> None:
    """Test ready endpoint when database is available."""
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_session.execute.return_value = mock_result

    async def mock_dep() -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    # Override the dependency
    client.app.dependency_overrides[get_session] = mock_dep

    try:
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        # Verify execute was called
        mock_session.execute.assert_called_once()
    finally:
        client.app.dependency_overrides.clear()


def test_ready_unavailable(client: TestClient) -> None:
    """Test ready endpoint when database is unavailable."""
    mock_session = AsyncMock()
    mock_session.execute.side_effect = Exception("Connection refused")

    async def mock_dep() -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    # Override the dependency
    client.app.dependency_overrides[get_session] = mock_dep

    try:
        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["status"] == "unavailable"
        # Ensure no exception text is leaked
        assert "Connection refused" not in str(response.text)
    finally:
        client.app.dependency_overrides.clear()
