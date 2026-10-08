"""M1 integration test: a tampered audit row is detected by verify-audit (real Postgres).

This module leaves the audit chain broken on purpose, so it has its own upgrade/downgrade
fixture and never shares a database state with ``test_m1_db.py``.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.audit import write_audit
from app.settings import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parent.parent
JWT_SECRET = "integration-test-jwt-secret-0123456789ab"  # 40 characters
TRIGGER = "trg_audit_log_no_update_delete"


def _alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


async def _write_rows(url: str, actions: list[str]) -> None:
    engine = create_async_engine(_psycopg_url(url))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        for action in actions:
            async with factory() as session:
                await write_audit(session, action=action, detail={"source": "tamper-test"})
                await session.commit()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def db_env() -> Iterator[str]:
    """Upgrade to head for the module and downgrade to base afterwards."""
    url = os.environ.get("DATABASE_URL", "")
    if not url or "localhost/test" in url:
        pytest.skip("DATABASE_URL not set to a real database; skipping integration tests")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        mp.setenv("JWT_SECRET", JWT_SECRET)
        get_settings.cache_clear()
        config = _alembic_config()
        command.upgrade(config, "head")
        try:
            yield url
        finally:
            command.downgrade(config, "base")
            get_settings.cache_clear()


def test_tampered_audit_row_is_detected(db_env: str) -> None:
    asyncio.run(_write_rows(db_env, ["test.tamper.one", "test.tamper.two", "test.tamper.three"]))

    engine = create_engine(_psycopg_url(db_env))
    try:
        with engine.connect() as conn:
            target_seq = conn.execute(
                text("SELECT seq FROM audit_log ORDER BY seq OFFSET 1 LIMIT 1")
            ).scalar_one()

        # Bypass the append-only trigger for one UPDATE, then restore it in the same transaction.
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE audit_log DISABLE TRIGGER {TRIGGER}"))
            conn.execute(
                text("UPDATE audit_log SET action = 'tampered' WHERE seq = :seq"),
                {"seq": target_seq},
            )
            conn.execute(text(f"ALTER TABLE audit_log ENABLE TRIGGER {TRIGGER}"))
    finally:
        engine.dispose()

    env = {key: value for key, value in os.environ.items() if key != "TAXRESEARCH_PASSWORD"}
    env["DATABASE_URL"] = db_env
    env["JWT_SECRET"] = JWT_SECRET
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "verify-audit"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"audit chain BROKEN at seq {target_seq}" in result.stdout
