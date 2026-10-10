"""Search and provision linking router (TSD 6.1 - 6.10, 8.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, require_permission
from app.db import get_session
from app.modules.search.engine import execute_search
from app.modules.search.expansion import expand_query

router = APIRouter(tags=["search"])

NO_STORE = "private, no-store"


class SearchItemModel(BaseModel):
    """A search result entry."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    provision_version_id: uuid.UUID | None = None
    doc_type: str
    doc_title: str
    doc_canonical_id: str
    authority_rank: int
    structure_path: str | None = None
    heading_path: str | None = None
    chunk_kind: str
    snippet: str
    valid_from: date | None = None
    valid_to: date | None = None
    score: float
    passage_count: int = 1
    court_level: str | None = None
    state_code: str | None = None
    status: str | None = None


class SearchResponse(BaseModel):
    """Full-text search response with facets and query expansion (TSD 8.2)."""

    query: str
    as_on: date
    expanded_terms: list[str] = []
    total_count: int
    groups: dict[str, int]
    items: list[SearchItemModel]


class LinkedDocumentItem(BaseModel):
    """A document linked to a legal provision."""

    link_id: uuid.UUID
    link_type: str
    document_id: uuid.UUID
    title: str
    doc_type: str
    canonical_id: str
    authority_rank: int
    doc_date: date | None = None
    in_force_date: date | None = None
    source_block_id: uuid.UUID | None = None
    confidence: float = 1.0


class ProvisionLinkedResponse(BaseModel):
    """All instruments and mentions linked to a provision (TSD 6.10, FR-KM-09, FR-RES-14)."""

    provision_id: uuid.UUID
    total_count: int
    groups: dict[str, list[LinkedDocumentItem]]
    counts: dict[str, int]


PROVISION_LINKS_SQL = text(
    """
    SELECT
        l.id AS link_id,
        l.link_type,
        l.source_block_id,
        l.confidence,
        d.id AS document_id,
        d.title,
        d.doc_type,
        d.canonical_id,
        d.authority_rank,
        d.doc_date,
        d.in_force_date
    FROM links l
    JOIN documents d ON d.id = l.src_id
    WHERE l.dst_type = 'provision'
      AND l.dst_id = :provision_id
    ORDER BY d.doc_date DESC NULLS LAST
    """
)


@router.get("/v1/search", response_model=SearchResponse)
async def search_corpus(
    response: Response,
    q: str = Query(..., description="Search query string"),  # noqa: B008
    as_on: date | None = Query(None, description="Point-in-time date (default: today)"),  # noqa: B008
    types: list[str] | None = Query(None, description="Filter by doc_type list"),  # noqa: B008
    court: str | None = Query(None, description="Filter by court level"),  # noqa: B008
    state: str | None = Query(None, description="Filter by state code"),  # noqa: B008
    date_from: date | None = Query(None, description="Filter documents from date"),  # noqa: B008
    date_to: date | None = Query(None, description="Filter documents to date"),  # noqa: B008
    expand: bool = Query(True, description="Enable query expansion using synonyms"),  # noqa: B008
    limit: int = Query(20, ge=1, le=100, description="Page limit"),  # noqa: B008
    offset: int = Query(0, ge=0, description="Offset for pagination"),  # noqa: B008
    user: CurrentUser = Depends(require_permission("search.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SearchResponse:
    """Search the tax research corpus with point-in-time filtering and ranking (TSD 6.1 - 6.6)."""
    response.headers["Cache-Control"] = NO_STORE

    target_date = as_on or datetime.now(UTC).date()
    augmented_q, expanded_terms = expand_query(q, expand=expand)

    items, group_counts, total_count = await execute_search(
        session=session,
        query=augmented_q if expanded_terms else q,
        as_on=target_date,
        doc_types=types,
        court_level=court,
        state_code=state,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )

    item_models = [
        SearchItemModel(
            chunk_id=it.chunk_id,
            document_id=it.document_id,
            provision_version_id=it.provision_version_id,
            doc_type=it.doc_type,
            doc_title=it.doc_title,
            doc_canonical_id=it.doc_canonical_id,
            authority_rank=it.authority_rank,
            structure_path=it.structure_path,
            heading_path=it.heading_path,
            chunk_kind=it.chunk_kind,
            snippet=it.snippet,
            valid_from=it.valid_from,
            valid_to=it.valid_to,
            score=it.score,
            passage_count=it.passage_count,
            court_level=it.court_level,
            state_code=it.state_code,
            status=it.status,
        )
        for it in items
    ]

    return SearchResponse(
        query=q,
        as_on=target_date,
        expanded_terms=expanded_terms,
        total_count=total_count,
        groups=group_counts,
        items=item_models,
    )


@router.get("/v1/provisions/{id}/linked", response_model=ProvisionLinkedResponse)
async def get_provision_linked(
    id: uuid.UUID,
    response: Response,
    user: CurrentUser = Depends(require_permission("provisions.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ProvisionLinkedResponse:
    """Return all instruments and mentions linked to a provision (TSD 6.10, FR-KM-09, FR-RES-14)."""
    response.headers["Cache-Control"] = NO_STORE

    res = await session.execute(PROVISION_LINKS_SQL, {"provision_id": id})
    rows = res.mappings().all()

    groups: dict[str, list[LinkedDocumentItem]] = {
        "amending_instruments": [],
        "issued_under": [],
        "circulars": [],
        "judgements": [],
        "mentions": [],
        "other": [],
    }

    for r in rows:
        link_type = str(r["link_type"])
        source_block_raw = r.get("source_block_id")
        source_block_id = uuid.UUID(str(source_block_raw)) if source_block_raw else None
        item = LinkedDocumentItem(
            link_id=uuid.UUID(str(r["link_id"])),
            link_type=link_type,
            document_id=uuid.UUID(str(r["document_id"])),
            title=str(r["title"]),
            doc_type=str(r["doc_type"]),
            canonical_id=str(r["canonical_id"]),
            authority_rank=int(r["authority_rank"]),
            doc_date=r.get("doc_date"),
            in_force_date=r.get("in_force_date"),
            source_block_id=source_block_id,
            confidence=float(r.get("confidence") or 1.0),
        )

        if link_type in ("inserts", "substitutes", "omits", "amends"):
            groups["amending_instruments"].append(item)
        elif link_type == "mentions":
            groups["mentions"].append(item)
        elif link_type == "issued_under":
            groups["issued_under"].append(item)
        elif link_type == "clarifies":
            groups["circulars"].append(item)
        elif link_type == "interprets":
            groups["judgements"].append(item)
        elif r["doc_type"] in ("circular", "instruction"):
            groups["circulars"].append(item)
        elif r["doc_type"] == "judgement":
            groups["judgements"].append(item)
        else:
            groups["other"].append(item)

    counts = {k: len(v) for k, v in groups.items()}
    total = sum(counts.values())

    return ProvisionLinkedResponse(
        provision_id=id,
        total_count=total,
        groups=groups,
        counts=counts,
    )
