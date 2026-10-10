"""Mention indexer: extract provision citations from document blocks (TSD 4.5 & 6.10).

Scans document blocks for legal provision citations, resolves them against the provisions table,
and stores them as 'mentions' links in the links table.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from legal_core.citations import parse_citation
from sqlalchemy.engine import Connection

from worker import db

logger = logging.getLogger(__name__)


def chapterless_pattern(path: str) -> str:
    r"""Postgres regex pattern for matching a provision path like 's16.2.c'."""
    if not re.match(r"^[A-Za-z0-9.]+$", path):
        raise ValueError(f"Path contains invalid characters: {path}")
    escaped = re.escape(path)
    return f"^(ch[0-9]+\\.)?{escaped}$"


def extract_mentions_from_blocks(
    blocks: list[dict[str, Any]],
    default_instrument: str = "CGST_ACT",
) -> list[dict[str, Any]]:
    """Pure extraction: find provision citations in blocks.

    Returns a list of dicts:
        source_block_id: UUID
        instrument_code: str
        target_path: str
        confidence: float
        raw: str
    """
    results: list[dict[str, Any]] = []

    for block in blocks:
        text = (block.get("text") or "").strip()
        if not text:
            continue
        block_id = block["id"]

        citations = parse_citation(text, default_instrument=default_instrument)
        for cite in citations:
            if cite.kind != "provision" or not cite.canonical_id:
                continue

            # canonical_id format: 'prov:INSTRUMENT:path'
            parts = cite.canonical_id.split(":")
            if len(parts) >= 3:
                inst_code = parts[1]
                path = parts[2]
            else:
                inst_code = cite.instrument or default_instrument
                path = parts[-1]

            results.append(
                {
                    "source_block_id": block_id,
                    "instrument_code": inst_code,
                    "target_path": path,
                    "confidence": cite.confidence,
                    "raw": cite.raw,
                }
            )

    return results


def index_document_mentions(
    conn: Connection,
    document_id: UUID,
    default_instrument: str = "CGST_ACT",
) -> int:
    """Extract and persist provision mention links for a document.

    Returns the count of mention links stored.
    """
    # Fetch blocks for the latest document version
    ver_row = conn.execute(
        sa.select(db.document_versions.c.id)
        .where(db.document_versions.c.document_id == document_id)
        .order_by(db.document_versions.c.created_at.desc())
        .limit(1)
    ).first()

    if ver_row is None:
        return 0
    version_id = ver_row[0]

    block_rows = (
        conn.execute(
            sa.select(db.blocks.c.id, db.blocks.c.text)
            .where(
                db.blocks.c.document_version_id == version_id,
                db.blocks.c.is_boilerplate.is_(False),
            )
            .order_by(db.blocks.c.seq)
        )
        .mappings()
        .all()
    )

    blocks = [dict(b) for b in block_rows]
    if not blocks:
        return 0

    extracted = extract_mentions_from_blocks(blocks, default_instrument=default_instrument)
    if not extracted:
        return 0

    # Fetch instruments map: code -> id
    inst_rows = conn.execute(sa.select(db.instruments.c.code, db.instruments.c.id)).all()
    inst_map = {row[0]: row[1] for row in inst_rows}

    # Resolve mentions to provisions.id
    resolved_links: list[dict[str, Any]] = []
    seen: set[tuple[UUID, UUID]] = set()

    for item in extracted:
        inst_code = item["instrument_code"]
        inst_id = inst_map.get(inst_code)
        if not inst_id:
            continue

        target_path = item["target_path"]
        try:
            pattern = chapterless_pattern(target_path)
            prov_row = conn.execute(
                sa.select(db.provisions.c.id).where(
                    db.provisions.c.instrument_id == inst_id,
                    sa.text("path::text ~ :pattern").bindparams(sa.bindparam("pattern", pattern)),
                )
            ).first()

            if prov_row:
                prov_id = prov_row[0]
                dedup_key = (prov_id, item["source_block_id"])
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                resolved_links.append(
                    {
                        "src_type": "document",
                        "src_id": document_id,
                        "dst_type": "provision",
                        "dst_id": prov_id,
                        "link_type": "mentions",
                        "source_block_id": item["source_block_id"],
                        "confidence": item["confidence"],
                        "review_status": "approved",
                        "origin": "mention_extractor",
                        "effective_from": None,
                        "effective_to": None,
                        "updated_by": None,
                        "created_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                    }
                )
        except Exception:
            continue

    if not resolved_links:
        return 0

    # Delete existing mention links for this document
    conn.execute(
        db.links.delete().where(
            db.links.c.src_type == "document",
            db.links.c.src_id == document_id,
            db.links.c.link_type == "mentions",
        )
    )

    # Insert new mention links
    conn.execute(db.links.insert(), resolved_links)
    logger.info(f"Inserted {len(resolved_links)} mention links for document {document_id}")
    return len(resolved_links)
