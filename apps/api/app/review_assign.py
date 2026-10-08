"""Round-robin assignment of new review tasks to active platform content editors (TSD 5.8).

The rule: order the active platform_content_editor users by id, and give the new task to the
first editor whose id is greater than the assignee of the most recent task that has one. When
there is none greater, wrap to the first editor. With no editors the task stays unassigned.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EDITOR_IDS_SQL = text(
    """
    SELECT DISTINCT u.id
    FROM users u
    JOIN user_roles ur ON ur.user_id = u.id
    JOIN roles r ON r.id = ur.role_id
    WHERE r.code = 'platform_content_editor' AND u.status = 'active'
    ORDER BY u.id
    """
)
LAST_ASSIGNEE_SQL = text(
    """
    SELECT assignee_id
    FROM review_tasks
    WHERE assignee_id IS NOT NULL
    ORDER BY created_at DESC, id DESC
    LIMIT 1
    """
)


async def next_assignee(session: AsyncSession) -> uuid.UUID | None:
    """Return the editor who should get the next task, or None if there are no editors."""
    editors = list((await session.execute(EDITOR_IDS_SQL)).scalars().all())
    if not editors:
        return None
    last = (await session.execute(LAST_ASSIGNEE_SQL)).scalar_one_or_none()
    if last is None:
        return uuid.UUID(str(editors[0]))
    for editor in editors:
        if str(editor) > str(last):
            return uuid.UUID(str(editor))
    return uuid.UUID(str(editors[0]))
