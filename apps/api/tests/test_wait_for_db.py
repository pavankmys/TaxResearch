"""Tests for scripts/wait_for_db.py URL parsing."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def load_wait_for_db_script():
    """Load wait_for_db.py as a module."""
    script_path = Path(__file__).parent.parent.parent.parent / "scripts" / "wait_for_db.py"
    spec = spec_from_file_location("wait_for_db", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {script_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_database_url_basic():
    """Test basic URL parsing."""
    wait_for_db = load_wait_for_db_script()
    url = "postgresql://user:password@localhost:5432/dbname"
    result = wait_for_db.parse_database_url(url)

    assert result["host"] == "localhost"
    assert result["port"] == 5432
    assert result["user"] == "user"
    assert result["password"] == "password"
    assert result["dbname"] == "dbname"


def test_parse_database_url_default_port():
    """Test URL parsing with default port."""
    wait_for_db = load_wait_for_db_script()
    url = "postgresql://user:password@localhost/dbname"
    result = wait_for_db.parse_database_url(url)

    assert result["host"] == "localhost"
    assert result["port"] == 5432
    assert result["dbname"] == "dbname"


def test_parse_database_url_special_chars_in_password():
    """Test URL parsing with special characters in password."""
    wait_for_db = load_wait_for_db_script()
    # Password with special chars: "p@ss:word" encoded as "p%40ss%3Aword"
    url = "postgresql://user:p%40ss%3Aword@localhost/dbname"
    result = wait_for_db.parse_database_url(url)

    assert result["user"] == "user"
    assert result["password"] == "p@ss:word"
    assert result["dbname"] == "dbname"


def test_parse_database_url_with_sslmode():
    """Test URL parsing with sslmode query parameter."""
    wait_for_db = load_wait_for_db_script()
    url = "postgresql://user:password@localhost/dbname?sslmode=require"
    result = wait_for_db.parse_database_url(url)

    assert result["host"] == "localhost"
    assert result["dbname"] == "dbname"
    assert "query_params" in result
    assert result["query_params"]["sslmode"] == "require"


def test_parse_database_url_multiple_query_params():
    """Test URL parsing with multiple query parameters."""
    wait_for_db = load_wait_for_db_script()
    url = "postgresql://user:password@localhost/dbname?sslmode=require&connect_timeout=10&sslrootcert=/path/to/cert"
    result = wait_for_db.parse_database_url(url)

    assert result["query_params"]["sslmode"] == "require"
    assert result["query_params"]["connect_timeout"] == "10"
    assert result["query_params"]["sslrootcert"] == "/path/to/cert"


def test_parse_database_url_postgres_scheme():
    """Test URL parsing with 'postgres' scheme (alias for postgresql)."""
    wait_for_db = load_wait_for_db_script()
    url = "postgres://user:password@localhost/dbname"
    result = wait_for_db.parse_database_url(url)

    assert result["user"] == "user"
    assert result["dbname"] == "dbname"


def test_parse_database_url_psycopg_scheme():
    """Test URL parsing with postgresql+psycopg scheme."""
    wait_for_db = load_wait_for_db_script()
    url = "postgresql+psycopg://user:password@localhost/dbname"
    result = wait_for_db.parse_database_url(url)

    assert result["user"] == "user"
    assert result["dbname"] == "dbname"


def test_parse_database_url_psycopg_async_scheme():
    """Test URL parsing with postgresql+psycopg_async scheme."""
    wait_for_db = load_wait_for_db_script()
    url = "postgresql+psycopg_async://user:password@localhost/dbname"
    result = wait_for_db.parse_database_url(url)

    assert result["user"] == "user"
    assert result["dbname"] == "dbname"


def test_parse_database_url_missing_dbname():
    """Test URL parsing with missing database name (should default to 'postgres')."""
    wait_for_db = load_wait_for_db_script()
    url = "postgresql://user:password@localhost"
    result = wait_for_db.parse_database_url(url)

    assert result["dbname"] == "postgres"


def test_parse_database_url_invalid_scheme():
    """Test URL parsing with invalid scheme raises ValueError."""
    wait_for_db = load_wait_for_db_script()
    url = "mysql://user:password@localhost/dbname"

    with pytest.raises(ValueError):
        wait_for_db.parse_database_url(url)
