"""Unit tests for /v1/resolve endpoint (TSD 6.3 & 8.2)."""

import uuid
from typing import Any

from app.auth.deps import CurrentUser, get_current_user
from app.db import get_session
from app.routers import resolve
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeResult:
    def __init__(self, rows: Any = None) -> None:  # noqa: ANN401
        self._rows = rows or []

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeResolveSession:
    def __init__(self, prov_rows: list[Any] | None = None) -> None:
        self.prov_rows = prov_rows or []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:  # noqa: ANN401
        sql = str(statement)
        if "FROM provisions p" in sql:
            return FakeResult(rows=self.prov_rows)
        return FakeResult()


def _make_client(user: CurrentUser, prov_rows: list[Any] | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(resolve.router)
    fake_session = FakeResolveSession(prov_rows=prov_rows)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: fake_session
    return TestClient(app)


def test_resolve_empty_query() -> None:
    user = CurrentUser(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )
    client = _make_client(user)
    resp = client.get("/v1/resolve?q=")
    assert resp.status_code == 200
    data = resp.json()
    assert data["matched"] is False


def test_resolve_unmatched_query() -> None:
    user = CurrentUser(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )
    client = _make_client(user)
    resp = client.get("/v1/resolve?q=some random string")
    assert resp.status_code == 200
    data = resp.json()
    assert data["matched"] is False


def test_resolve_provision_success() -> None:
    user = CurrentUser(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )
    prov_id = uuid.uuid4()
    prov_rows = [
        (prov_id, "s16.2.c", "clause", "CGST_ACT", "CGST Act"),
    ]
    client = _make_client(user, prov_rows=prov_rows)

    resp = client.get("/v1/resolve?q=s.16(2)(c) CGST")
    assert resp.status_code == 200
    data = resp.json()
    assert data["matched"] is True
    assert data["kind"] == "provision"
    assert data["entity_id"] == str(prov_id)
    assert "CGST Act" in data["title"]
