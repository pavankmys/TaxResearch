"""Tests for settings configuration."""

import os
from unittest.mock import patch

import pytest
from app.settings import Settings, get_settings

SECRET = "test-only-jwt-secret-0123456789abcdefghi"


def test_database_url_required() -> None:
    """Test that DATABASE_URL is required."""
    # Clear any cached settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError):
            # This should fail because DATABASE_URL is required
            Settings()


def test_database_url_normalization() -> None:
    """Test that postgresql:// is normalized to postgresql+psycopg://."""
    settings = Settings(database_url="postgresql://user:pass@localhost/db", jwt_secret=SECRET)
    normalized = settings.get_database_url()
    assert normalized == "postgresql+psycopg://user:pass@localhost/db"


def test_database_url_already_normalized() -> None:
    """Test that postgresql+psycopg:// is not double-normalized."""
    settings = Settings(
        database_url="postgresql+psycopg://user:pass@localhost/db", jwt_secret=SECRET
    )
    normalized = settings.get_database_url()
    assert normalized == "postgresql+psycopg://user:pass@localhost/db"


def test_cors_origins_parsing() -> None:
    """Test CORS origins parsing from comma-separated string."""
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        jwt_secret=SECRET,
        cors_origins="http://localhost:3000, https://example.com , http://api.local",
    )
    origins = settings.get_cors_origins_list()
    assert origins == [
        "http://localhost:3000",
        "https://example.com",
        "http://api.local",
    ]


def test_cors_origins_empty() -> None:
    """Test CORS origins when empty."""
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        jwt_secret=SECRET,
        cors_origins="",
    )
    origins = settings.get_cors_origins_list()
    assert origins == []


def test_cors_origins_whitespace() -> None:
    """Test CORS origins with only whitespace."""
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        jwt_secret=SECRET,
        cors_origins="   ",
    )
    origins = settings.get_cors_origins_list()
    assert origins == []


def test_default_values() -> None:
    """Test default configuration values."""
    settings = Settings(database_url="postgresql://u:p@localhost/db", jwt_secret=SECRET)
    assert settings.api_port == 8000
    assert settings.log_level == "INFO"
    assert settings.cors_origins == ""


def test_custom_values() -> None:
    """Test custom configuration values."""
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        jwt_secret=SECRET,
        api_port=9000,
        log_level="DEBUG",
    )
    assert settings.api_port == 9000
    assert settings.log_level == "DEBUG"
