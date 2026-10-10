"""Amendment detection stage: from blocks and pure detector to amendments table (M4b).

Payload: {document_id, force?: bool}.

Uses the pure detector from amend_detect.py to find amendments in a notification's blocks,
resolves targets to provision rows, and stores amendments + review tasks.

With force=true, only unreviewed amendments (proposed/needs_info) are deleted and re-created.
With force=false or omitted, a second run is a no-op (idempotent).
"""

import logging
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from worker import db, review
from worker.errors import PermanentError
from worker.ingest.amend_apply import apply_op, op_from_amendment
from worker.ingest.amend_detect import BlockText, detect
from worker.queue import Job

logger = logging.getLogger(__name__)


def chapterless_pattern(path: str) -> str:
    r"""Postgres regex pattern for matching a path like 'r36.4.a'.

    Against a chapterless provision path, returns the regex pattern:
    ^(ch[0-9]+\.)?<path with dots escaped>$

    Raises ValueError if the path contains characters other than [A-Za-z0-9.].
    """
    if not re.match(r"^[A-Za-z0-9.]+$", path):
        raise ValueError(f"Path contains invalid characters: {path}")
    escaped = re.escape(path)
    return f"^(ch[0-9]+\\.)?{escaped}$"


def effective_for(
    proposal: Any, notification_effective: Any, doc_date: date | None
) -> tuple[date | None, str, dict[str, Any]]:
    """Effective date and condition from proposal + notification.

    Returns (effective_from, effective_condition, extra) where:
    - effective_from: the computed date or None
    - effective_condition: 'on_date', 'on_gazette', or 'on_notification'
    - extra: dict with 'effective_phrase' (str or None) and 'retrospective' (bool)
    """
    extra = {
        "effective_phrase": None,
        "retrospective": False,
    }

    # Unit-level proposal.effective wins over notification_effective
    if proposal.effective is not None:
        eff = proposal.effective
        extra["effective_phrase"] = eff.phrase
        extra["retrospective"] = eff.retrospective
        if eff.kind == "on_date":
            return eff.day, "on_date", extra
        elif eff.kind == "on_notification":
            return None, "on_notification", extra
        elif eff.kind == "on_gazette":
            return doc_date, "on_gazette", extra

    # Fall back to notification's effective
    if notification_effective is not None:
        eff = notification_effective
        extra["effective_phrase"] = eff.phrase
        extra["retrospective"] = eff.retrospective
        if eff.kind == "on_date":
            return eff.day, "on_date", extra
        elif eff.kind == "on_notification":
            return None, "on_notification", extra
        elif eff.kind == "on_gazette":
            return doc_date, "on_gazette", extra

    # Default: assume gazette date
    return doc_date, "on_gazette", extra


def path_to_resolve(proposal: Any) -> str | None:
    """The chapter-less path to look up: the provision a proposal changes.

    An inserted provision does not exist yet, so the provision it goes next to is looked up.
    """
    if proposal.op == "insert" and proposal.kind == "provision":
        return str(proposal.anchor_path) if proposal.anchor_path else None
    return str(proposal.target_path) if proposal.target_path else None


def review_status_for(proposal: Any, target_resolved: bool) -> str:
    """Review status based on proposal completeness and target resolution.

    Returns 'needs_info' if:
    - proposal.status == 'raw'
    - proposal.problems is non-empty
    - target_resolved is False

    Otherwise returns 'proposed'.
    """
    if proposal.status == "raw" or proposal.problems or not target_resolved:
        return "needs_info"
    return "proposed"


def locator_json(
    proposal: Any, instrument_code: str | None, extra: dict[str, Any]
) -> dict[str, Any]:
    """Serialize proposal locator to JSON (no date/UUID objects).

    Returns a dict with: kind, instrument, target_path, anchor_path, position,
    anchor_text, new_label, problems (list), unit_text, effective_phrase, retrospective.
    """
    return {
        "kind": proposal.kind,
        "instrument": instrument_code,
        "target_path": proposal.target_path,
        "anchor_path": proposal.anchor_path,
        "position": proposal.position,
        "anchor_text": proposal.anchor_text,
        "new_label": proposal.new_label,
        "problems": list(proposal.problems),
        "unit_text": proposal.unit_text,
        "effective_phrase": extra.get("effective_phrase"),
        "retrospective": extra.get("retrospective", False),
    }


