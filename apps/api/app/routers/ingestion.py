"""Platform ingestion endpoints: submit a URL for loading, and read a job's status.

Submitting writes the ingestion job and the acquire job in the request transaction. The worker
computes the canonical ID from the metadata, so the API passes the raw fields through.
"""

import json
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.db import get_session
from app.ingest_config import SourceInfo, load_doc_types, load_sources

router = APIRouter(prefix="/v1/platform/ingestion", tags=["ingestion"])

NO_STORE = "private, no-store"
MAX_TEXT = 300

UPSERT_SOURCE_SQL = text(
    """
    INSERT INTO sources (code, kind, enabled, updated_at)
    VALUES (:code, :kind, true, now())
    ON CONFLICT (code) DO UPDATE SET updated_at = now()
    RETURNING id
    """
)
INSERT_JOB_SQL = text(
    """
    INSERT INTO ingestion_jobs (source_id, url, stage, status, attempt)
    VALUES (:source_id, :url, 'acquire', 'queued', 0)
    RETURNING id
    """
)
INSERT_QUEUE_SQL = text(
    """
    INSERT INTO job_queue (queue, payload, status, idempotency_key)
    VALUES ('ingest.acquire', CAST(:payload AS JSON), 'queued', :idempotency_key)
    """
)
JOB_STATUS_SQL = text(
    """
    SELECT id, stage, status, attempt, error_code, error_detail, document_id, url,
           started_at, finished_at
    FROM ingestion_jobs
    WHERE id = :id
    """
)


class UrlSubmission(BaseModel):
    """Body of POST /url."""

    source: str = Field(min_length=1, max_length=100)
    doc_type: str = Field(min_length=1, max_length=50)
    url: str = Field(min_length=8, max_length=2048)
    title: str | None = None
    series: str | None = None
    number: str | int | None = None
    year: str | int | None = None
    circular_a: str | int | None = None
    circular_b: str | int | None = None
    case_number: str | None = None
    court_code: str | None = None
    decision_date: str | None = None


class SubmittedJob(BaseModel):
    """Response of POST /url."""

    ingestion_job_id: uuid.UUID


class IngestionJobStatus(BaseModel):
    """Response of GET /jobs/{id}."""

    id: uuid.UUID
    stage: str
    status: str
    attempt: int
    error_code: str | None
    error_detail: str | None
    document_id: uuid.UUID | None
    url: str | None
    started_at: datetime | None
    finished_at: datetime | None


def _source_or_422(code: str) -> SourceInfo:
    source = load_sources().get(code)
    if source is None:
        raise HTTPException(status_code=422, detail=f"Unknown source: {code}")
    if not source.enabled:
        raise HTTPException(status_code=422, detail=f"Source is disabled: {code}")
    return source


def _check_url(url: str, source: SourceInfo) -> str:
    if any(ord(char) < 32 or char.isspace() for char in url):
        raise HTTPException(status_code=422, detail="URL contains invalid characters")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="URL is malformed") from exc
    if parts.scheme not in ("http", "https"):
        raise HTTPException(status_code=422, detail="Only http and https URLs are accepted")
    if host not in source.allowed_hosts:
        raise HTTPException(
            status_code=422,
            detail=f"Host is not allowed for source {source.code}: {host or '(none)'}",
        )
    return url


def _clean(name: str, value: str | int | None) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    if len(text_value) > MAX_TEXT:
        raise HTTPException(status_code=422, detail=f"{name} is too long")
    return text_value


@router.post("/url", status_code=202, response_model=SubmittedJob)
async def submit_url(
    body: UrlSubmission,
    request: Request,
    actor: CurrentUser = Depends(require_permission("ingest.submit")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SubmittedJob:
    """Queue a document for loading by URL. The worker fetches it and writes the records."""
    source = _source_or_422(body.source)
    if body.doc_type not in load_doc_types():
        raise HTTPException(status_code=422, detail=f"Unknown doc_type: {body.doc_type}")
    url = _check_url(body.url, source)

    metadata: dict[str, Any] = {
        "title": _clean("title", body.title),
        "series": _clean("series", body.series),
        "number": _clean("number", body.number),
        "year": _clean("year", body.year),
        "circular_a": _clean("circular_a", body.circular_a),
        "circular_b": _clean("circular_b", body.circular_b),
        "case_number": _clean("case_number", body.case_number),
        "court_code": _clean("court_code", body.court_code),
        "decision_date": _clean("decision_date", body.decision_date),
    }

    source_id = (
        await session.execute(UPSERT_SOURCE_SQL, {"code": source.code, "kind": source.kind})
    ).scalar_one()
    job_id = (
        await session.execute(INSERT_JOB_SQL, {"source_id": source_id, "url": url})
    ).scalar_one()

    payload: dict[str, Any] = {
        "ingestion_job_id": str(job_id),
        "source_code": source.code,
        "doc_type": body.doc_type,
        "url": url,
        "file_path": None,
        **metadata,
    }
    await session.execute(
        INSERT_QUEUE_SQL,
        {"payload": json.dumps(payload), "idempotency_key": str(job_id)},
    )

    await write_audit(
        session,
        action="ingest.submit_url",
        actor=actor,
        object_type="ingestion_job",
        object_id=str(job_id),
        detail={"source": source.code, "doc_type": body.doc_type, "url": url},
        ctx=audit_context_from_request(request),
    )
    return SubmittedJob(ingestion_job_id=uuid.UUID(str(job_id)))


@router.get("/jobs/{job_id}", response_model=IngestionJobStatus)
async def get_job(
    job_id: uuid.UUID,
    response: Response,
    actor: CurrentUser = Depends(require_permission("ingest.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> IngestionJobStatus:
    """Return the stage, status and error (if any) of one ingestion job."""
    response.headers["Cache-Control"] = NO_STORE
    row = (await session.execute(JOB_STATUS_SQL, {"id": job_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return IngestionJobStatus(**dict(row))
