"""Baseline verification: view and verify the baseline version of legal instruments.

The baseline is a snapshot of the law at a specific date, ingested from a document
and parsed into provisions. Users can review the baseline tree structure and verify
that the parsing is correct; verification is audited.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.db import get_session

router = APIRouter(prefix="/v1/baseline", tags=["baseline"])

NO_STORE = "private, no-store"

# SQL for instruments list
INSTRUMENTS_SQL = text(
    """
    SELECT i.code, i.kind, i.short_name, i.baseline_status, i.baseline_as_on,
           i.baseline_document_id, i.baseline_verified_at, u.display_name,
           COUNT(DISTINCT p.id)
               FILTER (WHERE pv.origin = 'baseline' AND pv.rec_to IS NULL) AS provision_count,
           COUNT(DISTINCT p.id)
               FILTER (WHERE p.level IN ('section', 'rule')
                       AND pv.origin = 'baseline' AND pv.rec_to IS NULL) AS section_count
    FROM instruments i
    LEFT JOIN users u ON u.id = i.baseline_verified_by
    LEFT JOIN provisions p ON p.instrument_id = i.id
    LEFT JOIN provision_versions pv ON pv.provision_id = p.id
    GROUP BY i.code, i.kind, i.short_name, i.baseline_status, i.baseline_as_on,
             i.baseline_document_id, i.baseline_verified_at, u.display_name
    ORDER BY i.code
    """
)

# SQL for provisions of an instrument
PROVISIONS_SQL = text(
    """
    SELECT p.id, p.path::text, p.parent_id, p.level, p.number_label, p.ordinal,
           pv.heading, pv.text, LENGTH(pv.text) AS text_chars, pv.id AS version_id
    FROM provisions p
    LEFT JOIN provision_versions pv ON pv.provision_id = p.id
                                    AND pv.origin = 'baseline'
                                    AND pv.rec_to IS NULL
    WHERE p.instrument_id = :instrument_id
    ORDER BY p.ordinal
    """
)

# SQL to get instrument by code
INSTRUMENT_BY_CODE_SQL = text(
    """
    SELECT i.id, i.code, i.kind, i.short_name, i.baseline_status, i.baseline_as_on,
           i.baseline_document_id, i.baseline_verified_at, u.display_name,
           COUNT(DISTINCT p.id)
               FILTER (WHERE pv.origin = 'baseline' AND pv.rec_to IS NULL) AS provision_count,
           COUNT(DISTINCT p.id)
               FILTER (WHERE p.level IN ('section', 'rule')
                       AND pv.origin = 'baseline' AND pv.rec_to IS NULL) AS section_count
    FROM instruments i
    LEFT JOIN users u ON u.id = i.baseline_verified_by
    LEFT JOIN provisions p ON p.instrument_id = i.id
    LEFT JOIN provision_versions pv ON pv.provision_id = p.id
    WHERE i.code = :code
    GROUP BY i.id, i.code, i.kind, i.short_name, i.baseline_status, i.baseline_as_on,
             i.baseline_document_id, i.baseline_verified_at, u.display_name
    """
)

# SQL for one provision detail
PROVISION_DETAIL_SQL = text(
    """
    SELECT p.id, p.path::text, p.level, p.number_label, pv.heading, pv.text, pv.valid_from,
           pv.text_sha256, pv.block_ids, i.baseline_document_id
    FROM provisions p
    JOIN provision_versions pv ON pv.provision_id = p.id
                               AND pv.origin = 'baseline'
                               AND pv.rec_to IS NULL
    JOIN instruments i ON i.id = p.instrument_id
    WHERE p.id = :provision_id AND i.code = :code
    """
)

# SQL to verify baseline status update
VERIFY_BASELINE_SQL = text(
    """
    UPDATE instruments
    SET baseline_status = 'verified',
        baseline_verified_by = :actor_id,
        baseline_verified_at = :now,
        updated_at = :now
    WHERE code = :code AND baseline_status = 'loaded'
    RETURNING id, code, kind, short_name, baseline_status, baseline_as_on,
              baseline_document_id, baseline_verified_at
    """
)

# SQL to get user display name after update
GET_VERIFIER_SQL = text(
    """
    SELECT u.display_name
    FROM users u
    WHERE u.id = :user_id
    """
)

# SQL to count provisions and sections for audit
COUNT_PROVISIONS_SQL = text(
    """
    SELECT COUNT(DISTINCT p.id)
               FILTER (WHERE pv.origin = 'baseline' AND pv.rec_to IS NULL) AS provision_count,
           COUNT(DISTINCT p.id)
               FILTER (WHERE p.level IN ('section', 'rule')
                       AND pv.origin = 'baseline' AND pv.rec_to IS NULL) AS section_count
    FROM provisions p
    LEFT JOIN provision_versions pv ON pv.provision_id = p.id
    WHERE p.instrument_id = :instrument_id
    """
)


class InstrumentOut(BaseModel):
    """One instrument's baseline status and verification info."""

    code: str
    kind: str
    short_name: str
    baseline_status: str
    baseline_as_on: date | None
    baseline_document_id: uuid.UUID | None
    baseline_verified_at: datetime | None
    baseline_verified_by_name: str | None
    provision_count: int
    section_count: int


