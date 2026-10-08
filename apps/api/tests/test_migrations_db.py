"""Integration tests: run the migrations against a real Postgres (skipped without DATABASE_URL)."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url or "localhost/test" in url:
        pytest.skip("DATABASE_URL not set to a real database; skipping integration tests")
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def test_upgrade_then_downgrade(db_url: str) -> None:
    from app.settings import get_settings

    get_settings.cache_clear()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(config, "head")
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            names = {r[0] for r in conn.execute(text("SELECT extname FROM pg_extension"))}
            assert {"pg_trgm", "btree_gist", "ltree", "citext"} <= names
            conn.execute(text("INSERT INTO corpus_versions (reason) VALUES ('test')"))
            count = conn.execute(text("SELECT count(*) FROM corpus_versions")).scalar_one()
            assert count >= 1
        command.downgrade(config, "base")
        with engine.begin() as conn:
            exists = conn.execute(text("SELECT to_regclass('public.corpus_versions')")).scalar_one()
            assert exists is None
    finally:
        engine.dispose()
