"""M1 integration tests against a real Postgres (run with ``-m integration``).

Skipped unless DATABASE_URL points at a real database. The module runs ``alembic upgrade head``
once and ``downgrade base`` at the end, so the database is left as it was found.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import app.db as app_db
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.audit import verify_chain, write_audit
from app.auth.ratelimit import get_login_rate_limiter
from app.main import create_app
from app.settings import get_settings
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parent.parent
JWT_SECRET = "integration-test-jwt-secret-0123456789ab"  # 40 characters
ADMIN_PASSWORD = "admin-password-integration"
USER_PASSWORD = "user-password-integration"
MODULE_TABLES = ("users", "audit_log", "provision_versions", "chunks", "review_tasks")
SEEDED_ROLES = {
    "platform_admin",
    "platform_content_editor",
    "firm_admin",
    "partner",
    "professional",
    "junior",
    "client_viewer",
}


def _alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}@example.test"


def _run_cli(url: str, *args: str, password: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "TAXRESEARCH_PASSWORD"}
    env["DATABASE_URL"] = url
    env["JWT_SECRET"] = JWT_SECRET
    if password is not None:
        env["TAXRESEARCH_PASSWORD"] = password
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _create_user_cli(url: str, email: str, role: str, password: str) -> None:
    result = _run_cli(
        url,
        "create-user",
        "--email",
        email,
        "--display-name",
        "Integration User",
        "--role",
        role,
        password=password,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _write_audit_rows(url: str, actions: list[str]) -> None:
    engine = create_async_engine(_psycopg_url(url))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        for action in actions:
            async with factory() as session:
                await write_audit(session, action=action, detail={"source": "test"})
                await session.commit()
    finally:
        await engine.dispose()


def _reset_app_state() -> None:
    get_settings.cache_clear()
    get_login_rate_limiter.cache_clear()
    app_db._engine = None


@pytest.fixture(scope="module")
def db_env() -> Iterator[str]:
    """Upgrade to head for the module and downgrade to base afterwards."""
    url = os.environ.get("DATABASE_URL", "")
    if not url or "localhost/test" in url:
        pytest.skip("DATABASE_URL not set to a real database; skipping integration tests")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        mp.setenv("JWT_SECRET", JWT_SECRET)
        mp.delenv("TAXRESEARCH_PASSWORD", raising=False)
        _reset_app_state()
        config = _alembic_config()
        command.upgrade(config, "head")
        try:
            yield url
        finally:
            command.downgrade(config, "base")
            _reset_app_state()


@pytest.fixture(autouse=True)
def _fresh_app_state(db_env: str) -> Iterator[None]:
    """Give each test its own settings, rate limiter and engine."""
    _reset_app_state()
    yield
    _reset_app_state()


def test_migrations_round_trip(db_env: str) -> None:
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    head = ScriptDirectory.from_config(config).get_current_head()

    engine = create_engine(_psycopg_url(db_env))
    try:
        with engine.connect() as conn:
            tables = set(
                conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = ANY(:names)"
                    ),
                    {"names": list(MODULE_TABLES)},
                ).scalars()
            )
            assert tables == set(MODULE_TABLES)
            codes = set(conn.execute(text("SELECT code FROM roles")).scalars())
            assert codes == SEEDED_ROLES
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert version == head
    finally:
        engine.dispose()


def test_provision_versions_no_overlap(db_env: str) -> None:
    suffix = uuid.uuid4().hex[:12]
    engine = create_engine(_psycopg_url(db_env))
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                instrument_id = conn.execute(
                    text(
                        "INSERT INTO instruments (code, kind, short_name) "
                        "VALUES (:code, 'act', 'Overlap test') RETURNING id"
                    ),
                    {"code": f"overlap-{suffix}"},
                ).scalar_one()
                provision_id = conn.execute(
                    text(
                        "INSERT INTO provisions (instrument_id, path, level, ordinal) "
                        "VALUES (:instrument_id, CAST(:path AS ltree), 'section', 1) RETURNING id"
                    ),
                    {"instrument_id": instrument_id, "path": f"p{suffix}"},
                ).scalar_one()

                insert_version = text(
                    "INSERT INTO provision_versions "
                    "(provision_id, valid_from, valid_to, text, text_sha256, origin) "
                    "VALUES (:provision_id, :valid_from, :valid_to, 'body', 'sha', 'baseline')"
                )
                conn.execute(
                    insert_version,
                    {
                        "provision_id": provision_id,
                        "valid_from": "2020-01-01",
                        "valid_to": "2021-01-01",
                    },
                )

                # Current (rec_to IS NULL) and overlapping: the exclusion constraint rejects it.
                with pytest.raises(IntegrityError, match="pv_no_overlap"):
                    with conn.begin_nested():
                        conn.execute(
                            insert_version,
                            {
                                "provision_id": provision_id,
                                "valid_from": "2020-06-01",
                                "valid_to": "2022-01-01",
                            },
                        )

                # Starts where the first one ends: half-open ranges do not overlap.
                conn.execute(
                    insert_version,
                    {"provision_id": provision_id, "valid_from": "2021-01-01", "valid_to": None},
                )
                count = conn.execute(
                    text("SELECT count(*) FROM provision_versions WHERE provision_id = :p"),
                    {"p": provision_id},
                ).scalar_one()
                assert count == 2
            finally:
                trans.rollback()

        with engine.connect() as conn:
            leftover = conn.execute(
                text("SELECT count(*) FROM instruments WHERE code = :code"),
                {"code": f"overlap-{suffix}"},
            ).scalar_one()
            assert leftover == 0
    finally:
        engine.dispose()


def test_audit_log_is_append_only(db_env: str) -> None:
    asyncio.run(_write_audit_rows(db_env, ["test.append_only"]))
    engine = create_engine(_psycopg_url(db_env))
    try:
        for statement in (
            "UPDATE audit_log SET action = 'tampered'",
            "DELETE FROM audit_log",
            "TRUNCATE audit_log",
        ):
            with engine.connect() as conn:
                with pytest.raises(DBAPIError, match="append-only"):
                    conn.execute(text(statement))
                conn.rollback()

        with engine.connect() as conn:
            remaining = conn.execute(
                text("SELECT count(*) FROM audit_log WHERE action = 'test.append_only'")
            ).scalar_one()
            assert remaining == 1
            tampered = conn.execute(
                text("SELECT count(*) FROM audit_log WHERE action = 'tampered'")
            ).scalar_one()
            assert tampered == 0
    finally:
        engine.dispose()


def _audit_items(
    client: TestClient, headers: dict[str, str], **params: Any
) -> list[dict[str, Any]]:
    response = client.get("/v1/admin/audit", headers=headers, params={"limit": 500, **params})
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def test_end_to_end_auth_and_admin(db_env: str) -> None:
    admin_email = _unique_email("admin")
    pro_email = _unique_email("pro")

    created = _run_cli(
        db_env,
        "create-user",
        "--email",
        admin_email,
        "--display-name",
        "Admin",
        "--role",
        "platform_admin",
        password=ADMIN_PASSWORD,
    )
    assert created.returncode == 0, created.stdout + created.stderr

    with TestClient(create_app()) as client:
        login = client.post(
            "/v1/auth/login", json={"email": admin_email, "password": ADMIN_PASSWORD}
        )
        assert login.status_code == 200, login.text
        admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        me = client.get("/v1/me", headers=admin_headers)
        assert me.status_code == 200, me.text
        assert me.json()["roles"] == ["platform_admin"]
        assert "no-store" in me.headers["cache-control"]
        admin_id = me.json()["id"]

        create_body = {
            "email": pro_email,
            "display_name": "Professional",
            "password": USER_PASSWORD,
            "roles": ["professional"],
        }
        created_pro = client.post("/v1/admin/users", headers=admin_headers, json=create_body)
        assert created_pro.status_code == 201, created_pro.text
        pro_id = created_pro.json()["id"]

        duplicate = client.post(
            "/v1/admin/users",
            headers=admin_headers,
            json={**create_body, "email": pro_email.upper()},
        )
        assert duplicate.status_code == 409, duplicate.text

        unknown_role = client.post(
            "/v1/admin/users",
            headers=admin_headers,
            json={**create_body, "email": _unique_email("badrole"), "roles": ["no_such_role"]},
        )
        assert unknown_role.status_code == 422, unknown_role.text

        pro_login = client.post(
            "/v1/auth/login", json={"email": pro_email, "password": USER_PASSWORD}
        )
        assert pro_login.status_code == 200, pro_login.text
        pro_headers = {"Authorization": f"Bearer {pro_login.json()['access_token']}"}

        forbidden = client.get("/v1/admin/users", headers=pro_headers)
        assert forbidden.status_code == 403, forbidden.text

        disabled = client.patch(
            f"/v1/admin/users/{pro_id}", headers=admin_headers, json={"status": "disabled"}
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "disabled"

        rejected = client.get("/v1/me", headers=pro_headers)
        assert rejected.status_code == 401, rejected.text

        self_disable = client.patch(
            f"/v1/admin/users/{admin_id}", headers=admin_headers, json={"status": "disabled"}
        )
        assert self_disable.status_code == 409, self_disable.text

        login_rows = _audit_items(
            client, admin_headers, action="auth.login_success", actor_user_id=admin_id
        )
        assert login_rows, "expected an auth.login_success row for the admin"
        create_rows = _audit_items(client, admin_headers, action="user.create", object_id=pro_id)
        assert len(create_rows) == 1
        update_rows = _audit_items(client, admin_headers, action="user.update", object_id=pro_id)
        assert update_rows, "expected a user.update row for the professional"

        _audit_items(client, admin_headers, action="audit.query")
        query_rows = _audit_items(client, admin_headers, action="audit.query")
        assert any(row["actor_user_id"] == admin_id for row in query_rows)

        logout = client.post("/v1/auth/logout", headers=admin_headers)
        assert logout.status_code == 204, logout.text

    verified = _run_cli(db_env, "verify-audit")
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "audit chain OK" in verified.stdout


def test_login_rate_limit(db_env: str) -> None:
    email = _unique_email("limit")
    _create_user_cli(db_env, email, "professional", USER_PASSWORD)

    with TestClient(create_app()) as client:
        for _ in range(5):
            wrong = client.post("/v1/auth/login", json={"email": email, "password": "wrong-pass-x"})
            assert wrong.status_code == 401, wrong.text

        blocked = client.post("/v1/auth/login", json={"email": email, "password": USER_PASSWORD})
        assert blocked.status_code == 429, blocked.text

    engine = create_engine(_psycopg_url(db_env))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT action, count(*) FROM audit_log "
                    "WHERE detail->>'email' = :email AND action LIKE 'auth.login_%' "
                    "GROUP BY action"
                ),
                {"email": email},
            ).all()
            counts = {action: count for action, count in rows}
            assert counts == {"auth.login_failed": 5, "auth.login_blocked": 1}
    finally:
        engine.dispose()


async def _write_audit_concurrently(url: str, count: int) -> int | None:
    engine = create_async_engine(_psycopg_url(url), pool_size=count, max_overflow=0)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _one(index: int) -> None:
        async with factory() as session:
            await write_audit(session, action="test.concurrent", detail={"index": index})
            await session.commit()

    try:
        await asyncio.gather(*(_one(index) for index in range(count)))
        async with factory() as session:
            return await verify_chain(session)
    finally:
        await engine.dispose()


def test_concurrent_audit_writes_keep_chain(db_env: str) -> None:
    count = 20
    bad_seq = asyncio.run(_write_audit_concurrently(db_env, count))
    assert bad_seq is None

    engine = create_engine(_psycopg_url(db_env))
    try:
        with engine.connect() as conn:
            seqs = list(
                conn.execute(
                    text("SELECT seq FROM audit_log WHERE action = 'test.concurrent'")
                ).scalars()
            )
    finally:
        engine.dispose()
    assert len(seqs) == count
    assert len(set(seqs)) == count
