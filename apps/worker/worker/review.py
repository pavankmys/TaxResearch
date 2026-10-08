"""Review task opening with round-robin assignment (TSD 5.8).

Every task the worker opens goes through open_review_task. The assignee is the next active
platform_content_editor after the assignee of the most recent assigned task.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from worker import db

PRIORITY_BY_KIND: dict[str, int] = {
    "amendment": 1,
    "parse_failure": 2,
    "metadata": 3,
    "treatment": 3,
    "miss_report": 4,
}
DEFAULT_PRIORITY = 3


def priority_for(kind: str) -> int:
    """Priority of a review task kind (1 is most urgent)."""
    return PRIORITY_BY_KIND.get(kind, DEFAULT_PRIORITY)


def round_robin_next(candidates: Sequence[UUID], last: UUID | None) -> UUID | None:
    """The first candidate whose id sorts after ``last``, wrapping to the first.

    This is the rule of apps/api/app/review_assign.py: ids are compared as text. None when there
    are no candidates. With no last assignee the first candidate is returned.
    """
    if not candidates:
        return None
    if last is None:
        return candidates[0]
    for candidate in candidates:
        if str(candidate) > str(last):
            return candidate
    return candidates[0]


def _editor_ids(conn: Connection) -> list[UUID]:
    """Active platform_content_editor users, ordered by id."""
    rows = conn.execute(
        sa.select(db.users.c.id)
        .select_from(
            db.users.join(db.user_roles, db.user_roles.c.user_id == db.users.c.id).join(
                db.roles, db.roles.c.id == db.user_roles.c.role_id
            )
        )
        .where(db.roles.c.code == "platform_content_editor", db.users.c.status == "active")
        .order_by(db.users.c.id)
    ).all()
    return [UUID(str(row[0])) for row in rows]


def _last_assignee(conn: Connection) -> UUID | None:
    """The assignee of the most recently opened task that has one."""
    value: Any = conn.execute(
        sa.select(db.review_tasks.c.assignee_id)
        .where(db.review_tasks.c.assignee_id.is_not(None))
        .order_by(db.review_tasks.c.created_at.desc(), db.review_tasks.c.id.desc())
        .limit(1)
    ).scalar()
    return UUID(str(value)) if value is not None else None


def next_assignee(conn: Connection) -> UUID | None:
    """The user the next task goes to, or None when no content editor is active."""
    return round_robin_next(_editor_ids(conn), _last_assignee(conn))


def open_review_task(
    conn: Connection,
    kind: str,
    subject_type: str,
    subject_id: UUID | None,
    resolution: dict[str, Any] | None = None,
) -> UUID:
    """Open a review task with its priority and round-robin assignee, in the caller's
    transaction."""
    return db.open_review_task(
        conn,
        kind,
        subject_type,
        subject_id,
        resolution,
        priority=priority_for(kind),
        assignee_id=next_assignee(conn),
    )
