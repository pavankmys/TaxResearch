"""Platform source endpoints: the source list and the enable flag and cadence per source.

config/sources.yaml is the source of truth for a source's code, kind and allowed hosts. The
sources table holds what changes at run time: enabled, expected cadence and the last success
and new-document times. The list merges the two; a PATCH upserts the table row.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_context_from_request, write_audit
from app.auth.deps import CurrentUser, require_permission
from app.db import get_session
from app.ingest_config import load_source_entries

router = APIRouter(prefix="/v1/platform/sources", tags=["sources"])

NO_STORE = "private, no-store"

ROWS_SQL = text(
    """
    SELECT code, kind, enabled, expected_cadence_hours, last_success_at, last_new_doc_at, health
    FROM sources
    """
)
ONE_ROW_SQL = text(
    """
    SELECT code, kind, enabled, expected_cadence_hours, last_success_at, last_new_doc_at, health
    FROM sources
    WHERE code = :code
    """
)
UPSERT_SQL = text(
    """
    INSERT INTO sources (code, kind, enabled, expected_cadence_hours, updated_by, updated_at)
    VALUES (
        :code,
        :kind,
        COALESCE(CAST(:enabled AS boolean), CAST(:config_enabled AS boolean)),
        CAST(:cadence AS integer),
        :actor,
        now()
    )
    ON CONFLICT (code) DO UPDATE SET
        enabled = COALESCE(CAST(:enabled AS boolean), sources.enabled),
        expected_cadence_hours = COALESCE(
            CAST(:cadence AS integer), sources.expected_cadence_hours
        ),
        updated_by = :actor,
        updated_at = now()
    RETURNING code, kind, enabled, expected_cadence_hours, last_success_at, last_new_doc_at,
              health
    """
)


class SourceOut(BaseModel):
    """A source: config fields merged with the run-time row when there is one."""

    code: str
    kind: str
    description: str | None
    release: str | None
    allowed_hosts: list[str]
    in_config: bool
    config_enabled: bool | None
    enabled: bool
    expected_cadence_hours: int | None
    last_success_at: datetime | None
    last_new_doc_at: datetime | None
    health: str | None


class SourceList(BaseModel):
    """Every source in config, then any row in the table that config does not name."""

    items: list[SourceOut]


class SourceUpdate(BaseModel):
    """Body of PATCH /{code}. At least one field must be set."""

    enabled: bool | None = None
    expected_cadence_hours: int | None = Field(default=None, ge=1, le=8760)


def _allowed_hosts(entry: dict[str, Any]) -> list[str]:
    return sorted(str(host).strip().lower() for host in (entry.get("allowed_hosts") or []))


def _merge(entry: dict[str, Any] | None, row: dict[str, Any] | None, code: str) -> SourceOut:
    """Combine a config entry and a table row. Table values win for run-time fields."""
    config_enabled = bool(entry["enabled"]) if entry is not None else None
    if row is not None:
        enabled = bool(row["enabled"])
        cadence = row["expected_cadence_hours"]
    else:
        enabled = bool(config_enabled) if config_enabled is not None else False
        cadence = entry.get("expected_cadence_hours") if entry is not None else None
    description = entry.get("description") if entry is not None else None
    release = entry.get("release") if entry is not None else None
    if entry is not None:
        kind = str(entry["kind"])
    else:
        kind = str(row["kind"]) if row is not None else "manual"
    return SourceOut(
        code=code,
        kind=kind,
        description=str(description) if description is not None else None,
        release=str(release) if release is not None else None,
        allowed_hosts=_allowed_hosts(entry) if entry is not None else [],
        in_config=entry is not None,
        config_enabled=config_enabled,
        enabled=enabled,
        expected_cadence_hours=int(cadence) if cadence is not None else None,
        last_success_at=row["last_success_at"] if row else None,
        last_new_doc_at=row["last_new_doc_at"] if row else None,
        health=row["health"] if row else None,
    )


def _config_by_code() -> dict[str, dict[str, Any]]:
    return {str(entry["code"]): entry for entry in load_source_entries()}


@router.get("", response_model=SourceList)
async def list_sources(
    response: Response,
    actor: CurrentUser = Depends(require_permission("sources.read")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SourceList:
    """Every configured source with its enable flag, cadence and last success."""
    response.headers["Cache-Control"] = NO_STORE
    config = _config_by_code()
    rows = {str(row["code"]): dict(row) for row in (await session.execute(ROWS_SQL)).mappings()}
    items = [_merge(entry, rows.get(code), code) for code, entry in config.items()]
    items += [_merge(None, row, code) for code, row in sorted(rows.items()) if code not in config]
    return SourceList(items=items)


@router.patch("/{code}", response_model=SourceOut)
async def update_source(
    code: str,
    body: SourceUpdate,
    request: Request,
    response: Response,
    actor: CurrentUser = Depends(require_permission("sources.manage")),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SourceOut:
    """Enable or disable a source, and set its expected cadence. Audited as source.update."""
    response.headers["Cache-Control"] = NO_STORE
    if body.enabled is None and body.expected_cadence_hours is None:
        raise HTTPException(status_code=422, detail="Nothing to change")
    entry = _config_by_code().get(code)
    if entry is None:
        raise HTTPException(status_code=404, detail="Source not found in config")

    previous_row = (await session.execute(ONE_ROW_SQL, {"code": code})).mappings().first()
    previous = dict(previous_row) if previous_row is not None else None
    row = (
        (
            await session.execute(
                UPSERT_SQL,
                {
                    "code": code,
                    "kind": str(entry["kind"]),
                    "enabled": body.enabled,
                    "config_enabled": bool(entry["enabled"]),
                    "cadence": body.expected_cadence_hours,
                    "actor": actor.id,
                },
            )
        )
        .mappings()
        .one()
    )
    await write_audit(
        session,
        action="source.update",
        actor=actor,
        object_type="source",
        object_id=code,
        detail={
            "enabled": {
                "before": bool(previous["enabled"]) if previous else None,
                "after": bool(row["enabled"]),
            },
            "expected_cadence_hours": {
                "before": previous["expected_cadence_hours"] if previous else None,
                "after": row["expected_cadence_hours"],
            },
        },
        ctx=audit_context_from_request(request),
    )
    return _merge(entry, dict(row), code)
