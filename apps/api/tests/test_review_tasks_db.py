"""Review-task integration tests against a real Postgres (run with ``-m integration``).

Skipped unless DATABASE_URL points at a real database. The module runs ``alembic upgrade head``
once and ``downgrade base`` at the end. Requires migration 0007 (documents.metadata and
meta_confidence) and the review.read / review.decide permissions.

Users are created with SQL and called with real bearer tokens, so roles come from the database.
"""

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import app.db as app_db
import pytest
from alembic import command
from alembic.config import Config
from app.auth.ratelimit import get_login_rate_limiter
from app.auth.tokens import issue_token
from app.main import create_app
from app.routers import review_tasks
from app.settings import get_settings
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parent.parent
JWT_SECRET = "integration-test-jwt-secret-0123456789ab"  # 40 characters
ROUTE_PREFIX = "/v1/platform/review-tasks"

T_OLD = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
T_NEW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
T_EARLY = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
T_PARSE_OPENED = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


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
        app.include_router(review_tasks.router)
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
def editor_two(engine: Engine) -> Person:
    return _seed_person(engine, "platform_content_editor", "Editor Two")


@pytest.fixture(scope="module")
def professional(engine: Engine) -> Person:
    return _seed_person(engine, "professional", "Professional")


def _document(
    conn: Any,
    title: str,
    *,
    metadata: dict[str, Any] | None = None,
    confidence: float | None = None,
    review_state: str = "pending_review",
) -> uuid.UUID:
    document_id: uuid.UUID = conn.execute(
        text(
            """
            INSERT INTO documents (canonical_id, doc_type, authority_rank, title, review_state,
                                   metadata, meta_confidence)
            VALUES (:canonical_id, 'notification', 5, :title, :review_state,
                    CAST(:metadata AS JSONB), :confidence)
            RETURNING id
            """
        ),
        {
            "canonical_id": _unique("test:doc"),
            "title": title,
            "review_state": review_state,
            "metadata": json.dumps(metadata or {}),
            "confidence": confidence,
        },
    ).scalar_one()
    return document_id


def _link_source(conn: Any, document_id: uuid.UUID, source: str) -> None:  # noqa: ANN401
    conn.execute(
        text(
            "INSERT INTO document_sources (document_id, source_id, url) "
            "SELECT :document_id, id, :url FROM sources WHERE code = :code"
        ),
        {
            "document_id": document_id,
            "url": f"https://example.test/{uuid.uuid4().hex}",
            "code": source,
        },
    )


def _task(
    conn: Any,
    kind: str,
    subject_type: str,
    subject_id: uuid.UUID | None,
    *,
    priority: int = 3,
    status: str = "open",
    opened_at: datetime = T_OLD,
    resolution: dict[str, Any] | None = None,
    closed_at: datetime | None = None,
) -> uuid.UUID:
    task_id: uuid.UUID = conn.execute(
        text(
            """
            INSERT INTO review_tasks (kind, subject_type, subject_id, priority, status,
                                      opened_at, closed_at, resolution)
            VALUES (:kind, :subject_type, :subject_id, :priority, :status, :opened_at,
                    :closed_at, CAST(:resolution AS JSONB))
            RETURNING id
            """
        ),
        {
            "kind": kind,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "priority": priority,
            "status": status,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "resolution": json.dumps(resolution) if resolution is not None else None,
        },
    ).scalar_one()
    return task_id


@dataclass(frozen=True)
class Case:
    source: str
    d_meta_old: uuid.UUID
    d_meta_new: uuid.UUID
    d_version: uuid.UUID
    version: uuid.UUID
    d_dup_target: uuid.UUID
    d_dup_subject: uuid.UUID
    t_parse: uuid.UUID
    t_meta_old: uuid.UUID
    t_meta_new: uuid.UUID
    t_done: uuid.UUID
    t_dup: uuid.UUID
    t_miss: uuid.UUID
    query: str


PROPOSAL = {
    "fields": {"title": "Notification 11/2026", "number": "11", "year": 2026},
    "confidence": {"title": 0.95, "number": 0.7},
    "issues": ["number taken from the file name"],
    "extractor_version": "meta-1",
}


