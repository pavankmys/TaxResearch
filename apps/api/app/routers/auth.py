"""Login, logout and the current-user endpoint."""

from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditContext, audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, get_current_user
from app.auth.passwords import DUMMY_HASH, hash_password, needs_rehash, verify_password
from app.auth.ratelimit import LoginKey, LoginRateLimiter, get_login_rate_limiter
from app.auth.tokens import issue_token
from app.db import get_session
from app.models import User
from app.settings import Settings, get_settings

router = APIRouter(prefix="/v1", tags=["auth"])

NO_STORE = "private, no-store"
INVALID_CREDENTIALS = "Invalid email or password"


class LoginRequest(BaseModel):
    """Email and password to exchange for a token."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    """A bearer token and its lifetime in seconds."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    """The authenticated caller."""

    id: UUID
    email: str
    display_name: str
    tenant_id: UUID | None
    roles: list[str]


async def _reject_login(
    session: AsyncSession,
    limiter: LoginRateLimiter,
    key: LoginKey,
    ctx: AuditContext,
    *,
    email: str,
    reason: str,
    actor_user_id: UUID | None = None,
) -> NoReturn:
    """Record a failed login, commit the audit row, and return the generic 401."""
    limiter.record_failure(key)
    await write_audit(
        session,
        action="auth.login_failed",
        actor_user_id=actor_user_id,
        detail={"email": email, "reason": reason},
        ctx=ctx,
    )
    await session.commit()
    raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: LoginRateLimiter = Depends(get_login_rate_limiter),  # noqa: B008
) -> TokenResponse:
    """Exchange email and password for a bearer token."""
    ctx = audit_context_from_request(request)
    key: LoginKey = (body.email.lower(), ctx.ip)

    if limiter.is_blocked(key):
        await write_audit(
            session,
            action="auth.login_blocked",
            detail={"email": body.email},
            ctx=ctx,
        )
        await session.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again later.",
        )

    result = await session.execute(select(User).where(func.lower(User.email) == body.email.lower()))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        # Spend the same time as a real check so unknown emails are not distinguishable.
        verify_password(DUMMY_HASH, body.password)
        await _reject_login(session, limiter, key, ctx, email=body.email, reason="unknown_user")

    if not verify_password(user.password_hash, body.password):
        await _reject_login(
            session,
            limiter,
            key,
            ctx,
            email=body.email,
            reason="bad_password",
            actor_user_id=user.id,
        )

    if user.status != "active":
        await _reject_login(
            session,
            limiter,
            key,
            ctx,
            email=body.email,
            reason="disabled",
            actor_user_id=user.id,
        )

    limiter.reset(key)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    now = datetime.now(UTC)
    user.last_login_at = now

    await write_audit(
        session,
        action="auth.login_success",
        actor_user_id=user.id,
        object_type="user",
        object_id=str(user.id),
        ctx=ctx,
    )

    token, expires_in = issue_token(user.id, settings)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    user: CurrentUser = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Response:
    """Record the logout. Tokens are stateless, so the client discards its token."""
    await write_audit(
        session,
        action="auth.logout",
        actor=user,
        object_type="user",
        object_id=str(user.id),
        ctx=audit_context_from_request(request),
    )
    return Response(status_code=204)


@router.get("/me", response_model=MeResponse)
async def me(
    response: Response,
    user: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> MeResponse:
    """Return the authenticated caller with roles loaded from the database."""
    response.headers["Cache-Control"] = NO_STORE
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tenant_id=user.tenant_id,
        roles=sorted(user.roles),
    )
