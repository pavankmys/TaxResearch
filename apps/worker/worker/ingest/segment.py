"""Segment stage: structure_path per block, and the numbering gate (TSD 5.5).

The stage runs for one document version (queue ``ingest.segment``):

1. Skip the work when the version was segmented by the current segmenter and every block has
   a path. The next stage is still enqueued (its key makes this idempotent).
2. Otherwise compute the path of every block for the document's type and write
   blocks.structure_path.
3. Run the numbering gate on the numbered items (Acts and Rules sections, numbered paragraphs of
   notifications, circulars and judgements). Problems go to one parse_failure task per version;
   an open task gets the new problems appended. The pipeline continues either way.
4. Enqueue ingest.extract_meta and mark the job done.
"""

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from worker import db, review
from worker.ingest.queues import EXTRACT_META_QUEUE
from worker.ingest.stages import make_version_stage_handler, mark_done, utc_now
from worker.ingest.structure import (
    SEGMENTER_VERSION,
    SegBlock,
    numbering_problems,
    segment,
)
from worker.objectstore import ObjectStore
from worker.queue import Job

logger = logging.getLogger(__name__)

STAGE = "segment"
PARSE_FAILURE = "parse_failure"
NUMBERED_TYPES = frozenset(
    {"act", "rules", "notification", "circular", "instruction", "order", "judgement"}
)


def _fully_segmented(conn: Connection, version_id: UUID) -> bool:
    row = conn.execute(
        sa.select(
            db.document_versions.c.segmenter_version, db.document_versions.c.segmented_at
        ).where(db.document_versions.c.id == version_id)
    ).one()
    if row[0] != SEGMENTER_VERSION or row[1] is None:
        return False
    missing = conn.execute(
        sa.select(sa.func.count())
        .select_from(db.blocks)
        .where(
            db.blocks.c.document_version_id == version_id,
            db.blocks.c.structure_path.is_(None),
        )
    ).scalar_one()
    return int(missing) == 0


def _record_numbering(conn: Connection, version_id: UUID, problems: list[dict[str, str]]) -> None:
    """Open the parse_failure task for the version, or append the problems to the open one."""
    open_task = conn.execute(
        sa.select(db.review_tasks.c.id, db.review_tasks.c.resolution)
        .where(
            db.review_tasks.c.kind == PARSE_FAILURE,
            db.review_tasks.c.subject_type == "document_version",
            db.review_tasks.c.subject_id == version_id,
            db.review_tasks.c.status == "open",
        )
        .limit(1)
    ).first()
    if open_task is None:
        review.open_review_task(
            conn, PARSE_FAILURE, "document_version", version_id, {"numbering": problems}
        )
        return
    resolution: dict[str, Any] = dict(open_task[1] or {})
    existing: list[dict[str, Any]] = list(resolution.get("numbering", []))
    seen = {(item.get("path"), item.get("problem")) for item in existing}
    for problem in problems:
        if (problem["path"], problem["problem"]) not in seen:
            existing.append(dict(problem))
    resolution["numbering"] = existing
    conn.execute(
        db.review_tasks.update()
        .where(db.review_tasks.c.id == open_task[0])
        .values(resolution=resolution, updated_at=utc_now())
    )


def _segment(conn: Connection, job_id: UUID, version_id: UUID) -> None:
    """Segment one version and enqueue extraction, in the caller's transaction."""
    version = conn.execute(
        sa.select(db.document_versions.c.document_id).where(db.document_versions.c.id == version_id)
    ).first()
    if version is None:
        raise LookupError(f"document version not found: {version_id}")
    document_id = UUID(str(version[0]))
    doc_type = str(
        conn.execute(
            sa.select(db.documents.c.doc_type).where(db.documents.c.id == document_id)
        ).scalar_one()
    )

    if not _fully_segmented(conn, version_id):
        rows = conn.execute(
            sa.select(
                db.blocks.c.id, db.blocks.c.kind, db.blocks.c.text, db.blocks.c.is_boilerplate
            )
            .where(db.blocks.c.document_version_id == version_id)
            .order_by(db.blocks.c.seq)
        ).all()
        blocks = [
            SegBlock(kind=str(row[1]), text=str(row[2]), is_boilerplate=bool(row[3]))
            for row in rows
        ]
        result = segment(doc_type, blocks)
        if rows:
            conn.execute(
                db.blocks.update()
                .where(db.blocks.c.id == sa.bindparam("block_id"))
                .values(structure_path=sa.bindparam("path")),
                [
                    {"block_id": row[0], "path": path}
                    for row, path in zip(rows, result.paths, strict=True)
                ],
            )
        if doc_type in NUMBERED_TYPES:
            problems = numbering_problems(result.numbered)
            if problems:
                _record_numbering(conn, version_id, problems)
                logger.info(f"Version {version_id}: {len(problems)} numbering problems")
        conn.execute(
            db.document_versions.update()
            .where(db.document_versions.c.id == version_id)
            .values(
                segmenter_version=SEGMENTER_VERSION,
                segmented_at=utc_now(),
                updated_at=utc_now(),
            )
        )

    db.enqueue(
        conn,
        EXTRACT_META_QUEUE,
        {"ingestion_job_id": str(job_id), "document_version_id": str(version_id)},
        idempotency_key=f"{version_id}:extract_meta",
    )
    mark_done(conn, job_id)


def make_segment_handler(engine: Engine, store: ObjectStore) -> Callable[[Job], None]:
    """Build the handler for queue ``ingest.segment``. The store is unused (uniform signature)."""

    def body(job_id: UUID, version_id: UUID) -> None:
        with engine.begin() as conn:
            _segment(conn, job_id, version_id)

    return make_version_stage_handler(engine, STAGE, body)
