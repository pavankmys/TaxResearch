"""Unit tests for /v1/provisions endpoints and review task amendment enrichment."""

import uuid
from datetime import date
from typing import Any

from app.auth.deps import CurrentUser, get_current_user
from app.db import get_session
from app.routers import provisions
from fastapi import FastAPI
from fastapi.testclient import TestClient


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

    def scalar_one_or_none(self) -> Any:  # noqa: ANN401
        return self._row


class FakeProvisionsSession:
    """Answers provisions queries with predictable synthetic data."""

    def __init__(
        self,
        provision: dict[str, Any] | None = None,
        versions_by_date: dict[str, dict[str, Any]] | None = None,
        latest_version: dict[str, Any] | None = None,
        versions_by_id: dict[uuid.UUID, dict[str, Any]] | None = None,
        timeline_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.provision = provision
        self.versions_by_date = versions_by_date or {}
        self.latest_version = latest_version
        self.versions_by_id = versions_by_id or {}
        self.timeline_rows = timeline_rows or []
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:  # noqa: ANN401
        sql = str(statement)
        self.calls.append((sql, params))

        if "FROM provisions p" in sql:
            return FakeResult(row=self.provision)

        if "FROM provision_versions pv" in sql:
            if "pv.valid_from <= :as_on" in sql:
                as_on = str(params.get("as_on") if params else "")
                ver = self.versions_by_date.get(as_on, self.latest_version)
                return FakeResult(row=ver)
            if "pv.id = :id AND pv.provision_id = :provision_id" in sql:
                ver_id = params.get("id") if params else None
                return FakeResult(row=self.versions_by_id.get(ver_id))  # type: ignore[arg-type]
            if "SUBSTRING(pv.text FROM 1 FOR 200) AS text_preview" in sql:
                return FakeResult(rows=self.timeline_rows)
            return FakeResult(row=self.latest_version)

        return FakeResult()


def test_get_provision_found() -> None:
    prov_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    ver_id = uuid.uuid4()

    fake_prov = {
        "id": prov_id,
        "instrument_id": inst_id,
        "instrument_code": "CGST_RULES",
        "instrument_short_name": "CGST Rules, 2017",
        "path": "r36.4",
        "level": "rule",
        "number_label": "4",
        "ordinal": 4,
    }
    fake_ver = {
        "id": ver_id,
        "heading": "Documentary requirements",
        "text": (
            "Input tax credit to be availed by a registered person shall not exceed 105 per cent."
        ),
        "valid_from": date(2020, 1, 1),
        "valid_to": None,
        "origin": "amendment",
        "created_by_amendment_id": None,
    }

    session = FakeProvisionsSession(provision=fake_prov, latest_version=fake_ver)

    app = FastAPI()
    app.include_router(provisions.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=uuid.uuid4(),
        email="test@example.com",
        display_name="Tester",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )

    client = TestClient(app)
    response = client.get(f"/v1/provisions/{prov_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(prov_id)
    assert data["path"] == "r36.4"
    assert data["version"]["heading"] == "Documentary requirements"
    assert "105 per cent" in data["version"]["text"]


def test_get_provision_with_as_on() -> None:
    prov_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    v1_id = uuid.uuid4()

    fake_prov = {
        "id": prov_id,
        "instrument_id": inst_id,
        "instrument_code": "CGST_RULES",
        "instrument_short_name": "CGST Rules, 2017",
        "path": "r36.4",
        "level": "rule",
        "number_label": "4",
        "ordinal": 4,
    }
    fake_v1 = {
        "id": v1_id,
        "heading": "Documentary requirements",
        "text": "Input tax credit shall not exceed 120 per cent.",
        "valid_from": date(2019, 10, 9),
        "valid_to": date(2020, 1, 1),
        "origin": "baseline",
        "created_by_amendment_id": None,
    }

    session = FakeProvisionsSession(
        provision=fake_prov,
        versions_by_date={"2019-11-01": fake_v1},
    )

    app = FastAPI()
    app.include_router(provisions.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=uuid.uuid4(),
        email="test@example.com",
        display_name="Tester",
        tenant_id=None,
        roles=frozenset({"junior"}),
    )

    client = TestClient(app)
    response = client.get(f"/v1/provisions/{prov_id}?as_on=2019-11-01")
    assert response.status_code == 200
    data = response.json()
    assert data["version"]["valid_from"] == "2019-10-09"
    assert "120 per cent" in data["version"]["text"]


def test_get_provision_timeline() -> None:
    prov_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    fake_prov = {
        "id": prov_id,
        "instrument_id": inst_id,
        "instrument_code": "CGST_RULES",
        "instrument_short_name": "CGST Rules, 2017",
        "path": "r36.4",
        "level": "rule",
        "number_label": "4",
        "ordinal": 4,
    }
    timeline_rows = [
        {
            "version_id": v1_id,
            "heading": "Baseline",
            "valid_from": date(2019, 10, 9),
            "valid_to": date(2020, 1, 1),
            "origin": "baseline",
            "text_chars": 50,
            "text_preview": "Input tax credit 120 per cent",
            "created_by_amendment_id": None,
            "source_document_id": None,
            "amending_doc_title": None,
            "amending_doc_number": None,
            "amending_doc_date": None,
        },
        {
            "version_id": v2_id,
            "heading": "Amended",
            "valid_from": date(2020, 1, 1),
            "valid_to": None,
            "origin": "amendment",
            "text_chars": 50,
            "text_preview": "Input tax credit 105 per cent",
            "created_by_amendment_id": uuid.uuid4(),
            "source_document_id": doc_id,
            "amending_doc_title": "Central Tax Notification 75/2019",
            "amending_doc_number": "75/2019",
            "amending_doc_date": date(2019, 12, 26),
        },
    ]

    session = FakeProvisionsSession(provision=fake_prov, timeline_rows=timeline_rows)

    app = FastAPI()
    app.include_router(provisions.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=uuid.uuid4(),
        email="test@example.com",
        display_name="Tester",
        tenant_id=None,
        roles=frozenset({"platform_admin"}),
    )

    client = TestClient(app)
    response = client.get(f"/v1/provisions/{prov_id}/timeline")
    assert response.status_code == 200
    data = response.json()
    assert data["provision_id"] == str(prov_id)
    assert len(data["items"]) == 2
    assert data["items"][0]["origin"] == "baseline"
    assert data["items"][1]["origin"] == "amendment"
    assert data["items"][1]["amending_document"]["number"] == "75/2019"


def test_get_provision_diff_dates() -> None:
    prov_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()

    fake_prov = {
        "id": prov_id,
        "instrument_id": inst_id,
        "instrument_code": "CGST_RULES",
        "instrument_short_name": "CGST Rules, 2017",
        "path": "r36.4",
        "level": "rule",
        "number_label": "4",
        "ordinal": 4,
    }
    fake_v1 = {
        "id": v1_id,
        "heading": "Rule 36(4)",
        "text": "shall not exceed 120 per cent of eligible credit.",
        "valid_from": date(2019, 10, 9),
        "valid_to": date(2020, 1, 1),
        "origin": "baseline",
    }
    fake_v2 = {
        "id": v2_id,
        "heading": "Rule 36(4)",
        "text": "shall not exceed 110 per cent of eligible credit.",
        "valid_from": date(2020, 1, 1),
        "valid_to": None,
        "origin": "amendment",
    }

    session = FakeProvisionsSession(
        provision=fake_prov,
        versions_by_date={"2019-11-01": fake_v1, "2020-02-01": fake_v2},
    )

    app = FastAPI()
    app.include_router(provisions.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=uuid.uuid4(),
        email="test@example.com",
        display_name="Tester",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )

    client = TestClient(app)
    response = client.get(f"/v1/provisions/{prov_id}/diff?from_date=2019-11-01&to_date=2020-02-01")
    assert response.status_code == 200
    data = response.json()
    assert data["identical"] is False
    assert "[-120-]{+110+}" in data["diff"]
    assert data["additions_count"] >= 1
    assert data["deletions_count"] >= 1


def test_get_provision_diff_validation() -> None:
    prov_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    fake_prov = {
        "id": prov_id,
        "instrument_id": inst_id,
        "instrument_code": "CGST_RULES",
        "instrument_short_name": "CGST Rules, 2017",
        "path": "r36.4",
        "level": "rule",
        "number_label": "4",
        "ordinal": 4,
    }

    session = FakeProvisionsSession(provision=fake_prov)

    app = FastAPI()
    app.include_router(provisions.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=uuid.uuid4(),
        email="test@example.com",
        display_name="Tester",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )

    client = TestClient(app)
    # Missing parameters
    response = client.get(f"/v1/provisions/{prov_id}/diff")
    assert response.status_code == 422
