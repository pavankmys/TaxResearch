"""identity, tenancy, matters, audit log

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import UserDefinedType

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class LTree(UserDefinedType):
    """Postgres ltree column type (extension created in 0001)."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "LTREE"


class CIText(UserDefinedType):
    """Postgres citext column type (extension created in 0001)."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "CITEXT"


# UUIDv7 generator. gen_random_uuid() is core in PG13+, so pgcrypto is not needed.
UUID_V7_FUNCTION = """
CREATE OR REPLACE FUNCTION uuid_generate_v7() RETURNS uuid AS $$
DECLARE
  unix_ts_ms bytea;
  uuid_bytes bytea;
BEGIN
  unix_ts_ms := substring(
    int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3
  );
  uuid_bytes := unix_ts_ms || substring(uuid_send(gen_random_uuid()) FROM 7 FOR 10);
  uuid_bytes := set_byte(uuid_bytes, 6, (b'0111' || get_byte(uuid_bytes, 6)::bit(4))::bit(8)::int);
  uuid_bytes := set_byte(uuid_bytes, 8, (b'10' || get_byte(uuid_bytes, 8)::bit(6))::bit(8)::int);
  RETURN encode(uuid_bytes, 'hex')::uuid;
END
$$ LANGUAGE plpgsql VOLATILE;
"""

# Append-only guard for audit_log: rejects UPDATE, DELETE and TRUNCATE.
AUDIT_BLOCK_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_log_block_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = 'insufficient_privilege';
END
$$ LANGUAGE plpgsql;
"""


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
    """Create identity, tenancy, matter workspace and audit tables."""
    op.execute(UUID_V7_FUNCTION)

    # tenants
    op.create_table(
        "tenants",
        _id_column(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("data_region", sa.Text(), nullable=True),
        sa.Column("retention_delete_after", sa.Date(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')",
            name="ck_tenants_status",
        ),
    )

    # users
    op.create_table(
        "users",
        _id_column(),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("email", CIText(), nullable=False),
        sa.Column("cognito_sub", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("cognito_sub", name="uq_users_cognito_sub"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
    )

    # roles
    op.create_table(
        "roles",
        _id_column(),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
        sa.CheckConstraint("scope IN ('platform', 'tenant')", name="ck_roles_scope"),
    )
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("code", sa.Text),
            sa.column("scope", sa.Text),
            sa.column("description", sa.Text),
        ),
        [
            {
                "code": "platform_content_editor",
                "scope": "platform",
                "description": "Platform staff who edit and review the shared corpus",
            },
            {
                "code": "platform_admin",
                "scope": "platform",
                "description": "Platform administrator",
            },
            {
                "code": "firm_admin",
                "scope": "tenant",
                "description": "Firm administrator (P2)",
            },
            {"code": "partner", "scope": "tenant", "description": "Partner (P2)"},
            {"code": "professional", "scope": "tenant", "description": "Tax professional"},
            {
                "code": "junior",
                "scope": "tenant",
                "description": "Junior professional (P2)",
            },
            {
                "code": "client_viewer",
                "scope": "tenant",
                "description": "Client viewer (P3)",
            },
        ],
    )

    # user_roles
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    # audit_log: append-only, hash-chained. The app supplies id; no server default.
    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=True),
        sa.Column("object_id", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("prev_hash", sa.Text(), nullable=False),
        sa.Column("row_hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq", name="uq_audit_log_seq"),
        sa.UniqueConstraint("row_hash", name="uq_audit_log_row_hash"),
    )
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_user_id", "ts"])
    op.create_index("ix_audit_log_action", "audit_log", ["action", "ts"])
    op.create_index("ix_audit_log_object", "audit_log", ["object_type", "object_id"])
    op.execute(AUDIT_BLOCK_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_block_mutation()"
    )

    # topics
    op.create_table(
        "topics",
        _id_column(),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("path", LTree(), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_topics_code"),
    )
    op.create_index("ix_topics_path", "topics", ["path"], postgresql_using="gist")

    # matters
    op.create_table(
        "matters",
        _id_column(),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column(
            "gstins",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("period_from", sa.Date(), nullable=True),
        sa.Column("period_to", sa.Date(), nullable=True),
        sa.Column("state_code", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'archived')",
            name="ck_matters_status",
        ),
    )

    # matter_members
    op.create_table(
        "matter_members",
        sa.Column(
            "matter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("access", sa.Text(), nullable=False),
        sa.Column("added_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("matter_id", "user_id"),
        sa.CheckConstraint("access IN ('view', 'edit')", name="ck_matter_members_access"),
    )

    # matter_topics
    op.create_table(
        "matter_topics",
        sa.Column(
            "matter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("matter_id", "topic_id"),
    )

    # user_topic_follows
    op.create_table(
        "user_topic_follows",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("user_id", "topic_id"),
    )

    # digest_prefs
    op.create_table(
        "digest_prefs",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("frequency", sa.Text(), nullable=False, server_default="off"),
        sa.Column("send_hour_ist", sa.SmallInteger(), nullable=False, server_default="8"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint(
            "frequency IN ('off', 'daily', 'weekly')",
            name="ck_digest_prefs_frequency",
        ),
        sa.CheckConstraint(
            "send_hour_ist BETWEEN 0 AND 23",
            name="ck_digest_prefs_send_hour_ist",
        ),
    )

    # saved_searches
    op.create_table(
        "saved_searches",
        _id_column(),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("matter_id", UUID(as_uuid=True), sa.ForeignKey("matters.id"), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("as_on", sa.Date(), nullable=True),
        sa.Column("corpus_version", sa.BigInteger(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
    )

    # saved_items: block_id FK to blocks is added in 0004 (blocks does not exist yet).
    op.create_table(
        "saved_items",
        _id_column(),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("matter_id", UUID(as_uuid=True), sa.ForeignKey("matters.id"), nullable=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="private"),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "visibility IN ('private', 'team')",
            name="ck_saved_items_visibility",
        ),
    )

    # exports
    op.create_table(
        "exports",
        _id_column(),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "saved_search_id",
            UUID(as_uuid=True),
            sa.ForeignKey("saved_searches.id"),
            nullable=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=True),
        sa.Column("watermark", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("approved_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("format IN ('csv', 'docx', 'pdf')", name="ck_exports_format"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="ck_exports_status",
        ),
    )


def downgrade() -> None:
    """Drop everything created in upgrade(), in reverse order."""
    op.drop_table("exports")
    op.drop_table("saved_items")
    op.drop_table("saved_searches")
    op.drop_table("digest_prefs")
    op.drop_table("user_topic_follows")
    op.drop_table("matter_topics")
    op.drop_table("matter_members")
    op.drop_table("matters")
    op.drop_index("ix_topics_path", table_name="topics")
    op.drop_table("topics")

    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update_delete ON audit_log")
    op.drop_index("ix_audit_log_object", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_actor", table_name="audit_log")
    op.drop_index("ix_audit_log_ts", table_name="audit_log")
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_block_mutation()")

    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("tenants")

    op.execute("DROP FUNCTION IF EXISTS uuid_generate_v7()")
