"""Parse stage: blocks, page accounting and the cross-check, written in one transaction.

The stage runs for one document version (queue ``ingest.parse``):

1. Mark the ingestion job running (stage parse).
2. Skip when the version was already parsed by the current parser version.
3. Read the raw bytes and parse them (PDF or HTML).
4. An unreadable PDF opens a parse_failure review task and fails the job without a retry.
5. Otherwise replace the version's blocks and pages in one transaction, check page accounting,
   open one parse_failure task when pages are flagged or failed, and mark the job done.

Other failures mark the job failed in a separate transaction and are re-raised, so the runner
can retry them. A PermanentError is not retried.
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection, Engine

from worker import db, review
from worker.config import load_ingestion_config
from worker.errors import PermanentError
from worker.ingest import html as html_parser
from worker.ingest.pdf import PdfParseError, parse_pdf
from worker.ingest.queues import CLASSIFY_QUEUE
from worker.ingest.simhash import simhash64
from worker.ingest.types import Block, PageResult, ParseConfig, ParseResult
from worker.objectstore import ObjectStore
from worker.queue import Job

logger = logging.getLogger(__name__)

PARSE_FAILURE = "parse_failure"
_PDF = "application/pdf"
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def _now() -> datetime:
    return datetime.now(UTC)


def parse_config_from(raw: dict[str, Any]) -> ParseConfig:
    """Build a ParseConfig from the ``parse`` section of config/ingestion.yaml.

    Keys that ParseConfig does not declare are ignored.
    """
    known = {f.name for f in fields(ParseConfig)}
    return ParseConfig(**{key: value for key, value in raw.items() if key in known})


def current_parser_version(mime: str, cfg: ParseConfig) -> str:
    """The parser version that would produce blocks for this mime type.

    Raises:
        PermanentError: no parser handles this mime type.
    """
    if mime == _PDF:
        return cfg.parser_version
    if mime in _HTML_TYPES:
        return html_parser.PARSER_VERSION
    raise PermanentError(f"no parser for mime type: {mime}")


def parse_bytes(data: bytes, mime: str, cfg: ParseConfig) -> ParseResult:
    """Run the parser for the mime type.

    Raises:
        PdfParseError: the PDF cannot be opened.
        PermanentError: no parser handles this mime type.
    """
    if mime == _PDF:
        return parse_pdf(data, cfg)
    if mime in _HTML_TYPES:
        return html_parser.parse_html(data, cfg)
    raise PermanentError(f"no parser for mime type: {mime}")


def document_text(pages: list[PageResult]) -> str:
    """The version's text: every page text joined with a newline."""
    return "\n".join(page.text for page in pages)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def page_extraction_rows(
    version_id: UUID, pages: list[PageResult], now: datetime
) -> list[dict[str, Any]]:
    """One page_extractions row per page."""
    return [
        {
            "document_version_id": version_id,
            "page_no": page.page_no,
            "method": page.method,
            "chars_engine_a": page.chars_engine_a,
            "chars_engine_b": page.chars_engine_b,
            "garble_score": page.garble_score,
            "ocr_conf": page.ocr_conf,
            "status": page.status,
            "flagged": page.flagged,
            "updated_at": now,
        }
        for page in pages
    ]


def page_text_rows(
    version_id: UUID, pages: list[PageResult], now: datetime
) -> list[dict[str, Any]]:
    """One page_texts row per page. ``body`` feeds the tsvector expression in db.py."""
    return [
        {
            "document_version_id": version_id,
            "page_no": page.page_no,
            "text": page.text,
            "body": page.text,
            "updated_at": now,
        }
        for page in pages
    ]


def block_rows(version_id: UUID, blocks: list[Block]) -> list[dict[str, Any]]:
    """One blocks row per block. structure_path stays NULL until the segmenter (M3)."""
    return [
        {
            "document_version_id": version_id,
            "seq": block.seq,
            "kind": block.kind,
            "page": block.page,
            "bbox": block.bbox,
            "para_label": block.para_label,
            "structure_path": None,
            "text": block.text,
            "text_sha256": _sha256_text(block.text),
            "is_boilerplate": block.is_boilerplate,
            "lang": block.lang,
        }
        for block in blocks
    ]


def problem_pages(pages: list[PageResult]) -> list[dict[str, Any]]:
    """The pages that are failed or flagged, with the reason, for the parse_failure task."""
    return [
        {"page_no": page.page_no, "status": page.status, "reason": page.reason}
        for page in pages
        if page.status == "failed" or page.flagged
    ]


def check_page_accounting(result: ParseResult, stored_rows: int) -> None:
    """Every page must have a PageResult and a stored page_extractions row.

    Raises:
        RuntimeError: the counts disagree. This is a bug in the parser or the writer.
    """
    if not len(result.pages) == result.page_count == stored_rows:
        raise RuntimeError(
            "page accounting mismatch: "
            f"pages={len(result.pages)} page_count={result.page_count} "
            f"page_extractions={stored_rows}"
        )


