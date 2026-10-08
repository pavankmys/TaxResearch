"""Command-line loaders and job status.

Run inside the worker container, for example::

    python -m worker.cli ingest-url https://www.cbic-gst.gov.in/... \\
        --source cbic_gst_portal --doc-type notification --series CT --number 11 --year 2017
    python -m worker.cli ingest-file /watch/cbic_gst_portal/notification/file.pdf \\
        --source cbic_gst_portal --doc-type notification
    python -m worker.cli job-status <ingestion-job-id>

Each command prints the ingestion job id (or the status) on stdout. Errors go to stderr.
"""

import argparse
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine

from worker import db
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
    return parser


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
