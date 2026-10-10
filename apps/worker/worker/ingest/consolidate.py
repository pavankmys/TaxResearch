"""Consolidation stage: apply approved amendments to provisions (TSD 4.10, 5.7, 5.9).

Payload: {provision_id?: str, amendment_id?: str, instrument_id?: str}

Replays approved amendments for a provision in chronological order using
worker.ingest.amend_apply.plan_timeline. Writes new provision_versions, closes
superseded intervals with rec_to, writes consolidation_runs, bumps corpus_versions,
and records links edges.
"""

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from worker import db
from worker.errors import PermanentError
from worker.ingest.amend_apply import Step, op_from_amendment, plan_timeline
from worker.queue import Job

logger = logging.getLogger(__name__)

OP_TO_LINK_TYPE: dict[str, str] = {
    "insert": "inserts",
    "substitute": "substitutes",
    "omit": "omits",
    "amend": "amends",
    "rescind": "rescinds",
    "supersede": "supersedes",
}


def op_to_link_type(op: str) -> str:
    """Map amendment op to links.link_type."""
    return OP_TO_LINK_TYPE.get(op, "amends")


def consolidate_provision(
    conn: Connection,
    provision_id: UUID,
    triggering_amendment_id: UUID | None = None,
) -> dict[str, Any]:
    """Replay approved amendments for a provision and update provision_versions."""
    now = datetime.now(UTC)

    # 1. Fetch provision and instrument
    prov_row = conn.execute(
        sa.select(
            db.provisions.c.id,
            db.provisions.c.instrument_id,
            db.provisions.c.path,
        ).where(db.provisions.c.id == provision_id)
    ).first()
    if prov_row is None:
        raise PermanentError(f"provision not found: {provision_id}")

    instrument_id = UUID(str(prov_row[1]))

    # 2. Fetch baseline version if one exists
    baseline_row = conn.execute(
        sa.select(
            db.provision_versions.c.id,
            db.provision_versions.c.text,
            db.provision_versions.c.valid_from,
            db.provision_versions.c.block_ids,
        )
        .where(
            db.provision_versions.c.provision_id == provision_id,
            db.provision_versions.c.origin == "baseline",
            db.provision_versions.c.rec_to.is_(None),
        )
        .order_by(db.provision_versions.c.valid_from.asc())
    ).first()

    baseline_text: str | None = None
    baseline_from: Any | None = None
    baseline_block_ids: list[UUID] = []

    if baseline_row is not None:
        baseline_text = str(baseline_row[1])
        baseline_from = baseline_row[2]
        baseline_block_ids = list(baseline_row[3] or [])

    # 3. Fetch all approved amendments for this provision, ordered by effective date
    amend_rows = conn.execute(
        sa.select(
            db.amendments.c.id,
            db.amendments.c.op,
            db.amendments.c.old_text,
            db.amendments.c.new_text,
            db.amendments.c.effective_from,
            db.amendments.c.effective_condition,
            db.amendments.c.target_locator,
            db.amendments.c.source_document_id,
            db.amendments.c.source_block_id,
            db.amendments.c.reviewer_id,
            db.documents.c.doc_date,
            db.documents.c.id.label("doc_id"),
        )
        .select_from(
            db.amendments.join(
                db.documents, db.documents.c.id == db.amendments.c.source_document_id
            )
        )
        .where(
            db.amendments.c.target_provision_id == provision_id,
            db.amendments.c.review_status == "approved",
            db.amendments.c.effective_from.is_not(None),
        )
        .order_by(
            db.amendments.c.effective_from.asc(),
            db.documents.c.doc_date.asc().nulls_last(),
            db.documents.c.id.asc(),
        )
    ).all()

    # Map rows to Step objects
    steps: list[Step] = []
    amendment_data: dict[str, Any] = {}
    for row in amend_rows:
        aid_str = str(row[0])
        amendment_data[aid_str] = row
        locator = row[6] or {}
        applied_op = op_from_amendment(row[1], row[2], row[3], locator)
        if applied_op is not None and row[4] is not None:
            order_key = (
                row[10].isoformat() if row[10] else "",
                str(row[11]),
            )
            steps.append(
                Step(
                    amendment_id=aid_str,
                    op=applied_op,
                    effective_from=row[4],
                    order=order_key,
                )
            )

    # 4. Plan timeline
    timeline = plan_timeline(baseline_text, baseline_from, steps)

    # 5. Fetch currently active versions
    active_rows = conn.execute(
        sa.select(
            db.provision_versions.c.id,
            db.provision_versions.c.valid_from,
            db.provision_versions.c.valid_to,
            db.provision_versions.c.text,
            db.provision_versions.c.created_by_amendment_id,
        )
        .where(
            db.provision_versions.c.provision_id == provision_id,
            db.provision_versions.c.rec_to.is_(None),
        )
        .order_by(db.provision_versions.c.valid_from.asc())
    ).all()

    # Determine if active versions already match the planned intervals
    active_tuples = [
        (
            r[1],
            r[2],
            r[3],
            str(r[4]) if r[4] else None,
        )
        for r in active_rows
    ]
    planned_tuples = [
        (
            iv.valid_from,
            iv.valid_to,
            iv.text,
            iv.amendment_id,
        )
        for iv in timeline.intervals
    ]

    versions_written = 0
    if active_tuples != planned_tuples:
        # Close currently active versions with rec_to = now
        active_ids = [r[0] for r in active_rows]
        if active_ids:
            conn.execute(
                db.provision_versions.update()
                .where(db.provision_versions.c.id.in_(active_ids))
                .values(rec_to=now, updated_at=now)
            )

        # Insert new intervals
        for iv in timeline.intervals:
            sha256 = hashlib.sha256(iv.text.encode("utf-8")).hexdigest()
            origin = "amendment" if iv.amendment_id else "baseline"
            created_by_id = UUID(iv.amendment_id) if iv.amendment_id else None

            block_ids: list[UUID] = []
            if iv.amendment_id and iv.amendment_id in amendment_data:
                am_row = amendment_data[iv.amendment_id]
                if am_row[8] is not None:
                    block_ids = [UUID(str(am_row[8]))]
            elif baseline_block_ids:
                block_ids = baseline_block_ids

            conn.execute(
                db.provision_versions.insert().values(
                    provision_id=provision_id,
                    valid_from=iv.valid_from,
                    valid_to=iv.valid_to,
                    heading=None,
                    text=iv.text,
                    text_sha256=sha256,
                    rec_from=now,
                    rec_to=None,
                    created_by_amendment_id=created_by_id,
                    origin=origin,
                    block_ids=block_ids,
                    created_at=now,
                    updated_at=now,
                )
            )
            versions_written += 1

    # 6. Mark applied amendments
    applied_aids = [
        UUID(iv.amendment_id) for iv in timeline.intervals if iv.amendment_id is not None
    ]
    if applied_aids:
        conn.execute(
            db.amendments.update()
            .where(
                db.amendments.c.id.in_(applied_aids),
                db.amendments.c.applied_at.is_(None),
            )
            .values(applied_at=now, updated_at=now)
        )

    # 7. Write links edges for applied amendments
    for aid_str in amendment_data:
        aid = UUID(aid_str)
        if aid in applied_aids:
            row = amendment_data[aid_str]
            link_type = op_to_link_type(str(row[1]))
            src_doc_id = UUID(str(row[7]))
            src_block_id = UUID(str(row[8])) if row[8] else None

            # Check if link already exists
            existing_link = conn.execute(
                sa.select(db.links.c.id).where(
                    db.links.c.src_type == "document",
                    db.links.c.src_id == src_doc_id,
                    db.links.c.dst_type == "provision",
                    db.links.c.dst_id == provision_id,
                    db.links.c.link_type == link_type,
                )
            ).first()

            if existing_link is None:
                conn.execute(
                    db.links.insert().values(
                        src_type="document",
                        src_id=src_doc_id,
                        dst_type="provision",
                        dst_id=provision_id,
                        link_type=link_type,
                        effective_from=row[4],
                        effective_to=None,
                        source_block_id=src_block_id,
                        confidence=1.0,
                        review_status="approved",
                        origin="amendment",
                        updated_by=row[9],
                        created_at=now,
                        updated_at=now,
                    )
                )

    # 8. Record consolidation run
    run_summary: dict[str, Any] = {
        "provision_id": str(provision_id),
        "intervals_count": len(timeline.intervals),
        "versions_written": versions_written,
        "failures": [f.reason for f in timeline.failures],
        "skipped": [s.reason for s in timeline.skipped],
    }
    conn.execute(
        db.consolidation_runs.insert().values(
            instrument_id=instrument_id,
            triggered_by_amendment_id=triggering_amendment_id,
            started_at=now,
            finished_at=now,
            versions_written=versions_written,
            status="done",
            diff_summary=run_summary,
            created_at=now,
            updated_at=now,
        )
    )

    # 9. Bump corpus_versions
    if versions_written > 0:
        conn.execute(
            db.corpus_versions.insert().values(reason=f"consolidation for provision {provision_id}")
        )

    logger.info(
        f"Consolidated provision {provision_id}: {versions_written} versions written, "
        f"summary: {run_summary}"
    )
    return run_summary


