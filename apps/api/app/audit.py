"""Hash-chained, append-only audit log.

Each row stores ``row_hash = sha256(prev_hash + canonical_payload)``. The payload covers
every recorded field except ``seq`` and ``row_hash``. Rows are written in the caller's
transaction, under a transaction-scoped advisory lock so the chain stays ordered.
"""

import hashlib
import ipaddress
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.ids import uuid7
from app.models import AuditLog

GENESIS_HASH = "0" * 64

_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext('audit_log'))")


@dataclass
class AuditContext:
    """Request details recorded with each audit row."""

    ip: str | None
    user_agent: str | None
    request_id: str | None


def audit_context_from_request(request: Request) -> AuditContext:
    """Build the audit context from a request."""
    client = request.client
    return AuditContext(
        ip=client.host if client is not None else None,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


def _normalise_ip(ip: str | None) -> str | None:
    """Return the canonical text form of an IP address, or None if it is not one.

    Postgres INET output is canonical, so hashing the canonical form keeps the
    verifier's recomputed hash equal to the one written.
    """
    if ip is None:
        return None
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def _check_detail(value: Any, path: str = "detail") -> None:  # noqa: ANN401
    """Allow only JSON types that round-trip through JSONB without changing the hash."""
    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError(f"{path} contains a NUL character")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_detail(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} has a non-string key")
            _check_detail(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} has unsupported type {type(value).__name__}")


def canonical_payload(
    *,
    id: UUID,  # noqa: A002
    ts: datetime,
    tenant_id: UUID | None,
    actor_user_id: UUID | None,
    actor_role: str | None,
    action: str,
    object_type: str | None,
    object_id: str | None,
    ip: str | None,
    user_agent: str | None,
    request_id: str | None,
    detail: dict[str, Any],
) -> str:
    """Serialise the hashed fields deterministically (sorted keys, no extra whitespace)."""
    _check_detail(detail)
    fields: dict[str, Any] = {
        "id": str(id),
        "ts": ts.astimezone(UTC).isoformat(),
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
        "actor_role": actor_role,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "ip": _normalise_ip(ip),
        "user_agent": user_agent,
        "request_id": request_id,
        "detail": detail,
    }
    return json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def compute_row_hash(prev_hash: str, payload: str) -> str:
    """Return the chain hash for a row: sha256(prev_hash + payload), hex."""
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


async def write_audit(
    session: AsyncSession,
    *,
    action: str,
    actor: CurrentUser | None = None,
    actor_user_id: UUID | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ctx: AuditContext | None = None,
) -> AuditLog:
    """Append one audit row in the caller's transaction. Does not commit."""
    await session.execute(_LOCK_SQL)
    last_hash = await session.execute(
        select(AuditLog.row_hash).order_by(AuditLog.seq.desc()).limit(1)
    )
    prev_hash = last_hash.scalar_one_or_none() or GENESIS_HASH

    if actor is not None:
        actor_id: UUID | None = actor.id
        actor_role = ",".join(sorted(actor.roles)) or None
        tenant_id = actor.tenant_id
    else:
        actor_id = actor_user_id
        actor_role = None
        tenant_id = None

    row_id = uuid7()
    ts = datetime.now(UTC)
    ip = _normalise_ip(ctx.ip) if ctx is not None else None
    user_agent = ctx.user_agent if ctx is not None else None
    request_id = ctx.request_id if ctx is not None else None
    payload_detail = detail if detail is not None else {}

    payload = canonical_payload(
        id=row_id,
        ts=ts,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        actor_role=actor_role,
        action=action,
        object_type=object_type,
        object_id=object_id,
        ip=ip,
        user_agent=user_agent,
        request_id=request_id,
        detail=payload_detail,
    )
    row = AuditLog(
        id=row_id,
        ts=ts,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        actor_role=actor_role,
        action=action,
        object_type=object_type,
        object_id=object_id,
        ip=ip,
        user_agent=user_agent,
        request_id=request_id,
        detail=payload_detail,
        prev_hash=prev_hash,
        row_hash=compute_row_hash(prev_hash, payload),
    )
    session.add(row)
    await session.flush()
    return row


async def verify_chain_with_count(session: AsyncSession) -> tuple[int | None, int]:
    """Walk the chain in seq order. Returns (seq of first bad row or None, rows checked)."""
    prev_hash = GENESIS_HASH
    count = 0
    stream = await session.stream_scalars(select(AuditLog).order_by(AuditLog.seq))
    async for row in stream:
        count += 1
        if row.prev_hash != prev_hash:
            return row.seq, count
        payload = canonical_payload(
            id=row.id,
            ts=row.ts,
            tenant_id=row.tenant_id,
            actor_user_id=row.actor_user_id,
            actor_role=row.actor_role,
            action=row.action,
            object_type=row.object_type,
            object_id=row.object_id,
            ip=None if row.ip is None else str(row.ip),
            user_agent=row.user_agent,
            request_id=row.request_id,
            detail=row.detail,
        )
        if compute_row_hash(prev_hash, payload) != row.row_hash:
            return row.seq, count
        prev_hash = row.row_hash
    return None, count


async def verify_chain(session: AsyncSession) -> int | None:
    """Return the seq of the first row that fails the chain check, or None if intact."""
    bad_seq, _ = await verify_chain_with_count(session)
    return bad_seq
