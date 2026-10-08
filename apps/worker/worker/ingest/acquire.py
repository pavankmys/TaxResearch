"""Acquire stage: get the bytes, de-duplicate, and record the document and version.

The stage runs for one ingestion job (queue ``ingest.acquire``):

1. Mark the ingestion job running.
2. Read the file, or fetch the URL with the safety checks in fetch.py.
3. Hash the bytes and store them once, under ``raw/<sha[:2]>/<sha>``.
4. In one transaction: attach the URL to a known byte hash (skipped), or add a version to the
   document with the same canonical ID, or create a new document. Then enqueue the parse stage.

Failures are recorded on the ingestion job in a separate transaction and then re-raised, so the
runner can retry them. A PermanentError is not retried.
"""

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.engine import Engine

from worker import db
from worker.config import load_doc_type_ranks, load_ingestion_config, load_sources
from worker.errors import PermanentError
from worker.ingest.fetch import Resolver, fetch_url
from worker.ingest.loaders import (
    PARSE_QUEUE,
    LoadRequest,
    canonical_id_for,
    default_title,
    request_from_payload,
)
from worker.objectstore import ObjectStore
from worker.queue import Job

logger = logging.getLogger(__name__)

_HEAD_BYTES = 1024


def sniff_mime(data: bytes) -> str:
    """Identify a file by its first bytes. Only PDF and HTML are accepted.

    Raises:
        PermanentError: the bytes are neither PDF nor HTML.
    """
    head = data[:_HEAD_BYTES]
    if b"%PDF-" in head:
        return "application/pdf"
    lowered = head.lower()
    if b"<html" in lowered or b"<!doctype html" in lowered:
        return "text/html"
    raise PermanentError("unsupported file type: neither PDF nor HTML")


def raw_key(sha256: str) -> str:
    """Object key for raw bytes. Content-addressed, so it is never overwritten."""
    return f"raw/{sha256[:2]}/{sha256}"


def _job_id(payload: dict[str, Any]) -> UUID:
    try:
        return UUID(str(payload.get("ingestion_job_id")))
    except (ValueError, TypeError) as exc:
        raise PermanentError("payload has no valid ingestion_job_id") from exc


def _now() -> datetime:
    return datetime.now(UTC)


def _mark_running(engine: Engine, job_id: UUID) -> None:
    with engine.begin() as conn:
        changed = db.update_job(
            conn,
            job_id,
            stage="acquire",
            status="running",
            attempt=db.ingestion_jobs.c.attempt + 1,
            started_at=_now(),
            finished_at=None,
            error_code=None,
            error_detail=None,
        )
    if changed != 1:
        raise PermanentError(f"ingestion job not found: {job_id}")


def _mark_failed(engine: Engine, job_id: UUID, exc: BaseException) -> None:
    try:
        with engine.begin() as conn:
            db.update_job(
                conn,
                job_id,
                status="failed",
                error_code=type(exc).__name__,
                error_detail=str(exc)[:500],
                finished_at=_now(),
            )
    except Exception:
        # Never hide the original failure behind a database error while recording it.
        logger.exception(f"Could not record failure for ingestion job {job_id}")


def _read_input(
    req: LoadRequest,
    source_code: str,
    transport: httpx.BaseTransport | None,
    resolver: Resolver | None,
) -> tuple[bytes, str, str]:
    """Return (bytes, mime, source url recorded in document_sources)."""
    if req.file_path:
        path = Path(req.file_path)
        if not path.is_file():
            raise PermanentError(f"file not found: {path}")
        data = path.read_bytes()
        return data, sniff_mime(data), f"file://{path.name}"
    if req.url:
        source = load_sources()[source_code]
        result = fetch_url(
            req.url,
            source,
            load_ingestion_config().fetch,
            transport=transport,
            resolver=resolver,
        )
        return result.data, result.content_type, req.url
    raise PermanentError("the job has neither a URL nor a file path")


def _acquire(
    engine: Engine,
    store: ObjectStore,
    job_id: UUID,
    payload: dict[str, Any],
    transport: httpx.BaseTransport | None,
    resolver: Resolver | None,
) -> None:
    req = request_from_payload(payload)
    source = load_sources().get(req.source_code)
    if source is None:
        raise PermanentError(f"unknown source: {req.source_code}")
    if req.doc_type not in load_doc_type_ranks():
        raise PermanentError(f"unknown doc_type: {req.doc_type}")
    try:
        canonical = canonical_id_for(req)
    except ValueError as exc:
        raise PermanentError(str(exc)) from exc

    data, mime, source_url = _read_input(req, source.code, transport, resolver)
    sha = hashlib.sha256(data).hexdigest()
    key = raw_key(sha)
    if not store.exists(key):
        store.put(key, data, mime)

    with engine.begin() as conn:
        source_id = db.ensure_source(conn, source.code, source.kind)

        existing = db.find_version_by_sha(conn, sha)
        if existing is not None:
            _, existing_document_id = existing
            db.add_document_source(conn, existing_document_id, source_id, source_url)
            db.update_job(
                conn,
                job_id,
                stage="acquire",
                status="skipped",
                document_id=existing_document_id,
                finished_at=_now(),
            )
            logger.info(f"Ingestion job {job_id}: bytes already stored, skipped")
            return

        canonical_id = canonical or f"unk:{sha[:16]}"
        document_id = db.find_document_by_canonical(conn, canonical_id)
        if document_id is None:
            document_id = db.insert_document(
                conn,
                canonical_id=canonical_id,
                doc_type=req.doc_type,
                authority_rank=load_doc_type_ranks()[req.doc_type],
                title=default_title(req),
            )
        version_id, version_no = db.insert_version(
            conn,
            document_id=document_id,
            raw_s3_key=key,
            raw_sha256=sha,
            mime=mime,
        )
        db.set_current_version(conn, document_id, version_id)
        db.add_document_source(conn, document_id, source_id, source_url)
        db.update_job(
            conn,
            job_id,
            stage="acquire",
            status="done",
            document_id=document_id,
            finished_at=_now(),
        )
        db.enqueue(
            conn,
            PARSE_QUEUE,
            {"ingestion_job_id": str(job_id), "document_version_id": str(version_id)},
            idempotency_key=f"{version_id}:parse",
        )
        logger.info(f"Ingestion job {job_id}: document {document_id} version {version_no} acquired")


def make_acquire_handler(
    engine: Engine,
    store: ObjectStore,
    *,
    fetch_transport: httpx.BaseTransport | None = None,
    resolver: Resolver | None = None,
) -> Callable[[Job], None]:
    """Build the handler for queue ``ingest.acquire``.

    Args:
        engine: Sync engine for the worker database.
        store: Object store for raw bytes.
        fetch_transport: Optional httpx transport for URL loads (tests).
        resolver: Optional host resolver for URL loads (tests).
    """

    def handle(job: Job) -> None:
        job_id = _job_id(job.payload)
        _mark_running(engine, job_id)
        try:
            _acquire(engine, store, job_id, job.payload, fetch_transport, resolver)
        except Exception as exc:
            _mark_failed(engine, job_id, exc)
            raise

    return handle
