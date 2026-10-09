"""SQLAlchemy Core table definitions and repository functions for the ingestion pipeline.

Only the columns the worker uses are declared. Names and types match the migrations in
apps/api/alembic/versions (0002 job_queue, 0004 documents, 0006 operations). Functions take
a Connection so that callers decide the transaction boundary.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

metadata = sa.MetaData()

_uuid = postgresql.UUID(as_uuid=True)
_ts = sa.DateTime(timezone=True)

sources = sa.Table(
    "sources",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("code", sa.Text, nullable=False, unique=True),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

documents = sa.Table(
    "documents",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("tenant_id", _uuid, nullable=True),
    sa.Column("canonical_id", sa.Text, nullable=False),
    sa.Column("doc_type", sa.Text, nullable=False),
    sa.Column("authority_rank", sa.SmallInteger, nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("review_state", sa.Text, nullable=False),
    sa.Column("current_version_id", _uuid, nullable=True),
    sa.Column("issuing_authority", sa.Text, nullable=True),
    sa.Column("number", sa.Text, nullable=True),
    sa.Column("series", sa.Text, nullable=True),
    sa.Column("doc_date", sa.Date, nullable=True),
    sa.Column("in_force_date", sa.Date, nullable=True),
    sa.Column("court", sa.Text, nullable=True),
    sa.Column("bench", sa.Text, nullable=True),
    sa.Column("metadata", postgresql.JSONB, nullable=False),
    sa.Column("meta_confidence", sa.REAL, nullable=True),
    sa.Column("updated_at", _ts, nullable=False),
)

document_sources = sa.Table(
    "document_sources",
    metadata,
    sa.Column("document_id", _uuid, primary_key=True),
    sa.Column("source_id", _uuid, nullable=False),
    sa.Column("url", sa.Text, primary_key=True),
    sa.Column("first_seen_at", _ts, nullable=False),
    sa.Column("last_seen_at", _ts, nullable=False),
)

document_versions = sa.Table(
    "document_versions",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("document_id", _uuid, nullable=False),
    sa.Column("version_no", sa.Integer, nullable=False),
    sa.Column("raw_s3_key", sa.Text, nullable=False),
    sa.Column("raw_sha256", sa.Text, nullable=False),
    sa.Column("text_sha256", sa.Text, nullable=True),
    sa.Column("simhash", sa.BigInteger, nullable=True),
    sa.Column("mime", sa.Text, nullable=False),
    sa.Column("page_count", sa.Integer, nullable=True),
    sa.Column("parser_version", sa.Text, nullable=True),
    sa.Column("ocr_used", sa.Boolean, nullable=False),
    sa.Column("ocr_conf", sa.REAL, nullable=True),
    sa.Column("parsed_at", _ts, nullable=True),
    sa.Column("segmenter_version", sa.Text, nullable=True),
    sa.Column("segmented_at", _ts, nullable=True),
    sa.Column("extractor_version", sa.Text, nullable=True),
    sa.Column("extracted_at", _ts, nullable=True),
    sa.Column("created_at", _ts, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

page_extractions = sa.Table(
    "page_extractions",
    metadata,
    sa.Column("document_version_id", _uuid, primary_key=True),
    sa.Column("page_no", sa.Integer, primary_key=True),
    sa.Column("method", sa.Text, nullable=False),
    sa.Column("chars_engine_a", sa.Integer, nullable=True),
    sa.Column("chars_engine_b", sa.Integer, nullable=True),
    sa.Column("garble_score", sa.REAL, nullable=True),
    sa.Column("ocr_conf", sa.REAL, nullable=True),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("flagged", sa.Boolean, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

page_texts = sa.Table(
    "page_texts",
    metadata,
    sa.Column("document_version_id", _uuid, primary_key=True),
    sa.Column("page_no", sa.Integer, primary_key=True),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

blocks = sa.Table(
    "blocks",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("document_version_id", _uuid, nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("page", sa.Integer, nullable=True),
    sa.Column("bbox", postgresql.JSONB, nullable=True),
    sa.Column("para_label", sa.Text, nullable=True),
    sa.Column("structure_path", sa.Text, nullable=True),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("text_sha256", sa.Text, nullable=False),
    sa.Column("is_boilerplate", sa.Boolean, nullable=False),
    sa.Column("lang", sa.Text, nullable=True),
)

ingestion_jobs = sa.Table(
    "ingestion_jobs",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("source_id", _uuid, nullable=True),
    sa.Column("document_id", _uuid, nullable=True),
    sa.Column("url", sa.Text, nullable=True),
    sa.Column("stage", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("attempt", sa.Integer, nullable=False),
    sa.Column("error_code", sa.Text, nullable=True),
    sa.Column("error_detail", sa.Text, nullable=True),
    sa.Column("started_at", _ts, nullable=True),
    sa.Column("finished_at", _ts, nullable=True),
    sa.Column("discovered_at", _ts, nullable=False),
    sa.Column("published_at", _ts, nullable=True),
    sa.Column("updated_at", _ts, nullable=False),
)

review_tasks = sa.Table(
    "review_tasks",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("subject_type", sa.Text, nullable=False),
    sa.Column("subject_id", _uuid, nullable=True),
    sa.Column("priority", sa.SmallInteger, nullable=False),
    sa.Column("assignee_id", _uuid, nullable=True),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("opened_at", _ts, nullable=False),
    sa.Column("resolution", postgresql.JSONB, nullable=True),
    sa.Column("created_at", _ts, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

users = sa.Table(
    "users",
    metadata,
    sa.Column("id", _uuid, primary_key=True),
    sa.Column("status", sa.Text, nullable=False),
)

roles = sa.Table(
    "roles",
    metadata,
    sa.Column("id", _uuid, primary_key=True),
    sa.Column("code", sa.Text, nullable=False),
)

user_roles = sa.Table(
    "user_roles",
    metadata,
    sa.Column("user_id", _uuid, primary_key=True),
    sa.Column("role_id", _uuid, primary_key=True),
)

document_status_history = sa.Table(
    "document_status_history",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("document_id", _uuid, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("valid_from", sa.Date, nullable=False),
    sa.Column("valid_to", sa.Date, nullable=True),
    sa.Column("set_by", _uuid, nullable=True),
)

corpus_versions = sa.Table(
    "corpus_versions",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("reason", sa.Text, nullable=False),
)

notifications = sa.Table(
    "notifications",
    metadata,
    sa.Column("document_id", _uuid, primary_key=True),
    sa.Column("series", sa.Text, nullable=False),
    sa.Column("number", sa.Text, nullable=False),
    sa.Column("year", sa.SmallInteger, nullable=False),
    sa.Column("issue_date", sa.Date, nullable=True),
    sa.Column("effective_date", sa.Date, nullable=True),
    sa.Column("gazette_ref", sa.Text, nullable=True),
    sa.Column("updated_at", _ts, nullable=False),
)

circulars = sa.Table(
    "circulars",
    metadata,
    sa.Column("document_id", _uuid, primary_key=True),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("number", sa.Text, nullable=False),
    sa.Column("issue_date", sa.Date, nullable=True),
    sa.Column("subject", sa.Text, nullable=True),
    sa.Column("din", sa.Text, nullable=True),
    sa.Column("updated_at", _ts, nullable=False),
)

judgements = sa.Table(
    "judgements",
    metadata,
    sa.Column("document_id", _uuid, primary_key=True),
    sa.Column("court_level", sa.Text, nullable=False),
    sa.Column("court_name", sa.Text, nullable=False),
    sa.Column("bench", sa.Text, nullable=True),
    sa.Column("judges", sa.ARRAY(sa.Text), nullable=False),
    sa.Column("decision_date", sa.Date, nullable=True),
    sa.Column("parties", postgresql.JSONB, nullable=False),
    sa.Column("reporter_citations", sa.ARRAY(sa.Text), nullable=False),
    sa.Column("case_numbers", sa.ARRAY(sa.Text), nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

instruments = sa.Table(
    "instruments",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("code", sa.Text, nullable=False, unique=True),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("short_name", sa.Text, nullable=False),
    sa.Column("state_code", sa.Text, nullable=True),
    sa.Column("baseline_status", sa.Text, nullable=False),
    sa.Column("baseline_document_id", _uuid, nullable=True),
    sa.Column("baseline_as_on", sa.Date, nullable=True),
    sa.Column("baseline_verified_by", _uuid, nullable=True),
    sa.Column("baseline_verified_at", _ts, nullable=True),
    sa.Column("created_at", _ts, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

provisions = sa.Table(
    "provisions",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("instrument_id", _uuid, nullable=False),
    sa.Column("path", sa.Text, nullable=False),
    sa.Column("parent_id", _uuid, nullable=True),
    sa.Column("level", sa.Text, nullable=False),
    sa.Column("number_label", sa.Text, nullable=True),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("first_valid_from", sa.Date, nullable=True),
    sa.Column("updated_by", _uuid, nullable=True),
    sa.Column("created_at", _ts, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

provision_versions = sa.Table(
    "provision_versions",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("provision_id", _uuid, nullable=False),
    sa.Column("valid_from", sa.Date, nullable=False),
    sa.Column("valid_to", sa.Date, nullable=True),
    sa.Column("heading", sa.Text, nullable=True),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("text_sha256", sa.Text, nullable=False),
    sa.Column("rec_from", _ts, nullable=False),
    sa.Column("rec_to", _ts, nullable=True),
    sa.Column("origin", sa.Text, nullable=False),
    sa.Column("block_ids", postgresql.ARRAY(_uuid), nullable=False),
    sa.Column("created_at", _ts, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

amendments = sa.Table(
    "amendments",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("uuid_generate_v7()")),
    sa.Column("source_document_id", _uuid, nullable=False),
    sa.Column("source_block_id", _uuid, nullable=True),
    sa.Column("op", sa.Text, nullable=False),
    sa.Column("target_provision_id", _uuid, nullable=True),
    sa.Column("target_document_id", _uuid, nullable=True),
    sa.Column("target_locator", postgresql.JSONB, nullable=False),
    sa.Column("old_text", sa.Text, nullable=True),
    sa.Column("new_text", sa.Text, nullable=True),
    sa.Column("effective_from", sa.Date, nullable=True),
    sa.Column("effective_condition", sa.Text, nullable=False),
    sa.Column("bringing_into_force_doc_id", _uuid, nullable=True),
    sa.Column("extraction_method", sa.Text, nullable=False),
    sa.Column("extraction_conf", sa.REAL, nullable=True),
    sa.Column("dry_run_ok", sa.Boolean, nullable=True),
    sa.Column("dry_run_diff", sa.Text, nullable=True),
    sa.Column("review_status", sa.Text, nullable=False),
    sa.Column("reviewer_id", _uuid, nullable=True),
    sa.Column("reviewed_at", _ts, nullable=True),
    sa.Column("review_note", sa.Text, nullable=True),
    sa.Column("applied_at", _ts, nullable=True),
    sa.Column("updated_by", _uuid, nullable=True),
    sa.Column("created_at", _ts, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)

job_queue = sa.Table(
    "job_queue",
    metadata,
    sa.Column("id", _uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("queue", sa.Text, nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False),
    sa.Column("max_attempts", sa.Integer, nullable=False),
    sa.Column("run_after", _ts, nullable=False),
    sa.Column("idempotency_key", sa.Text, nullable=True),
    sa.Column("created_at", _ts, nullable=False),
    sa.Column("updated_at", _ts, nullable=False),
)


def _now() -> datetime:
    return datetime.now(UTC)


def ensure_source(conn: Connection, code: str, kind: str) -> UUID:
    """Return the id of the sources row for ``code``, creating it if needed."""
    stmt = (
        postgresql.insert(sources)
        .values(code=code, kind=kind, enabled=True, updated_at=_now())
        .on_conflict_do_update(index_elements=[sources.c.code], set_={"updated_at": _now()})
        .returning(sources.c.id)
    )
    return UUID(str(conn.execute(stmt).scalar_one()))


def create_ingestion_job(conn: Connection, *, source_id: UUID, url: str) -> UUID:
    """Insert an ingestion_jobs row in stage acquire, status queued."""
    now = _now()
    stmt = (
        postgresql.insert(ingestion_jobs)
        .values(
            source_id=source_id,
            url=url,
            stage="acquire",
            status="queued",
            attempt=0,
            discovered_at=now,
            updated_at=now,
        )
        .returning(ingestion_jobs.c.id)
    )
    return UUID(str(conn.execute(stmt).scalar_one()))


def enqueue(
    conn: Connection,
    queue: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> UUID:
    """Insert a job_queue row in the caller's transaction, unless the key already exists.

    This is a raw insert: PostgresJobQueue.enqueue opens its own transaction, which would
    split the job row from the work that created it.
    """
    existing = conn.execute(
        sa.select(job_queue.c.id)
        .where(job_queue.c.queue == queue, job_queue.c.idempotency_key == idempotency_key)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return UUID(str(existing))
    now = _now()
    stmt = (
        job_queue.insert()
        .values(
            queue=queue,
            payload=payload,
            status="queued",
            attempts=0,
            max_attempts=3,
            run_after=now,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        .returning(job_queue.c.id)
    )
    return UUID(str(conn.execute(stmt).scalar_one()))


def update_job(conn: Connection, job_id: UUID, **fields: Any) -> int:  # noqa: ANN401
    """Update columns of one ingestion_jobs row and bump updated_at. Returns rows changed."""
    result = conn.execute(
        ingestion_jobs.update()
        .where(ingestion_jobs.c.id == job_id)
        .values(**fields, updated_at=_now())
    )
    return int(result.rowcount)


def find_version_by_sha(conn: Connection, sha256: str) -> tuple[UUID, UUID] | None:
    """Return (version_id, document_id) for the first version with this byte hash."""
    row = conn.execute(
        sa.select(document_versions.c.id, document_versions.c.document_id)
        .where(document_versions.c.raw_sha256 == sha256)
        .order_by(document_versions.c.created_at, document_versions.c.id)
        .limit(1)
    ).first()
    if row is None:
        return None
    return UUID(str(row[0])), UUID(str(row[1]))


def find_document_by_canonical(
    conn: Connection, canonical_id: str, tenant_id: UUID | None = None
) -> UUID | None:
    """Return the document with this canonical ID in the given tenant scope (None = shared)."""
    tenant_clause = (
        documents.c.tenant_id.is_(None) if tenant_id is None else documents.c.tenant_id == tenant_id
    )
    row = conn.execute(
        sa.select(documents.c.id).where(documents.c.canonical_id == canonical_id, tenant_clause)
    ).first()
    return UUID(str(row[0])) if row is not None else None


def insert_document(
    conn: Connection,
    *,
    canonical_id: str,
    doc_type: str,
    authority_rank: int,
    title: str,
    tenant_id: UUID | None = None,
    status: str = "in_force",
    review_state: str = "pending_review",
) -> UUID:
    """Insert a documents row and return its id."""
    now = _now()
    stmt = (
        documents.insert()
        .values(
            tenant_id=tenant_id,
            canonical_id=canonical_id,
            doc_type=doc_type,
            authority_rank=authority_rank,
            title=title,
            status=status,
            review_state=review_state,
            updated_at=now,
        )
        .returning(documents.c.id)
    )
    return UUID(str(conn.execute(stmt).scalar_one()))


def insert_version(
    conn: Connection,
    *,
    document_id: UUID,
    raw_s3_key: str,
    raw_sha256: str,
    mime: str,
) -> tuple[UUID, int]:
    """Insert a document_versions row with version_no = max + 1 and return (id, version_no)."""
    next_no = (
        sa.select(sa.func.coalesce(sa.func.max(document_versions.c.version_no), 0) + 1)
        .where(document_versions.c.document_id == document_id)
        .scalar_subquery()
    )
    stmt = (
        document_versions.insert()
        .values(
            document_id=document_id,
            version_no=next_no,
            raw_s3_key=raw_s3_key,
            raw_sha256=raw_sha256,
            mime=mime,
            ocr_used=False,
            updated_at=_now(),
        )
        .returning(document_versions.c.id, document_versions.c.version_no)
    )
    row = conn.execute(stmt).one()
    return UUID(str(row[0])), int(row[1])


def add_document_source(conn: Connection, document_id: UUID, source_id: UUID, url: str) -> None:
    """Attach a URL to a document, or refresh last_seen_at if it is already attached."""
    now = _now()
    stmt = (
        postgresql.insert(document_sources)
        .values(
            document_id=document_id,
            source_id=source_id,
            url=url,
            first_seen_at=now,
            last_seen_at=now,
        )
        .on_conflict_do_update(
            index_elements=[document_sources.c.document_id, document_sources.c.url],
            set_={"last_seen_at": now},
        )
    )
    conn.execute(stmt)


def set_current_version(conn: Connection, document_id: UUID, version_id: UUID) -> None:
    """Point documents.current_version_id at a version."""
    conn.execute(
        documents.update()
        .where(documents.c.id == document_id)
        .values(current_version_id=version_id, updated_at=_now())
    )


def open_review_task(
    conn: Connection,
    kind: str,
    subject_type: str,
    subject_id: UUID | None,
    resolution: dict[str, Any] | None = None,
    *,
    priority: int = 3,
    assignee_id: UUID | None = None,
) -> UUID:
    """Open a review task (status open) and return its id. Use review.open_review_task."""
    now = _now()
    stmt = (
        review_tasks.insert()
        .values(
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            priority=priority,
            assignee_id=assignee_id,
            status="open",
            opened_at=now,
            resolution=resolution,
            created_at=now,
            updated_at=now,
        )
        .returning(review_tasks.c.id)
    )
    return UUID(str(conn.execute(stmt).scalar_one()))


def has_open_review_task(conn: Connection, kind: str, subject_type: str, subject_id: UUID) -> bool:
    """True when an open review task of this kind exists for the subject."""
    row = conn.execute(
        sa.select(review_tasks.c.id)
        .where(
            review_tasks.c.kind == kind,
            review_tasks.c.subject_type == subject_type,
            review_tasks.c.subject_id == subject_id,
            review_tasks.c.status == "open",
        )
        .limit(1)
    ).first()
    return row is not None


def get_version(conn: Connection, version_id: UUID) -> dict[str, Any] | None:
    """Return the parse-relevant columns of a document version, or None if it is missing."""
    row = (
        conn.execute(
            sa.select(
                document_versions.c.id,
                document_versions.c.raw_s3_key,
                document_versions.c.mime,
                document_versions.c.parser_version,
                document_versions.c.parsed_at,
            ).where(document_versions.c.id == version_id)
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def update_version(conn: Connection, version_id: UUID, **fields: Any) -> int:  # noqa: ANN401
    """Update columns of one document_versions row and bump updated_at. Returns rows changed."""
    result = conn.execute(
        document_versions.update()
        .where(document_versions.c.id == version_id)
        .values(**fields, updated_at=_now())
    )
    return int(result.rowcount)


def delete_parse_output(conn: Connection, version_id: UUID) -> None:
    """Remove the derived rows (page accounting, page texts, blocks) of a version."""
    for table in (blocks, page_texts, page_extractions):
        conn.execute(table.delete().where(table.c.document_version_id == version_id))


def insert_page_extractions(conn: Connection, rows: list[dict[str, Any]]) -> None:
    """Bulk-insert page accounting rows (one executemany)."""
    if rows:
        conn.execute(page_extractions.insert(), rows)


_INSERT_PAGE_TEXT = sa.text(
    "INSERT INTO page_texts (document_version_id, page_no, text, tsv, updated_at) VALUES ("
    ":document_version_id, :page_no, :text, "
    "to_tsvector('simple'::regconfig, CAST(:body AS text)), :updated_at)"
)


def insert_page_texts(conn: Connection, rows: list[dict[str, Any]]) -> None:
    """Bulk-insert page texts (one executemany). Each row carries ``body``, which fills tsv."""
    if rows:
        conn.execute(_INSERT_PAGE_TEXT, rows)


def insert_blocks(conn: Connection, rows: list[dict[str, Any]]) -> None:
    """Bulk-insert blocks (one executemany)."""
    if rows:
        conn.execute(blocks.insert(), rows)


def count_page_extractions(conn: Connection, version_id: UUID) -> int:
    """Number of page_extractions rows stored for a version."""
    return int(
        conn.execute(
            sa.select(sa.func.count())
            .select_from(page_extractions)
            .where(page_extractions.c.document_version_id == version_id)
        ).scalar_one()
    )
