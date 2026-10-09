"""Build provision tree from blocks and store baseline versions (M4a).

Payload: {document_id, instrument_code, as_on_date (YYYY-MM-DD ISO string)}.

Reads the blocks of the document's current version and stores the provision tree and the baseline
versions in one transaction. Running it again with the same text changes nothing, and keeps the
reviewer's verification of the instrument.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from legal_core.ids import instrument_id as canonical_instrument_id
from sqlalchemy.engine import Connection, Engine

from worker import db
from worker.errors import PermanentError
from worker.ingest.provisions import BlockIn, build_provisions, text_sha256
from worker.queue import Job

logger = logging.getLogger(__name__)


def build_provisions_for(conn: Connection, payload: dict[str, Any]) -> dict[str, int]:
    """Build and store provisions in the caller's transaction.

    Returns a counts dict: {provisions, created, unchanged, replaced, skipped_amended,
    orphaned, skipped_blocks}.
    """
    try:
        document_id = UUID(str(payload["document_id"]))
        instrument_code = str(payload["instrument_code"])
        as_on_str = str(payload["as_on_date"])
        as_on_date = date.fromisoformat(as_on_str)
    except (KeyError, ValueError, TypeError) as exc:
        msg = f"build_provisions needs document_id, instrument_code, as_on_date: {exc}"
        raise PermanentError(msg) from exc

    # Fetch instrument
    instrument_row = conn.execute(
        sa.select(
            db.instruments.c.id, db.instruments.c.kind, db.instruments.c.baseline_status
        ).where(db.instruments.c.code == instrument_code)
    ).first()
    if instrument_row is None:
        raise PermanentError(f"instrument not found: {instrument_code}")
    instrument_id = UUID(str(instrument_row[0]))
    instrument_kind = str(instrument_row[1])
    previous_status = str(instrument_row[2])

    # Fetch document and current version
    doc_row = conn.execute(
        sa.select(db.documents.c.current_version_id).where(db.documents.c.id == document_id)
    ).first()
    if doc_row is None:
        raise PermanentError(f"document not found: {document_id}")
    version_id = doc_row[0]
    if version_id is None:
        raise PermanentError(f"document has no current version: {document_id}")

    # Fetch blocks for this version
    block_rows = conn.execute(
        sa.select(
            db.blocks.c.id,
            db.blocks.c.seq,
            db.blocks.c.kind,
            db.blocks.c.text,
            db.blocks.c.structure_path,
            db.blocks.c.is_boilerplate,
        )
        .where(db.blocks.c.document_version_id == version_id)
        .order_by(db.blocks.c.seq)
    ).all()
    if not block_rows:
        raise PermanentError(f"document has no blocks: {document_id}")

    # Convert to BlockIn
    blocks = [
        BlockIn(
            id=str(row[0]),
            ordinal=int(row[1]),
            kind=str(row[2]),
            text=str(row[3]),
            structure_path=row[4],
            is_boilerplate=bool(row[5]),
        )
        for row in block_rows
    ]

    # Build provisions
    rules = instrument_kind == "rules"
    result = build_provisions(blocks, rules=rules)
    drafts = result.drafts
    if not drafts:
        raise PermanentError(f"builder returned no drafts: {document_id}")

    # Counts
    counts: dict[str, int] = {
        "provisions": 0,
        "created": 0,
        "unchanged": 0,
        "replaced": 0,
        "skipped_amended": 0,
        "orphaned": 0,
        "skipped_blocks": result.skipped_blocks,
    }

    # Upsert provisions in draft order
    path_to_id: dict[str, UUID] = {}
    for draft in drafts:
        # Resolve parent_id
        parent_id = None
        if draft.parent_path:
            parent_id = path_to_id.get(draft.parent_path)

        # Upsert provision row
        stmt = sa.text(
            "INSERT INTO provisions "
            "(instrument_id, path, parent_id, level, number_label, ordinal, "
            "first_valid_from, updated_at, created_at) VALUES "
            "(CAST(:instrument_id AS uuid), CAST(:path AS ltree), CAST(:parent_id AS uuid), "
            ":level, "
            ":number_label, :ordinal, :first_valid_from, now(), now()) "
            "ON CONFLICT (instrument_id, path) DO UPDATE "
            "SET parent_id = EXCLUDED.parent_id, "
            "level = EXCLUDED.level, "
            "first_valid_from = COALESCE(provisions.first_valid_from, EXCLUDED.first_valid_from), "
            "number_label = EXCLUDED.number_label, "
            "ordinal = EXCLUDED.ordinal, "
            "updated_at = now() "
            "RETURNING id"
        )
        prov_id = conn.execute(
            stmt,
            {
                "instrument_id": str(instrument_id),
                "path": draft.path,
                "parent_id": str(parent_id) if parent_id else None,
                "level": draft.level,
                "number_label": draft.number_label,
                "ordinal": draft.ordinal,
                "first_valid_from": as_on_date,
            },
        ).scalar_one()
        prov_id_uuid = UUID(str(prov_id))
        path_to_id[draft.path] = prov_id_uuid
        counts["provisions"] += 1

        # Handle baseline version
        text_sha = text_sha256(draft.text)
        block_ids_uuid = [UUID(bid) for bid in draft.block_ids]

        # Look for open baseline version
        open_baseline = conn.execute(
            sa.select(db.provision_versions.c.id, db.provision_versions.c.text_sha256).where(
                db.provision_versions.c.provision_id == prov_id_uuid,
                db.provision_versions.c.origin == "baseline",
                db.provision_versions.c.rec_to.is_(None),
            )
        ).first()

        if open_baseline is None:
            # Insert new baseline version
            conn.execute(
                db.provision_versions.insert().values(
                    provision_id=prov_id_uuid,
                    valid_from=as_on_date,
                    valid_to=None,
                    heading=draft.heading,
                    text=draft.text,
                    text_sha256=text_sha,
                    origin="baseline",
                    block_ids=block_ids_uuid,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            counts["created"] += 1
        elif open_baseline[1] == text_sha:
            # Text unchanged
            counts["unchanged"] += 1
        else:
            # Text changed; check if there are amended versions
            amended_rows = conn.execute(
                sa.select(sa.func.count())
                .select_from(db.provision_versions)
                .where(
                    db.provision_versions.c.provision_id == prov_id_uuid,
                    db.provision_versions.c.origin != "baseline",
                    db.provision_versions.c.rec_to.is_(None),
                )
            ).scalar_one()
            if int(amended_rows) > 0:
                # Skip due to amendments
                counts["skipped_amended"] += 1
            else:
                # Update old baseline to closed, insert new one
                conn.execute(
                    db.provision_versions.update()
                    .where(db.provision_versions.c.id == open_baseline[0])
                    .values(rec_to=datetime.now(UTC))
                )
                conn.execute(
                    db.provision_versions.insert().values(
                        provision_id=prov_id_uuid,
                        valid_from=as_on_date,
                        valid_to=None,
                        heading=draft.heading,
                        text=draft.text,
                        text_sha256=text_sha,
                        origin="baseline",
                        block_ids=block_ids_uuid,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
                counts["replaced"] += 1

    # Provisions of this instrument that the new tree does not contain are left as they are.
    orphaned = conn.execute(
        sa.text(
            "SELECT count(*) FROM provisions WHERE instrument_id = CAST(:instrument_id AS uuid) "
            "AND NOT (path::text = ANY(CAST(:paths AS text[])))"
        ),
        {"instrument_id": str(instrument_id), "paths": list(path_to_id)},
    ).scalar_one()
    counts["orphaned"] = int(orphaned)

    # A new or changed baseline needs verifying again; an unchanged one keeps its verification.
    if counts["created"] + counts["replaced"] > 0 or previous_status == "none":
        conn.execute(
            db.instruments.update()
            .where(db.instruments.c.id == instrument_id)
            .values(
                baseline_status="loaded",
                baseline_document_id=document_id,
                baseline_as_on=as_on_date,
                baseline_verified_by=None,
                baseline_verified_at=None,
                updated_at=datetime.now(UTC),
            )
        )

    # Insert corpus_versions row if anything changed
    if counts["created"] + counts["replaced"] > 0:
        conn.execute(db.corpus_versions.insert().values(reason=f"baseline {instrument_code}"))

    # Re-key provisional canonical IDs (unk: prefix)
    doc_canon = conn.execute(
        sa.select(db.documents.c.canonical_id).where(db.documents.c.id == document_id)
    ).scalar_one()
    doc_canon_str = str(doc_canon)
    if doc_canon_str.startswith("unk:"):
        # Check if another document has the real ID
        real_id = canonical_instrument_id(instrument_code)
        existing = conn.execute(
            sa.select(db.documents.c.id).where(db.documents.c.canonical_id == real_id)
        ).first()
        if existing is None:
            # Re-key to real ID
            conn.execute(
                db.documents.update()
                .where(db.documents.c.id == document_id)
                .values(canonical_id=real_id, updated_at=datetime.now(UTC))
            )

    logger.info(f"Baseline loaded for {instrument_code} from {document_id}: {counts}")
    return counts


def make_build_provisions_handler(  # noqa: ANN401
    engine: Engine, store: Any
) -> Callable[[Job], None]:
    """Build the handler for queue BUILD_PROVISIONS_QUEUE.

    The store is unused (uniform signature for all stage handlers).
    """

    def handle(job: Job) -> None:
        with engine.begin() as conn:
            build_provisions_for(conn, job.payload)

    return handle
