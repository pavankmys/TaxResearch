"""Tests for the ingestion endpoints: permissions, validation, the happy path and job status.

The database session and the audit writer are replaced, so these tests need no Postgres.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.auth.deps import CurrentUser, get_current_user
from app.db import get_session
from app.main import create_app
from app.routers import ingestion
from fastapi.testclient import TestClient


class FakeResult:
    def __init__(self, value: Any = None, row: Any = None) -> None:  # noqa: ANN401
        self._value = value
        self._row = row

    def scalar_one(self) -> Any:  # noqa: ANN401
        return self._value

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> Any:  # noqa: ANN401
        return self._row


class FakeSession:
    """Answers the ingestion SQL by its text and records every statement."""

    def __init__(self, job_row: dict[str, Any] | None = None) -> None:
        self.job_id = uuid.uuid4()
        self.source_id = uuid.uuid4()
        self.job_row = job_row
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:  # noqa: ANN401
        sql = str(statement)
        self.calls.append((sql, params))
        if "INSERT INTO sources" in sql:
            return FakeResult(value=self.source_id)
        if "INSERT INTO ingestion_jobs" in sql:
            return FakeResult(value=self.job_id)
        if "FROM ingestion_jobs" in sql:
            return FakeResult(row=self.job_row)
        return FakeResult()

    def queued_payload(self) -> dict[str, Any] | None:
        import json

        for sql, params in self.calls:
            if "INSERT INTO job_queue" in sql and params is not None:
                return json.loads(params["payload"])
        return None


def _user(*roles: str) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        email="user@example.test",
        display_name="Test User",
        tenant_id=None,
        roles=frozenset(roles),
    )


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(ingestion, "write_audit", mock)
    return mock


def _client(user: CurrentUser, session: FakeSession) -> TestClient:
    app = create_app()

    async def override_user() -> CurrentUser:
        return user

    async def override_session() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


VALID_BODY: dict[str, Any] = {
    "source": "cbic_gst_portal",
    "doc_type": "notification",
    "url": "https://www.cbic-gst.gov.in/gst/notifications/ct11-2017.pdf",
    "series": "CT",
    "number": 11,
    "year": "2017",
}


def test_professional_is_forbidden(audit: AsyncMock) -> None:
    """A professional role cannot submit (403)."""
    session = FakeSession()
    client = _client(_user("professional"), session)
    response = client.post("/v1/platform/ingestion/url", json=VALID_BODY)
    assert response.status_code == 403
    assert session.calls == []
    audit.assert_not_called()


def test_unknown_source_is_422(audit: AsyncMock) -> None:
    """An unknown source code is rejected before anything is written."""
    session = FakeSession()
    client = _client(_user("platform_admin"), session)
    response = client.post("/v1/platform/ingestion/url", json={**VALID_BODY, "source": "nowhere"})
    assert response.status_code == 422
    assert "Unknown source" in response.json()["detail"]
    assert session.calls == []


def test_disabled_source_is_422(audit: AsyncMock) -> None:
    """A source that is disabled in config (gst_council) is rejected."""
    client = _client(_user("platform_admin"), FakeSession())
    response = client.post(
        "/v1/platform/ingestion/url", json={**VALID_BODY, "source": "gst_council"}
    )
    assert response.status_code == 422
    assert "disabled" in response.json()["detail"]


def test_unknown_doc_type_is_422(audit: AsyncMock) -> None:
    """A doc_type that is not in authority.yaml is rejected."""
    session = FakeSession()
    client = _client(_user("platform_admin"), session)
    response = client.post("/v1/platform/ingestion/url", json={**VALID_BODY, "doc_type": "poem"})
    assert response.status_code == 422
    assert "Unknown doc_type" in response.json()["detail"]
    assert session.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/ct11.pdf",
        "https://cbic-gst.gov.in.evil.example/ct11.pdf",
        "https://localhost/ct11.pdf",
        "https://10.0.0.5/ct11.pdf",
    ],
)
def test_host_not_on_allow_list_is_422(audit: AsyncMock, url: str) -> None:
    """Hosts outside the source's allowed_hosts are rejected."""
    session = FakeSession()
    client = _client(_user("platform_admin"), session)
    response = client.post("/v1/platform/ingestion/url", json={**VALID_BODY, "url": url})
    assert response.status_code == 422
    assert "Host is not allowed" in response.json()["detail"]
    assert session.calls == []


