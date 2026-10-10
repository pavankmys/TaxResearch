"""Provisions router: point-in-time lookup, version timeline, and diff.

Allows querying the text and metadata of a legal provision as it was in force on any
given date, inspecting its chronological version timeline, and comparing two versions or dates.
"""

import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from legal_core import word_diff
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, require_permission
from app.db import get_session

router = APIRouter(prefix="/v1/provisions", tags=["provisions"])

NO_STORE = "private, no-store"

PROVISION_SQL = text(
    """
    SELECT p.id, p.instrument_id, p.path::text, p.parent_id, p.level, p.number_label, p.ordinal,
           i.code AS instrument_code, i.short_name AS instrument_short_name
    FROM provisions p
    JOIN instruments i ON i.id = p.instrument_id
    WHERE p.id = :id
    """
)

VERSION_AT_DATE_SQL = text(
    """
    SELECT pv.id, pv.heading, pv.text, pv.valid_from, pv.valid_to,
           pv.origin, pv.created_by_amendment_id
    FROM provision_versions pv
    WHERE pv.provision_id = :id
      AND pv.valid_from <= :as_on
      AND (pv.valid_to IS NULL OR pv.valid_to > :as_on)
      AND pv.rec_to IS NULL
    ORDER BY pv.valid_from DESC
    LIMIT 1
    """
)

VERSION_LATEST_ACTIVE_SQL = text(
    """
    SELECT pv.id, pv.heading, pv.text, pv.valid_from, pv.valid_to,
           pv.origin, pv.created_by_amendment_id
    FROM provision_versions pv
    WHERE pv.provision_id = :id
      AND pv.rec_to IS NULL
    ORDER BY pv.valid_from DESC
    LIMIT 1
    """
)

VERSION_BY_ID_SQL = text(
    """
    SELECT pv.id, pv.heading, pv.text, pv.valid_from, pv.valid_to,
           pv.origin, pv.created_by_amendment_id
    FROM provision_versions pv
    WHERE pv.id = :id AND pv.provision_id = :provision_id
    """
)

TIMELINE_SQL = text(
    """
    SELECT pv.id AS version_id, pv.heading, pv.valid_from, pv.valid_to, pv.origin,
           LENGTH(pv.text) AS text_chars,
           SUBSTRING(pv.text FROM 1 FOR 200) AS text_preview,
           pv.created_by_amendment_id,
           a.source_document_id,
           d.title AS amending_doc_title,
           d.number AS amending_doc_number,
           d.doc_date AS amending_doc_date
    FROM provision_versions pv
    LEFT JOIN amendments a ON a.id = pv.created_by_amendment_id
    LEFT JOIN documents d ON d.id = a.source_document_id
    WHERE pv.provision_id = :id
      AND pv.rec_to IS NULL
    ORDER BY pv.valid_from ASC, pv.id ASC
    """
)

_ADD_PATTERN = re.compile(r"\{\+.*?\+\}")
_DEL_PATTERN = re.compile(r"\[-.*?-\]")


class ProvisionVersionDetail(BaseModel):
    """The text and temporal metadata for a single provision version."""

    id: uuid.UUID
    heading: str | None
    text: str
    valid_from: date
    valid_to: date | None
    origin: str
    created_by_amendment_id: uuid.UUID | None = None


class PointInTimeProvisionDetail(BaseModel):
    """A legal provision and its version active at a point in time."""

    id: uuid.UUID
    instrument_id: uuid.UUID
    instrument_code: str
    instrument_short_name: str
    path: str
    level: str
    number_label: str | None
    ordinal: int
    version: ProvisionVersionDetail | None = None


class AmendingDocumentSummary(BaseModel):
    """Summary of the document that introduced an amendment."""

    id: uuid.UUID
    title: str | None
    number: str | None
    doc_date: date | None


class ProvisionTimelineItem(BaseModel):
    """An item in the chronological timeline of a provision."""

    version_id: uuid.UUID
    heading: str | None
    valid_from: date
    valid_to: date | None
    origin: str
    text_chars: int
    text_preview: str
    created_by_amendment_id: uuid.UUID | None = None
    amending_document: AmendingDocumentSummary | None = None


class ProvisionTimelineResponse(BaseModel):
    """The timeline of versions for a provision."""

    provision_id: uuid.UUID
    path: str
    items: list[ProvisionTimelineItem]


class VersionRef(BaseModel):
    """Summary of a version for comparison."""

    id: uuid.UUID
    valid_from: date
    valid_to: date | None
    origin: str
    heading: str | None


class ProvisionDiffResponse(BaseModel):
    """Word diff comparison between two versions of a provision."""

    provision_id: uuid.UUID
    from_version: VersionRef
    to_version: VersionRef
    identical: bool
    diff: str
    additions_count: int
    deletions_count: int


