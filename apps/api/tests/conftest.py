"""Test configuration and fixtures."""

import os
from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session", autouse=True)
def setup_test_env() -> None:
    """Set up test environment with a dummy DATABASE_URL if not set."""
    if not os.getenv("DATABASE_URL"):
        os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"


@pytest.fixture
def test_database_url() -> str:
    """Get test database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set; skipping integration tests")
    return url


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    # Import here to ensure setup_test_env runs first
    from app.main import create_app  # noqa: E402

    app = create_app()
    return TestClient(app)


@pytest.fixture
def anyio_backend() -> str:
    """Set asyncio as the backend for anyio."""
    return "asyncio"


@pytest.fixture
async def async_session(
    test_database_url: str,
) -> AsyncGenerator[AsyncSession, None]:
    """Create an async session for testing."""
    engine = create_async_engine(test_database_url, echo=False)
    async_session_local = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_local() as session:
        yield session
        await engine.dispose()
