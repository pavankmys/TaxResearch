"""M3: structure and metadata columns, and the ingestion dashboard views

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Dashboard views (TSD 5.11). Each one is read by the API's dashboard endpoint.
# Views are dropped in reverse order of creation on downgrade.
VIEWS: tuple[str, ...] = (
    # Jobs per source per day by status, last 30 days.
    """
    CREATE OR REPLACE VIEW v_ingest_daily AS
    SELECT s.code AS source_code,
           date_trunc('day', j.discovered_at) AS day,
           count(*) AS discovered,
           count(*) FILTER (WHERE j.status = 'done') AS done,
           count(*) FILTER (WHERE j.status = 'failed') AS failed,
           count(*) FILTER (WHERE j.status = 'skipped') AS skipped,
           count(*) FILTER (WHERE j.status = 'running') AS running,
           count(*) FILTER (WHERE j.status = 'queued') AS queued
    FROM ingestion_jobs j
    JOIN sources s ON s.id = j.source_id
    WHERE j.discovered_at >= now() - interval '30 days'
    GROUP BY s.code, date_trunc('day', j.discovered_at)
    """,
    # Discovery to publication time in hours, p50 and p95, over 7 days. One overall row
    # (source_code NULL) followed by one row per source.
    """
    CREATE OR REPLACE VIEW v_ingest_freshness AS
    WITH f AS (
        SELECT s.code AS source_code,
               extract(epoch FROM (j.published_at - j.discovered_at))::double precision
                   / 3600.0 AS hours
        FROM ingestion_jobs j
        LEFT JOIN sources s ON s.id = j.source_id
        WHERE j.published_at IS NOT NULL
          AND j.discovered_at >= now() - interval '7 days'
    )
    SELECT NULL::text AS source_code,
           count(*) AS samples,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY f.hours) AS p50_hours,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY f.hours) AS p95_hours
    FROM f
    UNION ALL
    SELECT f.source_code,
           count(*) AS samples,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY f.hours) AS p50_hours,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY f.hours) AS p95_hours
    FROM f
    GROUP BY f.source_code
    """,
    # Time since the last new document against the expected cadence. Stale means more than
    # three cadences; a source without a cadence is never stale.
    """
    CREATE OR REPLACE VIEW v_source_health AS
    SELECT x.code,
           x.enabled,
           x.expected_cadence_hours,
           x.last_success_at,
           x.last_new_doc_at,
           x.hours_since_new_doc,
           COALESCE(
               x.expected_cadence_hours IS NOT NULL
               AND x.hours_since_new_doc > 3 * x.expected_cadence_hours,
               false
           ) AS stale
    FROM (
        SELECT s.code,
               s.enabled,
               s.expected_cadence_hours,
               s.last_success_at,
               s.last_new_doc_at,
               extract(epoch FROM (now() - s.last_new_doc_at))::double precision
                   / 3600.0 AS hours_since_new_doc
        FROM sources s
    ) x
    """,
    # Open work by kind and status, with the oldest opening time and overdue tasks.
    """
    CREATE OR REPLACE VIEW v_review_queue AS
    SELECT t.kind,
           t.status,
           count(*) AS count,
           min(t.opened_at) AS oldest_opened_at,
           count(*) FILTER (WHERE t.sla_due_at < now()) AS overdue_count
    FROM review_tasks t
    WHERE t.status IN ('open', 'in_review')
    GROUP BY t.kind, t.status
    """,
    # Page extraction outcomes by method and status, with flagged pages and pages parsed in the
    # last 30 days.
    """
    CREATE OR REPLACE VIEW v_page_accounting AS
    SELECT pe.method,
           pe.status,
           count(*) AS pages,
           count(*) FILTER (WHERE pe.flagged) AS flagged_pages,
           count(*) FILTER (
               WHERE dv.parsed_at >= now() - interval '30 days'
           ) AS pages_last_30d
    FROM page_extractions pe
    JOIN document_versions dv ON dv.id = pe.document_version_id
    GROUP BY pe.method, pe.status
    """,
    # Pages where the two text engines differ by more than 5% of the larger count.
    """
    CREATE OR REPLACE VIEW v_cross_check_disagreements AS
    SELECT count(*) AS compared_pages,
           count(*) FILTER (
               WHERE abs(pe.chars_engine_a - pe.chars_engine_b)
                     > 0.05 * greatest(pe.chars_engine_a, pe.chars_engine_b)
           ) AS disagreements
    FROM page_extractions pe
    WHERE pe.chars_engine_a IS NOT NULL AND pe.chars_engine_b IS NOT NULL
    """,
    # Queued jobs per queue. Lag is measured from the oldest run_after, so a job waiting for a
    # retry backoff does not count as lagging before it is due.
    """
    CREATE OR REPLACE VIEW v_queue_lag AS
    SELECT q.queue,
           count(*) AS queued,
           min(q.run_after) AS oldest_run_after,
           min(q.created_at) AS oldest_created_at,
           greatest(
               0,
               extract(epoch FROM (now() - min(q.run_after)))::double precision
           ) / 60.0 AS lag_minutes
    FROM job_queue q
    WHERE q.status = 'queued'
    GROUP BY q.queue
    """,
)

VIEW_NAMES: tuple[str, ...] = (
    "v_queue_lag",
    "v_cross_check_disagreements",
    "v_page_accounting",
    "v_review_queue",
    "v_source_health",
    "v_ingest_freshness",
    "v_ingest_daily",
)


def upgrade() -> None:
    """Add the M3 columns to documents and document_versions, then create the views."""
    op.add_column(
        "document_versions",
        sa.Column("segmenter_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("extractor_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("segmented_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("meta_confidence", sa.REAL(), nullable=True),
    )
    for statement in VIEWS:
        op.execute(statement)


def downgrade() -> None:
    """Drop the views, then the M3 columns."""
    for name in VIEW_NAMES:
        op.execute(f"DROP VIEW IF EXISTS {name}")
    op.drop_column("documents", "meta_confidence")
    op.drop_column("documents", "metadata")
    op.drop_column("document_versions", "extracted_at")
    op.drop_column("document_versions", "segmented_at")
    op.drop_column("document_versions", "extractor_version")
    op.drop_column("document_versions", "segmenter_version")
