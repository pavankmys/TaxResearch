"""Tests for Alembic migrations (offline SQL; no database needed)."""

import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

API_ROOT = Path(__file__).resolve().parent.parent


def _offline_sql(monkeypatch: pytest.MonkeyPatch, direction: str) -> str:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    from app.settings import get_settings

    get_settings.cache_clear()
    buffer = io.StringIO()
    config = Config(str(API_ROOT / "alembic.ini"), output_buffer=buffer)
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    if direction == "up":
        command.upgrade(config, "head", sql=True)
    else:
        command.downgrade(config, "head:base", sql=True)
    get_settings.cache_clear()
    return buffer.getvalue()


def test_upgrade_sql_creates_extensions_and_table(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _offline_sql(monkeypatch, "up")
    for ext in ("pg_trgm", "btree_gist", "ltree", "citext"):
        assert f"CREATE EXTENSION IF NOT EXISTS {ext}" in sql
    assert "CREATE TABLE corpus_versions" in sql
    assert "GENERATED ALWAYS AS IDENTITY" in sql


def test_downgrade_sql_drops_table_but_keeps_extensions(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _offline_sql(monkeypatch, "down")
    assert "DROP TABLE corpus_versions" in sql
    assert "DROP EXTENSION" not in sql


def test_upgrade_sql_creates_job_queue_table(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _offline_sql(monkeypatch, "up")
    assert "CREATE TABLE job_queue" in sql
    assert "id UUID" in sql or "id uuid" in sql.lower()
    assert "queue TEXT" in sql or "queue text" in sql.lower()
    assert "payload JSON" in sql or "payload jsonb" in sql.lower()
    assert "status TEXT" in sql or "status text" in sql.lower()
    assert "CHECK" in sql and "queued" in sql and "running" in sql


def test_upgrade_sql_creates_job_queue_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _offline_sql(monkeypatch, "up")
    # Check for unique partial index on (queue, idempotency_key)
    assert "UNIQUE" in sql
    assert "idempotency_key" in sql
    # Check for index on (queue, status, run_after)
    assert "CREATE INDEX" in sql


def test_downgrade_sql_drops_job_queue_table(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _offline_sql(monkeypatch, "down")
    assert "DROP TABLE job_queue" in sql