def detect_amendments_for(conn: Connection, payload: dict[str, Any]) -> dict[str, int]:
    """Detect and store amendments from a notification's blocks.

    Payload: {document_id, force?: bool}

    Returns counts dict: {proposals, parsed, raw, needs_info, resolved_targets, tasks, skipped}.

    Raises PermanentError for malformed payload, missing document, no current version, or no blocks.
    """
    try:
        document_id = UUID(str(payload["document_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        msg = f"detect_amendments needs document_id: {exc}"
        raise PermanentError(msg) from exc

    force = payload.get("force", False)

    # Fetch document
    doc_row = conn.execute(
        sa.select(
            db.documents.c.current_version_id,
            db.documents.c.doc_date,
        ).where(db.documents.c.id == document_id)
    ).first()
    if doc_row is None:
        raise PermanentError(f"document not found: {document_id}")
    version_id = doc_row[0]
    doc_date = doc_row[1]
    if version_id is None:
        raise PermanentError(f"document has no current version: {document_id}")

    # Fetch blocks for this version (excluding boilerplate, ordered by seq)
    block_rows = conn.execute(
        sa.select(db.blocks.c.id, db.blocks.c.text)
        .where(
            db.blocks.c.document_version_id == version_id,
            db.blocks.c.is_boilerplate.is_(False),
        )
        .order_by(db.blocks.c.seq)
    ).all()
    if not block_rows:
        raise PermanentError(f"document has no blocks: {document_id}")

    # Convert to BlockText
    blocks = [BlockText(id=str(row[0]), text=str(row[1])) for row in block_rows]

    # Run detection
    detected = detect(blocks)
    proposals = detected.proposals

    # Idempotency: if amendments already exist for this document and not force, skip
    counts: dict[str, int] = {
        "proposals": len(proposals),
        "parsed": sum(1 for p in proposals if p.status == "parsed"),
        "raw": sum(1 for p in proposals if p.status == "raw"),
        "needs_info": 0,
        "resolved_targets": 0,
        "tasks": 0,
        "skipped": 0,
    }

    existing = conn.execute(
        sa.select(sa.func.count())
        .select_from(db.amendments)
        .where(db.amendments.c.source_document_id == document_id)
    ).scalar_one()
    if int(existing) > 0 and not force:
        counts["skipped"] = 1
        return counts

    # With force, delete only unreviewed amendments and their open tasks
    if force and int(existing) > 0:
        unreviewed_ids = (
            conn.execute(
                sa.select(db.amendments.c.id).where(
                    db.amendments.c.source_document_id == document_id,
                    db.amendments.c.review_status.in_(("proposed", "needs_info")),
                )
            )
            .scalars()
            .all()
        )

        for amendment_id in unreviewed_ids:
            conn.execute(
                db.review_tasks.delete().where(
                    db.review_tasks.c.subject_type == "amendment",
                    db.review_tasks.c.subject_id == amendment_id,
                    db.review_tasks.c.status.in_(("open", "in_review")),
                )
            )

        conn.execute(
            db.amendments.delete().where(
                db.amendments.c.source_document_id == document_id,
                db.amendments.c.review_status.in_(("proposed", "needs_info")),
            )
        )

    # With force, a proposal that a kept (already reviewed) amendment covers is not stored twice
    kept = {
        (str(row[0]) if row[0] else None, row[1], row[2], row[3])
        for row in conn.execute(
            sa.select(
                db.amendments.c.source_block_id,
                db.amendments.c.op,
                db.amendments.c.old_text,
                db.amendments.c.new_text,
            ).where(db.amendments.c.source_document_id == document_id)
        ).all()
    }

    # Process each proposal
    for proposal in proposals:
        key = (
            str(proposal.block_ids[0]) if proposal.block_ids else None,
            proposal.op,
            proposal.old_text,
            proposal.new_text,
        )
        if key in kept:
            continue

        # Resolve the target provision
        target_provision_id = None
        target_resolved = False
        problems_list = list(proposal.problems)

        if proposal.instrument:
            instrument_row = conn.execute(
                sa.select(db.instruments.c.id).where(db.instruments.c.code == proposal.instrument)
            ).first()

            if instrument_row is not None:
                instrument_id = UUID(str(instrument_row[0]))
                # Choose the path to match
                path_to_match = path_to_resolve(proposal)

                if path_to_match:
                    try:
                        pattern = chapterless_pattern(path_to_match)
                        matching_rows = (
                            conn.execute(
                                sa.select(db.provisions.c.id).where(
                                    db.provisions.c.instrument_id == instrument_id,
                                    sa.text("path::text ~ :pattern").bindparams(
                                        sa.bindparam("pattern", pattern)
                                    ),
                                )
                            )
                            .scalars()
                            .all()
                        )

                        if len(matching_rows) == 1:
                            target_provision_id = matching_rows[0]
                            target_resolved = True
                        elif len(matching_rows) == 0:
                            if "target_not_found" not in problems_list:
                                problems_list.append("target_not_found")
                        else:
                            if "target_ambiguous" not in problems_list:
                                problems_list.append("target_ambiguous")
                    except ValueError:
                        if "target_not_found" not in problems_list:
                            problems_list.append("target_not_found")

        # Compute effective date and condition
        effective_from, effective_condition, extra = effective_for(
            proposal, detected.effective, doc_date
        )

        # Build locator JSON
        locator = locator_json(proposal, proposal.instrument, extra)

        # Determine dry run diff
        dry_run_ok: bool | None = None
        dry_run_diff: str | None = None

        if target_provision_id is not None:
            check_date = effective_from or doc_date or date.today()
            prov_version_row = conn.execute(
                sa.select(db.provision_versions.c.text)
                .where(
                    db.provision_versions.c.provision_id == target_provision_id,
                    db.provision_versions.c.valid_from <= check_date,
                    sa.or_(
                        db.provision_versions.c.valid_to.is_(None),
                        db.provision_versions.c.valid_to > check_date,
                    ),
                    db.provision_versions.c.rec_to.is_(None),
                )
                .order_by(db.provision_versions.c.valid_from.desc())
            ).first()

            if prov_version_row is None:
                prov_version_row = conn.execute(
                    sa.select(db.provision_versions.c.text)
                    .where(
                        db.provision_versions.c.provision_id == target_provision_id,
                        db.provision_versions.c.rec_to.is_(None),
                    )
                    .order_by(db.provision_versions.c.valid_from.desc())
                ).first()

            current_text = str(prov_version_row[0]) if prov_version_row else None
            applied_op = op_from_amendment(
                proposal.op, proposal.old_text, proposal.new_text, locator
            )
            if applied_op is None:
                dry_run_ok = False
                dry_run_diff = "unsupported_operation"
                if "unsupported_operation" not in problems_list:
                    problems_list.append("unsupported_operation")
            else:
                res = apply_op(current_text, applied_op)
                dry_run_ok = res.ok
                dry_run_diff = res.diff if res.ok else (res.reason or "dry_run_failed")
                if not res.ok and res.reason and res.reason not in problems_list:
                    problems_list.append(res.reason)
        else:
            dry_run_ok = False
            dry_run_diff = (
                "target_not_found" if "target_not_found" in problems_list else "target_unresolved"
            )

        # Determine review status
        review_status = review_status_for(proposal, target_resolved)
        if review_status == "needs_info":
            counts["needs_info"] += 1

        locator["problems"] = problems_list

        # Determine source_block_id (first block_id from proposal.block_ids, or NULL)
        source_block_id = None
        if proposal.block_ids:
            source_block_id = UUID(proposal.block_ids[0])

        # Insert amendment row
        now = datetime.now(UTC)
        stmt = (
            db.amendments.insert()
            .values(
                source_document_id=document_id,
                source_block_id=source_block_id,
                op=proposal.op,
                target_provision_id=target_provision_id,
                target_document_id=None,
                target_locator=locator,
                old_text=proposal.old_text,
                new_text=proposal.new_text,
                effective_from=effective_from,
                effective_condition=effective_condition,
                bringing_into_force_doc_id=None,
                extraction_method="rule",
                extraction_conf=proposal.confidence,
                dry_run_ok=dry_run_ok,
                dry_run_diff=dry_run_diff,
                review_status=review_status,
                reviewer_id=None,
                reviewed_at=None,
                review_note=None,
                applied_at=None,
                updated_by=None,
                created_at=now,
                updated_at=now,
            )
            .returning(db.amendments.c.id)
        )
        amendment_id = UUID(str(conn.execute(stmt).scalar_one()))

        # Count resolved targets
        if target_resolved:
            counts["resolved_targets"] += 1

        # Open review task if none is open
        if not db.has_open_review_task(conn, "amendment", "amendment", amendment_id):
            review.open_review_task(
                conn,
                "amendment",
                "amendment",
                amendment_id,
                {
                    "document_id": str(document_id),
                    "kind": proposal.kind,
                    "status": proposal.status,
                    "problems": problems_list,
                    "dry_run_ok": dry_run_ok,
                    "dry_run_diff": dry_run_diff,
                },
            )
            counts["tasks"] += 1

    logger.info(f"Document {document_id}: amendments detected: {counts}")
    return counts


def make_amend_detect_handler(engine: Engine, store: Any) -> Callable[[Job], None]:  # noqa: ANN401
    """Build the handler for queue ``ingest.amend_detect``. The store is unused."""

    def handle(job: Job) -> None:
        with engine.begin() as conn:
            detect_amendments_for(conn, job.payload)

    return handle
