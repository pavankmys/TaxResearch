"""M4a: baseline law columns and instruments seeding.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add baseline columns to instruments, seed three instruments, update check."""
    # Add baseline columns to instruments
    op.add_column(
        "instruments",
        sa.Column(
            "baseline_status",
            sa.Text(),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "instruments",
        sa.Column("baseline_document_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "instruments",
        sa.Column("baseline_as_on", sa.Date(), nullable=True),
    )
    op.add_column(
        "instruments",
        sa.Column("baseline_verified_by", sa.UUID(), nullable=True),
    )
    op.add_column(
        "instruments",
        sa.Column("baseline_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Add foreign keys for the new columns
    op.create_foreign_key(
        "fk_instruments_baseline_document",
        "instruments",
        "documents",
        ["baseline_document_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_instruments_baseline_verified_by",
        "instruments",
        "users",
        ["baseline_verified_by"],
        ["id"],
    )

    # Add CHECK constraint for baseline_status
    op.create_check_constraint(
        "ck_instruments_baseline_status",
        "instruments",
        "baseline_status IN ('none', 'loaded', 'verified')",
    )

    # Seed instruments (idempotent: INSERT ... ON CONFLICT DO NOTHING)
    op.execute(
        """
        INSERT INTO instruments (code, kind, short_name, created_at, updated_at)
        VALUES
            ('CGST_ACT', 'act', 'CGST Act', now(), now()),
            ('IGST_ACT', 'act', 'IGST Act', now(), now()),
            ('CGST_RULES', 'rules', 'CGST Rules', now(), now())
        ON CONFLICT (code) DO NOTHING;
        """
    )

    # Replace the provisions level CHECK constraint to include 'subclause'
    op.drop_constraint("ck_provisions_level", "provisions", type_="check")
    op.create_check_constraint(
        "ck_provisions_level",
        "provisions",
        "level IN ('chapter', 'section', 'subsection', 'clause', 'subclause', "
        "'proviso', 'explanation', 'rule', 'schedule_entry')",
    )


def downgrade() -> None:
    """Remove baseline columns, unseed instruments, restore old provisions level check."""
    # Restore old provisions level CHECK constraint (without 'subclause')
    op.drop_constraint("ck_provisions_level", "provisions", type_="check")
    op.create_check_constraint(
        "ck_provisions_level",
        "provisions",
        "level IN ('chapter', 'section', 'subsection', 'clause', 'proviso', "
        "'explanation', 'rule', 'schedule_entry')",
    )

    # Delete only the three seeded instruments if they have no provisions
    op.execute(
        """
        DELETE FROM instruments
        WHERE code IN ('CGST_ACT', 'IGST_ACT', 'CGST_RULES')
        AND NOT EXISTS (SELECT 1 FROM provisions WHERE instrument_id = instruments.id);
        """
    )

    # Drop foreign keys
    op.drop_constraint("fk_instruments_baseline_verified_by", "instruments", type_="foreignkey")
    op.drop_constraint("fk_instruments_baseline_document", "instruments", type_="foreignkey")

    # Drop CHECK constraint for baseline_status
    op.drop_constraint("ck_instruments_baseline_status", "instruments", type_="check")

    # Drop columns
    op.drop_column("instruments", "baseline_verified_at")
    op.drop_column("instruments", "baseline_verified_by")
    op.drop_column("instruments", "baseline_as_on")
    op.drop_column("instruments", "baseline_document_id")
    op.drop_column("instruments", "baseline_status")
