"""Extract-meta stage: rule-based metadata, near-duplicate handling, and the apply job (TSD 5.6).

The stage runs for one document version (queue ``ingest.extract_meta``):

1. Skip when the version was extracted by the current extractor.
2. Run the rule extractors for the document's type (metadata.py holds the contract).
3. Near-duplicates (TSD 5.4). A canonical ID that already belongs to another document, or a
   probable duplicate that shares a number, merges this version into that document. A probable
   duplicate without a shared number keeps the provisional canonical ID and opens a metadata task
   that names the candidate.
4. Enqueue ingest.apply_metadata with the proposal. Open a metadata task when the document
   confidence is below 0.85, an issue was found, or a near-duplicate was held.
5. Mark the job done. Publishing happens after apply_metadata.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from worker import db, review
from worker.ingest.extractors import extract_metadata, file_name_of
from worker.ingest.metadata import (
    CONFIDENCE_THRESHOLD,
    EXTRACTOR_VERSION,
    required_confidence,
)
from worker.ingest.near_dup import (
    Probe,
    fetch_candidates,
    merge_target,
    merge_version_into,
    numbers_for,
    probable_duplicates,
)
from worker.ingest.queues import APPLY_METADATA_QUEUE
from worker.ingest.stages import make_version_stage_handler, mark_done
from worker.ingest.structure import SegBlock
from worker.objectstore import ObjectStore
from worker.queue import Job

logger = logging.getLogger(__name__)

STAGE = "extract_meta"


def _today() -> date:
    return datetime.now(UTC).date()


def _iso_date(value: Any) -> date | None:  # noqa: ANN401 - JSON value from the proposal
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _probe(
    fields: dict[str, Any],
    *,
    document_id: UUID,
    version_id: UUID,
    simhash: int | None,
    canonical_id: str | None,
) -> Probe:
    decided = _iso_date(fields.get("doc_date")) or _iso_date(fields.get("decision_date"))
    cases = fields.get("case_numbers") or []
    court = fields.get("court_code")
    return Probe(
        document_id=document_id,
        version_id=version_id,
        simhash=simhash,
        doc_date=decided,
        court=str(court) if court is not None else None,
        numbers=numbers_for(canonical_id, [str(c) for c in cases]),
    )


def _extract(conn: Connection, job_id: UUID, version_id: UUID, today: date) -> None:
    version = conn.execute(
        sa.select(
            db.document_versions.c.document_id,
            db.document_versions.c.extractor_version,
            db.document_versions.c.extracted_at,
            db.document_versions.c.simhash,
        ).where(db.document_versions.c.id == version_id)
    ).first()
    if version is None:
        raise LookupError(f"document version not found: {version_id}")
    if version[1] == EXTRACTOR_VERSION and version[2] is not None:
        mark_done(conn, job_id)
        logger.info(f"Ingestion job {job_id}: version {version_id} already extracted, skipped")
        return

    document_id = UUID(str(version[0]))
    simhash = int(version[3]) if version[3] is not None else None
    doc = conn.execute(
        sa.select(db.documents.c.doc_type, db.documents.c.title, db.documents.c.canonical_id).where(
            db.documents.c.id == document_id
        )
    ).one()
    doc_type, title, _ = str(doc[0]), str(doc[1]), str(doc[2])
    url = conn.execute(
        sa.select(db.ingestion_jobs.c.url).where(db.ingestion_jobs.c.id == job_id)
    ).scalar()
    block_rows = conn.execute(
        sa.select(db.blocks.c.kind, db.blocks.c.text, db.blocks.c.is_boilerplate)
        .where(db.blocks.c.document_version_id == version_id)
        .order_by(db.blocks.c.seq)
    ).all()
    blocks = [
        SegBlock(kind=str(row[0]), text=str(row[1]), is_boilerplate=bool(row[2]))
        for row in block_rows
    ]

    proposal = extract_metadata(
        doc_type,
        blocks,
        title=title,
        file_name=file_name_of(str(url) if url is not None else None),
        today=today,
    )
    fields = dict(proposal.fields)
    canonical = fields.get("canonical_id")
    canonical_text = str(canonical) if canonical is not None else None

    target = document_id
    near: list[UUID] = []
    if canonical_text is not None:
        hit = db.find_document_by_canonical(conn, canonical_text)
        if hit is not None and hit != document_id:
            merge_version_into(conn, version_id, document_id, hit)
            target = hit
            logger.info(f"Version {version_id} merged into {hit} (canonical {canonical_text})")
    if target == document_id:
        probe = _probe(
            fields,
            document_id=document_id,
            version_id=version_id,
            simhash=simhash,
            canonical_id=canonical_text,
        )
        candidates = fetch_candidates(conn, probe)
        matched = merge_target(probe, candidates)
        if matched is not None:
            merge_version_into(conn, version_id, document_id, matched.document_id)
            target = matched.document_id
            logger.info(f"Version {version_id} merged into {target} (same number)")
        else:
            near = [c.document_id for c in probable_duplicates(probe, candidates)]

    apply_fields = dict(fields)
    if near:
        apply_fields.pop("canonical_id", None)

    confidence = required_confidence(doc_type, fields, proposal.confidence)
    if near or proposal.issues or confidence < CONFIDENCE_THRESHOLD:
        resolution: dict[str, Any] = {
            "proposal": proposal.to_json(),
            "meta_confidence": round(confidence, 4),
            "issues": list(proposal.issues),
        }
        if near:
            resolution["near_duplicate_of"] = str(near[0])
        review.open_review_task(conn, "metadata", "document", target, resolution)

    db.enqueue(
        conn,
        APPLY_METADATA_QUEUE,
        {
            "document_id": str(target),
            "fields": apply_fields,
            "actor_user_id": None,
            "reason": "extracted",
            "review_task_id": None,
            "metadata": proposal.to_json(),
        },
        idempotency_key=f"{version_id}:apply",
    )
    conn.execute(
        db.document_versions.update()
        .where(db.document_versions.c.id == version_id)
        .values(
            extractor_version=EXTRACTOR_VERSION,
            extracted_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    mark_done(conn, job_id)
    logger.info(f"Ingestion job {job_id}: version {version_id} extracted for document {target}")


def make_extract_meta_handler(engine: Engine, store: ObjectStore) -> Callable[[Job], None]:
    """Build the handler for queue ``ingest.extract_meta``. The store is unused."""

    def body(job_id: UUID, version_id: UUID) -> None:
        with engine.begin() as conn:
            _extract(conn, job_id, version_id, _today())

    return make_version_stage_handler(engine, STAGE, body)
