"""Review queue endpoints: list and read tasks, assign them, and record decisions.

Writes run in the request transaction. Assign and decision lock the task row first. A decision
that closes a task also locks its document row, so two closes on the same document cannot
both see the other as still open. Metadata edits are applied by the worker through the
``ingest.apply_metadata`` job; this router never writes ``documents.metadata`` itself.
"""

import base64
import binascii
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.db import get_session

router = APIRouter(prefix="/v1/platform/review-tasks", tags=["review"])

NO_STORE = "private, no-store"
ASSIGNABLE_ROLES = ["platform_content_editor", "platform_admin"]
OPEN_STATUSES = ["open", "in_review"]
CLOSED_STATUSES = ("done", "rejected")
BLOCKS_PER_PAGE = 20
PAGE_TEXT_LIMIT = 5000
NEAR_DUPLICATE_NOTICE = (
    "The proposal names a near-duplicate document. No merge was made; merge it manually."
)

# Field names accepted by an edit to a metadata task (TSD / plan "Metadata JSON").
METADATA_FIELDS: frozenset[str] = frozenset(
    {
        # common
        "doc_type",
        "title",
        "number",
        "series",
        "year",
        "doc_date",
        "in_force_date",
        "issuing_authority",
        "canonical_id",
        "sections_referred",
        # notification
        "effective_date",
        "gazette_ref",
        # circular
        "circular_kind",
        "subject",
        "din",
        # judgement
        "court_level",
        "court_name",
        "court_code",
        "bench",
        "judges",
        "decision_date",
        "parties",
        "case_numbers",
        "reporter_citations",
    }
)

Kind = Literal["amendment", "metadata", "parse_failure", "miss_report", "treatment"]
Status = Literal["open", "in_review", "done", "rejected"]
Action = Literal["approve", "edit_approve", "reject", "needs_info"]

# Columns shared by the list and the single-task reads. Joins: see _TASK_FROM.
_TASK_COLUMNS = """
    t.id, t.kind, t.status, t.priority, t.subject_type, t.subject_id, t.assignee_id,
    u.display_name AS assignee_name, t.opened_at, t.sla_due_at,
    COALESCE(d.title, t.resolution -> 'report' ->> 'query') AS title
"""
_TASK_FROM = """
    FROM review_tasks t
    LEFT JOIN users u ON u.id = t.assignee_id
    LEFT JOIN document_versions dv
        ON t.subject_type = 'document_version' AND dv.id = t.subject_id
    LEFT JOIN documents d
        ON d.id = CASE WHEN t.subject_type = 'document' THEN t.subject_id ELSE dv.document_id END
"""
SOURCE_CLAUSE = """
    EXISTS (
        SELECT 1 FROM document_sources ds
        JOIN sources s ON s.id = ds.source_id
        WHERE ds.document_id = d.id AND s.code = :source
    )
"""

