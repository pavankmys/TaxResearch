"""Citation resolution router: resolve legal citation strings to entities (TSD 6.3 & 8.2)."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Query, Response
from legal_core.citations import parse_citation
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, require_permission
from app.db import get_session

router = APIRouter(prefix="/v1/resolve", tags=["resolve"])

NO_STORE = "private, no-store"


class AlternativeMatch(BaseModel):
    """An alternative resolution candidate."""

    canonical_id: str
    title: str
    entity_id: uuid.UUID


class ResolveResponse(BaseModel):
    """Citation resolution result."""

    matched: bool
    kind: str | None = None
    canonical_id: str | None = None
    entity_id: uuid.UUID | None = None
    title: str | None = None
    confidence: float = 0.0
    alternatives: list[AlternativeMatch] = []


def chapterless_pattern(path: str) -> str:
    r"""Postgres regex pattern for matching a provision path like 's16.2.c'."""
    if not re.match(r"^[A-Za-z0-9.]+$", path):
        return f"^{re.escape(path)}$"
    escaped = re.escape(path)
    return f"^(ch[0-9]+\\.)?{escaped}$"


RESOLVE_PROVISION_SQL = text(
    """
    SELECT p.id, p.path::text, p.level, i.code AS instrument_code, i.short_name AS instrument_name
    FROM provisions p
    JOIN instruments i ON i.id = p.instrument_id
    WHERE i.code = :instrument_code
      AND p.path::text ~ :pattern
    ORDER BY p.ordinal
    LIMIT 5
    """
)

RESOLVE_NOTIFICATION_SQL = text(
    """
    SELECT d.id, d.title, d.canonical_id
    FROM documents d
    JOIN notifications n ON n.document_id = d.id
    WHERE n.number = :number AND n.year = :year
    LIMIT 5
    """
)

RESOLVE_CIRCULAR_SQL = text(
    """
    SELECT d.id, d.title, d.canonical_id
    FROM documents d
    JOIN circulars c ON c.document_id = d.id
    WHERE c.number ILIKE :pattern
    LIMIT 5
    """
)


@router.get("", response_model=ResolveResponse)
async def resolve_citation(
    response: Response,
    q: str = Query(..., description="Citation string to resolve"),  # noqa: B008
    user: CurrentUser = Depends(require_permission("search.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ResolveResponse:
    """Resolve a citation string to a document or provision (TSD 6.3, FR-RES-02)."""
    response.headers["Cache-Control"] = NO_STORE

    cleaned = q.strip()
    if not cleaned:
        return ResolveResponse(matched=False)

    citations = parse_citation(cleaned, default_instrument="CGST_ACT")
    if not citations:
        return ResolveResponse(matched=False)

    cite = citations[0]

    if cite.kind == "provision" and cite.canonical_id:
        parts = cite.canonical_id.split(":")
        inst_code = parts[1] if len(parts) >= 3 else (cite.instrument or "CGST_ACT")
        target_path = parts[2] if len(parts) >= 3 else parts[-1]

        pattern = chapterless_pattern(target_path)
        try:
            res = await session.execute(
                RESOLVE_PROVISION_SQL,
                {"instrument_code": inst_code, "pattern": pattern},
            )
            rows = res.all()
        except Exception:
            rows = []

        if rows:
            top = rows[0]
            alts = [
                AlternativeMatch(
                    canonical_id=f"prov:{r[3]}:{r[1]}",
                    title=f"{r[4]} > {r[1]}",
                    entity_id=r[0],
                )
                for r in rows[1:]
            ]
            return ResolveResponse(
                matched=True,
                kind="provision",
                canonical_id=f"prov:{top[3]}:{top[1]}",
                entity_id=top[0],
                title=f"{top[4]} > {top[1]}",
                confidence=cite.confidence,
                alternatives=alts,
            )

    return ResolveResponse(
        matched=True,
        kind=cite.kind,
        canonical_id=cite.canonical_id,
        entity_id=None,
        title=cite.raw,
        confidence=cite.confidence,
        alternatives=[],
    )