def _seed_case(engine: Engine) -> Case:
    source = _unique("test-src")
    query = f"input tax credit on rent {uuid.uuid4().hex[:6]}"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sources (code, kind) VALUES (:code, 'manual')"), {"code": source}
        )
        d_meta_old = _document(
            conn,
            "Notification 11/2026",
            metadata=PROPOSAL["fields"],
            confidence=0.7,
        )
        d_meta_new = _document(conn, "Notification 12/2026", confidence=0.6)
        d_done = _document(conn, "Notification 13/2026", review_state="reviewed")
        d_version = _document(conn, "Circular 5/2026")
        d_dup_target = _document(conn, "Notification 11/2026 (original)", review_state="reviewed")
        d_dup_subject = _document(conn, "Notification 11/2026 (copy)")
        for document_id in (d_meta_old, d_meta_new, d_done, d_version):
            _link_source(conn, document_id, source)

        version = conn.execute(
            text(
                """
                INSERT INTO document_versions (document_id, version_no, raw_s3_key, raw_sha256,
                                               mime, page_count)
                VALUES (:document_id, 1, :key, :sha, 'application/pdf', 3)
                RETURNING id
                """
            ),
            {
                "document_id": d_version,
                "key": f"raw/{uuid.uuid4().hex}.pdf",
                "sha": uuid.uuid4().hex,
            },
        ).scalar_one()
        conn.execute(
            text("UPDATE documents SET current_version_id = :v WHERE id = :d"),
            {"v": version, "d": d_version},
        )
        conn.execute(
            text(
                """
                INSERT INTO page_extractions (document_version_id, page_no, method, status, flagged)
                VALUES (:v, :page, :method, :status, :flagged)
                """
            ),
            [
                {"v": version, "page": 1, "method": "text", "status": "ok", "flagged": False},
                {
                    "v": version,
                    "page": 2,
                    "method": "ocr",
                    "status": "needs_review",
                    "flagged": True,
                },
                {"v": version, "page": 3, "method": "failed", "status": "failed", "flagged": False},
            ],
        )
        blocks = [
            {
                "v": version,
                "seq": seq,
                "page": 1 if seq <= 2 else 2,
                "path": f"p{seq}",
                "text": f"block {seq}",
            }
            for seq in range(1, 28)
        ]
        conn.execute(
            text(
                """
                INSERT INTO blocks (document_version_id, seq, kind, page, bbox, structure_path,
                                    text, text_sha256)
                VALUES (:v, :seq, 'para', :page,
                        CAST('{"x0": 1, "y0": 2, "x1": 3, "y1": 4}' AS JSONB),
                        :path, :text, 'sha')
                """
            ),
            blocks,
        )
        conn.execute(
            text("INSERT INTO page_texts (document_version_id, page_no, text) VALUES (:v, :p, :t)"),
            [
                {"v": version, "p": 1, "t": "short page"},
                {"v": version, "p": 2, "t": "x" * 6000},
            ],
        )

        t_parse = _task(
            conn,
            "parse_failure",
            "document_version",
            version,
            priority=1,
            opened_at=T_PARSE_OPENED,
            resolution={"pages": [2, 3]},
        )
        t_meta_old = _task(
            conn,
            "metadata",
            "document",
            d_meta_old,
            priority=2,
            opened_at=T_OLD,
            resolution={"proposal": PROPOSAL},
        )
        t_meta_new = _task(
            conn,
            "metadata",
            "document",
            d_meta_new,
            priority=2,
            opened_at=T_NEW,
            resolution={"proposal": {"fields": {"title": "Notification 12/2026"}}},
        )
        t_done = _task(
            conn,
            "metadata",
            "document",
            d_done,
            priority=1,
            status="done",
            opened_at=T_EARLY,
            closed_at=T_EARLY,
            resolution={"proposal": {"fields": {}}},
        )
        t_dup = _task(
            conn,
            "metadata",
            "document",
            d_dup_subject,
            priority=2,
            opened_at=T_OLD,
            resolution={
                "proposal": PROPOSAL,
                "near_duplicate_of": str(d_dup_target),
            },
        )
        t_miss = _task(
            conn,
            "miss_report",
            "miss_report",
            None,
            priority=3,
            opened_at=T_OLD,
            resolution={
                "report": {
                    "query": query,
                    "filters": {"doc_type": ["notification"]},
                    "as_on_date": "2026-10-01",
                    "corpus_version": 42,
                }
            },
        )
    return Case(
        source=source,
        d_meta_old=d_meta_old,
        d_meta_new=d_meta_new,
        d_version=d_version,
        version=version,
        d_dup_target=d_dup_target,
        d_dup_subject=d_dup_subject,
        t_parse=t_parse,
        t_meta_old=t_meta_old,
        t_meta_new=t_meta_new,
        t_done=t_done,
        t_dup=t_dup,
        t_miss=t_miss,
        query=query,
    )


