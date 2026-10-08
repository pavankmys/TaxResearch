"""Shared plumbing for the M3 stages: payload parsing, job status and the handler wrapper.

Stages follow parse.py: mark the ingestion job running, do the work and its writes in one
transaction, mark the job done. A failure marks the job failed in a separate transaction and is
re-raised, so the runner can retry it (PermanentError is not retried).
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Engine

from worker import db
from worker.errors import PermanentError
from worker.queue import Job

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """The current time in UTC."""
    return datetime.now(UTC)


def stage_ids(payload: dict[str, Any]) -> tuple[UUID, UUID]:
    """(ingestion_job_id, document_version_id) from a stage payload.

    Raises:
        PermanentError: either id is missing or malformed.
    """
    try:
        job_id = UUID(str(payload.get("ingestion_job_id")))
        version_id = UUID(str(payload.get("document_version_id")))
    except (ValueError, TypeError) as exc:
        raise PermanentError("payload needs ingestion_job_id and document_version_id") from exc
    return job_id, version_id


def mark_running(engine: Engine, job_id: UUID, stage: str) -> None:
    """Set the job's stage and status to running and count the attempt."""
    with engine.begin() as conn:
        changed = db.update_job(
            conn,
            job_id,
            stage=stage,
            status="running",
            attempt=db.ingestion_jobs.c.attempt + 1,
            started_at=utc_now(),
            finished_at=None,
            error_code=None,
            error_detail=None,
        )
    if changed != 1:
        raise PermanentError(f"ingestion job not found: {job_id}")


def mark_failed(engine: Engine, job_id: UUID, exc: BaseException) -> None:
    """Record a failure on the job. Never hides the original error."""
    try:
        with engine.begin() as conn:
            db.update_job(
                conn,
                job_id,
                status="failed",
                error_code=type(exc).__name__,
                error_detail=str(exc)[:500],
                finished_at=utc_now(),
            )
    except Exception:
        logger.exception(f"Could not record failure for ingestion job {job_id}")


def mark_done(conn: Any, job_id: UUID, **extra: Any) -> None:  # noqa: ANN401 - SQLAlchemy Connection
    """Set the job's status to done inside the caller's transaction."""
    db.update_job(
        conn,
        job_id,
        status="done",
        error_code=None,
        error_detail=None,
        finished_at=utc_now(),
        **extra,
    )


def make_version_stage_handler(
    engine: Engine,
    stage: str,
    body: Callable[[UUID, UUID], None],
) -> Callable[[Job], None]:
    """Wrap a stage body that takes (job_id, version_id) with the job status handling."""

    def handle(job: Job) -> None:
        job_id, version_id = stage_ids(job.payload)
        mark_running(engine, job_id, stage)
        try:
            body(job_id, version_id)
        except Exception as exc:
            mark_failed(engine, job_id, exc)
            raise

    return handle
