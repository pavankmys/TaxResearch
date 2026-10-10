"""Unit tests for amendment review-task decisions (no database)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime
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
    def __init__(self, row: Any = None, rows: Any = None) -> None:
        self._row = row
        self._rows = rows or []

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> Any:
        return self._row

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._row

    def scalar_one(self) -> int:
        return 0


class FakeSession:
    """Answers SQL statements and tracks writes and queue items."""

    def __init__(
        self,
        task_row: dict[str, Any] | None = None,
        amendment_row: dict[str, Any] | None = None,
    ) -> None:
        self.task_row = task_row
        default_am_id = (task_row.get("subject_id") if task_row else None) or uuid.uuid4()
        self.amendment_row = amendment_row or {
            "id": default_am_id,
            "source_document_id": uuid.uuid4(),
            "source_block_id": None,
            "op": "substitute",
            "old_text": "twenty",
            "new_text": "ten",
            "effective_from": date(2026, 1, 1),
            "effective_condition": "on_date",
            "target_provision_id": uuid.uuid4(),
            "target_locator": {"instrument": "CGST_RULES", "target_path": "r36.4"},
            "extraction_method": "rule",
            "extraction_conf": 1.0,
            "dry_run_ok": True,
            "dry_run_diff": "[-twenty-]{+ten+}",
            "review_status": "proposed",
            "target_provision_path": "r36.4",
        }
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:
        sql = str(statement)
        self.calls.append((sql, params))
        if "UPDATE review_tasks" in sql and params and self.task_row:
            self.task_row["status"] = params.get("status", self.task_row["status"])
            self.task_row["closed_at"] = params.get("closed_at", self.task_row.get("closed_at"))
        if "review_tasks" in sql and (
            "FOR UPDATE" in sql or "t.id = :id" in sql or "WHERE t.id = :id" in sql
        ):
            return FakeResult(row=self.task_row)
        if "FROM amendments a" in sql:
            return FakeResult(row=self.amendment_row)
        if "FROM provision_versions" in sql:
            return FakeResult(row="Old provision text before amendment")
        if "SELECT op, old_text, new_text" in sql and "amendments" in sql:
            return FakeResult(row=self.amendment_row)
        if "SELECT target_provision_id, effective_from" in sql and "amendments" in sql:
            return FakeResult(row=self.amendment_row)
        if "SELECT source_document_id FROM amendments" in sql:
            return FakeResult(row=uuid.uuid4())
        return FakeResult()

    def writes(self) -> list[tuple[str, dict[str, Any] | None]]:
        return [
            (sql, params)
            for sql, params in self.calls
            if sql.lstrip().upper().startswith(("UPDATE", "INSERT"))
        ]


def _user(*roles: str) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        email="reviewer@example.test",
        display_name="Reviewer",
        tenant_id=None,
        roles=frozenset(roles),
    )


def _amendment_task(status: str = "open", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "kind": "amendment",
        "status": status,
        "subject_type": "amendment",
        "subject_id": uuid.uuid4(),
        "assignee_id": None,
        "assignee_name": None,
        "priority": 1,
        "opened_at": datetime.now(UTC),
        "sla_due_at": None,
        "title": "Notification No. 01/2026",
        "closed_at": None,
        "resolution": {"problems": []},
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _review_permissions(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = deps.has_permission

    def grant(roles: Any, action: str) -> bool:
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


def test_amendment_approve_enqueues_consolidation(audit: AsyncMock) -> None:
    task = _amendment_task()
    session = FakeSession(task_row=task)
    client = _client(_user("platform_content_editor"), session)

    res = client.post(
        f"/v1/platform/review-tasks/{task['id']}/decision",
        json={"action": "approve", "note": "looks good"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "done"

    # Verify amendment table update
    amendment_updates = [
        (sql, params) for sql, params in session.writes() if "UPDATE amendments" in sql
    ]
    assert len(amendment_updates) == 1
    assert amendment_updates[0][1]["review_status"] == "approved"

    # Verify consolidation queue job was enqueued
    consolidate_enqueues = [
        (sql, params)
        for sql, params in session.writes()
        if "INSERT INTO job_queue" in sql and params and params.get("queue") == "ingest.consolidate"
    ]
    assert len(consolidate_enqueues) == 1


def test_amendment_edit_approve_saves_override_and_updates(audit: AsyncMock) -> None:
    task = _amendment_task()
    session = FakeSession(task_row=task)
    client = _client(_user("platform_content_editor"), session)

    res = client.post(
        f"/v1/platform/review-tasks/{task['id']}/decision",
        json={
            "action": "edit_approve",
            "note": "corrected text",
            "fields": {"new_text": "fifteen per cent."},
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "done"

    # Verify task resolution stores original
    task_updates = [
        (sql, params) for sql, params in session.writes() if "UPDATE review_tasks" in sql
    ]
    assert len(task_updates) == 1
    resolution_str = task_updates[0][1]["resolution"]
    assert "original_amendment" in resolution_str


def test_amendment_edit_approve_unknown_field_is_422() -> None:
    task = _amendment_task()
    session = FakeSession(task_row=task)
    client = _client(_user("platform_content_editor"), session)

    res = client.post(
        f"/v1/platform/review-tasks/{task['id']}/decision",
        json={
            "action": "edit_approve",
            "fields": {"unknown_field": "val"},
        },
    )
    assert res.status_code == 422
    assert "Unknown amendment field" in res.text


def test_amendment_reject(audit: AsyncMock) -> None:
    task = _amendment_task()
    session = FakeSession(task_row=task)
    client = _client(_user("platform_content_editor"), session)

    res = client.post(
        f"/v1/platform/review-tasks/{task['id']}/decision",
        json={"action": "reject", "note": "not applicable"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"

    # Verify amendment updated to rejected
    amendment_updates = [
        (sql, params) for sql, params in session.writes() if "UPDATE amendments" in sql
    ]
    assert len(amendment_updates) == 1
    assert amendment_updates[0][1]["review_status"] == "rejected"

    # No consolidate job
    consolidate_enqueues = [
        (sql, params)
        for sql, params in session.writes()
        if "INSERT INTO job_queue" in sql and params and params.get("queue") == "ingest.consolidate"
    ]
    assert len(consolidate_enqueues) == 0


def test_amendment_needs_info(audit: AsyncMock) -> None:
    task = _amendment_task()
    session = FakeSession(task_row=task)
    client = _client(_user("platform_content_editor"), session)

    res = client.post(
        f"/v1/platform/review-tasks/{task['id']}/decision",
        json={"action": "needs_info", "note": "need gazette copy"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "in_review"

    amendment_updates = [
        (sql, params)
        for sql, params in session.writes()
        if "UPDATE amendments" in sql and params and params.get("review_status") == "needs_info"
    ]
    assert len(amendment_updates) == 1


def test_get_amendment_task_detail() -> None:
    task = _amendment_task()
    session = FakeSession(task_row=task)
    client = _client(_user("platform_content_editor"), session)

    res = client.get(f"/v1/platform/review-tasks/{task['id']}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(task["id"])
    assert data["kind"] == "amendment"
    assert data["amendment"] is not None
    assert data["amendment"]["op"] == "substitute"
    assert data["amendment"]["old_text"] == "twenty"
    assert data["amendment"]["new_text"] == "ten"
    assert data["amendment"]["dry_run_ok"] is True
    assert data["amendment"]["dry_run_diff"] == "[-twenty-]{+ten+}"
    assert data["amendment"]["target_provision_path"] == "r36.4"
    assert data["amendment"]["current_provision_text"] == "Old provision text before amendment"