def _payload_ids(payload: dict[str, Any]) -> tuple[UUID, UUID]:
    try:
        job_id = UUID(str(payload.get("ingestion_job_id")))
        version_id = UUID(str(payload.get("document_version_id")))
    except (ValueError, TypeError) as exc:
        raise PermanentError("payload needs ingestion_job_id and document_version_id") from exc
    return job_id, version_id


def _mark_running(engine: Engine, job_id: UUID) -> None:
    with engine.begin() as conn:
        changed = db.update_job(
            conn,
            job_id,
            stage="parse",
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


def _mark_done(engine: Engine, job_id: UUID) -> None:
    with engine.begin() as conn:
        db.update_job(
            conn,
            job_id,
            status="done",
            error_code=None,
            error_detail=None,
            finished_at=_now(),
        )


def _record_unreadable(engine: Engine, job_id: UUID, version_id: UUID, exc: Exception) -> None:
    """Open a parse_failure task for an unreadable PDF and fail the job. Not retried."""
    now = _now()
    with engine.begin() as conn:
        if not db.has_open_review_task(conn, PARSE_FAILURE, "document_version", version_id):
            review.open_review_task(
                conn,
                PARSE_FAILURE,
                "document_version",
                version_id,
                {"reason": "unreadable_pdf", "error": str(exc)},
            )
        db.update_job(
            conn,
            job_id,
            status="failed",
            error_code="unreadable_pdf",
            error_detail=str(exc)[:500],
            finished_at=now,
        )
    logger.warning(f"Ingestion job {job_id}: version {version_id} is an unreadable PDF")


def _enqueue_classify(conn: Connection, job_id: UUID, version_id: UUID) -> None:
    """Queue the classify stage. Re-queueing the same version is a no-op (idempotency key)."""
    db.enqueue(
        conn,
        CLASSIFY_QUEUE,
        {"ingestion_job_id": str(job_id), "document_version_id": str(version_id)},
        idempotency_key=f"{version_id}:classify",
    )


def _write_parse_output(
    engine: Engine, job_id: UUID, version_id: UUID, result: ParseResult
) -> None:
    """Replace the version's derived rows and mark the job done, in one transaction."""
    now = _now()
    text = document_text(result.pages)
    with engine.begin() as conn:
        db.delete_parse_output(conn, version_id)
        db.insert_page_extractions(conn, page_extraction_rows(version_id, result.pages, now))
        db.insert_page_texts(conn, page_text_rows(version_id, result.pages, now))
        db.insert_blocks(conn, block_rows(version_id, result.blocks))
        check_page_accounting(result, db.count_page_extractions(conn, version_id))
        db.update_version(
            conn,
            version_id,
            page_count=result.page_count,
            parser_version=result.parser_version,
            ocr_used=result.ocr_used,
            ocr_conf=result.ocr_conf,
            parsed_at=now,
            text_sha256=_sha256_text(text),
            simhash=simhash64(text),
        )
        problems = problem_pages(result.pages)
        if problems and not db.has_open_review_task(
            conn, PARSE_FAILURE, "document_version", version_id
        ):
            review.open_review_task(
                conn,
                PARSE_FAILURE,
                "document_version",
                version_id,
                {"pages": problems},
            )
        db.update_job(
            conn,
            job_id,
            status="done",
            error_code=None,
            error_detail=None,
            finished_at=now,
        )
        _enqueue_classify(conn, job_id, version_id)
    logger.info(
        f"Ingestion job {job_id}: version {version_id} parsed, {result.page_count} pages, "
        f"{len(result.blocks)} blocks, {len(problems)} problem pages"
    )


def _parse(engine: Engine, store: ObjectStore, job_id: UUID, version_id: UUID) -> None:
    cfg = parse_config_from(load_ingestion_config().parse)
    with engine.begin() as conn:
        version = db.get_version(conn, version_id)
    if version is None:
        raise PermanentError(f"document version not found: {version_id}")

    mime = str(version["mime"])
    current = current_parser_version(mime, cfg)
    if version["parsed_at"] is not None and version["parser_version"] == current:
        _mark_done(engine, job_id)
        with engine.begin() as conn:
            _enqueue_classify(conn, job_id, version_id)
        logger.info(f"Ingestion job {job_id}: version {version_id} already parsed, skipped")
        return

    data = store.get(str(version["raw_s3_key"]))
    try:
        result = parse_bytes(data, mime, cfg)
    except PdfParseError as exc:
        _record_unreadable(engine, job_id, version_id, exc)
        return
    _write_parse_output(engine, job_id, version_id, result)


def make_parse_handler(engine: Engine, store: ObjectStore) -> Callable[[Job], None]:
    """Build the handler for queue ``ingest.parse``.

    Args:
        engine: Sync engine for the worker database.
        store: Object store that holds the raw bytes.
    """

    def handle(job: Job) -> None:
        job_id, version_id = _payload_ids(job.payload)
        _mark_running(engine, job_id)
        try:
            _parse(engine, store, job_id, version_id)
        except Exception as exc:
            _mark_failed(engine, job_id, exc)
            raise

    return handle
