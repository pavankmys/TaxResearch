"""Unit tests for the baseline endpoints: permissions, validation, and tree ordering.

The database session and audit writer are mocked, so these tests need no Postgres.
The router is mounted on a bare FastAPI app.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.auth import deps
from app.auth.deps import CurrentUser, get_current_user
from app.db import get_session
from app.routers import baseline
from fastapi import FastAPI
from fastapi.testclient import TestClient

BASELINE_PERMISSIONS = {"baseline.read", "baseline.verify"}
EDITOR_ROLES = {"platform_content_editor", "platform_admin"}


class FakeResult:
    def __init__(self, row: Any = None, rows: Any = None) -> None:  # noqa: ANN401
        self._row = row
        self._rows = rows or []

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> Any:  # noqa: ANN401
        return self._row

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar(self) -> Any:  # noqa: ANN401
        return self._row


class FakeSession:
    """Answers baseline SQL by type and records every statement."""

    def __init__(
        self,
        instruments: dict[str, dict[str, Any]] | None = None,
        provisions: list[dict[str, Any]] | None = None,
        provision_detail: dict[str, Any] | None = None,
        can_verify: bool = True,
    ) -> None:
        self.instruments = instruments or {}
        self.provisions = provisions or []
        self.provision_detail = provision_detail
        self.can_verify = can_verify
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:  # noqa: ANN401
        sql = str(statement)
        self.calls.append((sql, params))

        # Get instrument by code (before list check since it's more specific)
        if "FROM instruments i" in sql and ":code" in sql and "GROUP BY" in sql:
            if params and "code" in params:
                code = params["code"]
                if code in self.instruments:
                    return FakeResult(row=self.instruments[code])
            return FakeResult(row=None)

        # List instruments
        if "FROM instruments i" in sql and "COUNT(DISTINCT p.id)" in sql and "GROUP BY" in sql:
            return FakeResult(rows=list(self.instruments.values()))

        # List provisions
        if "FROM provisions p" in sql and "provision_versions pv" in sql:
            return FakeResult(rows=self.provisions)

        # Get provision detail
        if "JOIN provision_versions pv" in sql and ":provision_id" in sql:
            return FakeResult(row=self.provision_detail)

        # Verify baseline update
        if "UPDATE instruments" in sql and "baseline_status = 'verified'" in sql:
            if self.can_verify:
                result = self.instruments.get(params.get("code") if params else None)
                if result:
                    return FakeResult(row=result)
            return FakeResult(row=None)

        # Check baseline status
        if "SELECT baseline_status FROM instruments" in sql:
            if params and "code" in params:
                code = params["code"]
                if code in self.instruments:
                    status = self.instruments[code].get("baseline_status")
                    return FakeResult(row=status)
            return FakeResult(row=None)

        # Get verifier info
        if "SELECT u.display_name FROM users u" in sql:
            return FakeResult(row={"display_name": "Verifier Name"})

        # Count provisions
        if "COUNT(DISTINCT p.id)" in sql and "instrument_id" in sql and "FROM provisions" in sql:
            return FakeResult(
                row={
                    "provision_count": 5,
                    "section_count": 2,
                }
            )

        # Get min page
        if "SELECT MIN(b.page)" in sql:
            return FakeResult(row=1)

        return FakeResult()

    def writes(self) -> list[str]:
        return [
            sql for sql, _ in self.calls if sql.lstrip().upper().startswith(("UPDATE", "INSERT"))
        ]


def _user(*roles: str) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        email="user@example.test",
        display_name="User",
        tenant_id=None,
        roles=frozenset(roles),
    )


def _instrument(
    code: str = "TEST_ACT",
    status: str = "loaded",
    as_on: date | None = None,
    verified_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "code": code,
        "kind": "act",
        "short_name": "Test Act",
        "baseline_status": status,
        "baseline_as_on": as_on,
        "baseline_document_id": uuid.uuid4(),
        "baseline_verified_at": verified_at,
        "display_name": None if status != "verified" else "Verifier",
        "provision_count": 5,
        "section_count": 2,
    }


@pytest.fixture(autouse=True)
def _baseline_permissions(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = deps.has_permission

    def grant(roles: Any, action: str) -> bool:  # noqa: ANN401
        if action in BASELINE_PERMISSIONS:
            return bool(EDITOR_ROLES & set(roles))
        return original(roles, action)

    monkeypatch.setattr(deps, "has_permission", grant)
    yield


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(baseline, "write_audit", mock)
    return mock


def _client(user: CurrentUser, session: FakeSession) -> TestClient:
    app = FastAPI()
    app.include_router(baseline.router)

    async def override_user() -> CurrentUser:
        return user

    async def override_session() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_list_without_permission_is_403() -> None:
    session = FakeSession()
    client = _client(_user("professional"), session)
    response = client.get("/v1/baseline/instruments")
    assert response.status_code == 403
    assert session.calls == []


def test_provisions_without_permission_is_403() -> None:
    session = FakeSession()
    client = _client(_user("junior"), session)
    response = client.get("/v1/baseline/instruments/TEST_ACT/provisions")
    assert response.status_code == 403
    assert session.calls == []


def test_provision_detail_without_permission_is_403() -> None:
    session = FakeSession()
    client = _client(_user("professional"), session)
    response = client.get(f"/v1/baseline/instruments/TEST_ACT/provisions/{uuid.uuid4()}")
    assert response.status_code == 403
    assert session.calls == []


def test_verify_without_permission_is_403(audit: AsyncMock) -> None:
    session = FakeSession()
    client = _client(_user("professional"), session)
    response = client.post("/v1/baseline/instruments/TEST_ACT/verify")
    assert response.status_code == 403
    assert session.calls == []
    audit.assert_not_called()


def test_list_instruments() -> None:
    instruments = {
        "CGST_ACT": _instrument("CGST_ACT", "verified", date(2024, 7, 1)),
        "CGST_RULES": _instrument("CGST_RULES", "loaded"),
    }
    session = FakeSession(instruments=instruments)
    client = _client(_user("platform_content_editor"), session)
    response = client.get("/v1/baseline/instruments")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["items"][0]["code"] == "CGST_ACT"
    assert data["items"][0]["baseline_status"] == "verified"


def test_list_instruments_response_shape() -> None:
    """Instruments list has correct response shape."""
    instruments = {
        "CGST_ACT": _instrument("CGST_ACT", "verified", date(2024, 7, 1)),
    }
    session = FakeSession(instruments=instruments)
    client = _client(_user("platform_admin"), session)
    response = client.get("/v1/baseline/instruments")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert "code" in item
    assert "baseline_status" in item
    assert "provision_count" in item


def test_provisions_404_unknown_instrument() -> None:
    session = FakeSession(instruments={})
    client = _client(_user("platform_content_editor"), session)
    response = client.get("/v1/baseline/instruments/UNKNOWN/provisions")
    assert response.status_code == 404


def test_provisions_tree_order() -> None:
    """Provisions are returned in depth-first tree order (s2, s10, s10.1)."""
    instruments = {"TEST_ACT": _instrument("TEST_ACT")}
    provisions = [
        {
            "id": uuid.uuid4(),
            "path": "1",
            "parent_id": None,
            "level": "section",
            "number_label": "2",
            "ordinal": 0,
            "heading": "Section 2",
            "text": "Content",
            "text_chars": 7,
            "version_id": uuid.uuid4(),
        },
        {
            "id": uuid.uuid4(),
            "path": "2",
            "parent_id": None,
            "level": "section",
            "number_label": "10",
            "ordinal": 1,
            "heading": "Section 10",
            "text": "Content",
            "text_chars": 7,
            "version_id": uuid.uuid4(),
        },
        {
            "id": uuid.uuid4(),
            "path": "2.1",
            "parent_id": uuid.uuid4(),
            "level": "subsection",
            "number_label": "1",
            "ordinal": 0,
            "heading": "Subsection 1",
            "text": "Content",
            "text_chars": 7,
            "version_id": uuid.uuid4(),
        },
    ]
    # Fix parent_id for subsection to point to s10
    prov_id_s10 = provisions[1]["id"]
    provisions[2]["parent_id"] = prov_id_s10

    session = FakeSession(instruments=instruments, provisions=provisions)
    client = _client(_user("platform_admin"), session)
    response = client.get("/v1/baseline/instruments/TEST_ACT/provisions")
    assert response.status_code == 200
    data = response.json()
    items = data["items"]
    # Should be s2, s10, s10.1 in order
    assert len(items) == 3
    assert items[0]["number_label"] == "2"
    assert items[1]["number_label"] == "10"
    assert items[2]["number_label"] == "1"
    assert items[0]["depth"] == 0
    assert items[1]["depth"] == 0
    assert items[2]["depth"] == 1


def test_provisions_numbering_gaps() -> None:
    """Numbering gaps for sections/rules are computed correctly."""
    instruments = {"TEST_ACT": _instrument("TEST_ACT")}
    provisions = [
        {
            "id": uuid.uuid4(),
            "path": "1",
            "parent_id": None,
            "level": "section",
            "number_label": "1",
            "ordinal": 0,
            "heading": None,
            "text": None,
            "text_chars": 0,
            "version_id": None,
        },
        {
            "id": uuid.uuid4(),
            "path": "2",
            "parent_id": None,
            "level": "section",
            "number_label": "2",
            "ordinal": 1,
            "heading": None,
            "text": None,
            "text_chars": 0,
            "version_id": None,
        },
        {
            "id": uuid.uuid4(),
            "path": "3",
            "parent_id": None,
            "level": "section",
            "number_label": "4",
            "ordinal": 2,
            "heading": None,
            "text": None,
            "text_chars": 0,
            "version_id": None,
        },
        {
            "id": uuid.uuid4(),
            "path": "4",
            "parent_id": None,
            "level": "section",
            "number_label": "7",
            "ordinal": 3,
            "heading": None,
            "text": None,
            "text_chars": 0,
            "version_id": None,
        },
    ]
    session = FakeSession(instruments=instruments, provisions=provisions)
    client = _client(_user("platform_content_editor"), session)
    response = client.get("/v1/baseline/instruments/TEST_ACT/provisions")
    assert response.status_code == 200
    data = response.json()
    # Sections 1,2,4,7 -> gaps are 3, 5, 6
    assert data["numbering_gaps"] == ["3", "5", "6"]


def test_provision_detail_404_not_found() -> None:
    session = FakeSession(instruments={})
    client = _client(_user("platform_admin"), session)
    response = client.get(f"/v1/baseline/instruments/TEST_ACT/provisions/{uuid.uuid4()}")
    assert response.status_code == 404


def test_verify_404_unknown_instrument(audit: AsyncMock) -> None:
    session = FakeSession(instruments={})
    client = _client(_user("platform_admin"), session)
    response = client.post("/v1/baseline/instruments/UNKNOWN/verify")
    assert response.status_code == 404
    audit.assert_not_called()


def test_verify_409_no_baseline_loaded(audit: AsyncMock) -> None:
    instruments = {"TEST_ACT": _instrument("TEST_ACT", "none")}
    session = FakeSession(instruments=instruments, can_verify=False)
    client = _client(_user("platform_admin"), session)
    response = client.post("/v1/baseline/instruments/TEST_ACT/verify")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "No baseline loaded" in detail or "Already verified" in detail
    audit.assert_not_called()


def test_verify_409_already_verified(audit: AsyncMock) -> None:
    instruments = {"TEST_ACT": _instrument("TEST_ACT", "verified", date(2024, 7, 1))}
    session = FakeSession(instruments=instruments, can_verify=False)
    client = _client(_user("platform_admin"), session)
    response = client.post("/v1/baseline/instruments/TEST_ACT/verify")
    assert response.status_code == 409
    assert "Already verified" in response.json()["detail"]
    audit.assert_not_called()
