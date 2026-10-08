"""sources, documents, versions, blocks and document-type detail tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_STATUS_VALUES = "'in_force', 'amended', 'superseded', 'rescinded', 'struck_down', 'stayed'"


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        UUID(as_uuid=True),
        nullable=False,
        server_default=sa.text("uuid_generate_v7()"),
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    """Create the shared-corpus document model and parsed-content tables."""
    # sources
    op.create_table(
        "sources",
        _id_column(),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("schedule_cron", sa.Text(), nullable=True),
        sa.Column("expected_cadence_hours", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_new_doc_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health", sa.Text(), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_sources_code"),
        sa.CheckConstraint(
            "kind IN ('html_list', 'rss', 'api', 'manual')",
            name="ck_sources_kind",
        ),
    )

    # documents: FK to document_versions is added after that table exists.
    op.create_table(
        "documents",
        _id_column(),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("canonical_id", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("authority_rank", sa.SmallInteger(), nullable=False),
        sa.Column("issuing_authority", sa.Text(), nullable=True),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("series", sa.Text(), nullable=True),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("in_force_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="in_force"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("court", sa.Text(), nullable=True),
        sa.Column("bench", sa.Text(), nullable=True),
        sa.Column("state_code", sa.Text(), nullable=True),
        sa.Column("jurisdiction_scope", sa.Text(), nullable=True),
        sa.Column("current_version_id", UUID(as_uuid=True), nullable=True),
        sa.Column("review_state", sa.Text(), nullable=False, server_default="pending_review"),
        sa.Column(
            "topic_ids",
            postgresql.ARRAY(UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "authority_rank BETWEEN 1 AND 11",
            name="ck_documents_authority_rank",
        ),
        sa.CheckConstraint(
            f"status IN ({DOCUMENT_STATUS_VALUES})",
            name="ck_documents_status",
        ),
        sa.CheckConstraint(
            "review_state IN ('auto_published', 'pending_review', 'reviewed')",
            name="ck_documents_review_state",
        ),
    )
    # canonical_id is unique per tenant scope: once for shared rows, once per tenant.
    op.create_index(
        "uq_documents_canonical_shared",
        "documents",
        ["canonical_id"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        "uq_documents_canonical_tenant",
        "documents",
        ["tenant_id", "canonical_id"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index("ix_documents_doc_type_doc_date", "documents", ["doc_type", "doc_date"])
    op.execute("CREATE INDEX ix_documents_title_trgm ON documents USING gin (title gin_trgm_ops)")
    op.execute("CREATE INDEX ix_documents_number_trgm ON documents USING gin (number gin_trgm_ops)")

    # document_sources: all URLs for one canonical record.
    op.create_table(
        "document_sources",
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("http_etag", sa.Text(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("document_id", "url"),
    )

    # document_versions
    op.create_table(
        "document_versions",
        _id_column(),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("raw_s3_key", sa.Text(), nullable=False),
        sa.Column("raw_sha256", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=True),
        sa.Column("simhash", sa.BigInteger(), nullable=True),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parser_version", sa.Text(), nullable=True),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ocr_conf", sa.REAL(), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "supersedes_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id"),
            nullable=True,
        ),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "version_no",
            name="uq_document_versions_document_version_no",
        ),
    )
    op.create_index(
        "ix_document_versions_raw_sha256",
        "document_versions",
        ["raw_sha256"],
    )

    # document_status_history: cause_link_id FK to links is added in 0005.
    op.create_table(
        "document_status_history",
        _id_column(),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("cause_link_id", UUID(as_uuid=True), nullable=True),
        sa.Column("set_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"status IN ({DOCUMENT_STATUS_VALUES})",
            name="ck_document_status_history_status",
        ),
    )
    op.create_index(
        "ix_document_status_history_document_valid",
        "document_status_history",
        ["document_id", "valid_from"],
    )

    # blocks: atomic addressable units. Citations point here.
    op.create_table(
        "blocks",
        _id_column(),
        sa.Column(
            "document_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(), nullable=True),
        sa.Column("para_label", sa.Text(), nullable=True),
        sa.Column("structure_path", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("is_boilerplate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lang", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "seq",
            name="uq_blocks_document_version_seq",
        ),
        sa.CheckConstraint(
            "kind IN ('heading', 'para', 'table', 'table_row', 'footnote')",
            name="ck_blocks_kind",
        ),
    )

    # page_extractions: page accounting, one row per page of a version.
    op.create_table(
        "page_extractions",
        sa.Column(
            "document_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("chars_engine_a", sa.Integer(), nullable=True),
        sa.Column("chars_engine_b", sa.Integer(), nullable=True),
        sa.Column("garble_score", sa.REAL(), nullable=True),
        sa.Column("ocr_conf", sa.REAL(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("document_version_id", "page_no"),
        sa.CheckConstraint(
            "method IN ('text', 'ocr', 'failed')",
            name="ck_page_extractions_method",
        ),
    )

    # page_texts: raw page text fallback, full-text indexed.
    op.create_table(
        "page_texts",
        sa.Column(
            "document_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("document_version_id", "page_no"),
    )
    op.create_index("ix_page_texts_tsv", "page_texts", ["tsv"], postgresql_using="gin")

    # notifications: typed attributes of a notification document.
    op.create_table(
        "notifications",
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("series", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("parent_power_text", sa.Text(), nullable=True),
        # FK to provisions is added in 0005.
        sa.Column("parent_provision_id", UUID(as_uuid=True), nullable=True),
        sa.Column("gazette_ref", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("document_id"),
    )

    # circulars
    op.create_table(
        "circulars",
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("din", sa.Text(), nullable=True),
        sa.Column("circular_status", sa.Text(), nullable=False, server_default="in_force"),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("document_id"),
        sa.CheckConstraint(
            "kind IN ('circular', 'instruction', 'order', 'rod_order')",
            name="ck_circulars_kind",
        ),
        sa.CheckConstraint(
            "circular_status IN ('in_force', 'withdrawn', 'held_contrary')",
            name="ck_circulars_circular_status",
        ),
    )

    # judgements
    op.create_table(
        "judgements",
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("court_level", sa.Text(), nullable=False),
        sa.Column("court_name", sa.Text(), nullable=False),
        sa.Column("bench", sa.Text(), nullable=True),
        sa.Column("judges", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("decision_date", sa.Date(), nullable=True),
        sa.Column("parties", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "reporter_citations",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "case_numbers",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("outcome", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("outcome_conf", sa.REAL(), nullable=True),
        sa.Column("good_law_flag", sa.Text(), nullable=True),
        sa.Column("good_law_note", sa.Text(), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("document_id"),
        sa.CheckConstraint(
            "court_level IN ('SC', 'HC', 'GSTAT', 'AAR', 'AAAR')",
            name="ck_judgements_court_level",
        ),
        sa.CheckConstraint(
            "outcome IN ('for_assessee', 'against', 'mixed', 'remand', 'unknown')",
            name="ck_judgements_outcome",
        ),
    )

    # judgement_treatments: table defined in MVP, populated in P2.
    op.create_table(
        "judgement_treatments",
        _id_column(),
        sa.Column(
            "citing_judgement_id",
            UUID(as_uuid=True),
            sa.ForeignKey("judgements.document_id"),
            nullable=False,
        ),
        sa.Column(
            "cited_judgement_id",
            UUID(as_uuid=True),
            sa.ForeignKey("judgements.document_id"),
            nullable=False,
        ),
        sa.Column("treatment", sa.Text(), nullable=False),
        sa.Column("block_id", UUID(as_uuid=True), sa.ForeignKey("blocks.id"), nullable=True),
        sa.Column("proposed_by", sa.Text(), nullable=False, server_default="human"),
        sa.Column("review_status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column("reviewed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("proposed_by IN ('human')", name="ck_judgement_treatments_proposed_by"),
        sa.CheckConstraint(
            "review_status IN ('proposed', 'approved', 'rejected')",
            name="ck_judgement_treatments_review_status",
        ),
    )

    # council_items (rank 10 council material)
    op.create_table(
        "council_items",
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("meeting_no", sa.Integer(), nullable=False),
        sa.Column("meeting_date", sa.Date(), nullable=True),
        sa.Column("item_ref", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("document_id"),
    )

    # document_topics: composite key join table.
    op.create_table(
        "document_topics",
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("conf", sa.REAL(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("document_id", "topic_id"),
        sa.CheckConstraint("source IN ('rule', 'human')", name="ck_document_topics_source"),
    )

    # numbering_checks: gap detection per series and year.
    op.create_table(
        "numbering_checks",
        sa.Column("series_key", sa.Text(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("expected_range", postgresql.INT4RANGE(), nullable=True),
        sa.Column(
            "missing_numbers",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("explained", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("series_key", "year"),
    )

    # source_coverage: one row per source, shown on results page and /v1/coverage.
    op.create_table(
        "source_coverage",
        sa.Column(
            "source_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("loaded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("earliest_date", sa.Date(), nullable=True),
        sa.Column("latest_date", sa.Date(), nullable=True),
        sa.Column("known_gaps", postgresql.JSONB(), nullable=False, server_default="[]"),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("source_id"),
    )

    # synonym_terms: expert-maintained query expansion, visible to the user.
    op.create_table(
        "synonym_terms",
        _id_column(),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column(
            "expansions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("maintained_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("term", name="uq_synonym_terms_term"),
        sa.CheckConstraint(
            "kind IN ('synonym', 'abbreviation')",
            name="ck_synonym_terms_kind",
        ),
    )

    # feed_items: shared feed, filtered per user at read time.
    op.create_table(
        "feed_items",
        _id_column(),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_ids",
            postgresql.ARRAY(UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column(
            "sections_referred",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feed_items_published_at", "feed_items", ["published_at"])

    # Deferred foreign keys: these need tables created above.
    op.create_foreign_key(
        "fk_documents_current_version",
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_saved_items_block",
        "saved_items",
        "blocks",
        ["block_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Drop everything created in upgrade(), in reverse order."""
    op.drop_constraint("fk_saved_items_block", "saved_items", type_="foreignkey")
    op.drop_constraint("fk_documents_current_version", "documents", type_="foreignkey")

    op.drop_index("ix_feed_items_published_at", table_name="feed_items")
    op.drop_table("feed_items")
    op.drop_table("synonym_terms")
    op.drop_table("source_coverage")
    op.drop_table("numbering_checks")
    op.drop_table("document_topics")
    op.drop_table("council_items")
    op.drop_table("judgement_treatments")
    op.drop_table("judgements")
    op.drop_table("circulars")
    op.drop_table("notifications")
    op.drop_index("ix_page_texts_tsv", table_name="page_texts")
    op.drop_table("page_texts")
    op.drop_table("page_extractions")
    op.drop_table("blocks")
    op.drop_index(
        "ix_document_status_history_document_valid",
        table_name="document_status_history",
    )
    op.drop_table("document_status_history")
    op.drop_index("ix_document_versions_raw_sha256", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_table("document_sources")
    op.execute("DROP INDEX IF EXISTS ix_documents_number_trgm")
    op.execute("DROP INDEX IF EXISTS ix_documents_title_trgm")
    op.drop_index("ix_documents_doc_type_doc_date", table_name="documents")
    op.drop_index("uq_documents_canonical_tenant", table_name="documents")
    op.drop_index("uq_documents_canonical_shared", table_name="documents")
    op.drop_table("documents")
    op.drop_table("sources")
