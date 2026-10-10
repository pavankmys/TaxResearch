"""Unit tests for /v1/search and /v1/provisions/{id}/linked endpoints (TSD 6.1 - 6.10)."""

import uuid
from datetime import date
from typing import Any

from app.auth.deps import CurrentUser, get_current_user
from app.db import get_session
from app.routers import search
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeResult:
    def __init__(self, rows: Any = None) -> None:  # noqa: ANN401
        self._rows = rows or []

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSearchSession:
    def __init__(
        self,
        chunk_rows: list[Any] | None = None,
        link_rows: list[Any] | None = None,
    ) -> None:
        self.chunk_rows = chunk_rows or []
        self.link_rows = link_rows or []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:  # noqa: ANN401
        sql = str(statement)
        if "FROM chunks c" in sql:
            return FakeResult(rows=self.chunk_rows)
        if "FROM links l" in sql:
            return FakeResult(rows=self.link_rows)
        return FakeResult()


def _make_client(
    user: CurrentUser,
    chunk_rows: list[Any] | None = None,
    link_rows: list[Any] | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(search.router)
    fake_session = FakeSearchSession(chunk_rows=chunk_rows, link_rows=link_rows)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: fake_session
    return TestClient(app)


def test_search_empty_results() -> None:
    user = CurrentUser(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )
    client = _make_client(user, chunk_rows=[])

    resp = client.get("/v1/search?q=unmatched+query")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 0
    assert data["items"] == []
    assert "groups" in data


def test_search_with_expansion() -> None:
    user = CurrentUser(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )
    client = _make_client(user, chunk_rows=[])

    resp = client.get("/v1/search?q=eligibility+for+ITC&expand=true")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["expanded_terms"]) > 0


def test_search_results_with_chunks() -> None:
    user = CurrentUser(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    chunk_rows = [
        {
            "chunk_id": chunk_id,
            "document_id": doc_id,
            "document_version_id": uuid.uuid4(),
            "provision_version_id": None,
            "chunk_kind": "paragraph",
            "structure_path": "p1",
            "heading_path": "Notification 11/2017 > Paragraph 1",
            "text": "Rate of tax on supply of services...",
            "token_count": 50,
            "authority_rank": 5,
            "doc_type": "notification",
            "court_level": None,
            "state_code": None,
            "status_at_index": "in_force",
            "valid_from": date(2017, 6, 28),
            "valid_to": None,
            "doc_title": "Notification No. 11/2017-Central Tax (Rate)",
            "doc_canonical_id": "ntf:CT(R):11/2017",
            "raw_rank": 0.85,
            "snippet": "Rate of tax on <mark>supply</mark> of services...",
        }
    ]

    client = _make_client(user, chunk_rows=chunk_rows)

    resp = client.get("/v1/search?q=supply+of+services")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["chunk_id"] == str(chunk_id)
    assert item["doc_type"] == "notification"
    assert item["passage_count"] == 1
    assert data["groups"]["notifications"] == 1


def test_provision_linked_endpoint() -> None:
    user = CurrentUser(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        tenant_id=None,
        roles=frozenset({"professional"}),
    )
    prov_id = uuid.uuid4()
    doc1_id = uuid.uuid4()
    doc2_id = uuid.uuid4()

    link_rows = [
        {
            "link_id": uuid.uuid4(),
            "link_type": "inserts",
            "document_id": doc1_id,
            "title": "Finance Act, 2020",
            "doc_type": "act",
            "canonical_id": "act:FinanceAct:2020",
            "authority_rank": 2,
            "doc_date": date(2020, 3, 27),
            "in_force_date": date(2020, 6, 30),
            "source_block_id": None,
            "confidence": 1.0,
        },
        {
            "link_id": uuid.uuid4(),
            "link_type": "mentions",
            "document_id": doc2_id,
            "title": "Circular No. 183/15/2022-GST",
            "doc_type": "circular",
            "canonical_id": "cir:183/15/2022",
            "authority_rank": 8,
            "doc_date": date(2022, 12, 27),
            "in_force_date": date(2022, 12, 27),
            "source_block_id": uuid.uuid4(),
            "confidence": 0.95,
        },
    ]

    client = _make_client(user, link_rows=link_rows)

    resp = client.get(f"/v1/provisions/{prov_id}/linked")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provision_id"] == str(prov_id)
    assert data["total_count"] == 2
    assert len(data["groups"]["amending_instruments"]) == 1
    assert len(data["groups"]["mentions"]) == 1
    assert data["counts"]["amending_instruments"] == 1
    assert data["counts"]["mentions"] == 1