class InstrumentList(BaseModel):
    """List of all instruments."""

    items: list[InstrumentOut]


class ProvisionRow(BaseModel):
    """One provision in the tree: minimal info for tree display."""

    id: uuid.UUID
    path: str
    parent_id: uuid.UUID | None
    level: str
    number_label: str | None
    heading: str | None
    depth: int
    text_chars: int
    has_baseline: bool


class ProvisionsList(BaseModel):
    """Instrument with its provisions tree and numbering gaps."""

    instrument: InstrumentOut
    items: list[ProvisionRow]
    numbering_gaps: list[str]


class ProvisionDetail(BaseModel):
    """One provision with full text."""

    id: uuid.UUID
    path: str
    level: str
    number_label: str | None
    heading: str | None
    text: str
    valid_from: date
    block_count: int
    source_document_id: uuid.UUID | None
    source_page: int | None
    text_sha256: str


def _extract_depth(path: str) -> int:
    """Calculate depth from a ltree path: number of dots + 1, minus 1 = number of dots."""
    if not path:
        return 0
    return len(path.split(".")) - 1


def _extract_number(label: str) -> int | None:
    """Extract leading digits from a label; return None if no digits."""
    if not label:
        return None
    i = 0
    while i < len(label) and label[i].isdigit():
        i += 1
    if i == 0:
        return None
    return int(label[:i])


def _numbering_gaps(labels: list[str]) -> list[str]:
    """Return gap numbers between min and max as strings, empty list if < 2 numbers."""
    numbers: list[int] = [
        n for n in (_extract_number(label) for label in labels if label) if n is not None
    ]
    if len(numbers) < 2:
        return []
    mn, mx = min(numbers), max(numbers)
    present = set(numbers)
    return [str(i) for i in range(mn, mx + 1) if i not in present]


def _build_tree(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[uuid.UUID | None, list[dict[str, Any]]]]:
    """Build a tree from flat rows. Returns (roots, children_by_parent_id)."""
    children_by_parent: dict[uuid.UUID | None, list[dict[str, Any]]] = {}
    for row in rows:
        parent_id = row["parent_id"]
        if parent_id not in children_by_parent:
            children_by_parent[parent_id] = []
        children_by_parent[parent_id].append(row)

    # Sort each level by ordinal
    for parent_list in children_by_parent.values():
        parent_list.sort(key=lambda r: r["ordinal"])

    roots = children_by_parent.get(None, [])
    return roots, children_by_parent


