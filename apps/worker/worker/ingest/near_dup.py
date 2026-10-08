"""Near-duplicate matching (TSD 5.4 layer 3; plan M3a).

A version is a probable duplicate of another document's version when:
- the simhash of the normalised text is within Hamming distance 3,
- the document dates are equal, and
- for judgements, the courts are equal.

A probable duplicate is merged into the other document when a number matches too (the
notification or circular canonical ID, or a case number). Otherwise the caller opens a metadata
task that names the candidate, and the canonical ID stays provisional.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from worker import db
from worker.ingest.simhash import hamming

HAMMING_LIMIT = 3
PROVISIONAL_PREFIX = "unk:"


@dataclass(frozen=True)
class Probe:
    """The version being extracted."""

    document_id: UUID
    version_id: UUID
    simhash: int | None
    doc_date: date | None
    court: str | None
    numbers: frozenset[str]


@dataclass(frozen=True)
class Candidate:
    """Another document's version, as the matcher sees it."""

    document_id: UUID
    version_id: UUID
    simhash: int | None
    doc_date: date | None
    court: str | None
    numbers: frozenset[str]


def numbers_for(canonical_id: str | None, case_numbers: Sequence[str]) -> frozenset[str]:
    """The number keys of a document: its canonical ID (when not provisional) and case numbers."""
    keys: set[str] = set()
    if canonical_id and not canonical_id.startswith(PROVISIONAL_PREFIX):
        keys.add(f"canon:{canonical_id}")
    for case in case_numbers:
        keys.add(f"case:{' '.join(case.split()).upper()}")
    return frozenset(keys)


def is_probable_duplicate(probe: Probe, candidate: Candidate) -> bool:
    """Simhash within the limit, the same date, and the same court when the probe has one."""
    if probe.simhash is None or candidate.simhash is None:
        return False
    if probe.doc_date is None or candidate.doc_date != probe.doc_date:
        return False
    if probe.court is not None and candidate.court != probe.court:
        return False
    return hamming(probe.simhash, candidate.simhash) <= HAMMING_LIMIT


def probable_duplicates(probe: Probe, candidates: Iterable[Candidate]) -> list[Candidate]:
    """Every candidate that is a probable duplicate, in the order given."""
    return [
        c
        for c in candidates
        if c.document_id != probe.document_id and is_probable_duplicate(probe, c)
    ]


def merge_target(probe: Probe, candidates: Iterable[Candidate]) -> Candidate | None:
    """The first probable duplicate that shares a number, or None."""
    for candidate in probable_duplicates(probe, candidates):
        if probe.numbers & candidate.numbers:
            return candidate
    return None


def fetch_candidates(conn: Connection, probe: Probe) -> list[Candidate]:
    """Versions of other documents with the probe's date, and their number keys."""
    if probe.doc_date is None or probe.simhash is None:
        return []
    rows = conn.execute(
        sa.select(
            db.document_versions.c.id,
            db.document_versions.c.document_id,
            db.document_versions.c.simhash,
            db.documents.c.doc_date,
            db.documents.c.court,
            db.documents.c.canonical_id,
            db.documents.c.metadata,
        )
        .select_from(
            db.document_versions.join(
                db.documents, db.documents.c.id == db.document_versions.c.document_id
            )
        )
        .where(
            db.document_versions.c.simhash.is_not(None),
            db.documents.c.doc_date == probe.doc_date,
            db.documents.c.id != probe.document_id,
            db.document_versions.c.id != probe.version_id,
        )
    ).mappings()
    candidates: list[Candidate] = []
    for row in rows:
        candidates.append(_candidate_from_row(dict(row)))
    return candidates


def _candidate_from_row(row: dict[str, Any]) -> Candidate:
    metadata = row.get("metadata") or {}
    fields = metadata.get("fields", {}) if isinstance(metadata, dict) else {}
    cases = fields.get("case_numbers") or []
    doc_date = row.get("doc_date")
    return Candidate(
        document_id=UUID(str(row["document_id"])),
        version_id=UUID(str(row["id"])),
        simhash=int(row["simhash"]) if row.get("simhash") is not None else None,
        doc_date=doc_date if isinstance(doc_date, date) else None,
        court=row.get("court"),
        numbers=numbers_for(row.get("canonical_id"), [str(c) for c in cases]),
    )


def merge_version_into(conn: Connection, version_id: UUID, source: UUID, target: UUID) -> int:
    """Move a version from document ``source`` to document ``target``.

    The version becomes the target's current version with the next version number. Source
    URLs and ingestion jobs move too. The source document is deleted when no version is left.

    Returns:
        The version number the version has in the target document.
    """
    next_no = conn.execute(
        sa.select(sa.func.coalesce(sa.func.max(db.document_versions.c.version_no), 0) + 1).where(
            db.document_versions.c.document_id == target
        )
    ).scalar_one()
    conn.execute(
        db.document_versions.update()
        .where(db.document_versions.c.id == version_id)
        .values(document_id=target, version_no=int(next_no), updated_at=datetime.now(UTC))
    )
    db.set_current_version(conn, target, version_id)
    conn.execute(
        sa.text(
            "INSERT INTO document_sources "
            "(document_id, source_id, url, first_seen_at, last_seen_at) "
            "SELECT :target, source_id, url, first_seen_at, last_seen_at FROM document_sources "
            "WHERE document_id = :source "
            "ON CONFLICT (document_id, url) DO UPDATE SET "
            "last_seen_at = GREATEST(document_sources.last_seen_at, EXCLUDED.last_seen_at)"
        ),
        {"target": target, "source": source},
    )
    conn.execute(
        sa.text("DELETE FROM document_sources WHERE document_id = :source"), {"source": source}
    )
    conn.execute(
        db.ingestion_jobs.update()
        .where(db.ingestion_jobs.c.document_id == source)
        .values(document_id=target)
    )
    remaining = conn.execute(
        sa.select(sa.func.count())
        .select_from(db.document_versions)
        .where(db.document_versions.c.document_id == source)
    ).scalar_one()
    if int(remaining) == 0:
        conn.execute(
            db.documents.update().where(db.documents.c.id == source).values(current_version_id=None)
        )
        conn.execute(db.documents.delete().where(db.documents.c.id == source))
    return int(next_no)