def _one(engine: Engine, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = conn.execute(text(sql), params).mappings().first()
    return None if row is None else dict(row)


def _document_state(engine: Engine, document_id: uuid.UUID) -> str:
    row = _one(engine, "SELECT review_state FROM documents WHERE id = :id", {"id": document_id})
    assert row is not None
    state: str = row["review_state"]
    return state


def _jobs(engine: Engine, queue: str, key: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT payload, status FROM job_queue "
                "WHERE queue = :queue AND idempotency_key = :key"
            ),
            {"queue": queue, "key": key},
        ).mappings()
        return [dict(row) for row in rows]


def _audit(engine: Engine, action: str, object_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT actor_user_id, object_type, object_id, detail FROM audit_log "
                "WHERE action = :action AND object_id = :object_id ORDER BY seq"
            ),
            {"action": action, "object_id": object_id},
        ).mappings()
        return [dict(row) for row in rows]


def _set_assignee(engine: Engine, task_id: uuid.UUID, person: Person) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE review_tasks SET assignee_id = :person, status = 'in_review' WHERE id = :id"
            ),
            {"person": person.id, "id": task_id},
        )


def _url(task_id: uuid.UUID, suffix: str = "") -> str:
    return f"{ROUTE_PREFIX}/{task_id}{suffix}"


def test_list_defaults_to_open_tasks_in_queue_order(
    client: TestClient, engine: Engine, editor: Person
) -> None:
    case = _seed_case(engine)
    response = client.get(ROUTE_PREFIX, params={"source": case.source}, headers=editor.headers)
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    body = response.json()
    assert [item["id"] for item in body["items"]] == [
        str(case.t_parse),
        str(case.t_meta_old),
        str(case.t_meta_new),
    ]
    assert body["total"] == 3
    assert body["next_cursor"] is None
    parse_item = body["items"][0]
    assert parse_item["title"] == "Circular 5/2026"
    assert parse_item["subject_type"] == "document_version"
    assert parse_item["assignee_id"] is None


def test_list_status_and_kind_filters(client: TestClient, engine: Engine, editor: Person) -> None:
    case = _seed_case(engine)
    done = client.get(
        ROUTE_PREFIX, params={"source": case.source, "status": "done"}, headers=editor.headers
    ).json()
    assert [item["id"] for item in done["items"]] == [str(case.t_done)]

    both = client.get(
        ROUTE_PREFIX,
        params={"source": case.source, "status": ["open", "done"]},
        headers=editor.headers,
    ).json()
    assert both["total"] == 4

    metadata = client.get(
        ROUTE_PREFIX, params={"source": case.source, "kind": "metadata"}, headers=editor.headers
    ).json()
    assert [item["id"] for item in metadata["items"]] == [
        str(case.t_meta_old),
        str(case.t_meta_new),
    ]


def test_list_miss_report_has_query_as_title(
    client: TestClient, engine: Engine, editor: Person
) -> None:
    case = _seed_case(engine)
    body = client.get(
        ROUTE_PREFIX, params={"kind": "miss_report", "limit": 200}, headers=editor.headers
    ).json()
    match = [item for item in body["items"] if item["id"] == str(case.t_miss)]
    assert len(match) == 1
    assert match[0]["title"] == case.query
    assert match[0]["subject_id"] is None


