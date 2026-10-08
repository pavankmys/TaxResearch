"""Platform document endpoints: browse documents, read their structure and pages, fix metadata.

Reads need ``documents.read``. Metadata edits need ``documents.edit``: field changes are queued as
an ``ingest.apply_metadata`` job (the worker is the one write path for metadata), and status
changes are written here with a history row. Every write is audited.
"""

import io
import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Literal

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from taxresearch_storage import ObjectStore

from app.audit import audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.db import get_session
from app.object_store import get_object_store

router = APIRouter(prefix="/v1/platform/documents", tags=["documents"])

NO_STORE = "private, no-store"
PAGE_IMAGE_CACHE = "private, max-age=3600"
PAGE_IMAGE_DPI = 110
PAGE_IMAGE_KEY = "derived/pages/{sha}/{page}-{dpi}.png"
MAX_LIMIT = 200
CHUNK_BYTES = 64 * 1024
OPEN_TASK_STATES = ("open", "in_review")
TYPED_TABLES: tuple[str, ...] = ("notifications", "circulars", "judgements")

DocumentStatus = Literal["in_force", "amended", "superseded", "rescinded", "struck_down", "stayed"]

# Field names a metadata edit may change. This is the contract list in the M3 plan; the worker
# job ingest.apply_metadata writes these into documents, the typed table and documents.metadata.
COMMON_FIELDS = frozenset(
    {
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
    }
)
NOTIFICATION_FIELDS = frozenset({"effective_date", "gazette_ref"})
CIRCULAR_FIELDS = frozenset({"circular_kind", "subject", "din"})
JUDGEMENT_FIELDS = frozenset(
    {
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
EDITABLE_FIELDS = COMMON_FIELDS | NOTIFICATION_FIELDS | CIRCULAR_FIELDS | JUDGEMENT_FIELDS
MAX_FIELDS_PER_EDIT = 40

DOCUMENT_SQL = text(
    """
    SELECT id, canonical_id, doc_type, authority_rank, title, number, series, doc_date,
           in_force_date, issuing_authority, status, review_state, current_version_id,
           court, bench, metadata, meta_confidence, created_at, updated_at
    FROM documents
    WHERE id = :id
    """
)
VERSION_SQL = text(
    """
    SELECT dv.id, dv.document_id, dv.raw_s3_key, dv.raw_sha256, dv.mime, dv.page_count,
           d.canonical_id
    FROM document_versions dv
    JOIN documents d ON d.id = dv.document_id
    WHERE dv.id = :version_id AND dv.document_id = :document_id
    """
)
VERSIONS_SQL = text(
    """
    SELECT id, version_no, mime, page_count, parsed_at, parser_version, segmenter_version,
           extractor_version, ocr_used
    FROM document_versions
    WHERE document_id = :id
    ORDER BY version_no
    """
)
SOURCE_LINKS_SQL = text(
    """
    SELECT s.code AS source_code, ds.url, ds.first_seen_at, ds.last_seen_at
    FROM document_sources ds
    JOIN sources s ON s.id = ds.source_id
    WHERE ds.document_id = :id
    ORDER BY ds.first_seen_at, ds.url
    """
)
STATUS_HISTORY_SQL = text(
    """
    SELECT status, valid_from, valid_to, set_by, created_at
    FROM document_status_history
    WHERE document_id = :id
    ORDER BY valid_from, created_at
    """
)
OPEN_TASKS_SQL = text(
    """
    SELECT id
    FROM review_tasks
    WHERE status IN ('open', 'in_review')
      AND (
        (subject_type = 'document' AND subject_id = :id)
        OR (subject_type = 'document_version' AND subject_id IN (
            SELECT dv.id FROM document_versions dv WHERE dv.document_id = :id))
      )
    ORDER BY opened_at
    """
)
BLOCKS_SQL = text(
    """
    SELECT b.id, b.seq, b.kind, b.page, b.bbox, b.para_label, b.structure_path,
           b.is_boilerplate, b.lang, b.text
    FROM blocks b
    JOIN document_versions dv ON dv.id = b.document_version_id
    WHERE b.document_version_id = :version_id AND dv.document_id = :document_id
    """
)
PAGES_SQL = text(
    """
    SELECT pe.page_no, pe.method, pe.chars_engine_a, pe.chars_engine_b, pe.garble_score,
           pe.ocr_conf, pe.status, pe.flagged
    FROM page_extractions pe
    JOIN document_versions dv ON dv.id = pe.document_version_id
    WHERE pe.document_version_id = :version_id AND dv.document_id = :document_id
    ORDER BY pe.page_no
    """
)
OPEN_STATUS_SQL = text(
    """
    SELECT valid_from
    FROM document_status_history
    WHERE document_id = :id AND valid_to IS NULL
    ORDER BY valid_from DESC
    LIMIT 1
    """
)
CLOSE_STATUS_SQL = text(
    """
    UPDATE document_status_history
    SET valid_to = :valid_from, updated_at = now()
    WHERE document_id = :id AND valid_to IS NULL
    """
)
INSERT_STATUS_SQL = text(
    """
    INSERT INTO document_status_history (document_id, status, valid_from, valid_to, set_by)
    VALUES (:id, :status, :valid_from, NULL, :actor)
    """
)
UPDATE_STATUS_SQL = text(
    """
    UPDATE documents SET status = :status, updated_at = now() WHERE id = :id
    """
)
INSERT_QUEUE_SQL = text(
    """
    INSERT INTO job_queue (queue, payload, status, idempotency_key)
    VALUES ('ingest.apply_metadata', CAST(:payload AS JSON), 'queued', :idempotency_key)
    """
)


class DocumentSummary(BaseModel):
    """One row of the document list."""

    id: uuid.UUID
    canonical_id: str
    doc_type: str
    title: str
    number: str | None
    series: str | None
    doc_date: date | None
    status: str
    review_state: str
    current_version_id: uuid.UUID | None
    updated_at: datetime


class DocumentList(BaseModel):
    """A page of documents. next_cursor is passed back as ``cursor``; null on the last page."""

    items: list[DocumentSummary]
    next_cursor: uuid.UUID | None


class VersionOut(BaseModel):
    """One version of a document."""

    id: uuid.UUID
    version_no: int
    mime: str
    page_count: int | None
    parsed_at: datetime | None
    parser_version: str | None
    segmenter_version: str | None
    extractor_version: str | None
    ocr_used: bool


class SourceLinkOut(BaseModel):
    """A URL a document was seen at, with the source it came from."""

    source_code: str
    url: str
    first_seen_at: datetime
    last_seen_at: datetime


class StatusEvent(BaseModel):
    """One row of the status history."""

    status: str
    valid_from: date
    valid_to: date | None
    set_by: uuid.UUID | None
    created_at: datetime


class DocumentDetail(BaseModel):
    """A document with its metadata, typed-table row, versions, sources and open tasks."""

    id: uuid.UUID
    canonical_id: str
    doc_type: str
    authority_rank: int
    title: str
    number: str | None
    series: str | None
    doc_date: date | None
    in_force_date: date | None
    issuing_authority: str | None
    court: str | None
    bench: str | None
    status: str
    review_state: str
    current_version_id: uuid.UUID | None
    metadata: dict[str, Any]
    meta_confidence: float | None
    created_at: datetime
    updated_at: datetime
    typed_table: str | None
    typed_row: dict[str, Any] | None
    versions: list[VersionOut]
    sources: list[SourceLinkOut]
    status_history: list[StatusEvent]
    open_review_task_ids: list[uuid.UUID]


class BlockOut(BaseModel):
    """One block of a version, in reading order."""

    id: uuid.UUID
    seq: int
    kind: str
    page: int | None
    bbox: Any  # noqa: ANN401 - JSONB: a list or object, as the worker wrote it
    para_label: str | None
    structure_path: str | None
    is_boilerplate: bool
    lang: str | None
    text: str


class BlockPage(BaseModel):
    """A page of blocks. next_cursor is the last seq; pass it back as ``after``."""

    items: list[BlockOut]
    next_cursor: int | None


class PageOut(BaseModel):
    """Extraction outcome for one page."""

    page_no: int
    method: str
    chars_engine_a: int | None
    chars_engine_b: int | None
    garble_score: float | None
    ocr_conf: float | None
    status: str
    flagged: bool


class PageList(BaseModel):
    """Page accounting for one version."""

    items: list[PageOut]


class DocumentPatch(BaseModel):
    """Body of PATCH /{id}: metadata fields, and optionally a status change."""

    fields: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=2000)
    status: DocumentStatus | None = None
    status_valid_from: date | None = None


class PatchAccepted(BaseModel):
    """What the PATCH did. Field edits are queued; status changes are written at once."""

    queued: bool
    status_changed: bool


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _document_or_404(session: AsyncSession, document_id: uuid.UUID) -> dict[str, Any]:
    row = (await session.execute(DOCUMENT_SQL, {"id": document_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)


async def _version_or_404(
    session: AsyncSession, document_id: uuid.UUID, version_id: uuid.UUID
) -> dict[str, Any]:
    row = (
        (await session.execute(VERSION_SQL, {"version_id": version_id, "document_id": document_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return dict(row)


@router.get("", response_model=DocumentList)
async def list_documents(
    response: Response,
    doc_type: str | None = Query(default=None, max_length=50),  # noqa: B008
    review_state: str | None = Query(default=None, max_length=50),  # noqa: B008
    q: str | None = Query(default=None, max_length=200),  # noqa: B008
    cursor: uuid.UUID | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),  # noqa: B008
    actor: CurrentUser = Depends(require_permission("documents.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DocumentList:
    """List documents, newest first. Filter by type, review state, or a title or ID prefix."""
    response.headers["Cache-Control"] = NO_STORE
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit + 1}
    if doc_type:
        clauses.append("doc_type = :doc_type")
        params["doc_type"] = doc_type
    if review_state:
        clauses.append("review_state = :review_state")
        params["review_state"] = review_state
    term = (q or "").strip()
    if term:
        pattern = _escape_like(term)
        clauses.append("(title ILIKE :contains OR canonical_id ILIKE :prefix)")
        params["contains"] = f"%{pattern}%"
        params["prefix"] = f"{pattern}%"
    if cursor is not None:
        clauses.append("id < :cursor")
        params["cursor"] = cursor
    where = " AND ".join(clauses) if clauses else "TRUE"
    sql = text(
        f"""
        SELECT id, canonical_id, doc_type, title, number, series, doc_date, status,
               review_state, current_version_id, updated_at
        FROM documents
        WHERE {where}
        ORDER BY id DESC
        LIMIT :limit
        """
    )
    rows = (await session.execute(sql, params)).mappings().all()
    has_more = len(rows) > limit
    items = [DocumentSummary(**dict(row)) for row in rows[:limit]]
    return DocumentList(items=items, next_cursor=items[-1].id if has_more and items else None)


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID,
    response: Response,
    actor: CurrentUser = Depends(require_permission("documents.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DocumentDetail:
    """One document: metadata, typed-table row, versions, sources, status history, open tasks."""
    response.headers["Cache-Control"] = NO_STORE
    doc = await _document_or_404(session, document_id)

    typed_table: str | None = None
    typed_row: dict[str, Any] | None = None
    for table in TYPED_TABLES:
        found = (
            (
                await session.execute(
                    text(f"SELECT * FROM {table} WHERE document_id = :id"),
                    {"id": document_id},
                )
            )
            .mappings()
            .first()
        )
        if found is not None:
            typed_table, typed_row = table, dict(found)
            break

    versions = (await session.execute(VERSIONS_SQL, {"id": document_id})).mappings().all()
    sources = (await session.execute(SOURCE_LINKS_SQL, {"id": document_id})).mappings().all()
    history = (await session.execute(STATUS_HISTORY_SQL, {"id": document_id})).mappings().all()
    tasks = (await session.execute(OPEN_TASKS_SQL, {"id": document_id})).scalars().all()

    return DocumentDetail(
        **doc,
        typed_table=typed_table,
        typed_row=typed_row,
        versions=[VersionOut(**dict(row)) for row in versions],
        sources=[SourceLinkOut(**dict(row)) for row in sources],
        status_history=[StatusEvent(**dict(row)) for row in history],
        open_review_task_ids=[uuid.UUID(str(task)) for task in tasks],
    )


@router.get("/{document_id}/versions/{version_id}/blocks", response_model=BlockPage)
async def list_blocks(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    response: Response,
    page: int | None = Query(default=None, ge=1),  # noqa: B008
    after: int | None = Query(default=None, ge=0, description="Last seq of the previous page"),  # noqa: B008
    limit: int = Query(default=200, ge=1, le=MAX_LIMIT),  # noqa: B008
    actor: CurrentUser = Depends(require_permission("documents.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BlockPage:
    """Blocks of one version in seq order. Optionally one page, and keyset-paged by seq."""
    response.headers["Cache-Control"] = NO_STORE
    await _version_or_404(session, document_id, version_id)
    filters = ""
    params: dict[str, Any] = {
        "version_id": version_id,
        "document_id": document_id,
        "limit": limit + 1,
    }
    if page is not None:
        filters += " AND b.page = :page"
        params["page"] = page
    if after is not None:
        filters += " AND b.seq > :after"
        params["after"] = after
    sql = text(f"{BLOCKS_SQL.text}{filters} ORDER BY b.seq LIMIT :limit")
    rows = (await session.execute(sql, params)).mappings().all()
    has_more = len(rows) > limit
    items = [BlockOut(**dict(row)) for row in rows[:limit]]
    return BlockPage(items=items, next_cursor=items[-1].seq if has_more and items else None)


@router.get("/{document_id}/versions/{version_id}/pages", response_model=PageList)
async def list_pages(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    response: Response,
    actor: CurrentUser = Depends(require_permission("documents.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PageList:
    """Extraction outcome for every page of one version."""
    response.headers["Cache-Control"] = NO_STORE
    await _version_or_404(session, document_id, version_id)
    rows = (
        (await session.execute(PAGES_SQL, {"version_id": version_id, "document_id": document_id}))
        .mappings()
        .all()
    )
    return PageList(items=[PageOut(**dict(row)) for row in rows])


def _render_page_png(data: bytes, page_no: int) -> bytes | None:
    """Render one PDF page at PAGE_IMAGE_DPI. None when the page is out of range or unreadable."""
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError:
        return None
    try:
        if page_no < 1 or page_no > len(pdf):
            return None
        page = pdf[page_no - 1]
        try:
            image = page.render(scale=PAGE_IMAGE_DPI / 72).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        finally:
            page.close()
    except pdfium.PdfiumError:
        return None
    finally:
        pdf.close()


def _cached_or_render_page(
    store: ObjectStore, raw_key: str, cache_key: str, page_no: int
) -> bytes | None:
    """Return the cached PNG for a page, rendering and caching it on the first request."""
    if store.exists(cache_key):
        return store.get(cache_key)
    try:
        data = store.get(raw_key)
    except KeyError:
        return None
    png = _render_page_png(data, page_no)
    if png is not None:
        store.put(cache_key, png, "image/png")
    return png


@router.get("/{document_id}/versions/{version_id}/pages/{page_no}.png")
async def page_image(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    page_no: int,
    actor: CurrentUser = Depends(require_permission("documents.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
    store: ObjectStore = Depends(get_object_store),  # noqa: B008
) -> Response:
    """Page n of a PDF version as a PNG at 110 dpi. Cached in the object store by raw hash."""
    if page_no < 1:
        raise HTTPException(status_code=404, detail="Page not found")
    version = await _version_or_404(session, document_id, version_id)
    if version["mime"] != "application/pdf":
        raise HTTPException(status_code=404, detail="Page images exist only for PDF versions")
    page_count = version["page_count"]
    if page_count is not None and page_no > page_count:
        raise HTTPException(status_code=404, detail="Page not found")
    cache_key = PAGE_IMAGE_KEY.format(sha=version["raw_sha256"], page=page_no, dpi=PAGE_IMAGE_DPI)
    png = await run_in_threadpool(
        _cached_or_render_page, store, version["raw_s3_key"], cache_key, page_no
    )
    if png is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": PAGE_IMAGE_CACHE},
    )


def _safe_filename(canonical_id: str, extension: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", canonical_id).strip("._")[:120] or "document"
    return f"{base}{extension}"


def _chunks(data: bytes) -> Iterator[bytes]:
    for start in range(0, len(data), CHUNK_BYTES):
        yield data[start : start + CHUNK_BYTES]


@router.get("/{document_id}/versions/{version_id}/raw")
async def raw_file(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    actor: CurrentUser = Depends(require_permission("documents.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
    store: ObjectStore = Depends(get_object_store),  # noqa: B008
) -> StreamingResponse:
    """The original file as it was received, as an attachment."""
    version = await _version_or_404(session, document_id, version_id)
    try:
        data = await run_in_threadpool(store.get, version["raw_s3_key"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Raw file not found") from exc
    extension = {"application/pdf": ".pdf", "text/html": ".html"}.get(version["mime"], "")
    filename = _safe_filename(version["canonical_id"], extension)
    return StreamingResponse(
        _chunks(data),
        media_type=version["mime"],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": NO_STORE,
            "Content-Length": str(len(data)),
        },
    )


async def _enqueue_metadata(
    session: AsyncSession,
    document_id: uuid.UUID,
    fields: dict[str, Any],
    actor: CurrentUser,
    reason: str,
) -> None:
    payload = {
        "document_id": str(document_id),
        "fields": fields,
        "actor_user_id": str(actor.id),
        "reason": reason,
        "review_task_id": None,
    }
    await session.execute(
        INSERT_QUEUE_SQL,
        {"payload": json.dumps(payload), "idempotency_key": str(uuid.uuid4())},
    )


async def _change_status(
    session: AsyncSession,
    document: dict[str, Any],
    new_status: str,
    valid_from: date,
    actor: CurrentUser,
) -> None:
    """Close the open status row and open a new one, then set documents.status."""
    open_row = (await session.execute(OPEN_STATUS_SQL, {"id": document["id"]})).scalar_one_or_none()
    if open_row is not None and open_row > valid_from:
        raise HTTPException(
            status_code=422,
            detail="status_valid_from is before the current status started",
        )
    await session.execute(CLOSE_STATUS_SQL, {"id": document["id"], "valid_from": valid_from})
    await session.execute(
        INSERT_STATUS_SQL,
        {
            "id": document["id"],
            "status": new_status,
            "valid_from": valid_from,
            "actor": actor.id,
        },
    )
    await session.execute(UPDATE_STATUS_SQL, {"id": document["id"], "status": new_status})


@router.patch("/{document_id}", status_code=202, response_model=PatchAccepted)
async def patch_document(
    document_id: uuid.UUID,
    body: DocumentPatch,
    request: Request,
    response: Response,
    actor: CurrentUser = Depends(require_permission("documents.edit")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PatchAccepted:
    """Edit metadata fields (queued for the worker) and/or set the status (written here)."""
    response.headers["Cache-Control"] = NO_STORE
    unknown = sorted(set(body.fields) - EDITABLE_FIELDS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown field(s): {', '.join(unknown)}")
    if len(body.fields) > MAX_FIELDS_PER_EDIT:
        raise HTTPException(status_code=422, detail="Too many fields in one edit")
    if not body.fields and body.status is None:
        raise HTTPException(status_code=422, detail="Nothing to change")
    if body.status is None and body.status_valid_from is not None:
        raise HTTPException(status_code=422, detail="status_valid_from needs a status")

    document = await _document_or_404(session, document_id)
    ctx = audit_context_from_request(request)
    status_changed = False

    if body.status is not None:
        if body.status == document["status"]:
            raise HTTPException(status_code=422, detail="Document already has that status")
        valid_from = body.status_valid_from or datetime.now(UTC).date()
        await _change_status(session, document, body.status, valid_from, actor)
        await write_audit(
            session,
            action="document.status_change",
            actor=actor,
            object_type="document",
            object_id=str(document_id),
            detail={
                "from": document["status"],
                "to": body.status,
                "valid_from": valid_from.isoformat(),
                "reason": body.reason,
            },
            ctx=ctx,
        )
        status_changed = True

    if body.fields:
        await _enqueue_metadata(session, document_id, body.fields, actor, body.reason)
        await write_audit(
            session,
            action="document.edit",
            actor=actor,
            object_type="document",
            object_id=str(document_id),
            detail={"fields": sorted(body.fields), "reason": body.reason},
            ctx=ctx,
        )

    return PatchAccepted(queued=bool(body.fields), status_changed=status_changed)
