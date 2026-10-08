"""legal structure: instruments, provisions, versions, amendments, links, HSN/SAC, chunks

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class LTree(UserDefinedType):
    """Postgres ltree column type (extension created in 0001)."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "LTREE"


LINK_TYPES = (
    "amends",
    "inserts",
    "substitutes",
    "omits",
    "rescinds",
    "supersedes",
    "issued_under",
    "clarifies",
    "upholds",
    "reads_down",
    "sets_aside",
    "interprets",
    "cites",
    "mentions",
    "followed",
    "relied_on",
    "distinguished",
    "doubted",
    "overruled",
    "reversed_in_appeal",
    "stayed",
    "appeal_of",
    "tagged_with",
)


def _in_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    """Create legal-structure tables, exclusion constraints and FKs onto earlier tables."""
    # instruments
    op.create_table(
        "instruments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("short_name", sa.Text(), nullable=False),
        sa.Column("state_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("code", name="uq_instruments_code"),
        sa.CheckConstraint("kind IN ('act', 'rules')", name="ck_instruments_kind"),
    )

    # provisions
    op.create_table(
        "provisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.id"),
            nullable=False,
        ),
        sa.Column("path", LTree(), nullable=False),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provisions.id"),
            nullable=True,
        ),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("number_label", sa.Text(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("first_valid_from", sa.Date(), nullable=True),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("instrument_id", "path", name="uq_provisions_instrument_path"),
        sa.CheckConstraint(
            "level IN ('chapter', 'section', 'subsection', 'clause', 'proviso', "
            "'explanation', 'rule', 'schedule_entry')",
            name="ck_provisions_level",
        ),
    )
    op.create_index(
        "ix_provisions_path",
        "provisions",
        ["path"],
        postgresql_using="gist",
    )

    # amendments (before provision_versions, which references it)
    op.create_table(
        "amendments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column(
            "source_block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id"),
            nullable=True,
        ),
        sa.Column("op", sa.Text(), nullable=False),
        sa.Column(
            "target_provision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provisions.id"),
            nullable=True,
        ),
        sa.Column(
            "target_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=True,
        ),
        sa.Column(
            "target_locator",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("old_text", sa.Text(), nullable=True),
        sa.Column("new_text", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_condition", sa.Text(), nullable=False),
        sa.Column(
            "bringing_into_force_doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=True,
        ),
        sa.Column(
            "extraction_method",
            sa.Text(),
            nullable=False,
            server_default="rule",
        ),
        sa.Column("extraction_conf", sa.REAL(), nullable=True),
        sa.Column("dry_run_ok", sa.Boolean(), nullable=True),
        sa.Column("dry_run_diff", sa.Text(), nullable=True),
        sa.Column(
            "review_status",
            sa.Text(),
            nullable=False,
            server_default="proposed",
        ),
        sa.Column(
            "reviewer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "op IN ('amend', 'insert', 'substitute', 'omit', 'rescind', 'supersede')",
            name="ck_amendments_op",
        ),
        sa.CheckConstraint(
            "effective_condition IN ('on_date', 'on_notification', 'on_gazette')",
            name="ck_amendments_effective_condition",
        ),
        sa.CheckConstraint(
            "extraction_method IN ('rule', 'human')",
            name="ck_amendments_extraction_method",
        ),
        sa.CheckConstraint(
            "review_status IN ('proposed', 'approved', 'rejected', 'needs_info', 'superseded')",
            name="ck_amendments_review_status",
        ),
    )
    op.create_index("ix_amendments_review_status", "amendments", ["review_status"])
    op.create_index("ix_amendments_target_provision_id", "amendments", ["target_provision_id"])

    # provision_versions
    op.create_table(
        "provision_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "provision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provisions.id"),
            nullable=False,
        ),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column(
            "rec_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("rec_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_amendment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("amendments.id"),
            nullable=True,
        ),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column(
            "block_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_provision_versions_valid_range",
        ),
        sa.CheckConstraint(
            "origin IN ('baseline', 'amendment', 'manual_correction')",
            name="ck_provision_versions_origin",
        ),
    )
    op.create_index(
        "ix_provision_versions_provision_valid_from",
        "provision_versions",
        ["provision_id", "valid_from"],
    )
    op.execute(
        "ALTER TABLE provision_versions ADD CONSTRAINT pv_no_overlap "
        "EXCLUDE USING gist ("
        "provision_id WITH =, "
        "daterange(valid_from, valid_to, '[)') WITH &&"
        ") WHERE (rec_to IS NULL)"
    )

    # provision_topics
    op.create_table(
        "provision_topics",
        sa.Column(
            "provision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("conf", sa.REAL(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("provision_id", "topic_id", name="pk_provision_topics"),
        sa.CheckConstraint(
            "source IN ('rule', 'human')",
            name="ck_provision_topics_source",
        ),
    )

    # consolidation_runs
    op.create_table(
        "consolidation_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.id"),
            nullable=False,
        ),
        sa.Column(
            "triggered_by_amendment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("amendments.id"),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "versions_written",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "diff_summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'done', 'failed')",
            name="ck_consolidation_runs_status",
        ),
    )

    # links
    op.create_table(
        "links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("src_type", sa.Text(), nullable=False),
        sa.Column("src_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dst_type", sa.Text(), nullable=False),
        sa.Column("dst_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_type", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "source_block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id"),
            nullable=True,
        ),
        sa.Column(
            "confidence",
            sa.REAL(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "review_status",
            sa.Text(),
            nullable=False,
            server_default="auto",
        ),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "src_type IN ('document', 'provision', 'topic', 'hsn')",
            name="ck_links_src_type",
        ),
        sa.CheckConstraint(
            "dst_type IN ('document', 'provision', 'topic', 'hsn')",
            name="ck_links_dst_type",
        ),
        sa.CheckConstraint(
            f"link_type IN ({_in_list(LINK_TYPES)})",
            name="ck_links_link_type",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="ck_links_confidence",
        ),
        sa.CheckConstraint(
            "review_status IN ('auto', 'approved', 'rejected')",
            name="ck_links_review_status",
        ),
        sa.CheckConstraint(
            "origin IN ('rule', 'human')",
            name="ck_links_origin",
        ),
    )
    op.create_index("ix_links_dst", "links", ["dst_type", "dst_id", "link_type"])
    op.create_index("ix_links_src", "links", ["src_type", "src_id", "link_type"])
    op.create_index(
        "ix_links_approved",
        "links",
        ["dst_type", "dst_id"],
        postgresql_where=sa.text("review_status = 'approved'"),
    )

    # hsn_sac_codes
    op.create_table(
        "hsn_sac_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("scheme", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("parent_code", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "scheme", "code", "valid_from", name="uq_hsn_sac_codes_scheme_code_valid_from"
        ),
        sa.CheckConstraint("scheme IN ('hsn', 'sac')", name="ck_hsn_sac_codes_scheme"),
        sa.CheckConstraint(
            "level IN ('chapter', 'heading', 'subheading', 'tariff_item')",
            name="ck_hsn_sac_codes_level",
        ),
    )
    op.execute("CREATE INDEX ix_hsn_sac_codes_code_prefix ON hsn_sac_codes (code text_pattern_ops)")

    # hsn_sac_rates
    op.create_table(
        "hsn_sac_rates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "code_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hsn_sac_codes.id"),
            nullable=False,
        ),
        sa.Column("tax_head", sa.Text(), nullable=False),
        sa.Column("rate_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("specific_amount", sa.Numeric(14, 4), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("condition_text", sa.Text(), nullable=True),
        sa.Column(
            "condition_key",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("schedule_ref", sa.Text(), nullable=True),
        sa.Column("entry_ref", sa.Text(), nullable=True),
        sa.Column(
            "notification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=True,
        ),
        sa.Column(
            "source_block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id"),
            nullable=True,
        ),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "rec_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("rec_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "review_status",
            sa.Text(),
            nullable=False,
            server_default="proposed",
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "tax_head IN ('cgst', 'sgst_utgst', 'igst', 'cess_adv', 'cess_specific')",
            name="ck_hsn_sac_rates_tax_head",
        ),
        sa.CheckConstraint(
            "review_status IN ('proposed', 'approved', 'rejected')",
            name="ck_hsn_sac_rates_review_status",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_hsn_sac_rates_valid_range",
        ),
    )
    op.execute(
        "ALTER TABLE hsn_sac_rates ADD CONSTRAINT rates_no_overlap "
        "EXCLUDE USING gist ("
        "code_id WITH =, "
        "tax_head WITH =, "
        "condition_key WITH =, "
        "daterange(valid_from, valid_to, '[)') WITH &&"
        ") WHERE (rec_to IS NULL)"
    )

    # chunks
    op.create_table(
        "chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "provision_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provision_versions.id"),
            nullable=True,
        ),
        sa.Column("chunk_kind", sa.Text(), nullable=False),
        sa.Column("structure_path", sa.Text(), nullable=True),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column(
            "block_start_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id"),
            nullable=True,
        ),
        sa.Column(
            "block_end_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id"),
            nullable=True,
        ),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("para_label", sa.Text(), nullable=True),
        sa.Column("authority_rank", sa.SmallInteger(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("court_level", sa.Text(), nullable=True),
        sa.Column("state_code", sa.Text(), nullable=True),
        sa.Column("status_at_index", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "topic_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_chunks_tenant_current_type",
        "chunks",
        ["tenant_id", "is_current", "doc_type"],
    )
    op.create_index(
        "ix_chunks_tsv",
        "chunks",
        ["tsv"],
        postgresql_using="gin",
    )
    op.create_index("ix_chunks_document", "chunks", ["document_id"])

    # FKs onto tables created in 0004
    op.create_foreign_key(
        "fk_document_status_history_cause_link",
        "document_status_history",
        "links",
        ["cause_link_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_notifications_parent_provision",
        "notifications",
        "provisions",
        ["parent_provision_id"],
        ["id"],
    )


def downgrade() -> None:
    """Drop legal-structure tables and the FKs added to 0004 tables."""
    op.drop_constraint("fk_notifications_parent_provision", "notifications", type_="foreignkey")
    op.drop_constraint(
        "fk_document_status_history_cause_link", "document_status_history", type_="foreignkey"
    )

    op.drop_table("chunks")
    op.drop_table("hsn_sac_rates")
    op.drop_table("hsn_sac_codes")
    op.drop_table("links")
    op.drop_table("consolidation_runs")
    op.drop_table("provision_topics")
    op.drop_table("provision_versions")
    op.drop_table("amendments")
    op.drop_table("provisions")
    op.drop_table("instruments")
