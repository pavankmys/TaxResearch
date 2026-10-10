"""Full-text search ranking and retrieval engine (TSD 6.4 - 6.6).

Executes PostgreSQL FTS queries with point-in-time as-on filtering, authority ranking,
jurisdiction adjustments, recency boosts, status factors, and deduplication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

import yaml
from app.ingest_config import config_dir
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Default authority weights from TSD 6.6
DEFAULT_AUTHORITY_WEIGHTS: dict[int, float] = {
    1: 1.30,  # Constitution
    2: 1.25,  # Acts
    3: 1.20,  # Supreme Court
    4: 1.15,  # Rules
    5: 1.12,  # Notifications
    6: 1.08,  # High Court
    7: 1.05,  # GSTAT
    8: 1.00,  # Circulars
    9: 0.92,  # AAR/AAAR
    10: 0.88,  # Council material
    11: 0.85,  # Firm content
}

DEFAULT_STATUS_FACTORS: dict[str, float] = {
    "rescinded": 0.5,
    "superseded": 0.5,
    "struck_down": 0.5,
    "stayed": 0.7,
    "withdrawn": 0.7,
    "in_force": 1.0,
}


def load_retrieval_config() -> dict[str, Any]:
    """Load retrieval weights from config/retrieval.yaml."""
    path = config_dir() / "retrieval.yaml"
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}


def compute_adjusted_score(
    raw_rank: float,
    authority_rank: int,
    doc_type: str,
    court_level: str | None,
    state_code: str | None,
    user_state: str | None,
    valid_from: date | None,
    status: str | None,
    as_on: date,
) -> float:
    """Compute score(c) = ts_rank_cd(c) * auth(c) * juris(c) * recency(c) * statusf(c) (TSD 6.6)."""
    # 1. Authority weight
    auth_weight = DEFAULT_AUTHORITY_WEIGHTS.get(authority_rank, 1.0)

    # 2. Jurisdiction weight
    juris_weight = 1.0
    if doc_type == "judgement" and court_level == "HC":
        if user_state and state_code and user_state.upper() == state_code.upper():
            juris_weight = 1.15
        else:
            juris_weight = 0.95

    # 3. Recency boost for judgements and circulars (last 3 years)
    recency_boost = 1.0
    if doc_type in ("judgement", "circular", "instruction", "order") and valid_from:
        days_diff = (as_on - valid_from).days
        if 0 <= days_diff <= (3 * 365):
            recency_boost = 1.05

    # 4. Status factor
    st = (status or "in_force").lower()
    status_factor = DEFAULT_STATUS_FACTORS.get(st, 1.0)

    return raw_rank * auth_weight * juris_weight * recency_boost * status_factor


@dataclass
class SearchResultItem:
    """A single deduplicated document search result."""

    chunk_id: UUID
    document_id: UUID
    provision_version_id: UUID | None
    doc_type: str
    doc_title: str
    doc_canonical_id: str
    authority_rank: int
    structure_path: str | None
    heading_path: str | None
    chunk_kind: str
    snippet: str
    valid_from: date | None
    valid_to: date | None
    score: float
    passage_count: int
    court_level: str | None
    state_code: str | None
    status: str | None


SEARCH_CHUNKS_SQL = text(
    """
    SELECT
        c.id AS chunk_id,
        c.document_id,
        c.document_version_id,
        c.provision_version_id,
        c.chunk_kind,
        c.structure_path,
        c.heading_path,
        c.text,
        c.token_count,
        c.authority_rank,
        c.doc_type,
        c.court_level,
        c.state_code,
        c.status_at_index,
        c.valid_from,
        c.valid_to,
        d.title AS doc_title,
        d.canonical_id AS doc_canonical_id,
        ts_rank_cd(c.tsv, q) AS raw_rank,
        ts_headline(
            'english', c.text, q,
            'StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=15'
        ) AS snippet
    FROM chunks c
    JOIN documents d ON d.id = c.document_id,
    websearch_to_tsquery('english', :query) AS q
    WHERE c.tsv @@ q
      AND (c.valid_from IS NULL OR c.valid_from <= :as_on)
      AND (c.valid_to IS NULL OR c.valid_to > :as_on)
      AND (:doc_types IS NULL OR c.doc_type = ANY(:doc_types))
      AND (:court_level IS NULL OR c.court_level = :court_level)
      AND (:state_code IS NULL OR c.state_code = :state_code)
      AND (:date_from IS NULL OR c.valid_from >= :date_from)
      AND (:date_to IS NULL OR c.valid_from <= :date_to)
    ORDER BY raw_rank DESC
    LIMIT 200
    """
)


async def execute_search(
    session: AsyncSession,
    query: str,
    as_on: date,
    doc_types: list[str] | None = None,
    court_level: str | None = None,
    state_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user_state: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[SearchResultItem], dict[str, int], int]:
    """Execute search query with point-in-time filtering, ranking, and deduplication.

    Returns:
        (deduplicated_results, group_counts, total_matching_documents)
    """
    bind_params = {
        "query": query,
        "as_on": as_on,
        "doc_types": doc_types if doc_types else None,
        "court_level": court_level,
        "state_code": state_code,
        "date_from": date_from,
        "date_to": date_to,
    }

    try:
        result = await session.execute(SEARCH_CHUNKS_SQL, bind_params)
        rows = result.mappings().all()
    except Exception as exc:
        logger.warning(f"FTS search query failed, using empty results: {exc}")
        return [], {"provisions": 0, "notifications": 0, "circulars": 0, "judgements": 0}, 0

    if not rows:
        return [], {"provisions": 0, "notifications": 0, "circulars": 0, "judgements": 0}, 0

    # Group by document_id for deduplication
    doc_groups: dict[UUID, list[dict[str, Any]]] = {}
    for r in rows:
        doc_id = UUID(str(r["document_id"]))
        doc_groups.setdefault(doc_id, []).append(dict(r))

    deduped_items: list[SearchResultItem] = []
    group_counts: dict[str, int] = {
        "provisions": 0,
        "notifications": 0,
        "circulars": 0,
        "judgements": 0,
    }

    for doc_id, matching_chunks in doc_groups.items():
        # Score each chunk in the document
        scored_chunks: list[tuple[float, dict[str, Any]]] = []
        for c in matching_chunks:
            raw_rank = float(c.get("raw_rank") or 0.1)
            auth_rank = int(c.get("authority_rank") or 5)
            doc_type = str(c.get("doc_type") or "document")
            c_level = c.get("court_level")
            s_code = c.get("state_code")
            v_from = c.get("valid_from")
            status = c.get("status_at_index")

            adjusted = compute_adjusted_score(
                raw_rank=raw_rank,
                authority_rank=auth_rank,
                doc_type=doc_type,
                court_level=c_level,
                state_code=s_code,
                user_state=user_state,
                valid_from=v_from,
                status=status,
                as_on=as_on,
            )
            scored_chunks.append((adjusted, c))

        # Best chunk is the primary representative
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        best_score, best_chunk = scored_chunks[0]

        d_type = str(best_chunk.get("doc_type") or "document")
        if d_type in ("act", "rules"):
            group_counts["provisions"] += 1
        elif d_type == "notification":
            group_counts["notifications"] += 1
        elif d_type in ("circular", "instruction", "order"):
            group_counts["circulars"] += 1
        elif d_type == "judgement":
            group_counts["judgements"] += 1

        pv_id_raw = best_chunk.get("provision_version_id")
        pv_id = UUID(str(pv_id_raw)) if pv_id_raw else None

        item = SearchResultItem(
            chunk_id=UUID(str(best_chunk["chunk_id"])),
            document_id=doc_id,
            provision_version_id=pv_id,
            doc_type=d_type,
            doc_title=str(best_chunk.get("doc_title") or "Document"),
            doc_canonical_id=str(best_chunk.get("doc_canonical_id") or ""),
            authority_rank=int(best_chunk.get("authority_rank") or 5),
            structure_path=best_chunk.get("structure_path"),
            heading_path=best_chunk.get("heading_path"),
            chunk_kind=str(best_chunk.get("chunk_kind") or "paragraph"),
            snippet=str(best_chunk.get("snippet") or best_chunk.get("text", "")[:200]),
            valid_from=best_chunk.get("valid_from"),
            valid_to=best_chunk.get("valid_to"),
            score=round(best_score, 4),
            passage_count=len(matching_chunks),
            court_level=best_chunk.get("court_level"),
            state_code=best_chunk.get("state_code"),
            status=best_chunk.get("status_at_index"),
        )
        deduped_items.append(item)

    # Sort deduplicated items by adjusted score descending
    deduped_items.sort(key=lambda x: x.score, reverse=True)
    total_count = len(deduped_items)

    paginated = deduped_items[offset : offset + limit]
    return paginated, group_counts, total_count
