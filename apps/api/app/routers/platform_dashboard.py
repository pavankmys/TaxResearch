"""Ingestion dashboard (TSD 5.11): the SQL views from migration 0007, and alerts over them.

The alerts are computed here from fixed thresholds. The 24 h failure rate is read straight from
ingestion_jobs, because the daily view is grouped by calendar day.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, require_permission
from app.db import get_session

router = APIRouter(prefix="/v1/platform/ingestion", tags=["dashboard"])

NO_STORE = "private, no-store"

FAILURE_RATE_LIMIT = 0.05
FRESHNESS_P95_LIMIT_HOURS = 12.0
QUEUE_LAG_LIMIT_MINUTES = 30.0

FAILURE_RATE_SQL = text(
    """
    SELECT count(*) AS total, count(*) FILTER (WHERE status = 'failed') AS failed
    FROM ingestion_jobs
    WHERE discovered_at >= now() - interval '24 hours'
    """
)
DAILY_SQL = text(
    """
    SELECT source_code, day, discovered, done, failed, skipped, running, queued
    FROM v_ingest_daily
    ORDER BY day DESC, source_code
    """
)
FRESHNESS_SQL = text(
    "SELECT source_code, samples, p50_hours, p95_hours FROM v_ingest_freshness "
    "ORDER BY source_code NULLS FIRST"
)
HEALTH_SQL = text(
    """
    SELECT code, enabled, expected_cadence_hours, last_success_at, last_new_doc_at,
           hours_since_new_doc, stale
    FROM v_source_health
    ORDER BY code
    """
)
REVIEW_QUEUE_SQL = text(
    "SELECT kind, status, count, oldest_opened_at, overdue_count FROM v_review_queue "
    "ORDER BY kind, status"
)
PAGES_SQL = text(
    "SELECT method, status, pages, flagged_pages, pages_last_30d FROM v_page_accounting "
    "ORDER BY method, status"
)
CROSS_CHECK_SQL = text("SELECT compared_pages, disagreements FROM v_cross_check_disagreements")
QUEUE_LAG_SQL = text(
    "SELECT queue, queued, oldest_run_after, oldest_created_at, lag_minutes FROM v_queue_lag "
    "ORDER BY queue"
)


class DailyRow(BaseModel):
    """Jobs discovered on one day for one source, by status."""

    source_code: str | None
    day: datetime
    discovered: int
    done: int
    failed: int
    skipped: int
    running: int
    queued: int


class FreshnessRow(BaseModel):
    """Hours from discovery to publication. source_code is null for the overall row."""

    source_code: str | None
    samples: int
    p50_hours: float | None
    p95_hours: float | None


class SourceHealthRow(BaseModel):
    """A source's last new document against its expected cadence."""

    code: str
    enabled: bool
    expected_cadence_hours: int | None
    last_success_at: datetime | None
    last_new_doc_at: datetime | None
    hours_since_new_doc: float | None
    stale: bool


class ReviewQueueRow(BaseModel):
    """Open review tasks by kind and status."""

    kind: str
    status: str
    count: int
    oldest_opened_at: datetime | None
    overdue_count: int


class PageAccountingRow(BaseModel):
    """Page extraction outcomes by method and status."""

    method: str
    status: str
    pages: int
    flagged_pages: int
    pages_last_30d: int


class CrossCheckRow(BaseModel):
    """Pages where the two text engines were compared, and how many disagree by over 5%."""

    compared_pages: int
    disagreements: int


class QueueLagRow(BaseModel):
    """Queued jobs per queue, and how long the oldest has been due."""

    queue: str
    queued: int
    oldest_run_after: datetime | None
    oldest_created_at: datetime | None
    lag_minutes: float


class Alert(BaseModel):
    """A threshold that is breached now."""

    kind: Literal[
        "failure_rate",
        "freshness_p95",
        "stale_source",
        "overdue_review",
        "queue_lag",
    ]
    message: str
    subject: str | None


class Dashboard(BaseModel):
    """Everything the ingestion dashboard shows, and the alerts that are firing."""

    daily: list[DailyRow]
    freshness: list[FreshnessRow]
    source_health: list[SourceHealthRow]
    review_queue: list[ReviewQueueRow]
    page_accounting: list[PageAccountingRow]
    cross_check_disagreements: CrossCheckRow
    queue_lag: list[QueueLagRow]
    numbering_gaps: dict[str, str]
    alerts: list[Alert]


def _alerts(
    failure: dict[str, Any],
    freshness: list[FreshnessRow],
    health: list[SourceHealthRow],
    queue: list[ReviewQueueRow],
    lag: list[QueueLagRow],
) -> list[Alert]:
    alerts: list[Alert] = []
    total = int(failure["total"] or 0)
    failed = int(failure["failed"] or 0)
    if total and failed / total > FAILURE_RATE_LIMIT:
        alerts.append(
            Alert(
                kind="failure_rate",
                message=f"{failed} of {total} jobs failed in the last 24 h",
                subject=None,
            )
        )
    for row in freshness:
        if row.p95_hours is not None and row.p95_hours > FRESHNESS_P95_LIMIT_HOURS:
            alerts.append(
                Alert(
                    kind="freshness_p95",
                    message=f"p95 freshness is {row.p95_hours:.1f} h (limit 12 h)",
                    subject=row.source_code,
                )
            )
    for source in health:
        if source.stale:
            alerts.append(
                Alert(
                    kind="stale_source",
                    message="No new document for more than 3 times the expected cadence",
                    subject=source.code,
                )
            )
    for task in queue:
        if task.overdue_count > 0:
            alerts.append(
                Alert(
                    kind="overdue_review",
                    message=f"{task.overdue_count} {task.kind} task(s) past SLA",
                    subject=task.kind,
                )
            )
    for entry in lag:
        if entry.lag_minutes > QUEUE_LAG_LIMIT_MINUTES:
            alerts.append(
                Alert(
                    kind="queue_lag",
                    message=f"Oldest queued job is {entry.lag_minutes:.0f} min old (limit 30)",
                    subject=entry.queue,
                )
            )
    return alerts


@router.get("/dashboard", response_model=Dashboard)
async def get_dashboard(
    response: Response,
    actor: CurrentUser = Depends(require_permission("dashboard.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Dashboard:
    """Ingestion metrics from the views, plus the alerts that are firing now."""
    response.headers["Cache-Control"] = NO_STORE
    failure = (await session.execute(FAILURE_RATE_SQL)).mappings().one()
    daily = [DailyRow(**dict(r)) for r in (await session.execute(DAILY_SQL)).mappings()]
    freshness = [FreshnessRow(**dict(r)) for r in (await session.execute(FRESHNESS_SQL)).mappings()]
    health = [SourceHealthRow(**dict(r)) for r in (await session.execute(HEALTH_SQL)).mappings()]
    queue = [
        ReviewQueueRow(**dict(r)) for r in (await session.execute(REVIEW_QUEUE_SQL)).mappings()
    ]
    pages = [PageAccountingRow(**dict(r)) for r in (await session.execute(PAGES_SQL)).mappings()]
    cross = (await session.execute(CROSS_CHECK_SQL)).mappings().one()
    lag = [QueueLagRow(**dict(r)) for r in (await session.execute(QUEUE_LAG_SQL)).mappings()]

    return Dashboard(
        daily=daily,
        freshness=freshness,
        source_health=health,
        review_queue=queue,
        page_accounting=pages,
        cross_check_disagreements=CrossCheckRow(**dict(cross)),
        queue_lag=lag,
        numbering_gaps={"status": "not_measured_until_M7"},
        alerts=_alerts(dict(failure), freshness, health, queue, lag),
    )
