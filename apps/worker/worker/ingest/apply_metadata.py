"""Apply-metadata job: the one write path for document metadata (M3a plan).

Payload: ``{document_id, fields, actor_user_id, reason, review_task_id, metadata?}``.

- ``fields`` are the values to apply now. They come from extraction, from a review edit
  (edit_approve) or from PATCH /v1/platform/documents/{id}.
- ``metadata`` is the full proposal JSON. Extraction sends it. Fields from it are merged into
  documents.metadata first; ``fields`` override them.
- With ``actor_user_id``, every applied field is recorded in metadata.overrides with the value,
  the actor, the time and the reason. The audit row is written by the API, not here.
- ``documents`` and the typed table (notifications, circulars, judgements) are written in one
  transaction. meta_confidence is recomputed only when reason is "extracted".
- A canonical_id that another document already holds is not applied. A metadata task names
  that document instead.
- Publish is queued last, so the document becomes searchable and gets its review_state.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection, Engine

from worker import db, review
from worker.errors import PermanentError
from worker.ingest.metadata import required_confidence
from worker.ingest.queues import AMEND_DETECT_QUEUE, PUBLISH_QUEUE
from worker.objectstore import ObjectStore
from worker.queue import Job

logger = logging.getLogger(__name__)

_DOCUMENT_COLUMNS = (
    "title",
    "number",
    "series",
    "doc_date",
    "in_force_date",
    "issuing_authority",
    "court",
    "bench",
)


def _as_date(value: Any) -> date | None:  # noqa: ANN401 - JSON value
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _document_values(fields: Mapping[str, Any], doc_type: str) -> dict[str, Any]:
    """Document columns from the merged fields. Judgements keep the court code and decision date."""
    values: dict[str, Any] = {}
    for column in _DOCUMENT_COLUMNS:
        if column in fields and fields[column] not in (None, ""):
            values[column] = fields[column]
    if doc_type == "judgement":
        values["court"] = fields.get("court_code")
        values["number"] = None
        values["series"] = None
    decided = fields.get("doc_date") or fields.get("decision_date")
    if decided not in (None, ""):
        values["doc_date"] = _as_date(decided)
    if "in_force_date" in values:
        values["in_force_date"] = _as_date(values["in_force_date"])
    return values


def _typed_row(doc_type: str, fields: Mapping[str, Any]) -> tuple[Any, dict[str, Any]] | None:
    """The typed table and the row for this document, or None when required values are missing."""
    if doc_type == "notification":
        if not (fields.get("series") and fields.get("number") and fields.get("year")):
            return None
        return db.notifications, {
            "series": fields["series"],
            "number": str(fields["number"]),
            "year": int(fields["year"]),
            "issue_date": _as_date(fields.get("doc_date")),
            "effective_date": _as_date(fields.get("effective_date")),
            "gazette_ref": fields.get("gazette_ref"),
        }
    if doc_type in {"circular", "instruction", "order"}:
        if not fields.get("number"):
            return None
        return db.circulars, {
            "kind": fields.get("circular_kind") or doc_type,
            "number": str(fields["number"]),
            "issue_date": _as_date(fields.get("doc_date")),
            "subject": fields.get("subject"),
            "din": fields.get("din"),
        }
    if doc_type == "judgement":
        if not (fields.get("court_level") and fields.get("court_name")):
            return None
        parties = fields.get("parties") or {}
        return db.judgements, {
            "court_level": fields["court_level"],
            "court_name": fields["court_name"],
            "bench": fields.get("bench"),
            "judges": list(fields.get("judges") or []),
            "decision_date": _as_date(fields.get("decision_date")),
            "parties": {
                "petitioners": list(parties.get("petitioners", [])),
                "respondents": list(parties.get("respondents", [])),
            },
            "reporter_citations": list(fields.get("reporter_citations") or []),
            "case_numbers": list(fields.get("case_numbers") or []),
        }
    return None


def _upsert_typed(
    conn: Connection, document_id: UUID, doc_type: str, fields: Mapping[str, Any]
) -> None:
    built = _typed_row(doc_type, fields)
    if built is None:
        return
    table, row = built
    now = datetime.now(UTC)
    values = {"document_id": document_id, **row, "updated_at": now}
    stmt = postgresql.insert(table).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.document_id],
        set_={key: stmt.excluded[key] for key in values if key != "document_id"},
    )
    conn.execute(stmt)


def _open_collision_task(conn: Connection, document_id: UUID, other: UUID, canonical: str) -> None:
    review.open_review_task(
        conn,
        "metadata",
        "document",
        document_id,
        {
            "reason": "canonical_collision",
            "canonical_id": canonical,
            "near_duplicate_of": str(other),
        },
    )


def apply_metadata(conn: Connection, payload: Mapping[str, Any]) -> UUID:
    """Apply one payload in the caller's transaction. Returns the document id.

    Raises:
        PermanentError: the payload is malformed or the document does not exist.
    """
    try:
        document_id = UUID(str(payload["document_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise PermanentError("apply_metadata needs a document_id") from exc
    fields: dict[str, Any] = dict(payload.get("fields") or {})
    actor = payload.get("actor_user_id")
    reason = str(payload.get("reason") or "edit")
    proposal: dict[str, Any] | None = payload.get("metadata")

    doc = conn.execute(
        sa.select(
            db.documents.c.doc_type,
            db.documents.c.canonical_id,
            db.documents.c.metadata,
            db.documents.c.current_version_id,
        ).where(db.documents.c.id == document_id)
    ).first()
    if doc is None:
        raise PermanentError(f"document not found: {document_id}")
    doc_type = str(doc[0])
    current_canonical = str(doc[1])
    old: dict[str, Any] = dict(doc[2] or {})
    current_version_id = doc[3]

    merged_fields: dict[str, Any] = dict(old.get("fields", {}))
    merged_conf: dict[str, float] = dict(old.get("confidence", {}))
    issues: list[str] = list(old.get("issues", []))
    extractor_version = old.get("extractor_version")
    if proposal is not None:
        merged_fields.update(proposal.get("fields", {}))
        merged_conf.update(proposal.get("confidence", {}))
        issues = list(proposal.get("issues", []))
        extractor_version = proposal.get("extractor_version", extractor_version)
    merged_fields.update(fields)

    overrides: dict[str, Any] = dict(old.get("overrides", {}))
    if actor is not None:
        at = datetime.now(UTC).isoformat()
        for name, value in fields.items():
            overrides[name] = {"value": value, "by": str(actor), "at": at, "reason": reason}

    values = _document_values(merged_fields, doc_type)
    new_canonical = fields.get("canonical_id")
    if new_canonical and new_canonical != current_canonical:
        other = db.find_document_by_canonical(conn, str(new_canonical))
        if other is not None and other != document_id:
            _open_collision_task(conn, document_id, other, str(new_canonical))
            logger.info(f"Document {document_id}: canonical {new_canonical} held by {other}")
        else:
            values["canonical_id"] = str(new_canonical)

    values["metadata"] = {
        "fields": merged_fields,
        "confidence": merged_conf,
        "issues": issues,
        "extractor_version": extractor_version,
        "overrides": overrides,
    }
    if reason == "extracted":
        values["meta_confidence"] = round(
            required_confidence(doc_type, merged_fields, merged_conf), 4
        )
    values["updated_at"] = datetime.now(UTC)
    conn.execute(db.documents.update().where(db.documents.c.id == document_id).values(**values))

    _upsert_typed(conn, document_id, doc_type, merged_fields)

    db.enqueue(
        conn,
        PUBLISH_QUEUE,
        {"document_id": str(document_id)},
        idempotency_key=f"{document_id}:publish:{uuid4()}",
    )

    # Enqueue amendment detection for notifications and orders
    if doc_type in ("notification", "order") and current_version_id is not None:
        db.enqueue(
            conn,
            AMEND_DETECT_QUEUE,
            {"document_id": str(document_id)},
            idempotency_key=f"{document_id}:amend_detect:{current_version_id}",
        )

    logger.info(f"Document {document_id}: metadata applied ({reason})")
    return document_id


def make_apply_metadata_handler(engine: Engine, store: ObjectStore) -> Callable[[Job], None]:
    """Build the handler for queue ``ingest.apply_metadata``. The store is unused."""

    def handle(job: Job) -> None:
        with engine.begin() as conn:
            apply_metadata(conn, job.payload)

    return handle
