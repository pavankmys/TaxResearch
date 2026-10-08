"""Platform ingestion endpoints: submit a URL or an uploaded file, and read a job's status.

Submitting writes the ingestion job and the acquire job in the request transaction. The worker
computes the canonical ID from the metadata, so the API passes the raw fields through. An upload
is stored once under its content hash, in the same layout the worker uses for fetched files.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from taxresearch_storage import ObjectStore, raw_key, sniff_mime

from app.audit import audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.db import get_session
from app.ingest_config import SourceInfo, load_doc_types, load_sources
from app.object_store import get_object_store

router = APIRouter(prefix="/v1/platform/ingestion", tags=["ingestion"])

NO_STORE = "private, no-store"
MAX_TEXT = 300
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
# Form fields and multipart framing can add a little to the file size.
UPLOAD_OVERHEAD_BYTES = 64 * 1024

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
SOURCE_ENABLED_SQL = text("SELECT enabled FROM sources WHERE code = :code")
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


async def _upsert_source(session: AsyncSession, source: SourceInfo) -> Any:  # noqa: ANN401
    """Ensure the sources row exists and that the source is enabled in the table too.

    The table's enabled flag is set through PATCH /v1/platform/sources/{code}. Config already
    rejected disabled sources; this rejects those disabled at run time.
    """
    source_id = (
        await session.execute(UPSERT_SOURCE_SQL, {"code": source.code, "kind": source.kind})
    ).scalar_one()
    enabled = (await session.execute(SOURCE_ENABLED_SQL, {"code": source.code})).scalar_one()
    if enabled is False:
        raise HTTPException(status_code=422, detail=f"Source is disabled: {source.code}")
    return source_id


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

    source_id = await _upsert_source(session, source)
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


def _upload_name(filename: str | None) -> str:
    """The base name of the uploaded file, without path parts or control characters."""
    name = re.split(r"[\\/]", filename or "")[-1]
    cleaned = "".join(char for char in name if ord(char) >= 32)
    return cleaned.strip()[:255] or "upload"


async def _read_capped(upload: UploadFile) -> bytes:
    """Read the upload in chunks, refusing anything over the cap."""
    buffer = bytearray()
    while True:
        chunk = await upload.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            return bytes(buffer)
        buffer.extend(chunk)
        if len(buffer) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File is larger than 50 MB")


def _store_once(store: ObjectStore, key: str, data: bytes, mime: str) -> None:
    """Write the bytes under their content hash unless they are already there."""
    if not store.exists(key):
        store.put(key, data, mime)


@router.post("/manual", status_code=202, response_model=SubmittedJob)
async def submit_manual(
    request: Request,
    response: Response,
    file: UploadFile = File(...),  # noqa: B008
    source: str = Form(..., min_length=1, max_length=100),
    doc_type: str = Form(..., min_length=1, max_length=50),
    title: str | None = Form(default=None),
    series: str | None = Form(default=None),
    number: str | None = Form(default=None),
    year: str | None = Form(default=None),
    circular_a: str | None = Form(default=None),
    circular_b: str | None = Form(default=None),
    case_number: str | None = Form(default=None),
    court_code: str | None = Form(default=None),
    decision_date: str | None = Form(default=None),
    actor: CurrentUser = Depends(require_permission("ingest.upload")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
    store: ObjectStore = Depends(get_object_store),  # noqa: B008
) -> SubmittedJob:
    """Upload a PDF or HTML file for loading. It is stored once, then the worker takes over."""
    response.headers["Cache-Control"] = NO_STORE
    declared = request.headers.get("content-length")
    if (
        declared is not None
        and declared.isdigit()
        and int(declared) > (MAX_UPLOAD_BYTES + UPLOAD_OVERHEAD_BYTES)
    ):
        raise HTTPException(status_code=413, detail="File is larger than 50 MB")

    source_info = _source_or_422(source)
    if doc_type not in load_doc_types():
        raise HTTPException(status_code=422, detail=f"Unknown doc_type: {doc_type}")

    data = await _read_capped(file)
    mime = sniff_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Only PDF and HTML files are accepted")
    sha = hashlib.sha256(data).hexdigest()
    key = raw_key(sha)
    await run_in_threadpool(_store_once, store, key, data, mime)

    metadata: dict[str, Any] = {
        "title": _clean("title", title),
        "series": _clean("series", series),
        "number": _clean("number", number),
        "year": _clean("year", year),
        "circular_a": _clean("circular_a", circular_a),
        "circular_b": _clean("circular_b", circular_b),
        "case_number": _clean("case_number", case_number),
        "court_code": _clean("court_code", court_code),
        "decision_date": _clean("decision_date", decision_date),
    }

    source_id = await _upsert_source(session, source_info)
    job_id = (
        await session.execute(INSERT_JOB_SQL, {"source_id": source_id, "url": None})
    ).scalar_one()

    payload: dict[str, Any] = {
        "ingestion_job_id": str(job_id),
        "source_code": source_info.code,
        "doc_type": doc_type,
        "url": None,
        "file_path": None,
        "object_key": key,
        "file_name": _upload_name(file.filename),
        **metadata,
    }
    await session.execute(
        INSERT_QUEUE_SQL,
        {"payload": json.dumps(payload), "idempotency_key": str(job_id)},
    )

    await write_audit(
        session,
        action="ingest.upload",
        actor=actor,
        object_type="ingestion_job",
        object_id=str(job_id),
        detail={
            "source": source_info.code,
            "doc_type": doc_type,
            "mime": mime,
            "size": len(data),
            "sha256": sha,
        },
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
