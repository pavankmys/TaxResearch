"""ORM models for the identity and audit tables (migration 0003).

Only the tables the M1 API uses are mapped here. Column nullability and types follow
the migration; defaults that the database provides are mirrored by Python-side defaults
so new rows get their ids and timestamps before the flush.
"""

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.ids import uuid7


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    """Declarative base for the API's ORM models."""


class User(Base):
    """A local account. Roles live in ``user_roles``."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=True
    )
    # CITEXT in the database; Text here is fine for queries (compare with func.lower).
    email: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    cognito_sub: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    display_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="active")
    mfa_enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=True
    )


class Role(Base):
    """A role code such as ``platform_admin``. Seeded by the migration."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    code: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    scope: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class UserRole(Base):
    """Join table between users and roles."""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class AuditLog(Base):
    """One row of the hash-chained, append-only audit log.

    ``seq`` is a database identity column that orders the chain. The database rejects
    UPDATE, DELETE and TRUNCATE on this table.
    """

    __tablename__ = "audit_log"
    # Fetch server-generated values (seq) on INSERT so the row is complete after flush.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    seq: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(always=True), nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=True
    )
    actor_role: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    object_type: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    object_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(postgresql.INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)
    prev_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    row_hash: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
