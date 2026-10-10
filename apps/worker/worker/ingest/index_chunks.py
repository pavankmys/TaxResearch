"""Worker indexing stage: generate and store search chunks (TSD 5.10 & 6.2).

Extracts chunks from document blocks or legal provision versions, generates full-text
search tsvectors with heading/title weighting, and writes them to the chunks table.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from worker import db
from worker.errors import PermanentError
from worker.ingest.chunking import (
    chunk_document_blocks,
    chunk_provision_versions,
)
from worker.queue import Job

logger = logging.getLogger(__name__)


def index_document(
    conn: Connection,
    document_id: UUID,
    document_version_id: UUID | None = None,
) -> int:
    """Index all blocks of a document version into chunks.

    Returns the number of chunks created.
    """
    doc_row = conn.execute(
        sa.select(
            db.documents.c.id,
            db.documents.c.title,
            db.documents.c.doc_type,
            db.documents.c.authority_rank,
            db.documents.c.status,
            db.documents.c.in_force_date,
            db.documents.c.doc_date,
            db.documents.c.tenant_id,
        ).where(db.documents.c.id == document_id)
    ).first()

    if doc_row is None:
        raise PermanentError(f"document not found: {document_id}")

    doc_type = str(doc_row[2])
    title = str(doc_row[1])
    authority_rank = int(doc_row[3])
    status = str(doc_row[4])
    in_force_date = doc_row[5] or doc_row[6]
    tenant_id = doc_row[7]

    # Optional extra metadata
    subject = None
    court_level = None
    state_code = None

    if doc_type in ("circular", "instruction", "order"):
        circ_row = conn.execute(
            sa.select(db.circulars.c.subject).where(db.circulars.c.document_id == document_id)
        ).first()
        if circ_row and circ_row[0]:
            subject = str(circ_row[0])

    if doc_type == "judgement":
        jdg_row = conn.execute(
            sa.select(db.judgements.c.court_level).where(db.judgements.c.document_id == document_id)
        ).first()
        if jdg_row and jdg_row[0]:
            court_level = str(jdg_row[0])

    # Find document version
    if document_version_id is None:
        ver_row = conn.execute(
            sa.select(db.document_versions.c.id)
            .where(db.document_versions.c.document_id == document_id)
            .order_by(db.document_versions.c.created_at.desc())
            .limit(1)
        ).first()
        if ver_row is None:
            logger.warning(f"No document version found for document {document_id}")
            return 0
        document_version_id = UUID(str(ver_row[0]))

    # Fetch blocks
    block_rows = (
        conn.execute(
            sa.select(
                db.blocks.c.id,
                db.blocks.c.seq,
                db.blocks.c.kind,
                db.blocks.c.page,
                db.blocks.c.para_label,
                db.blocks.c.structure_path,
                db.blocks.c.text,
                db.blocks.c.is_boilerplate,
            )
            .where(db.blocks.c.document_version_id == document_version_id)
            .order_by(db.blocks.c.seq)
        )
        .mappings()
        .all()
    )

    blocks = [dict(b) for b in block_rows]
    if not blocks:
        logger.info(f"No blocks to index for document {document_id}")
        return 0

    doc_meta = {
        "title": title,
        "doc_type": doc_type,
        "authority_rank": authority_rank,
        "valid_from": in_force_date,
        "valid_to": None,
        "court_level": court_level,
        "state_code": state_code,
        "status": status,
        "subject": subject,
        "tenant_id": tenant_id,
    }

    chunks = chunk_document_blocks(document_id, document_version_id, doc_meta, blocks)
    if not chunks:
        return 0

    # Mark existing chunks as superseded
    conn.execute(
        db.chunks.update().where(db.chunks.c.document_id == document_id).values(is_current=False)
    )

    # Insert new chunks
    chunk_dicts = [c.to_dict() for c in chunks]
    now = datetime.now(UTC)
    for cd in chunk_dicts:
        cd["created_at"] = now
    db.insert_chunks(conn, chunk_dicts)

    logger.info(f"Indexed {len(chunks)} chunks for document {document_id}")
    return len(chunks)


def index_provisions(
    conn: Connection,
    instrument_id: UUID | None = None,
    provision_id: UUID | None = None,
) -> int:
    """Index legal provisions and their active versions into chunks.

    Returns the number of chunks created.
    """
    query = (
        sa.select(
            db.provisions.c.id.label("provision_id"),
            db.provisions.c.instrument_id,
            db.provisions.c.path,
            db.provisions.c.level,
            db.instruments.c.short_name.label("instrument_name"),
            db.instruments.c.kind.label("instrument_kind"),
            db.instruments.c.baseline_document_id,
            db.provision_versions.c.id.label("provision_version_id"),
            db.provision_versions.c.heading,
            db.provision_versions.c.text,
            db.provision_versions.c.valid_from,
            db.provision_versions.c.valid_to,
            db.provision_versions.c.rec_to,
            db.provision_versions.c.block_ids,
        )
        .select_from(db.provisions)
        .join(db.instruments, db.instruments.c.id == db.provisions.c.instrument_id)
        .join(
            db.provision_versions,
            db.provision_versions.c.provision_id == db.provisions.c.id,
        )
    )

    if provision_id is not None:
        query = query.where(db.provisions.c.id == provision_id)
    elif instrument_id is not None:
        query = query.where(db.provisions.c.instrument_id == instrument_id)

    rows = conn.execute(query).mappings().all()
    if not rows:
        return 0

    # Group by instrument
    grouped: dict[str, list[dict[str, Any]]] = {}
    instrument_meta: dict[str, tuple[str, str, UUID | None]] = {}

    for r in rows:
        inst_key = str(r["instrument_id"])
        grouped.setdefault(inst_key, []).append(dict(r))
        if inst_key not in instrument_meta:
            instrument_meta[inst_key] = (
                str(r["instrument_name"]),
                str(r["instrument_kind"]),
                r["baseline_document_id"],
            )

    total_chunks = 0
    now = datetime.now(UTC)

    for inst_key, items in grouped.items():
        inst_name, inst_kind, baseline_doc_id = instrument_meta[inst_key]
        doc_id = baseline_doc_id or items[0]["provision_id"]
        doc_version_id = items[0]["provision_version_id"]

        chunks = chunk_provision_versions(
            instrument_name=inst_name,
            instrument_kind=inst_kind,
            document_id=doc_id,
            document_version_id=doc_version_id,
            provisions_data=items,
        )
        if not chunks:
            continue

        pv_ids = [it["provision_version_id"] for it in items]
        conn.execute(
            db.chunks.update()
            .where(db.chunks.c.provision_version_id.in_(pv_ids))
            .values(is_current=False)
        )

        chunk_dicts = [c.to_dict() for c in chunks]
        for cd in chunk_dicts:
            cd["created_at"] = now
        db.insert_chunks(conn, chunk_dicts)
        total_chunks += len(chunks)

    logger.info(f"Indexed {total_chunks} provision chunks")
    return total_chunks


def make_index_handler(engine: Engine) -> Callable[[Job], None]:
    """Build the handler for queue ``ingest.index``."""

    def handle(job: Job) -> None:
        payload = job.payload
        with engine.begin() as conn:
            if "document_id" in payload:
                doc_id = UUID(str(payload["document_id"]))
                ver_id = (
                    UUID(str(payload["document_version_id"]))
                    if "document_version_id" in payload
                    else None
                )
                index_document(conn, doc_id, ver_id)
            elif "provision_id" in payload:
                prov_id = UUID(str(payload["provision_id"]))
                index_provisions(conn, provision_id=prov_id)
            elif "instrument_id" in payload:
                inst_id = UUID(str(payload["instrument_id"]))
                index_provisions(conn, instrument_id=inst_id)
            else:
                msg = "index payload requires document_id, provision_id, or instrument_id"
                raise PermanentError(msg)

    return handle
