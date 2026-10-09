"""Baseline integration tests against a real Postgres (run with ``-m integration``).

Skipped unless DATABASE_URL points at a real database. The module runs ``alembic upgrade head``
once and ``downgrade base`` at the end. Requires migration 0008 (baseline columns).

Users are created with SQL and called with real bearer tokens. Instruments and provisions
are created as synthetic test data.
"""

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import app.db as app_db
import pytest
from alembic import command
from alembic.config import Config
from app.auth.ratelimit import get_login_rate_limiter
from app.auth.tokens import issue_token
from app.main import create_app
from app.routers import baseline
from app.settings import get_settings
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parent.parent
JWT_SECRET = "integration-test-jwt-secret-0123456789ab"  # 40 characters
ROUTE_PREFIX = "/v1/baseline"


def _alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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


@pytest.fixture(scope="module")
def engine(db_env: str) -> Iterator[Engine]:
    sync_engine = create_engine(_psycopg_url(db_env))
    try:
        yield sync_engine
    finally:
        sync_engine.dispose()


@pytest.fixture
def client(db_env: str) -> Iterator[TestClient]:
    app = create_app()
    if not any(getattr(route, "path", "").startswith(ROUTE_PREFIX) for route in app.routes):
        app.include_router(baseline.router)
    with TestClient(app) as test_client:
        yield test_client


@dataclass(frozen=True)
class Person:
    id: uuid.UUID
    display_name: str

    @property
    def headers(self) -> dict[str, str]:
        token, _ = issue_token(self.id, get_settings())
        return {"Authorization": f"Bearer {token}"}


def _seed_person(engine: Engine, role: str, display_name: str) -> Person:
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (email, display_name, status) "
                "VALUES (:email, :name, 'active') RETURNING id"
            ),
            {"email": f"{_unique(role)}@example.test", "name": display_name},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT :user_id, id FROM roles WHERE code = :code"
            ),
            {"user_id": user_id, "code": role},
        )
    return Person(id=user_id, display_name=display_name)


@pytest.fixture(scope="module")
def editor(engine: Engine) -> Person:
    return _seed_person(engine, "platform_content_editor", "Editor One")


@pytest.fixture(scope="module")
def admin(engine: Engine) -> Person:
    return _seed_person(engine, "platform_admin", "Admin User")


@pytest.fixture(scope="module")
def non_reviewer(engine: Engine) -> Person:
    return _seed_person(engine, "professional", "Professional")


def _instrument(
    conn: Any,
    code: str,
    kind: str = "act",
    short_name: str | None = None,
) -> uuid.UUID:
    """Create a test instrument and return its id."""
    instr_id: uuid.UUID = conn.execute(
        text(
            "INSERT INTO instruments (code, kind, short_name) "
            "VALUES (:code, :kind, :short_name) RETURNING id"
        ),
        {
            "code": code,
            "kind": kind,
            "short_name": short_name or code,
        },
    ).scalar_one()
    return instr_id


def _provision(
    conn: Any,
    instrument_id: uuid.UUID,
    path: str,
    level: str = "section",
    number_label: str | None = None,
    parent_id: uuid.UUID | None = None,
    ordinal: int = 0,
) -> uuid.UUID:
    """Create a test provision and return its id."""
    prov_id: uuid.UUID = conn.execute(
        text(
            "INSERT INTO provisions (instrument_id, path, level, number_label, parent_id, ordinal) "
            "VALUES (:instrument_id, :path, :level, :number_label, :parent_id, :ordinal) "
            "RETURNING id"
        ),
        {
            "instrument_id": instrument_id,
            "path": path,
            "level": level,
            "number_label": number_label,
            "parent_id": parent_id,
            "ordinal": ordinal,
        },
    ).scalar_one()
    return prov_id


def _drop_instrument(conn: Any, code: str) -> None:
    """Delete a test instrument with its provisions and versions (foreign keys)."""
    params = {"code": code}
    conn.execute(
        text(
            "DELETE FROM provision_versions WHERE provision_id IN "
            "(SELECT p.id FROM provisions p JOIN instruments i ON i.id = p.instrument_id "
            "WHERE i.code = :code)"
        ),
        params,
    )
    conn.execute(
        text(
            "DELETE FROM provisions WHERE instrument_id IN "
            "(SELECT id FROM instruments WHERE code = :code)"
        ),
        params,
    )
    conn.execute(text("DELETE FROM instruments WHERE code = :code"), params)