def consolidate_for(conn: Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """Execute consolidation job from payload."""
    provision_id_raw = payload.get("provision_id")
    amendment_id_raw = payload.get("amendment_id")

    if not provision_id_raw and not amendment_id_raw:
        raise PermanentError("consolidate payload needs provision_id or amendment_id")

    triggering_amendment_id = UUID(str(amendment_id_raw)) if amendment_id_raw else None

    if provision_id_raw:
        provision_id = UUID(str(provision_id_raw))
    else:
        # Resolve target provision from amendment
        am_row = conn.execute(
            sa.select(db.amendments.c.target_provision_id).where(
                db.amendments.c.id == triggering_amendment_id
            )
        ).first()
        if am_row is None:
            raise PermanentError(f"amendment not found: {triggering_amendment_id}")
        if am_row[0] is None:
            raise PermanentError(f"amendment has no target provision: {triggering_amendment_id}")
        provision_id = UUID(str(am_row[0]))

    return consolidate_provision(
        conn,
        provision_id=provision_id,
        triggering_amendment_id=triggering_amendment_id,
    )


def make_consolidate_handler(engine: Engine, store: Any) -> Callable[[Job], None]:  # noqa: ANN401
    """Build the handler for queue ``ingest.consolidate``."""

    def handle(job: Job) -> None:
        with engine.begin() as conn:
            consolidate_for(conn, job.payload)

    return handle