def test_list_pagination_is_keyset(client: TestClient, engine: Engine, editor: Person) -> None:
    case = _seed_case(engine)
    first = client.get(
        ROUTE_PREFIX, params={"source": case.source, "limit": 2}, headers=editor.headers
    ).json()
    assert [item["id"] for item in first["items"]] == [
        str(case.t_parse),
        str(case.t_meta_old),
    ]
    assert first["total"] == 3
    assert first["next_cursor"] is not None

    second = client.get(
        ROUTE_PREFIX,
        params={"source": case.source, "limit": 2, "cursor": first["next_cursor"]},
        headers=editor.headers,
    ).json()
    assert [item["id"] for item in second["items"]] == [str(case.t_meta_new)]
    assert second["next_cursor"] is None
    assert second["total"] == 3


def test_list_bad_cursor_is_422(client: TestClient, editor: Person) -> None:
    response = client.get(ROUTE_PREFIX, params={"cursor": "bm90LWpzb24"}, headers=editor.headers)
    assert response.status_code == 422, response.text


def test_list_assignee_filters(
    client: TestClient, engine: Engine, editor: Person, editor_two: Person
) -> None:
    case = _seed_case(engine)
    _set_assignee(engine, case.t_meta_old, editor)

    mine = client.get(
        ROUTE_PREFIX,
        params={"source": case.source, "assignee": "me"},
        headers=editor.headers,
    ).json()
    assert [item["id"] for item in mine["items"]] == [str(case.t_meta_old)]
    assert mine["items"][0]["assignee_name"] == editor.display_name

    unassigned = client.get(
        ROUTE_PREFIX,
        params={"source": case.source, "assignee": "none"},
        headers=editor.headers,
    ).json()
    assert [item["id"] for item in unassigned["items"]] == [
        str(case.t_parse),
        str(case.t_meta_new),
    ]

    by_id = client.get(
        ROUTE_PREFIX,
        params={"source": case.source, "assignee": str(editor_two.id)},
        headers=editor.headers,
    ).json()
    assert by_id["items"] == []