def _depth_first_walk(
    node: dict[str, Any], children_by_parent: dict[uuid.UUID | None, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Depth-first walk of the tree starting from node."""
    result = [node]
    node_id = node["id"]
    if node_id in children_by_parent:
        for child in children_by_parent[node_id]:
            result.extend(_depth_first_walk(child, children_by_parent))
    return result


@router.get("/instruments", response_model=InstrumentList)
async def list_instruments(
    response: Response,
    actor: CurrentUser = Depends(require_permission("baseline.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> InstrumentList:
    """List all instruments with their baseline status."""
    response.headers["Cache-Control"] = NO_STORE
    rows = (await session.execute(INSTRUMENTS_SQL)).mappings().all()
    items = [
        InstrumentOut(
            code=row["code"],
            kind=row["kind"],
            short_name=row["short_name"],
            baseline_status=row["baseline_status"],
            baseline_as_on=row["baseline_as_on"],
            baseline_document_id=row["baseline_document_id"],
            baseline_verified_at=row["baseline_verified_at"],
            baseline_verified_by_name=row["display_name"],
            provision_count=row["provision_count"] or 0,
            section_count=row["section_count"] or 0,
        )
        for row in rows
    ]
    return InstrumentList(items=items)


@router.get("/instruments/{code}/provisions", response_model=ProvisionsList)
async def list_provisions(
    code: str,
    response: Response,
    actor: CurrentUser = Depends(require_permission("baseline.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ProvisionsList:
    """List provisions of an instrument in tree order with numbering gaps."""
    response.headers["Cache-Control"] = NO_STORE

    # Get instrument
    instrument = (await session.execute(INSTRUMENT_BY_CODE_SQL, {"code": code})).mappings().first()
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")

    # Get all provisions for this instrument
    prov_rows = (
        (await session.execute(PROVISIONS_SQL, {"instrument_id": instrument["id"]}))
        .mappings()
        .all()
    )

    # Convert to dicts with computed fields
    rows = [
        {
            "id": row["id"],
            "path": row["path"],
            "parent_id": row["parent_id"],
            "level": row["level"],
            "number_label": row["number_label"],
            "ordinal": row["ordinal"],
            "heading": row["heading"],
            "text": row["text"],
            "text_chars": row["text_chars"] or 0,
            "has_baseline": row["version_id"] is not None,
        }
        for row in prov_rows
    ]

    # Build tree and depth-first walk
    roots, children_by_parent = _build_tree(rows)
    ordered_rows = []
    for root in roots:
        ordered_rows.extend(_depth_first_walk(root, children_by_parent))

    # Convert to ProvisionRow with depth
    items = [
        ProvisionRow(
            id=row["id"],
            path=row["path"],
            parent_id=row["parent_id"],
            level=row["level"],
            number_label=row["number_label"],
            heading=row["heading"],
            depth=_extract_depth(row["path"]),
            text_chars=row["text_chars"],
            has_baseline=row["has_baseline"],
        )
        for row in ordered_rows
    ]

    # Compute numbering gaps for sections/rules
    section_labels = [
        row["number_label"]
        for row in rows
        if row["level"] in ("section", "rule") and row["number_label"]
    ]
    gaps = _numbering_gaps(section_labels)

    instrument_out = InstrumentOut(
        code=instrument["code"],
        kind=instrument["kind"],
        short_name=instrument["short_name"],
        baseline_status=instrument["baseline_status"],
        baseline_as_on=instrument["baseline_as_on"],
        baseline_document_id=instrument["baseline_document_id"],
        baseline_verified_at=instrument["baseline_verified_at"],
        baseline_verified_by_name=instrument["display_name"],
        provision_count=instrument["provision_count"] or 0,
        section_count=instrument["section_count"] or 0,
    )

    return ProvisionsList(instrument=instrument_out, items=items, numbering_gaps=gaps)


@router.get("/instruments/{code}/provisions/{provision_id}", response_model=ProvisionDetail)
async def get_provision(
    code: str,
    provision_id: uuid.UUID,
    response: Response,
    actor: CurrentUser = Depends(require_permission("baseline.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ProvisionDetail:
    """Get one provision's text and metadata."""
    response.headers["Cache-Control"] = NO_STORE

    row = (
        (await session.execute(PROVISION_DETAIL_SQL, {"provision_id": provision_id, "code": code}))
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Provision not found")

    # Count blocks from the block_ids array
    block_ids = row["block_ids"] or []
    block_count = len([b for b in block_ids if b is not None])

    # Find minimum page from the blocks table
    source_page = None
    if block_ids:
        # Get minimum page for blocks in this version
        page_sql = text(
            """
            SELECT MIN(b.page) AS min_page FROM blocks b
            WHERE b.id = ANY(:block_ids) AND b.page IS NOT NULL
            """
        )
        page_result = (await session.execute(page_sql, {"block_ids": block_ids})).scalar()
        source_page = page_result

    return ProvisionDetail(
        id=row["id"],
        path=row["path"],
        level=row["level"],
        number_label=row["number_label"],
        heading=row["heading"],
        text=row["text"],
        valid_from=row["valid_from"],
        block_count=block_count,
        source_document_id=row["baseline_document_id"],
        source_page=source_page,
        text_sha256=row["text_sha256"],
    )


@router.post("/instruments/{code}/verify", response_model=InstrumentOut)
async def verify_baseline(
    code: str,
    request: Request,
    response: Response,
    actor: CurrentUser = Depends(require_permission("baseline.verify")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> InstrumentOut:
    """Mark the baseline of an instrument as verified."""
    response.headers["Cache-Control"] = NO_STORE

    now = datetime.now(UTC)

    # Attempt to update: only succeeds if baseline_status == 'loaded'
    verify_result = (
        (
            await session.execute(
                VERIFY_BASELINE_SQL,
                {"code": code, "actor_id": actor.id, "now": now},
            )
        )
        .mappings()
        .first()
    )

    if verify_result is None:
        # Check if instrument exists and what its current status is
        check_sql = text("SELECT baseline_status FROM instruments WHERE code = :code")
        status = (await session.execute(check_sql, {"code": code})).scalar()
        if status is None:
            raise HTTPException(status_code=404, detail="Instrument not found")
        if status == "verified":
            raise HTTPException(status_code=409, detail="Already verified")
        else:
            raise HTTPException(status_code=409, detail="No baseline loaded")

    # Get the full instrument row with counts
    instrument_row = (
        (await session.execute(INSTRUMENT_BY_CODE_SQL, {"code": code})).mappings().first()
    )
    if instrument_row is None:  # deleted between the update and this read
        raise HTTPException(status_code=404, detail="Instrument not found")
    instrument = dict(instrument_row)

    # Get user display name
    verifier_row = (
        (await session.execute(GET_VERIFIER_SQL, {"user_id": actor.id})).mappings().first()
    )
    verifier = dict(verifier_row) if verifier_row is not None else None

    # Get provision/section counts for audit
    counts_row = (
        (await session.execute(COUNT_PROVISIONS_SQL, {"instrument_id": verify_result["id"]}))
        .mappings()
        .first()
    )
    if counts_row is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    counts = dict(counts_row)

    # Write audit
    await write_audit(
        session,
        action="baseline.verify",
        actor=actor,
        object_type="instrument",
        object_id=code,
        detail={
            "as_on": instrument["baseline_as_on"].isoformat()
            if instrument["baseline_as_on"]
            else None,
            "provisions": counts["provision_count"] or 0,
            "sections": counts["section_count"] or 0,
        },
        ctx=audit_context_from_request(request),
    )

    return InstrumentOut(
        code=instrument["code"],
        kind=instrument["kind"],
        short_name=instrument["short_name"],
        baseline_status=instrument["baseline_status"],
        baseline_as_on=instrument["baseline_as_on"],
        baseline_document_id=instrument["baseline_document_id"],
        baseline_verified_at=instrument["baseline_verified_at"],
        baseline_verified_by_name=verifier["display_name"] if verifier else None,
        provision_count=counts["provision_count"] or 0,
        section_count=counts["section_count"] or 0,
    )
