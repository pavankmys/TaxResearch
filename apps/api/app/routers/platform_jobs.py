"""Platform job endpoints: re-run a failed ingestion job from the stage that failed.

A retry resets the ingestion job to queued (the attempt count is kept, the error is cleared) and
enqueues its stage on the job queue. Only failed jobs can be retried.

Acquire is special: its payload carries the original request (source, doc_type, URL or upload
key, metadata), which the job row does not store. The retry reuses that payload from the queue
row that the submit or upload endpoint wrote. Later stages take the document version instead.
"""

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.db import get_session

router = APIRouter(prefix="/v1/platform/jobs", tags=["jobs"])

NO_STORE = "private, no-store"
STAGES_AFTER_ACQUIRE = ("parse", "classify", "segment", "extract_meta", "publish")

JOB_FOR_UPDATE_SQL = text(
    """
    SELECT id, stage, status, document_id
    FROM ingestion_jobs
    WHERE id = :id
    FOR UPDATE
    """
)
CURRENT_VERSION_SQL = text("SELECT current_version_id FROM documents WHERE id = :id")
ORIGINAL_ACQUIRE_SQL = text(
    """
    SELECT payload
    FROM job_queue
    WHERE queue = 'ingest.acquire' AND idempotency_key = :key
    ORDER BY created_at DESC
    LIMIT 1
    """
)
RESET_JOB_SQL = text(
    """
    UPDATE ingestion_jobs
    SET status = 'queued', error_code = NULL, error_detail = NULL, finished_at = NULL,
        updated_at = now()
    WHERE id = :id
    """
)
INSERT_QUEUE_SQL = text(
    """
    INSERT INTO job_queue (queue, payload, status, idempotency_key)
    VALUES (:queue, CAST(:payload AS JSON), 'queued', :idempotency_key)
    """
)


class RetryAccepted(BaseModel):
    """The job is queued again on this queue."""

    ingestion_job_id: uuid.UUID
    queue: str


async def _retry_payload(
    session: AsyncSession, job_id: uuid.UUID, stage: str, document_id: uuid.UUID | None
) -> dict[str, Any]:
    if stage == "acquire":
        raw = (
            await session.execute(ORIGINAL_ACQUIRE_SQL, {"key": str(job_id)})
        ).scalar_one_or_none()
        if raw is None:
            raise HTTPException(status_code=409, detail="The original request is no longer queued")
        original = json.loads(raw) if isinstance(raw, str) else dict(raw)
        return {**original, "ingestion_job_id": str(job_id)}

    version_id: uuid.UUID | None = None
    if document_id is not None:
        current = (
            await session.execute(CURRENT_VERSION_SQL, {"id": document_id})
        ).scalar_one_or_none()
        version_id = uuid.UUID(str(current)) if current is not None else None
    if version_id is None:
        raise HTTPException(status_code=409, detail="The job has no document version to re-run")
    return {"ingestion_job_id": str(job_id), "document_version_id": str(version_id)}


@router.post("/{job_id}/retry", status_code=202, response_model=RetryAccepted)
async def retry_job(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    actor: CurrentUser = Depends(require_permission("jobs.retry")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RetryAccepted:
    """Re-queue a failed ingestion job for its stage. Anything else is 409."""
    response.headers["Cache-Control"] = NO_STORE
    job = (await session.execute(JOB_FOR_UPDATE_SQL, {"id": job_id})).mappings().first()
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    if job["status"] != "failed":
        raise HTTPException(status_code=409, detail="Only a failed job can be retried")
    stage = str(job["stage"])
    if stage != "acquire" and stage not in STAGES_AFTER_ACQUIRE:
        raise HTTPException(status_code=409, detail=f"Unknown stage: {stage}")

    payload = await _retry_payload(session, job_id, stage, job["document_id"])
    queue = f"ingest.{stage}"
    await session.execute(RESET_JOB_SQL, {"id": job_id})
    await session.execute(
        INSERT_QUEUE_SQL,
        {
            "queue": queue,
            "payload": json.dumps(payload),
            "idempotency_key": f"retry:{job_id}:{uuid.uuid4()}",
        },
    )
    await write_audit(
        session,
        action="ingest.retry",
        actor=actor,
        object_type="ingestion_job",
        object_id=str(job_id),
        detail={"stage": stage, "queue": queue},
        ctx=audit_context_from_request(request),
    )
    return RetryAccepted(ingestion_job_id=job_id, queue=queue)