@router.get("/{provision_id}", response_model=PointInTimeProvisionDetail)
async def get_provision(
    provision_id: uuid.UUID,
    response: Response,
    as_on: date | None = Query(default=None, description="Point-in-time date (YYYY-MM-DD)"),  # noqa: B008
    actor: CurrentUser = Depends(require_permission("provisions.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PointInTimeProvisionDetail:
    """Return provision details and the version active at `as_on` (or currently active)."""
    response.headers["Cache-Control"] = NO_STORE

    prov_res = await session.execute(PROVISION_SQL, {"id": provision_id})
    prov_row = prov_res.mappings().first()
    if prov_row is None:
        raise HTTPException(status_code=404, detail="Provision not found")

    if as_on is not None:
        ver_res = await session.execute(VERSION_AT_DATE_SQL, {"id": provision_id, "as_on": as_on})
    else:
        ver_res = await session.execute(VERSION_LATEST_ACTIVE_SQL, {"id": provision_id})
    ver_row = ver_res.mappings().first()

    version = (
        ProvisionVersionDetail(
            id=ver_row["id"],
            heading=ver_row["heading"],
            text=ver_row["text"],
            valid_from=ver_row["valid_from"],
            valid_to=ver_row["valid_to"],
            origin=ver_row["origin"],
            created_by_amendment_id=ver_row["created_by_amendment_id"],
        )
        if ver_row is not None
        else None
    )

    return PointInTimeProvisionDetail(
        id=prov_row["id"],
        instrument_id=prov_row["instrument_id"],
        instrument_code=prov_row["instrument_code"],
        instrument_short_name=prov_row["instrument_short_name"],
        path=prov_row["path"],
        level=prov_row["level"],
        number_label=prov_row["number_label"],
        ordinal=prov_row["ordinal"],
        version=version,
    )


@router.get("/{provision_id}/timeline", response_model=ProvisionTimelineResponse)
async def get_provision_timeline(
    provision_id: uuid.UUID,
    response: Response,
    actor: CurrentUser = Depends(require_permission("provisions.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ProvisionTimelineResponse:
    """Return the chronological history of versions for this provision."""
    response.headers["Cache-Control"] = NO_STORE

    prov_res = await session.execute(PROVISION_SQL, {"id": provision_id})
    prov_row = prov_res.mappings().first()
    if prov_row is None:
        raise HTTPException(status_code=404, detail="Provision not found")

    timeline_res = await session.execute(TIMELINE_SQL, {"id": provision_id})
    rows = timeline_res.mappings().all()

    items: list[ProvisionTimelineItem] = []
    for row in rows:
        amending_doc = None
        if row["source_document_id"] is not None:
            amending_doc = AmendingDocumentSummary(
                id=row["source_document_id"],
                title=row["amending_doc_title"],
                number=row["amending_doc_number"],
                doc_date=row["amending_doc_date"],
            )

        items.append(
            ProvisionTimelineItem(
                version_id=row["version_id"],
                heading=row["heading"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                origin=row["origin"],
                text_chars=row["text_chars"] or 0,
                text_preview=row["text_preview"] or "",
                created_by_amendment_id=row["created_by_amendment_id"],
                amending_document=amending_doc,
            )
        )

    return ProvisionTimelineResponse(
        provision_id=provision_id,
        path=prov_row["path"],
        items=items,
    )


@router.get("/{provision_id}/diff", response_model=ProvisionDiffResponse)
async def get_provision_diff(
    provision_id: uuid.UUID,
    response: Response,
    from_date: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),  # noqa: B008
    to_date: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),  # noqa: B008
    from_version_id: uuid.UUID | None = Query(default=None, description="Start version UUID"),  # noqa: B008
    to_version_id: uuid.UUID | None = Query(default=None, description="End version UUID"),  # noqa: B008
    actor: CurrentUser = Depends(require_permission("provisions.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ProvisionDiffResponse:
    """Compare two versions of a provision (either by version IDs or by valid dates)."""
    response.headers["Cache-Control"] = NO_STORE

    prov_res = await session.execute(PROVISION_SQL, {"id": provision_id})
    prov_row = prov_res.mappings().first()
    if prov_row is None:
        raise HTTPException(status_code=404, detail="Provision not found")

    v1_row = None
    v2_row = None

    if from_version_id is not None and to_version_id is not None:
        res1 = await session.execute(
            VERSION_BY_ID_SQL, {"id": from_version_id, "provision_id": provision_id}
        )
        v1_row = res1.mappings().first()
        res2 = await session.execute(
            VERSION_BY_ID_SQL, {"id": to_version_id, "provision_id": provision_id}
        )
        v2_row = res2.mappings().first()
        if v1_row is None:
            raise HTTPException(status_code=404, detail="Source version not found")
        if v2_row is None:
            raise HTTPException(status_code=404, detail="Target version not found")
    elif from_date is not None and to_date is not None:
        res1 = await session.execute(VERSION_AT_DATE_SQL, {"id": provision_id, "as_on": from_date})
        v1_row = res1.mappings().first()
        res2 = await session.execute(VERSION_AT_DATE_SQL, {"id": provision_id, "as_on": to_date})
        v2_row = res2.mappings().first()
        if v1_row is None:
            raise HTTPException(
                status_code=404, detail=f"No provision version in force on {from_date}"
            )
        if v2_row is None:
            raise HTTPException(
                status_code=404, detail=f"No provision version in force on {to_date}"
            )
    else:
        raise HTTPException(
            status_code=422,
            detail="Must provide either (from_date, to_date) or (from_version_id, to_version_id)",
        )

    from_text = str(v1_row["text"] or "")
    to_text = str(v2_row["text"] or "")

    diff_output = word_diff(from_text, to_text)
    identical = from_text == to_text
    additions = len(_ADD_PATTERN.findall(diff_output))
    deletions = len(_DEL_PATTERN.findall(diff_output))

    return ProvisionDiffResponse(
        provision_id=provision_id,
        from_version=VersionRef(
            id=v1_row["id"],
            valid_from=v1_row["valid_from"],
            valid_to=v1_row["valid_to"],
            origin=v1_row["origin"],
            heading=v1_row["heading"],
        ),
        to_version=VersionRef(
            id=v2_row["id"],
            valid_from=v2_row["valid_from"],
            valid_to=v2_row["valid_to"],
            origin=v2_row["origin"],
            heading=v2_row["heading"],
        ),
        identical=identical,
        diff=diff_output,
        additions_count=additions,
        deletions_count=deletions,
    )