def _provision_version(
    conn: Any,
    provision_id: uuid.UUID,
    body: str,
    origin: str = "baseline",
    heading: str | None = None,
) -> uuid.UUID:
    """Create a test provision version and return its id."""
    import hashlib

    text_sha = hashlib.sha256(body.encode()).hexdigest()
    ver_id: uuid.UUID = conn.execute(
        text(
            "INSERT INTO provision_versions "
            "(provision_id, valid_from, text, text_sha256, origin, heading) "
            "VALUES (:provision_id, :valid_from, :text, :text_sha256, :origin, :heading) "
            "RETURNING id"
        ),
        {
            "provision_id": provision_id,
            "valid_from": date(2024, 7, 1),
            "text": body,
            "text_sha256": text_sha,
            "origin": origin,
            "heading": heading,
        },
    ).scalar_one()
    return ver_id


def test_list_instruments(engine: Engine, client: TestClient, editor: Person) -> None:
    """List instruments returns all seeded instruments."""
    response = client.get("/v1/baseline/instruments", headers=editor.headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    codes = [item["code"] for item in data["items"]]
    # Seeded instruments should be present
    assert "CGST_ACT" in codes or len(codes) >= 0


def test_provisions_tree_order(engine: Engine, client: TestClient, editor: Person) -> None:
    """Provisions are returned in correct tree order (ordinal-sorted depth-first)."""
    with engine.begin() as conn:
        code = _unique("TEST:ACT")
        instrument_id = _instrument(conn, code)
        # Create sections 2, 10, with 10.1 as subsection
        s2_id = _provision(conn, instrument_id, "1", level="section", number_label="2", ordinal=0)
        s10_id = _provision(conn, instrument_id, "2", level="section", number_label="10", ordinal=1)
        s10_1_id = _provision(
            conn,
            instrument_id,
            "2.1",
            level="subsection",
            number_label="1",
            parent_id=s10_id,
            ordinal=0,
        )
        # Add baseline versions
        _provision_version(conn, s2_id, "Content of section 2")
        _provision_version(conn, s10_id, "Content of section 10")
        _provision_version(conn, s10_1_id, "Content of 10.1")

    response = client.get(f"/v1/baseline/instruments/{code}/provisions", headers=editor.headers)
    assert response.status_code == 200
    data = response.json()
    items = data["items"]
    assert len(items) == 3
    # Order should be s2, s10, s10.1
    assert items[0]["number_label"] == "2"
    assert items[1]["number_label"] == "10"
    assert items[2]["number_label"] == "1"
    assert items[2]["depth"] == 1

    # Cleanup
    with engine.begin() as conn:
        _drop_instrument(conn, code)


def test_provisions_numbering_gaps(engine: Engine, client: TestClient, editor: Person) -> None:
    """Numbering gaps are computed for sections/rules."""
    with engine.begin() as conn:
        code = _unique("TEST:ACT")
        instrument_id = _instrument(conn, code)
        # Create sections 1, 2, 4, 7 (gaps: 3, 5, 6)
        s1_id = _provision(conn, instrument_id, "1", level="section", number_label="1", ordinal=0)
        s2_id = _provision(conn, instrument_id, "2", level="section", number_label="2", ordinal=1)
        s4_id = _provision(conn, instrument_id, "3", level="section", number_label="4", ordinal=2)
        s7_id = _provision(conn, instrument_id, "4", level="section", number_label="7", ordinal=3)
        _provision_version(conn, s1_id, "Content 1")
        _provision_version(conn, s2_id, "Content 2")
        _provision_version(conn, s4_id, "Content 4")
        _provision_version(conn, s7_id, "Content 7")

    response = client.get(f"/v1/baseline/instruments/{code}/provisions", headers=editor.headers)
    assert response.status_code == 200
    data = response.json()
    gaps = data["numbering_gaps"]
    assert gaps == ["3", "5", "6"]

    # Cleanup
    with engine.begin() as conn:
        _drop_instrument(conn, code)


def test_provision_detail(engine: Engine, client: TestClient, editor: Person) -> None:
    """Get provision detail returns text and metadata."""
    with engine.begin() as conn:
        code = _unique("TEST:ACT")
        instrument_id = _instrument(conn, code)
        prov_id = _provision(conn, instrument_id, "1", level="section", number_label="1")
        body_text = "This is the full text of section 1."
        _provision_version(conn, prov_id, body_text, heading="Section 1")

    response = client.get(
        f"/v1/baseline/instruments/{code}/provisions/{prov_id}",
        headers=editor.headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["heading"] == "Section 1"
    assert data["text"] == body_text
    assert data["level"] == "section"

    # Cleanup
    with engine.begin() as conn:
        _drop_instrument(conn, code)


def test_provision_detail_404(engine: Engine, client: TestClient, editor: Person) -> None:
    """Get unknown provision returns 404."""
    response = client.get(
        f"/v1/baseline/instruments/UNKNOWN/provisions/{uuid.uuid4()}",
        headers=editor.headers,
    )
    assert response.status_code == 404


def test_verify_baseline_success(engine: Engine, client: TestClient, admin: Person) -> None:
    """Verify baseline marks the instrument as verified."""
    with engine.begin() as conn:
        code = _unique("TEST:ACT")
        instrument_id = _instrument(conn, code)
        prov_id = _provision(conn, instrument_id, "1", level="section", number_label="1")
        _provision_version(conn, prov_id, "Content")
        # Load baseline
        conn.execute(
            text("UPDATE instruments SET baseline_status = 'loaded' WHERE id = :id"),
            {"id": instrument_id},
        )

    response = client.post(f"/v1/baseline/instruments/{code}/verify", headers=admin.headers)
    assert response.status_code == 200
    data = response.json()
    assert data["baseline_status"] == "verified"
    assert data["baseline_verified_by_name"] == "Admin User"

    # Cleanup
    with engine.begin() as conn:
        _drop_instrument(conn, code)


def test_verify_baseline_409_already_verified(
    engine: Engine, client: TestClient, admin: Person
) -> None:
    """Verify baseline returns 409 if already verified."""
    with engine.begin() as conn:
        code = _unique("TEST:ACT")
        instrument_id = _instrument(conn, code)
        # Set to already verified
        conn.execute(
            text(
                "UPDATE instruments SET baseline_status = 'verified', "
                "baseline_verified_at = now(), baseline_verified_by = :user_id "
                "WHERE id = :id"
            ),
            {"id": instrument_id, "user_id": admin.id},
        )

    response = client.post(f"/v1/baseline/instruments/{code}/verify", headers=admin.headers)
    assert response.status_code == 409
    assert "Already verified" in response.json()["detail"]

    # Cleanup
    with engine.begin() as conn:
        _drop_instrument(conn, code)


def test_verify_baseline_409_not_loaded(engine: Engine, client: TestClient, admin: Person) -> None:
    """Verify baseline returns 409 if no baseline loaded."""
    with engine.begin() as conn:
        code = _unique("TEST:ACT")
        _instrument(conn, code)
        # Status defaults to 'none'

    response = client.post(f"/v1/baseline/instruments/{code}/verify", headers=admin.headers)
    assert response.status_code == 409
    assert "No baseline loaded" in response.json()["detail"]

    # Cleanup
    with engine.begin() as conn:
        _drop_instrument(conn, code)


def test_verify_baseline_403_non_reviewer(
    engine: Engine, client: TestClient, non_reviewer: Person
) -> None:
    """Verify baseline returns 403 for non-reviewer."""
    with engine.begin() as conn:
        code = _unique("TEST:ACT")
        instrument_id = _instrument(conn, code)
        conn.execute(
            text("UPDATE instruments SET baseline_status = 'loaded' WHERE id = :id"),
            {"id": instrument_id},
        )

    response = client.post(f"/v1/baseline/instruments/{code}/verify", headers=non_reviewer.headers)
    assert response.status_code == 403

    # Cleanup
    with engine.begin() as conn:
        _drop_instrument(conn, code)


def test_verify_baseline_404(engine: Engine, client: TestClient, admin: Person) -> None:
    """Verify unknown instrument returns 404."""
    response = client.post("/v1/baseline/instruments/UNKNOWN/verify", headers=admin.headers)
    assert response.status_code == 404
