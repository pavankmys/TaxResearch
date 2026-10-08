"""Unit tests for the review-task endpoints: permissions, validation and closed-task rules.

The database session and the audit writer are replaced, so these tests need no Postgres. The
router is mounted on a bare FastAPI app. The permission check is patched to grant the review
permissions to the content-editor and admin roles, because permissions.py may not list them yet.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.auth import deps
from app.auth.deps import CurrentUser, get_current_user
from app.db import get_session
from app.routers import review_tasks
from fastapi import FastAPI
from fastapi.testclient import TestClient

REVIEW_PERMISSIONS = {"review.read", "review.decide"}
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

    def scalar_one(self) -> int:
        return 0


class FakeSession:
    """Answers the review-task SQL by its text and records every statement."""

    def __init__(self, task_row: dict[str, Any] | None = None, assignable: bool = True) -> None:
        self.task_row = task_row
        self.assignable = assignable
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:  # noqa: ANN401
        sql = str(statement)
        self.calls.append((sql, params))
        if "FOR UPDATE" in sql and "review_tasks" in sql:
            return FakeResult(row=self.task_row)
        if "user_roles ur" in sql:
            return FakeResult(row={"id": uuid.uuid4()} if self.assignable else None)
        return FakeResult()

    def writes(self) -> list[str]:
        return [
            sql for sql, _ in self.calls if sql.lstrip().upper().startswith(("UPDATE", "INSERT"))
        ]


def _user(*roles: str) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        email="reviewer@example.test",
        display_name="Reviewer",
        tenant_id=None,
        roles=frozenset(roles),
    )


def _task(status: str = "open", kind: str = "metadata", **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "kind": kind,
        "status": status,
        "subject_type": "document",
        "subject_id": uuid.uuid4(),
        "assignee_id": None,
        "resolution": {"proposal": {"fields": {"title": "Old"}}},
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _review_permissions(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = deps.has_permission

    def grant(roles: Any, action: str) -> bool:  # noqa: ANN401
        if action in REVIEW_PERMISSIONS:
            return bool(EDITOR_ROLES & set(roles))
        return original(roles, action)

    monkeypatch.setattr(deps, "has_permission", grant)
    yield


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(review_tasks, "write_audit", mock)
    return mock


def _client(user: CurrentUser, session: FakeSession) -> TestClient:
    app = FastAPI()
    app.include_router(review_tasks.router)

    async def override_user() -> CurrentUser:
        return user

    async def override_session() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _writes_absent(session: FakeSession) -> None:
    assert session.writes() == []


def test_read_without_permission_is_403() -> None:
    session = FakeSession()
    client = _client(_user("professional"), session)
    response = client.get("/v1/platform/review-tasks")
    assert response.status_code == 403
    assert session.calls == []


def test_detail_without_permission_is_403() -> None:
    session = FakeSession()
    client = _client(_user("junior"), session)
    response = client.get(f"/v1/platform/review-tasks/{uuid.uuid4()}")
    assert response.status_code == 403
    assert session.calls == []


def test_decision_without_permission_is_403(audit: AsyncMock) -> None:
    session = FakeSession(task_row=_task())
    client = _client(_user("professional"), session)
    response = client.post(
        f"/v1/platform/review-tasks/{uuid.uuid4()}/decision", json={"action": "approve"}
    )
    assert response.status_code == 403
    assert session.calls == []
    audit.assert_not_called()


def test_assign_without_permission_is_403(audit: AsyncMock) -> None:
    session = FakeSession(task_row=_task())
    client = _client(_user("professional"), session)
    response = client.post(
        f"/v1/platform/review-tasks/{uuid.uuid4()}/assign", json={"assignee_id": "me"}
    )
    assert response.status_code == 403
    assert session.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"action": "edit_approve"},
        {"action": "edit_approve", "fields": {}},
        {"action": "approve", "fields": {"title": "x"}},
        {"action": "reject"},
        {"action": "reject", "note": "  "},
        {"action": "reject", "note": "no"},
        {"action": "needs_info"},
        {"action": "needs_info", "note": "ok"},
        {"action": "publish"},
    ],
)
def test_decision_body_validation_is_422(body: dict[str, Any], audit: AsyncMock) -> None:
    session = FakeSession(task_row=_task())
    client = _client(_user("platform_content_editor"), session)
    response = client.post(f"/v1/platform/review-tasks/{uuid.uuid4()}/decision", json=body)
    assert response.status_code == 422, response.text
    assert session.calls == []
    audit.assert_not_called()


def test_edit_approve_with_unknown_field_is_422(audit: AsyncMock) -> None:
    session = FakeSession(task_row=_task(kind="metadata"))
    client = _client(_user("platform_content_editor"), session)
    response = client.post(
        f"/v1/platform/review-tasks/{uuid.uuid4()}/decision",
        json={"action": "edit_approve", "fields": {"title": "New", "colour": "red"}},
    )
    assert response.status_code == 422, response.text
    assert "colour" in response.json()["detail"]
    _writes_absent(session)
    audit.assert_not_called()


@pytest.mark.parametrize("action", ["approve", "edit_approve", "reject", "needs_info"])
def test_decision_on_closed_task_is_409(action: str, audit: AsyncMock) -> None:
    session = FakeSession(task_row=_task(status="done"))
    client = _client(_user("platform_content_editor"), session)
    body: dict[str, Any] = {"action": action}
    if action == "edit_approve":
        body["fields"] = {"title": "New"}
    if action in ("reject", "needs_info"):
        body["note"] = "reason here"
    response = client.post(f"/v1/platform/review-tasks/{uuid.uuid4()}/decision", json=body)
    assert response.status_code == 409, response.text
    _writes_absent(session)
    audit.assert_not_called()


def test_reject_on_rejected_task_is_409(audit: AsyncMock) -> None:
    session = FakeSession(task_row=_task(status="rejected"))
    client = _client(_user("platform_content_editor"), session)
    response = client.post(
        f"/v1/platform/review-tasks/{uuid.uuid4()}/decision",
        json={"action": "reject", "note": "not valid"},
    )
    assert response.status_code == 409, response.text
    _writes_absent(session)


def test_decision_on_missing_task_is_404(audit: AsyncMock) -> None:
    session = FakeSession(task_row=None)
    client = _client(_user("platform_content_editor"), session)
    response = client.post(
        f"/v1/platform/review-tasks/{uuid.uuid4()}/decision", json={"action": "approve"}
    )
    assert response.status_code == 404, response.text
    _writes_absent(session)


def test_assign_to_closed_task_is_409(audit: AsyncMock) -> None:
    session = FakeSession(task_row=_task(status="done"))
    client = _client(_user("platform_content_editor"), session)
    response = client.post(
        f"/v1/platform/review-tasks/{uuid.uuid4()}/assign", json={"assignee_id": "me"}
    )
    assert response.status_code == 409, response.text
    _writes_absent(session)
    audit.assert_not_called()


def test_assign_to_ineligible_user_is_422(audit: AsyncMock) -> None:
    session = FakeSession(task_row=_task(), assignable=False)
    client = _client(_user("platform_content_editor"), session)
    response = client.post(
        f"/v1/platform/review-tasks/{uuid.uuid4()}/assign",
        json={"assignee_id": str(uuid.uuid4())},
    )
    assert response.status_code == 422, response.text
    _writes_absent(session)
    audit.assert_not_called()


def test_assign_body_must_name_the_field() -> None:
    session = FakeSession(task_row=_task())
    client = _client(_user("platform_content_editor"), session)
    response = client.post(f"/v1/platform/review-tasks/{uuid.uuid4()}/assign", json={})
    assert response.status_code == 422, response.text
    assert session.calls == []


@pytest.mark.parametrize("assignee", ["bogus", "ME", "me-please"])
def test_list_rejects_bad_assignee_before_querying(assignee: str) -> None:
    session = FakeSession()
    client = _client(_user("platform_content_editor"), session)
    response = client.get("/v1/platform/review-tasks", params={"assignee": assignee})
    assert response.status_code == 422, response.text
    assert session.calls == []


def test_list_rejects_malformed_cursor() -> None:
    session = FakeSession()
    client = _client(_user("platform_content_editor"), session)
    response = client.get("/v1/platform/review-tasks", params={"cursor": "%%%not-a-cursor"})
    assert response.status_code == 422, response.text
    assert session.calls == []


def test_list_rejects_limit_over_200() -> None:
    session = FakeSession()
    client = _client(_user("platform_content_editor"), session)
    response = client.get("/v1/platform/review-tasks", params={"limit": 201})
    assert response.status_code == 422, response.text


def test_cursor_round_trip() -> None:
    task_id = uuid.uuid4()
    opened = datetime(2026, 10, 8, 9, 30, 15, 123456, tzinfo=UTC)
    cursor = review_tasks._encode_cursor(2, opened, task_id)
    assert review_tasks._decode_cursor(cursor) == (2, opened, task_id)


def test_decision_body_strips_note() -> None:
    body = review_tasks.DecisionBody(action="reject", note="   needs a source   ")
    assert body.note == "needs a source"


def test_metadata_fields_match_contract() -> None:
    assert len(review_tasks.METADATA_FIELDS) == 24
    for name in ("canonical_id", "sections_referred", "gazette_ref", "din", "parties"):
        assert name in review_tasks.METADATA_FIELDS
