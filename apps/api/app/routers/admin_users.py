"""Admin endpoints for listing, creating and updating users."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditContext, audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.auth.passwords import hash_password
from app.db import get_session
from app.ids import uuid7
from app.models import Role, User, UserRole

router = APIRouter(prefix="/v1/admin/users", tags=["admin"])

NO_STORE = "private, no-store"
SELF_LOCKOUT_DETAIL = "You cannot disable yourself or remove your own admin role"


class AccountError(Exception):
    """A user-management rule was violated. Routers map it to an HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class UserItem(BaseModel):
    """A user as returned by the admin API."""

    id: uuid.UUID
    email: str
    display_name: str
    status: str
    roles: list[str]
    last_login_at: datetime | None
    created_at: datetime


class UserList(BaseModel):
    """One page of users, newest id last."""

    items: list[UserItem]
    next_cursor: str | None
    total: int


class UserCreate(BaseModel):
    """Body for creating a user."""

    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=1024)
    roles: list[str] = Field(min_length=1)


class UserUpdate(BaseModel):
    """Body for updating a user. Omitted fields are left unchanged."""

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "disabled"] | None = None
    roles: list[str] | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=12, max_length=1024)


async def load_roles(session: AsyncSession, codes: set[str]) -> dict[str, Role]:
    """Return the Role rows for the codes. Raises AccountError(422) on an unknown code."""
    result = await session.execute(select(Role).where(Role.code.in_(codes)))
    roles = {role.code: role for role in result.scalars().all()}
    unknown = sorted(codes - roles.keys())
    if unknown:
        raise AccountError(422, f"Unknown role: {unknown[0]}")
    return roles


async def _role_codes(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    result = await session.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return sorted(result.scalars().all())


async def _roles_for_users(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    if not user_ids:
        return {}
    result = await session.execute(
        select(UserRole.user_id, Role.code)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(user_ids))
    )
    by_user: dict[uuid.UUID, list[str]] = {}
    for user_id, code in result.all():
        by_user.setdefault(user_id, []).append(code)
    return {user_id: sorted(codes) for user_id, codes in by_user.items()}


def _to_item(user: User, roles: list[str]) -> UserItem:
    return UserItem(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        roles=roles,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


async def create_user_with_roles(
    session: AsyncSession,
    *,
    email: str,
    display_name: str,
    password: str,
    role_codes: list[str],
    actor: CurrentUser | None,
    ctx: AuditContext | None,
    via: str | None = None,
) -> User:
    """Create an active user with roles and write ``user.create``. Does not commit."""
    codes = set(role_codes)
    roles = await load_roles(session, codes)

    existing = await session.execute(select(User.id).where(func.lower(User.email) == email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise AccountError(409, "A user with this email already exists")

    now = datetime.now(UTC)
    user = User(
        id=uuid7(),
        email=email,
        display_name=display_name,
        password_hash=hash_password(password),
        status="active",
        mfa_enabled=False,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.add_all(
        [
            UserRole(user_id=user.id, role_id=roles[code].id, created_at=now)
            for code in sorted(codes)
        ]
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        raise AccountError(409, "A user with this email already exists") from exc

    detail: dict[str, Any] = {"email": email, "roles": sorted(codes)}
    if via is not None:
        detail["via"] = via
    await write_audit(
        session,
        action="user.create",
        actor=actor,
        object_type="user",
        object_id=str(user.id),
        detail=detail,
        ctx=ctx,
    )
    return user


@router.get("", response_model=UserList)
async def list_users(
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: uuid.UUID | None = None,
    _actor: CurrentUser = Depends(require_permission("users.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> UserList:
    """List users ordered by id. Pass next_cursor back as ``cursor`` for the next page."""
    response.headers["Cache-Control"] = NO_STORE

    total_result = await session.execute(select(func.count()).select_from(User))
    total = total_result.scalar_one()

    stmt = select(User).order_by(User.id)
    if cursor is not None:
        stmt = stmt.where(User.id > cursor)
    rows_result = await session.execute(stmt.limit(limit + 1))
    rows = list(rows_result.scalars().all())

    has_more = len(rows) > limit
    page = rows[:limit]
    roles_by_user = await _roles_for_users(session, [user.id for user in page])
    items = [_to_item(user, roles_by_user.get(user.id, [])) for user in page]
    next_cursor = str(page[-1].id) if has_more and page else None
    return UserList(items=items, next_cursor=next_cursor, total=total)


@router.post("", status_code=201, response_model=UserItem)
async def create_user(
    body: UserCreate,
    request: Request,
    response: Response,
    actor: CurrentUser = Depends(require_permission("users.manage")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> UserItem:
    """Create a user with one or more roles."""
    response.headers["Cache-Control"] = NO_STORE
    try:
        user = await create_user_with_roles(
            session,
            email=body.email,
            display_name=body.display_name,
            password=body.password,
            role_codes=body.roles,
            actor=actor,
            ctx=audit_context_from_request(request),
        )
    except AccountError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return _to_item(user, sorted(set(body.roles)))


@router.patch("/{user_id}", response_model=UserItem)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    response: Response,
    actor: CurrentUser = Depends(require_permission("users.manage")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> UserItem:
    """Update a user's display name, status, roles or password."""
    response.headers["Cache-Control"] = NO_STORE
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == actor.id and (
        body.status == "disabled" or (body.roles is not None and "platform_admin" not in body.roles)
    ):
        raise HTTPException(status_code=409, detail=SELF_LOCKOUT_DETAIL)

    now = datetime.now(UTC)
    roles_before = await _role_codes(session, user.id)
    roles_after = roles_before
    changed: list[str] = []

    if body.display_name is not None and body.display_name != user.display_name:
        user.display_name = body.display_name
        changed.append("display_name")

    if body.status is not None and body.status != user.status:
        user.status = body.status
        changed.append("status")

    if body.roles is not None:
        try:
            roles_map = await load_roles(session, set(body.roles))
        except AccountError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        new_codes = sorted(set(body.roles))
        if new_codes != roles_before:
            await session.execute(delete(UserRole).where(UserRole.user_id == user.id))
            session.add_all(
                [
                    UserRole(user_id=user.id, role_id=roles_map[code].id, created_at=now)
                    for code in new_codes
                ]
            )
            roles_after = new_codes
            changed.append("roles")

    if body.password is not None:
        user.password_hash = hash_password(body.password)
        changed.append("password")

    user.updated_by = actor.id
    user.updated_at = now

    detail: dict[str, Any] = {"changed": changed}
    if "roles" in changed:
        detail["roles_before"] = roles_before
        detail["roles_after"] = roles_after
    await write_audit(
        session,
        action="user.update",
        actor=actor,
        object_type="user",
        object_id=str(user.id),
        detail=detail,
        ctx=audit_context_from_request(request),
    )
    return _to_item(user, roles_after)
