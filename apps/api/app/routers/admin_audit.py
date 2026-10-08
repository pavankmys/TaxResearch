"""Admin endpoint for querying the audit log."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.db import get_session
from app.models import AuditLog

router = APIRouter(prefix="/v1/admin/audit", tags=["admin"])

NO_STORE = "private, no-store"


class AuditItem(BaseModel):
    """One audit row as returned by the admin API."""

    id: uuid.UUID
    seq: int
    ts: datetime
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    action: str
    object_type: str | None
    object_id: str | None
    ip: str | None
    request_id: str | None
    detail: dict[str, Any]


class AuditList(BaseModel):
    """One page of audit rows, newest first."""

    items: list[AuditItem]
    next_cursor: int | None


@router.get("", response_model=AuditList)
async def query_audit(
    request: Request,
    response: Response,
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: int | None = Query(default=None, ge=1),
    actor: CurrentUser = Depends(require_permission("audit.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AuditList:
    """Query audit rows, newest first. Pass next_cursor back as ``cursor`` for older rows."""
    response.headers["Cache-Control"] = NO_STORE

    filters: dict[str, str] = {"limit": str(limit)}
    if action is not None:
        filters["action"] = action
    if actor_user_id is not None:
        filters["actor_user_id"] = str(actor_user_id)
    if object_type is not None:
        filters["object_type"] = object_type
    if object_id is not None:
        filters["object_id"] = object_id
    if from_ts is not None:
        filters["from_ts"] = from_ts.isoformat()
    if to_ts is not None:
        filters["to_ts"] = to_ts.isoformat()
    if cursor is not None:
        filters["cursor"] = str(cursor)
    await write_audit(
        session,
        action="audit.query",
        actor=actor,
        detail=filters,
        ctx=audit_context_from_request(request),
    )

    stmt = select(AuditLog)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if object_type is not None:
        stmt = stmt.where(AuditLog.object_type == object_type)
    if object_id is not None:
        stmt = stmt.where(AuditLog.object_id == object_id)
    if from_ts is not None:
        stmt = stmt.where(AuditLog.ts >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(AuditLog.ts <= to_ts)
    if cursor is not None:
        stmt = stmt.where(AuditLog.seq < cursor)
    stmt = stmt.order_by(AuditLog.seq.desc()).limit(limit + 1)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        AuditItem(
            id=row.id,
            seq=row.seq,
            ts=row.ts,
            actor_user_id=row.actor_user_id,
            actor_role=row.actor_role,
            action=row.action,
            object_type=row.object_type,
            object_id=row.object_id,
            ip=None if row.ip is None else str(row.ip),
            request_id=row.request_id,
            detail=row.detail,
        )
        for row in page
    ]
    next_cursor = page[-1].seq if has_more and page else None
    return AuditList(items=items, next_cursor=next_cursor)
