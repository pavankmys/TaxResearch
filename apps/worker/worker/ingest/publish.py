"""Publish job: review state, first status row, corpus version and job completion (TSD 5.6).

Payload: ``{document_id, ingestion_job_id?}``. Without an ingestion job id, the document's latest
ingestion job that is not published yet is used.

- review_state: 'reviewed' stays when no task is open. Otherwise 'auto_published' when no task is
  open and meta_confidence is at least 0.85, else 'pending_review'.
- The first document_status_history row is 'in_force', from in_force_date, doc_date or today.
- A corpus_versions row is inserted, so that search caches see the change.
- The ingestion job gets published_at (once), stage publish and status done.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from worker import db
from worker.errors import PermanentError
from worker.ingest.metadata import CONFIDENCE_THRESHOLD
from worker.objectstore import ObjectStore
from worker.queue import Job

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("open", "in_review")


def review_state_for(reviewed: bool, open_tasks: int, meta_confidence: float | None) -> str:
    """The review state after a publish."""
    if open_tasks == 0 and reviewed:
        return "reviewed"
    if open_tasks == 0 and meta_confidence is not None and meta_confidence >= CONFIDENCE_THRESHOLD:
        return "auto_published"
    return "pending_review"


def _open_task_count(conn: Connection, document_id: UUID) -> int:
    version_ids = sa.select(db.document_versions.c.id).where(
        db.document_versions.c.document_id == document_id
    )
    count = conn.execute(
        sa.select(sa.func.count())
        .select_from(db.review_tasks)
        .where(
            db.review_tasks.c.status.in_(OPEN_STATUSES),
            sa.or_(
                sa.and_(
                    db.review_tasks.c.subject_type == "document",
                    db.review_tasks.c.subject_id == document_id,
                ),
                sa.and_(
                    db.review_tasks.c.subject_type == "document_version",
                    db.review_tasks.c.subject_id.in_(version_ids),
                ),
            ),
        )
    ).scalar_one()
    return int(count)


def _valid_from(conn: Connection, document_id: UUID, today: date) -> date:
    row = conn.execute(
        sa.select(db.documents.c.in_force_date, db.documents.c.doc_date).where(
            db.documents.c.id == document_id
        )
    ).one()
    value: Any = row[0] or row[1]
    return value if isinstance(value, date) else today


def _publish_job(conn: Connection, document_id: UUID, job_id: UUID | None, now: datetime) -> None:
    """Mark the job published, once: the given job, or the document's latest unpublished job."""
    query = sa.select(db.ingestion_jobs.c.id).where(db.ingestion_jobs.c.published_at.is_(None))
    if job_id is not None:
        query = query.where(db.ingestion_jobs.c.id == job_id)
    else:
        query = (
            query.where(db.ingestion_jobs.c.document_id == document_id)
            .order_by(db.ingestion_jobs.c.discovered_at.desc())
            .limit(1)
        )
    found = conn.execute(query).scalar()
    if found is None:
        return
    target = UUID(str(found))
    db.update_job(
        conn,
        target,
        stage="publish",
        status="done",
        published_at=now,
        error_code=None,
        error_detail=None,
        finished_at=now,
    )


def publish(conn: Connection, payload: dict[str, Any], today: date | None = None) -> str:
    """Publish one document in the caller's transaction. Returns the new review_state."""
    try:
        document_id = UUID(str(payload["document_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise PermanentError("publish needs a document_id") from exc
    raw_job = payload.get("ingestion_job_id")
    job_id = UUID(str(raw_job)) if raw_job else None
    now = datetime.now(UTC)
    day = today or now.date()

    doc = conn.execute(
        sa.select(
            db.documents.c.canonical_id,
            db.documents.c.review_state,
            db.documents.c.meta_confidence,
        ).where(db.documents.c.id == document_id)
    ).first()
    if doc is None:
        raise PermanentError(f"document not found: {document_id}")
    canonical_id = str(doc[0])
    previous = str(doc[1])
    meta_confidence = float(doc[2]) if doc[2] is not None else None

    state = review_state_for(
        reviewed=previous == "reviewed",
        open_tasks=_open_task_count(conn, document_id),
        meta_confidence=meta_confidence,
    )
    conn.execute(
        db.documents.update()
        .where(db.documents.c.id == document_id)
        .values(review_state=state, updated_at=now)
    )

    has_history = conn.execute(
        sa.select(sa.func.count())
        .select_from(db.document_status_history)
        .where(db.document_status_history.c.document_id == document_id)
    ).scalar_one()
    if int(has_history) == 0:
        conn.execute(
            db.document_status_history.insert().values(
                document_id=document_id,
                status="in_force",
                valid_from=_valid_from(conn, document_id, day),
                valid_to=None,
                set_by=None,
            )
        )

    conn.execute(db.corpus_versions.insert().values(reason=f"publish {canonical_id}"))
    _publish_job(conn, document_id, job_id, now)
    logger.info(f"Document {document_id}: published as {state}")
    return state


def make_publish_handler(engine: Engine, store: ObjectStore) -> Callable[[Job], None]:
    """Build the handler for queue ``ingest.publish``. The store is unused (uniform signature)."""

    def handle(job: Job) -> None:
        with engine.begin() as conn:
            publish(conn, job.payload)

    return handle