LIST_COUNT_SQL = "SELECT count(*) {from_sql} WHERE {where}"
LIST_PAGE_SQL = (
    "SELECT {columns} {from_sql} WHERE {where} "
    "ORDER BY t.priority ASC, t.opened_at ASC, t.id ASC LIMIT :limit"
)
TASK_SQL = text(f"SELECT {_TASK_COLUMNS}, t.closed_at, t.resolution {_TASK_FROM} WHERE t.id = :id")
LOCK_TASK_SQL = text(
    "SELECT id, kind, status, subject_type, subject_id, assignee_id, resolution "
    "FROM review_tasks WHERE id = :id FOR UPDATE"
)
ASSIGNABLE_SQL = text(
    """
    SELECT u.id FROM users u
    WHERE u.id = :id AND u.status = 'active'
      AND EXISTS (
        SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = u.id AND r.code = ANY(CAST(:roles AS TEXT[]))
      )
    """
)
ASSIGN_SQL = text(
    """
    UPDATE review_tasks
    SET assignee_id = :assignee_id, status = :status, updated_by = :actor, updated_at = :now
    WHERE id = :id
    """
)
DECISION_SQL = text(
    """
    UPDATE review_tasks
    SET status = :status, closed_at = :closed_at, resolution = CAST(:resolution AS JSONB),
        updated_by = :actor, updated_at = :now
    WHERE id = :id
    """
)
DOCUMENT_SQL = text(
    """
    SELECT id, canonical_id, doc_type, title, review_state, metadata, meta_confidence,
           current_version_id
    FROM documents WHERE id = :id
    """
)
LOCK_DOCUMENT_SQL = text("SELECT id FROM documents WHERE id = :id FOR UPDATE")
VERSION_SQL = text("SELECT id, document_id, page_count, mime FROM document_versions WHERE id = :id")
VERSION_DOCUMENT_SQL = text("SELECT document_id FROM document_versions WHERE id = :id")
PROBLEM_PAGES_SQL = text(
    """
    SELECT page_no, method, status, flagged FROM page_extractions
    WHERE document_version_id = :version_id AND (status = 'failed' OR flagged)
    ORDER BY page_no
    """
)
PROBLEM_BLOCKS_SQL = text(
    """
    SELECT page, seq, structure_path, bbox, text FROM (
        SELECT b.page, b.seq, b.structure_path, b.bbox, b.text,
               ROW_NUMBER() OVER (PARTITION BY b.page ORDER BY b.seq) AS rn
        FROM blocks b
        WHERE b.document_version_id = :version_id
          AND b.page = ANY(CAST(:pages AS INTEGER[]))
    ) ranked
    WHERE rn <= :per_page
    ORDER BY page, seq
    """
)
PAGE_TEXT_SQL = text(
    """
    SELECT page_no, text FROM page_texts
    WHERE document_version_id = :version_id AND page_no = ANY(CAST(:pages AS INTEGER[]))
    """
)
OPEN_TASKS_FOR_DOCUMENT_SQL = text(
    """
    SELECT t.id FROM review_tasks t
    LEFT JOIN document_versions dv
        ON t.subject_type = 'document_version' AND dv.id = t.subject_id
    WHERE t.id <> :task_id
      AND t.status = ANY(CAST(:open_statuses AS TEXT[]))
      AND ((t.subject_type = 'document' AND t.subject_id = :doc_id) OR dv.document_id = :doc_id)
    LIMIT 1
    """
)
MARK_REVIEWED_SQL = text(
    """
    UPDATE documents SET review_state = 'reviewed', updated_by = :actor, updated_at = :now
    WHERE id = :id
    """
)
ENQUEUE_SQL = text(
    """
    INSERT INTO job_queue (queue, payload, status, idempotency_key)
    VALUES (:queue, CAST(:payload AS JSON), 'queued', :idempotency_key)
    ON CONFLICT DO NOTHING
    """
)


class ReviewTaskItem(BaseModel):
    """A review task as listed."""

    id: uuid.UUID
    kind: str
    status: str
    priority: int
    subject_type: str
    subject_id: uuid.UUID | None
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    opened_at: datetime
    sla_due_at: datetime | None
    title: str | None


class ReviewTaskList(BaseModel):
    """One page of review tasks, in queue order."""

    items: list[ReviewTaskItem]
    next_cursor: str | None
    total: int


class DocumentSummary(BaseModel):
    """The document fields a reviewer needs next to a task."""

    id: uuid.UUID
    canonical_id: str
    doc_type: str
    title: str
    review_state: str
    metadata: dict[str, Any]
    meta_confidence: float | None
    current_version_id: uuid.UUID | None


class VersionSummary(BaseModel):
    """A document version as shown with a parse failure."""

    id: uuid.UUID
    document_id: uuid.UUID
    page_count: int | None
    mime: str


class BlockItem(BaseModel):
    """A block on a problem page."""

    seq: int
    structure_path: str | None
    page: int | None
    bbox: Any  # JSONB; the shape depends on the parser
    text: str


class ProblemPage(BaseModel):
    """A page that failed extraction or was flagged, with its first blocks and page text."""

    page_no: int
    method: str
    status: str
    flagged: bool
    page_text: str | None
    page_text_truncated: bool
    blocks: list[BlockItem]


class ReviewTaskDetail(ReviewTaskItem):
    """A review task with its context."""

    closed_at: datetime | None
    resolution: dict[str, Any] | None
    document: DocumentSummary | None = None
    version: VersionSummary | None = None
    problem_pages: list[ProblemPage] = Field(default_factory=list)
    near_duplicate_of: DocumentSummary | None = None


class ReviewTaskUpdate(ReviewTaskItem):
    """A task after an assign or decision, with any notices about what was not done."""

    closed_at: datetime | None
    resolution: dict[str, Any] | None
    notices: list[str] = Field(default_factory=list)


class AssignBody(BaseModel):
    """Body of POST /{id}/assign. ``null`` unassigns; ``me`` assigns the caller."""

    assignee_id: uuid.UUID | Literal["me"] | None


