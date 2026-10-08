"""Miss reports: a signed-in user says a search missed something.

The report opens a review task of kind miss_report (priority 4, no SLA). The search UI that calls
this comes in M5 and M6. Tasks go round-robin to the content editors (review_assign.py).
"""

import datetime as dt
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.db import get_session
from app.review_assign import next_assignee

router = APIRouter(prefix="/v1/miss-reports", tags=["miss-reports"])

NO_STORE = "private, no-store"

MISS_REPORT_PRIORITY = 4

INSERT_TASK_SQL = text(
    """
    INSERT INTO review_tasks (kind, subject_type, subject_id, priority, assignee_id, status,
                              sla_due_at, resolution, updated_by)
    VALUES ('miss_report', 'search', NULL, :priority, :assignee, 'open', NULL,
            CAST(:resolution AS JSON), :actor)
    RETURNING id
    """
)


class MissReportIn(BaseModel):
    """What the user searched for, and what they expected to find."""

    query: str = Field(min_length=1, max_length=2000)
    filters: dict[str, Any] = Field(default_factory=dict)
    as_on: dt.date | None = None
    expected: str | None = Field(default=None, max_length=2000)


class MissReportCreated(BaseModel):
    """The new review task."""

    id: uuid.UUID


@router.post("", status_code=201, response_model=MissReportCreated)
async def create_miss_report(
    body: MissReportIn,
    request: Request,
    response: Response,
    actor: CurrentUser = Depends(require_permission("miss_report.create")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> MissReportCreated:
    """Open a miss_report review task holding the query, filters and as-on date."""
    response.headers["Cache-Control"] = NO_STORE
    report = {
        "query": body.query,
        "filters": body.filters,
        "as_on": body.as_on.isoformat() if body.as_on is not None else None,
        "expected": body.expected,
        "reported_by": str(actor.id),
    }
    assignee = await next_assignee(session)
    task_id = (
        await session.execute(
            INSERT_TASK_SQL,
            {
                "priority": MISS_REPORT_PRIORITY,
                "assignee": assignee,
                "resolution": json.dumps({"report": report}),
                "actor": actor.id,
            },
        )
    ).scalar_one()
    await write_audit(
        session,
        action="miss_report.create",
        actor=actor,
        object_type="review_task",
        object_id=str(task_id),
        detail={"assigned": assignee is not None, "filter_keys": sorted(body.filters)},
        ctx=audit_context_from_request(request),
    )
    return MissReportCreated(id=uuid.UUID(str(task_id)))