def test_detail_document_task(client: TestClient, engine: Engine, editor: Person) -> None:
    case = _seed_case(engine)
    response = client.get(_url(case.t_meta_old), headers=editor.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "metadata"
    assert body["closed_at"] is None
    assert body["version"] is None
    assert body["problem_pages"] == []
    assert body["near_duplicate_of"] is None
    assert body["document"]["id"] == str(case.d_meta_old)
    assert body["document"]["metadata"] == PROPOSAL["fields"]
    assert body["document"]["meta_confidence"] == pytest.approx(0.7)
    assert body["resolution"]["proposal"] == PROPOSAL


def test_detail_parse_failure_context(client: TestClient, engine: Engine, editor: Person) -> None:
    case = _seed_case(engine)
    response = client.get(_url(case.t_parse), headers=editor.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"]["id"] == str(case.version)
    assert body["version"]["page_count"] == 3
    assert body["document"]["id"] == str(case.d_version)
    assert body["resolution"] == {"pages": [2, 3]}

    pages = {page["page_no"]: page for page in body["problem_pages"]}
    assert sorted(pages) == [2, 3]

    flagged = pages[2]
    assert flagged["flagged"] is True
    assert flagged["method"] == "ocr"
    assert [block["seq"] for block in flagged["blocks"]] == list(range(3, 23))
    assert flagged["blocks"][0]["structure_path"] == "p3"
    assert flagged["blocks"][0]["bbox"] == {"x0": 1, "y0": 2, "x1": 3, "y1": 4}
    assert flagged["page_text_truncated"] is True
    assert len(flagged["page_text"]) == review_tasks.PAGE_TEXT_LIMIT

    failed = pages[3]
    assert failed["method"] == "failed"
    assert failed["status"] == "failed"
    assert failed["blocks"] == []
    assert failed["page_text"] is None
    assert failed["page_text_truncated"] is False


def test_detail_miss_report_and_near_duplicate(
    client: TestClient, engine: Engine, editor: Person
) -> None:
    case = _seed_case(engine)
    miss = client.get(_url(case.t_miss), headers=editor.headers).json()
    assert miss["document"] is None
    assert miss["version"] is None
    assert miss["resolution"]["report"]["query"] == case.query
    assert miss["resolution"]["report"]["corpus_version"] == 42

    dup = client.get(_url(case.t_dup), headers=editor.headers).json()
    assert dup["near_duplicate_of"]["id"] == str(case.d_dup_target)
    assert dup["near_duplicate_of"]["title"] == "Notification 11/2026 (original)"


def test_detail_unknown_task_is_404(client: TestClient, editor: Person) -> None:
    response = client.get(_url(uuid.uuid4()), headers=editor.headers)
    assert response.status_code == 404, response.text


def test_professional_cannot_read_or_decide(
    client: TestClient, engine: Engine, professional: Person
) -> None:
    case = _seed_case(engine)
    assert client.get(ROUTE_PREFIX, headers=professional.headers).status_code == 403
    assert client.get(_url(case.t_parse), headers=professional.headers).status_code == 403
    response = client.post(
        _url(case.t_parse, "/decision"),
        json={"action": "reject", "note": "not for us"},
        headers=professional.headers,
    )
    assert response.status_code == 403, response.text


def test_assign_flow_and_audit(
    client: TestClient,
    engine: Engine,
    editor: Person,
    editor_two: Person,
    professional: Person,
) -> None:
    case = _seed_case(engine)
    task = _url(case.t_meta_new, "/assign")

    to_me = client.post(task, json={"assignee_id": "me"}, headers=editor.headers)
    assert to_me.status_code == 200, to_me.text
    assert to_me.json()["assignee_id"] == str(editor.id)
    assert to_me.json()["assignee_name"] == editor.display_name
    assert to_me.json()["status"] == "in_review"

    to_other = client.post(task, json={"assignee_id": str(editor_two.id)}, headers=editor.headers)
    assert to_other.status_code == 200, to_other.text
    assert to_other.json()["assignee_id"] == str(editor_two.id)
    assert to_other.json()["status"] == "in_review"

    ineligible = client.post(
        task, json={"assignee_id": str(professional.id)}, headers=editor.headers
    )
    assert ineligible.status_code == 422, ineligible.text

    cleared = client.post(task, json={"assignee_id": None}, headers=editor.headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["assignee_id"] is None
    assert cleared.json()["status"] == "in_review"

    rows = _audit(engine, "review.assign", str(case.t_meta_new))
    assert len(rows) == 3
    assert rows[0]["actor_user_id"] == editor.id
    assert rows[0]["object_type"] == "review_task"
    assert rows[0]["detail"]["assignee_id"] == str(editor.id)
    assert rows[0]["detail"]["status_before"] == "open"
    assert rows[0]["detail"]["status_after"] == "in_review"


def test_edit_approve_enqueues_metadata_and_keeps_proposal(
    client: TestClient, engine: Engine, editor: Person
) -> None:
    case = _seed_case(engine)
    response = client.post(
        _url(case.t_meta_old, "/decision"),
        json={
            "action": "edit_approve",
            "fields": {"title": "Notification 11/2026 (corrected)", "number": "11"},
            "note": "fixed from the gazette",
        },
        headers=editor.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "done"
    assert body["closed_at"] is not None
    assert body["notices"] == []
    assert body["resolution"]["proposal"] == PROPOSAL
    decision = body["resolution"]["decision"]
    assert decision["action"] == "edit_approve"
    assert decision["fields"] == {"title": "Notification 11/2026 (corrected)", "number": "11"}
    assert decision["note"] == "fixed from the gazette"
    assert decision["decided_by"] == str(editor.id)

    jobs = _jobs(engine, "ingest.apply_metadata", f"review:{case.t_meta_old}")
    assert len(jobs) == 1
    payload = jobs[0]["payload"]
    assert payload == {
        "document_id": str(case.d_meta_old),
        "fields": {"title": "Notification 11/2026 (corrected)", "number": "11"},
        "actor_user_id": str(editor.id),
        "reason": "fixed from the gazette",
        "review_task_id": str(case.t_meta_old),
    }

    # The only open task on this document, so it moves to reviewed and publish re-runs.
    assert _document_state(engine, case.d_meta_old) == "reviewed"
    publish = _jobs(engine, "ingest.publish", f"publish-after-review:{case.t_meta_old}")
    assert publish[0]["payload"] == {"document_id": str(case.d_meta_old)}

    audit = _audit(engine, "review.decision", str(case.t_meta_old))
    assert len(audit) == 1
    assert audit[0]["actor_user_id"] == editor.id
    assert audit[0]["detail"] == {
        "task_id": str(case.t_meta_old),
        "kind": "metadata",
        "action": "edit_approve",
        "fields": ["number", "title"],
    }


def test_reject_keeps_document_pending_until_last_task_closes(
    client: TestClient, engine: Engine, editor: Person
) -> None:
    case = _seed_case(engine)
    with engine.begin() as conn:
        extra = _task(conn, "metadata", "document", case.d_version, priority=2)

    reject = client.post(
        _url(case.t_parse, "/decision"),
        json={"action": "reject", "note": "scan is unreadable"},
        headers=editor.headers,
    )
    assert reject.status_code == 200, reject.text
    assert reject.json()["status"] == "rejected"
    assert reject.json()["closed_at"] is not None
    assert _document_state(engine, case.d_version) == "pending_review"
    assert _jobs(engine, "ingest.publish", f"publish-after-review:{case.t_parse}")
    assert _jobs(engine, "ingest.apply_metadata", f"review:{case.t_parse}") == []

    approve = client.post(
        _url(extra, "/decision"),
        json={"action": "approve"},
        headers=editor.headers,
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "done"
    assert _document_state(engine, case.d_version) == "reviewed"
    assert _jobs(engine, "ingest.publish", f"publish-after-review:{extra}")

    again = client.post(
        _url(case.t_parse, "/decision"),
        json={"action": "approve"},
        headers=editor.headers,
    )
    assert again.status_code == 409, again.text


def test_needs_info_keeps_task_open(client: TestClient, engine: Engine, editor: Person) -> None:
    case = _seed_case(engine)
    response = client.post(
        _url(case.t_meta_new, "/decision"),
        json={"action": "needs_info", "note": "which gazette issue?"},
        headers=editor.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "in_review"
    assert body["closed_at"] is None
    assert body["resolution"]["needs_info"] is True
    assert body["resolution"]["decision"]["action"] == "needs_info"
    assert body["resolution"]["proposal"] == {"fields": {"title": "Notification 12/2026"}}
    assert _document_state(engine, case.d_meta_new) == "pending_review"
    assert _jobs(engine, "ingest.publish", f"publish-after-review:{case.t_meta_new}") == []

    listed = client.get(ROUTE_PREFIX, params={"source": case.source}, headers=editor.headers).json()
    assert str(case.t_meta_new) in [item["id"] for item in listed["items"]]


def test_approve_near_duplicate_records_decision_without_merge(
    client: TestClient, engine: Engine, editor: Person
) -> None:
    case = _seed_case(engine)
    response = client.post(
        _url(case.t_dup, "/decision"),
        json={"action": "approve"},
        headers=editor.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "done"
    assert body["notices"]
    assert "No merge" in body["notices"][0]
    assert body["resolution"]["near_duplicate_of"] == str(case.d_dup_target)
    assert body["resolution"]["decision"]["action"] == "approve"
    assert _jobs(engine, "ingest.apply_metadata", f"review:{case.t_dup}") == []


def test_closed_task_rejects_further_decisions_and_assignment(
    client: TestClient, engine: Engine, editor: Person
) -> None:
    case = _seed_case(engine)
    closed = client.post(
        _url(case.t_done, "/decision"),
        json={"action": "approve"},
        headers=editor.headers,
    )
    assert closed.status_code == 409, closed.text
    assigned = client.post(
        _url(case.t_done, "/assign"), json={"assignee_id": "me"}, headers=editor.headers
    )
    assert assigned.status_code == 409, assigned.text
    assert _audit(engine, "review.decision", str(case.t_done)) == []
    assert _audit(engine, "review.assign", str(case.t_done)) == []


def test_unknown_metadata_field_is_422_and_writes_nothing(
    client: TestClient, engine: Engine, editor: Person
) -> None:
    case = _seed_case(engine)
    response = client.post(
        _url(case.t_meta_old, "/decision"),
        json={"action": "edit_approve", "fields": {"colour": "red"}},
        headers=editor.headers,
    )
    assert response.status_code == 422, response.text
    assert _jobs(engine, "ingest.apply_metadata", f"review:{case.t_meta_old}") == []
    assert _audit(engine, "review.decision", str(case.t_meta_old)) == []
    assert _document_state(engine, case.d_meta_old) == "pending_review"
