"""FastAPI dependencies for authentication and authorisation."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import has_permission
from app.auth.tokens import InvalidTokenError, decode_token
from app.db import get_session
from app.models import Role, User, UserRole
from app.settings import Settings, get_settings


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller, with roles loaded from the database for this request."""

    id: UUID
    email: str
    display_name: str
    tenant_id: UUID | None
    roles: frozenset[str]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("Not authenticated")
    return token


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> CurrentUser:
    """Authenticate the bearer token and load the user and roles from the database."""
    token = _bearer_token(request)
    try:
        user_id = decode_token(token, settings)
    except InvalidTokenError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.status != "active":
        raise _unauthorized("Invalid or expired token")

    roles_result = await session.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    roles = frozenset(roles_result.scalars().all())

    return CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tenant_id=user.tenant_id,
        roles=roles,
    )


def require_permission(action: str) -> Callable[..., Awaitable[CurrentUser]]:
    """Build a dependency that returns the caller only if their roles grant ``action``."""

    async def _check(
        user: CurrentUser = Depends(get_current_user),  # noqa: B008
    ) -> CurrentUser:
        if not has_permission(user.roles, action):
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return _check