@pytest.mark.parametrize(
    "url",
    ["ftp://www.cbic-gst.gov.in/ct11.pdf", "file:///etc/passwd"],
)
def test_non_http_url_is_422(audit: AsyncMock, url: str) -> None:
    """Only http and https URLs are accepted."""
    client = _client(_user("platform_admin"), FakeSession())
    response = client.post("/v1/platform/ingestion/url", json={**VALID_BODY, "url": url})
    assert response.status_code == 422


def test_url_with_control_characters_is_422(audit: AsyncMock) -> None:
    """A URL with a control character or a space is refused."""
    client = _client(_user("platform_admin"), FakeSession())
    response = client.post(
        "/v1/platform/ingestion/url",
        json={**VALID_BODY, "url": "https://www.cbic-gst.gov.in/a\x00.pdf"},
    )
    assert response.status_code == 422


def test_submit_happy_path_returns_202_and_queues_the_job(audit: AsyncMock) -> None:
    """A valid request writes the job and queues acquire with the raw metadata, then audits."""
    session = FakeSession()
    user = _user("platform_content_editor")
    client = _client(user, session)

    response = client.post("/v1/platform/ingestion/url", json=VALID_BODY)

    assert response.status_code == 202
    assert response.json() == {"ingestion_job_id": str(session.job_id)}

    payload = session.queued_payload()
    assert payload is not None
    assert payload["ingestion_job_id"] == str(session.job_id)
    assert payload["source_code"] == "cbic_gst_portal"
    assert payload["doc_type"] == "notification"
    assert payload["url"] == VALID_BODY["url"]
    assert payload["series"] == "CT"
    assert payload["number"] == "11"
    assert payload["year"] == "2017"
    assert payload["file_path"] is None
    sql_params = [params for sql, params in session.calls if "job_queue" in sql]
    assert sql_params[0] is not None
    assert sql_params[0]["idempotency_key"] == str(session.job_id)

    audit.assert_awaited_once()
    kwargs = audit.await_args.kwargs
    assert kwargs["action"] == "ingest.submit_url"
    assert kwargs["object_id"] == str(session.job_id)
    assert kwargs["detail"] == {
        "source": "cbic_gst_portal",
        "doc_type": "notification",
        "url": VALID_BODY["url"],
    }
    assert kwargs["actor"] == user


def test_blank_optional_fields_are_dropped(audit: AsyncMock) -> None:
    """Empty strings for optional metadata become null in the payload."""
    session = FakeSession()
    client = _client(_user("platform_admin"), session)
    response = client.post(
        "/v1/platform/ingestion/url", json={**VALID_BODY, "title": "   ", "case_number": ""}
    )
    assert response.status_code == 202
    payload = session.queued_payload()
    assert payload is not None
    assert payload["title"] is None
    assert payload["case_number"] is None


def test_job_status_is_returned_with_no_store(audit: AsyncMock) -> None:
    """GET /jobs/{id} returns the job and says it must not be cached."""
    job_id = uuid.uuid4()
    document_id = uuid.uuid4()
    session = FakeSession(
        job_row={
            "id": job_id,
            "stage": "acquire",
            "status": "done",
            "attempt": 1,
            "error_code": None,
            "error_detail": None,
            "document_id": document_id,
            "url": VALID_BODY["url"],
            "started_at": None,
            "finished_at": None,
        }
    )
    client = _client(_user("platform_admin"), session)

    response = client.get(f"/v1/platform/ingestion/jobs/{job_id}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["id"] == str(job_id)
    assert body["status"] == "done"
    assert body["document_id"] == str(document_id)


def test_missing_job_is_404(audit: AsyncMock) -> None:
    """An unknown job id is a 404."""
    client = _client(_user("platform_admin"), FakeSession(job_row=None))
    response = client.get(f"/v1/platform/ingestion/jobs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_job_status_requires_read_permission(audit: AsyncMock) -> None:
    """A professional cannot read job status."""
    client = _client(_user("professional"), FakeSession())
    response = client.get(f"/v1/platform/ingestion/jobs/{uuid.uuid4()}")
    assert response.status_code == 403
