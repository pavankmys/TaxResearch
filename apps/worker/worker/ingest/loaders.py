"""Loader requests shared by the CLI, the watch folder and the API.

A loader validates a request, creates the ingestion job and enqueues the acquire stage in
one transaction. Canonical IDs are computed by the acquire handler from the raw metadata in
the payload, so every loader takes the same code path.
"""

import re
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

from legal_core import load_aliases, normalise_series
from legal_core.ids import circular_id, instruction_id, judgement_id, notification_id, order_id
from sqlalchemy.engine import Connection

from worker import db
from worker.config import SourceConfig, config_dir, load_doc_type_ranks, load_sources

ACQUIRE_QUEUE = "ingest.acquire"
PARSE_QUEUE = "ingest.parse"

# Prefix added by the watch folder when it moves a file into .done/ (see watch.py)
_WATCH_PREFIX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}__")


class LoadError(ValueError):
    """A loader request is invalid. Nothing was written."""


@dataclass(frozen=True)
class LoadRequest:
    """What a person asks for: one document, by file or URL, with optional metadata."""

    source_code: str
    doc_type: str
    url: str | None = None
    file_path: str | None = None
    title: str | None = None
    series: str | None = None
    number: str | None = None
    year: str | None = None
    circular_a: str | None = None
    circular_b: str | None = None
    case_number: str | None = None
    court_code: str | None = None
    decision_date: str | None = None
    object_key: str | None = None  # upload: the object store key of the bytes (API upload)
    file_name: str | None = None  # upload: the name the user gave the file


_PAYLOAD_FIELDS = tuple(f.name for f in fields(LoadRequest))


def request_to_payload(req: LoadRequest, job_id: UUID) -> dict[str, Any]:
    """The job_queue payload for the acquire stage: the raw request plus the job id."""
    payload: dict[str, Any] = {"ingestion_job_id": str(job_id)}
    for name in _PAYLOAD_FIELDS:
        payload[name] = getattr(req, name)
    return payload


def request_from_payload(payload: dict[str, Any]) -> LoadRequest:
    """Rebuild a LoadRequest from an acquire payload. Unknown keys are ignored."""
    values: dict[str, Any] = {name: payload.get(name) for name in _PAYLOAD_FIELDS}
    return LoadRequest(**values)


@lru_cache(maxsize=1)
def _aliases() -> Any:  # noqa: ANN401 - legal_core.Aliases
    return load_aliases(config_dir() / "citation_aliases.yaml")


def validate_request(req: LoadRequest) -> SourceConfig:
    """Check the source, doc_type and the url/file choice. Returns the source config."""
    source = load_sources().get(req.source_code)
    if source is None:
        raise LoadError(f"unknown source: {req.source_code}")
    if not source.enabled:
        raise LoadError(f"source is disabled: {req.source_code}")
    if req.doc_type not in load_doc_type_ranks():
        allowed = ", ".join(sorted(load_doc_type_ranks()))
        raise LoadError(f"unknown doc_type: {req.doc_type} (one of: {allowed})")
    if sum(bool(value) for value in (req.url, req.file_path, req.object_key)) != 1:
        raise LoadError("give exactly one of a URL, a file path or an uploaded object")
    return source


def canonical_id_for(req: LoadRequest) -> str | None:
    """Build the canonical ID from the metadata, or return None when metadata is incomplete.

    Raises:
        ValueError: the metadata is present but invalid (for example an unknown series).
    """
    if req.doc_type == "notification":
        if req.series and req.number and req.year:
            series = normalise_series(req.series, _aliases())
            if series is None:
                raise ValueError(f"unknown notification series: {req.series}")
            return notification_id(series, req.number, req.year)
    elif req.doc_type == "circular":
        if req.circular_a and req.circular_b and req.year:
            return circular_id(req.circular_a, req.circular_b, req.year)
    elif req.doc_type == "instruction":
        if req.number and req.year:
            return instruction_id(req.number, req.year)
    elif req.doc_type == "order":
        if req.number and req.year:
            return order_id(req.number, req.year)
    elif req.doc_type == "judgement":
        if req.court_code and req.case_number and req.decision_date:
            return judgement_id(req.court_code, req.case_number, req.decision_date)
    return None


def default_title(req: LoadRequest) -> str:
    """The title used when the request has none: the file name or the last URL segment."""
    if req.title:
        return req.title
    if req.file_name:
        return Path(req.file_name).name or "Untitled"
    if req.file_path:
        name = Path(req.file_path).name
        return _WATCH_PREFIX.sub("", name) or "Untitled"
    if req.url:
        segment = unquote(urlsplit(req.url).path.rstrip("/").rsplit("/", 1)[-1])
        return segment or "Untitled"
    return "Untitled"


def submit(conn: Connection, req: LoadRequest) -> UUID:
    """Create the ingestion job and enqueue the acquire stage, in the caller's transaction.

    Returns:
        The ingestion job id.

    Raises:
        LoadError: the request is invalid. Nothing was written.
    """
    source = validate_request(req)
    try:
        canonical_id_for(req)
    except ValueError as exc:
        raise LoadError(str(exc)) from exc

    source_id = db.ensure_source(conn, source.code, source.kind)
    url = req.url if req.url else f"file://{Path(str(req.file_path)).resolve()}"
    job_id = db.create_ingestion_job(conn, source_id=source_id, url=url)
    db.enqueue(conn, ACQUIRE_QUEUE, request_to_payload(req, job_id), idempotency_key=str(job_id))
    return job_id