class DecisionBody(BaseModel):
    """Body of POST /{id}/decision."""

    action: Action
    fields: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _check_fields_and_note(self) -> "DecisionBody":
        if self.note is not None:
            self.note = self.note.strip() or None
        if self.action == "edit_approve":
            if not self.fields:
                raise ValueError("fields are required for edit_approve")
        elif self.fields is not None:
            raise ValueError("fields are only allowed for edit_approve")
        if self.action in ("reject", "needs_info"):
            if self.note is None or len(self.note) < 3:
                raise ValueError("a note of at least 3 characters is required")
        return self


def _encode_cursor(priority: int, opened_at: datetime, task_id: uuid.UUID) -> str:
    raw = json.dumps([priority, opened_at.isoformat(), str(task_id)], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        priority, opened_at, task_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return int(priority), datetime.fromisoformat(opened_at), uuid.UUID(task_id)
    except (binascii.Error, AttributeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc


def _assignee_clause(value: str | None, actor_id: uuid.UUID, params: dict[str, Any]) -> str | None:
    if value is None:
        return None
    if value == "none":
        return "t.assignee_id IS NULL"
    if value == "me":
        params["assignee"] = actor_id
        return "t.assignee_id = :assignee"
    try:
        params["assignee"] = uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="assignee must be me, none or a user id"
        ) from exc
    return "t.assignee_id = :assignee"


def _near_duplicate_id(resolution: dict[str, Any] | None) -> uuid.UUID | None:
    value: Any = (resolution or {}).get("near_duplicate_of")
    if isinstance(value, dict):
        value = value.get("document_id", value.get("id"))
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _task_row(session: AsyncSession, task_id: uuid.UUID) -> dict[str, Any]:
    row = (await session.execute(TASK_SQL, {"id": task_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Review task not found")
    return dict(row)


async def _lock_task(session: AsyncSession, task_id: uuid.UUID) -> dict[str, Any]:
    row = (await session.execute(LOCK_TASK_SQL, {"id": task_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Review task not found")
    return dict(row)


async def _document_id_for_subject(
    session: AsyncSession, subject_type: str, subject_id: uuid.UUID | None
) -> uuid.UUID | None:
    if subject_id is None:
        return None
    if subject_type == "document":
        return subject_id
    if subject_type == "document_version":
        result = await session.execute(VERSION_DOCUMENT_SQL, {"id": subject_id})
        document_id: uuid.UUID | None = result.scalar_one_or_none()
        return document_id
    return None


async def _fetch_document(session: AsyncSession, document_id: uuid.UUID) -> DocumentSummary | None:
    row = (await session.execute(DOCUMENT_SQL, {"id": document_id})).mappings().first()
    return None if row is None else DocumentSummary.model_validate(dict(row))


async def _problem_pages(session: AsyncSession, version_id: uuid.UUID) -> list[ProblemPage]:
    page_rows = (
        (await session.execute(PROBLEM_PAGES_SQL, {"version_id": version_id})).mappings().all()
    )
    if not page_rows:
        return []
    pages = [int(row["page_no"]) for row in page_rows]

    blocks_by_page: dict[int, list[BlockItem]] = {}
    block_rows = (
        (
            await session.execute(
                PROBLEM_BLOCKS_SQL,
                {"version_id": version_id, "pages": pages, "per_page": BLOCKS_PER_PAGE},
            )
        )
        .mappings()
        .all()
    )
    for block in block_rows:
        blocks_by_page.setdefault(int(block["page"]), []).append(
            BlockItem(
                seq=block["seq"],
                structure_path=block["structure_path"],
                page=block["page"],
                bbox=block["bbox"],
                text=block["text"],
            )
        )

    texts: dict[int, str] = {}
    text_rows = (
        (await session.execute(PAGE_TEXT_SQL, {"version_id": version_id, "pages": pages}))
        .mappings()
        .all()
    )
    for page_text in text_rows:
        texts[int(page_text["page_no"])] = page_text["text"]

    result: list[ProblemPage] = []
    for row in page_rows:
        page_no = int(row["page_no"])
        full_text = texts.get(page_no)
        result.append(
            ProblemPage(
                page_no=page_no,
                method=row["method"],
                status=row["status"],
                flagged=row["flagged"],
                page_text=None if full_text is None else full_text[:PAGE_TEXT_LIMIT],
                page_text_truncated=full_text is not None and len(full_text) > PAGE_TEXT_LIMIT,
                blocks=blocks_by_page.get(page_no, []),
            )
        )
    return result


async def _task_update(
    session: AsyncSession, task_id: uuid.UUID, notices: list[str]
) -> ReviewTaskUpdate:
    row = await _task_row(session, task_id)
    return ReviewTaskUpdate(**row, notices=notices)


async def _enqueue(
    session: AsyncSession, queue: str, payload: dict[str, Any], idempotency_key: str
) -> None:
    await session.execute(
        ENQUEUE_SQL,
        {"queue": queue, "payload": json.dumps(payload), "idempotency_key": idempotency_key},
    )


@router.get("", response_model=ReviewTaskList)
async def list_tasks(
    response: Response,
    kind: Kind | None = None,
    status: list[Status] | None = Query(default=None),  # noqa: B008
    assignee: str | None = Query(default=None, max_length=64),  # noqa: B008
    source: str | None = Query(default=None, max_length=100),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    cursor: str | None = Query(default=None, max_length=512),  # noqa: B008
    actor: CurrentUser = Depends(require_permission("review.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ReviewTaskList:
    """List review tasks. Defaults to open and in-review tasks, ordered by priority then age."""
    response.headers["Cache-Control"] = NO_STORE

    params: dict[str, Any] = {"statuses": status or OPEN_STATUSES}
    clauses = ["t.status = ANY(CAST(:statuses AS TEXT[]))"]
    if kind is not None:
        clauses.append("t.kind = :kind")
        params["kind"] = kind
    assignee_sql = _assignee_clause(assignee, actor.id, params)
    if assignee_sql is not None:
        clauses.append(assignee_sql)
    if source is not None:
        clauses.append(SOURCE_CLAUSE)
        params["source"] = source

    page_params = dict(params)
    page_clauses = list(clauses)
    if cursor is not None:
        priority, opened_at, task_id = _decode_cursor(cursor)
        page_clauses.append("(t.priority, t.opened_at, t.id) > (:c_priority, :c_opened_at, :c_id)")
        page_params.update(c_priority=priority, c_opened_at=opened_at, c_id=task_id)
    page_params["limit"] = limit + 1

    count_sql = LIST_COUNT_SQL.format(from_sql=_TASK_FROM, where=" AND ".join(clauses))
    total = (await session.execute(text(count_sql), params)).scalar_one()

    page_sql = LIST_PAGE_SQL.format(
        columns=_TASK_COLUMNS, from_sql=_TASK_FROM, where=" AND ".join(page_clauses)
    )
    rows = (await session.execute(text(page_sql), page_params)).mappings().all()
    has_more = len(rows) > limit
    page = rows[:limit]
    items = [ReviewTaskItem.model_validate(dict(row)) for row in page]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(int(last["priority"]), last["opened_at"], last["id"])
    return ReviewTaskList(items=items, next_cursor=next_cursor, total=int(total))


@router.get("/{task_id}", response_model=ReviewTaskDetail)
async def get_task(
    task_id: uuid.UUID,
    response: Response,
    actor: CurrentUser = Depends(require_permission("review.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ReviewTaskDetail:
    """Return one task with its context: the document, version, problem pages and duplicate."""
    response.headers["Cache-Control"] = NO_STORE
    row = await _task_row(session, task_id)

    document: DocumentSummary | None = None
    version: VersionSummary | None = None
    problem_pages: list[ProblemPage] = []
    subject_id = row["subject_id"]
    if subject_id is not None and row["subject_type"] == "document":
        document = await _fetch_document(session, subject_id)
    elif subject_id is not None and row["subject_type"] == "document_version":
        version_row = (await session.execute(VERSION_SQL, {"id": subject_id})).mappings().first()
        if version_row is not None:
            version = VersionSummary.model_validate(dict(version_row))
            document = await _fetch_document(session, version.document_id)
            problem_pages = await _problem_pages(session, version.id)

    near_duplicate: DocumentSummary | None = None
    duplicate_id = _near_duplicate_id(row["resolution"])
    if duplicate_id is not None:
        near_duplicate = await _fetch_document(session, duplicate_id)

    return ReviewTaskDetail(
        **row,
        document=document,
        version=version,
        problem_pages=problem_pages,
        near_duplicate_of=near_duplicate,
    )


@router.post("/{task_id}/assign", response_model=ReviewTaskUpdate)
async def assign_task(
    task_id: uuid.UUID,
    body: AssignBody,
    request: Request,
    response: Response,
    actor: CurrentUser = Depends(require_permission("review.decide")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ReviewTaskUpdate:
    """Assign a task to a content editor or platform admin, or unassign it with null."""
    response.headers["Cache-Control"] = NO_STORE
    task = await _lock_task(session, task_id)
    if task["status"] in CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail="Task is already closed")

    assignee_id = actor.id if isinstance(body.assignee_id, str) else body.assignee_id
    if assignee_id is not None:
        eligible = await session.execute(
            ASSIGNABLE_SQL, {"id": assignee_id, "roles": ASSIGNABLE_ROLES}
        )
        if eligible.first() is None:
            raise HTTPException(
                status_code=422,
                detail="Assignee must be an active content editor or platform admin",
            )

    status_before = str(task["status"])
    status_after = (
        "in_review" if assignee_id is not None and status_before == "open" else status_before
    )
    now = datetime.now(UTC)
    await session.execute(
        ASSIGN_SQL,
        {
            "id": task_id,
            "assignee_id": assignee_id,
            "status": status_after,
            "actor": actor.id,
            "now": now,
        },
    )
    await write_audit(
        session,
        action="review.assign",
        actor=actor,
        object_type="review_task",
        object_id=str(task_id),
        detail={
            "task_id": str(task_id),
            "assignee_id": None if assignee_id is None else str(assignee_id),
            "status_before": status_before,
            "status_after": status_after,
        },
        ctx=audit_context_from_request(request),
    )
    return await _task_update(session, task_id, notices=[])


@router.post("/{task_id}/decision", response_model=ReviewTaskUpdate)
async def decide_task(
    task_id: uuid.UUID,
    body: DecisionBody,
    request: Request,
    response: Response,
    actor: CurrentUser = Depends(require_permission("review.decide")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ReviewTaskUpdate:
    """Record a decision: approve, edit_approve, reject or needs_info.

    The proposal in ``resolution`` is never changed. The decision is stored next to it.
    """
    response.headers["Cache-Control"] = NO_STORE
    task = await _lock_task(session, task_id)
    if task["status"] in CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail="Task is already closed")

    kind = str(task["kind"])
    fields: dict[str, Any] = body.fields or {}
    is_metadata_edit = kind == "metadata" and body.action == "edit_approve"
    if is_metadata_edit:
        unknown = sorted(set(fields) - METADATA_FIELDS)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown metadata field(s): {', '.join(unknown)}",
            )

    document_id = await _document_id_for_subject(session, task["subject_type"], task["subject_id"])
    if is_metadata_edit and document_id is None:
        raise HTTPException(status_code=422, detail="Metadata task has no document to edit")

    now = datetime.now(UTC)
    resolution: dict[str, Any] = dict(task["resolution"] or {})
    decision: dict[str, Any] = {
        "action": body.action,
        "note": body.note,
        "decided_by": str(actor.id),
        "decided_at": now.isoformat(),
    }
    if body.fields is not None:
        decision["fields"] = body.fields
    resolution["decision"] = decision

    notices: list[str] = []
    if kind == "metadata" and body.action == "approve" and resolution.get("near_duplicate_of"):
        notices.append(NEAR_DUPLICATE_NOTICE)

    closes = body.action != "needs_info"
    if body.action == "needs_info":
        new_status = "in_review"
        resolution["needs_info"] = True
    elif body.action == "reject":
        new_status = "rejected"
    else:
        new_status = "done"

    await session.execute(
        DECISION_SQL,
        {
            "id": task_id,
            "status": new_status,
            "closed_at": now if closes else None,
            "resolution": json.dumps(resolution),
            "actor": actor.id,
            "now": now,
        },
    )

    if closes and document_id is not None:
        # Lock the document so two closes on it are serialised and each sees the other's result.
        await session.execute(LOCK_DOCUMENT_SQL, {"id": document_id})
        still_open = (
            await session.execute(
                OPEN_TASKS_FOR_DOCUMENT_SQL,
                {
                    "task_id": task_id,
                    "doc_id": document_id,
                    "open_statuses": OPEN_STATUSES,
                },
            )
        ).first()
        if still_open is None:
            await session.execute(
                MARK_REVIEWED_SQL, {"id": document_id, "actor": actor.id, "now": now}
            )
        await _enqueue(
            session,
            "ingest.publish",
            {"document_id": str(document_id)},
            f"publish-after-review:{task_id}",
        )

    if is_metadata_edit and document_id is not None:
        await _enqueue(
            session,
            "ingest.apply_metadata",
            {
                "document_id": str(document_id),
                "fields": fields,
                "actor_user_id": str(actor.id),
                "reason": body.note or "review edit",
                "review_task_id": str(task_id),
            },
            f"review:{task_id}",
        )

    await write_audit(
        session,
        action="review.decision",
        actor=actor,
        object_type="review_task",
        object_id=str(task_id),
        detail={
            "task_id": str(task_id),
            "kind": kind,
            "action": body.action,
            "fields": sorted(fields),
        },
        ctx=audit_context_from_request(request),
    )
    return await _task_update(session, task_id, notices=notices)
