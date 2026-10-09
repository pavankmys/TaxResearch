"""Command-line loaders and job status.

Run inside the worker container, for example::

    python -m worker.cli ingest-url https://www.cbic-gst.gov.in/... \\
        --source cbic_gst_portal --doc-type notification --series CT --number 11 --year 2017
    python -m worker.cli ingest-file /watch/cbic_gst_portal/notification/file.pdf \\
        --source cbic_gst_portal --doc-type notification
    python -m worker.cli job-status <ingestion-job-id>
    python -m worker.cli sample-audit --percent 2 --days 7

Each command prints the ingestion job id (or the status) on stdout. Errors go to stderr.
"""

import argparse
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine

from worker import db, review
from worker.errors import PermanentError
from worker.ingest.build_provisions import build_provisions_for
from worker.ingest.detect_amendments import detect_amendments_for
from worker.ingest.loaders import LoadError, LoadRequest, submit
from worker.settings import get_settings


def _add_metadata_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", required=True, help="source code from config/sources.yaml")
    parser.add_argument("--doc-type", required=True, help="doc_type from config/authority.yaml")
    parser.add_argument("--title", help="document title (default: file name or URL segment)")
    parser.add_argument("--series", help="notification series, e.g. CT or 'CT(R)'")
    parser.add_argument("--number", help="notification, instruction or order number")
    parser.add_argument("--year", help="four-digit year")
    parser.add_argument("--circular-a", help="first circular number")
    parser.add_argument("--circular-b", help="second circular number")
    parser.add_argument("--case-number", help="judgement case number")
    parser.add_argument("--court-code", help="judgement court code, e.g. SC")
    parser.add_argument("--decision-date", help="judgement decision date, YYYY-MM-DD")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(prog="python -m worker.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    file_cmd = commands.add_parser("ingest-file", help="load a PDF or HTML file from disk")
    file_cmd.add_argument("path", help="path readable by the worker")
    _add_metadata_options(file_cmd)

    url_cmd = commands.add_parser("ingest-url", help="fetch a PDF or HTML page by URL")
    url_cmd.add_argument("url", help="http or https URL on an allowed host")
    _add_metadata_options(url_cmd)

    status_cmd = commands.add_parser("job-status", help="show one ingestion job")
    status_cmd.add_argument("job_id", help="ingestion job id")

    audit_cmd = commands.add_parser(
        "sample-audit",
        help="open spot-check metadata tasks for a sample of auto-published documents",
    )
    audit_cmd.add_argument("--percent", type=float, default=2.0, help="share to sample (0-100)")
    audit_cmd.add_argument("--days", type=int, default=7, help="look back this many days")

    build_prov_cmd = commands.add_parser(
        "build-provisions",
        help="build provisions from a document's blocks",
    )
    build_prov_cmd.add_argument("--document-id", required=True, help="document UUID")
    build_prov_cmd.add_argument(
        "--instrument", required=True, help="instrument code (e.g., CGST_ACT)"
    )
    build_prov_cmd.add_argument("--as-on", required=True, help="as-on date (YYYY-MM-DD)")

    detect_amend_cmd = commands.add_parser(
        "detect-amendments",
        help="detect amendments from a document's blocks",
    )
    detect_amend_cmd.add_argument("--document-id", required=True, help="document UUID")
    detect_amend_cmd.add_argument("--force", action="store_true", help="force re-detection")

    return parser


def sample_audit(
    engine: Engine,
    percent: float,
    days: int,
    *,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> list[UUID]:
    """Open a spot-check metadata task for a random share of recently auto-published documents.

    The share is ``percent`` of the documents auto-published in the last ``days`` days, and at
    least one when there are any. Returns the ids of the sampled documents.

    Raises:
        ValueError: percent is outside (0, 100] or days is below 1.
    """
    if not 0 < percent <= 100:
        raise ValueError("--percent must be above 0 and at most 100")
    if days < 1:
        raise ValueError("--days must be at least 1")
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    picker = rng or random.Random()
    with engine.begin() as conn:
        rows = conn.execute(
            select(db.documents.c.id, db.documents.c.metadata).where(
                db.documents.c.review_state == "auto_published",
                db.documents.c.updated_at >= cutoff,
            )
        ).all()
        if not rows:
            return []
        size = min(len(rows), max(1, round(len(rows) * percent / 100)))
        sampled: list[UUID] = []
        for row in picker.sample(list(rows), size):
            document_id = UUID(str(row[0]))
            proposal: Any = row[1]
            review.open_review_task(
                conn,
                "metadata",
                "document",
                document_id,
                {"spot_check": True, "proposal": proposal},
            )
            sampled.append(document_id)
    return sampled


def _request(args: argparse.Namespace, *, url: str | None, file_path: str | None) -> LoadRequest:
    return LoadRequest(
        source_code=args.source,
        doc_type=args.doc_type,
        url=url,
        file_path=file_path,
        title=args.title,
        series=args.series,
        number=args.number,
        year=args.year,
        circular_a=args.circular_a,
        circular_b=args.circular_b,
        case_number=args.case_number,
        court_code=args.court_code,
        decision_date=args.decision_date,
    )


def _job_status(engine: Engine, job_id_text: str) -> int:
    try:
        job_id = UUID(job_id_text)
    except ValueError:
        print(f"error: not a job id: {job_id_text}", file=sys.stderr)
        return 2
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(
                    db.ingestion_jobs.c.stage,
                    db.ingestion_jobs.c.status,
                    db.ingestion_jobs.c.attempt,
                    db.ingestion_jobs.c.document_id,
                    db.ingestion_jobs.c.url,
                    db.ingestion_jobs.c.error_code,
                    db.ingestion_jobs.c.error_detail,
                ).where(db.ingestion_jobs.c.id == job_id)
            )
            .mappings()
            .first()
        )
    if row is None:
        print(f"error: no ingestion job {job_id}", file=sys.stderr)
        return 1
    print(f"id: {job_id}")
    for key in ("stage", "status", "attempt", "document_id", "url", "error_code", "error_detail"):
        value = row[key]
        print(f"{key}: {'' if value is None else value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one command. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    engine = create_engine(get_settings().get_database_url(), echo=False)
    try:
        if args.command == "job-status":
            return _job_status(engine, args.job_id)
        if args.command == "sample-audit":
            try:
                sampled = sample_audit(engine, args.percent, args.days)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"spot-check tasks opened: {len(sampled)}")
            return 0
        if args.command == "build-provisions":
            try:
                doc_id = UUID(args.document_id)
            except ValueError:
                print(f"error: not a UUID: {args.document_id}", file=sys.stderr)
                return 2
            try:
                with engine.begin() as conn:
                    result = build_provisions_for(
                        conn,
                        {
                            "document_id": str(doc_id),
                            "instrument_code": args.instrument,
                            "as_on_date": args.as_on,
                        },
                    )
                print(json.dumps(result))
                return 0
            except PermanentError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        if args.command == "detect-amendments":
            try:
                doc_id = UUID(args.document_id)
            except ValueError:
                print(f"error: not a UUID: {args.document_id}", file=sys.stderr)
                return 2
            try:
                with engine.begin() as conn:
                    result = detect_amendments_for(
                        conn,
                        {
                            "document_id": str(doc_id),
                            "force": args.force,
                        },
                    )
                print(json.dumps(result))
                return 0
            except PermanentError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        if args.command == "ingest-file":
            if not Path(args.path).is_file():
                print(f"error: file not found: {args.path}", file=sys.stderr)
                return 2
            request = _request(args, url=None, file_path=args.path)
        else:
            request = _request(args, url=args.url, file_path=None)
        with engine.begin() as conn:
            job_id = submit(conn, request)
        print(job_id)
        return 0
    except LoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
