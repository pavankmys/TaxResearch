"""Integration tests: loader, acquire handler and dedup against Postgres (``-m integration``)."""

import hashlib
import os
import random
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from worker import db
from worker.config import clear_caches
from worker.errors import PermanentError
from worker.ingest.acquire import make_acquire_handler, raw_key
from worker.ingest.loaders import ACQUIRE_QUEUE, PARSE_QUEUE, LoadRequest, submit
from worker.objectstore import LocalFolderObjectStore
from worker.queue import Job
from worker.queue_postgres import PostgresJobQueue

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"


@pytest.fixture(scope="module")
def migrated_db_url() -> Iterator[str]:
    """Migrate the test database to head once per module and yield its SQLAlchemy URL.

    Skips unless DATABASE_URL points at a real database. Module scope because the API
    migration test downgrades to base.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url or "localhost/test" in url or "test:test@" in url:
        pytest.skip("DATABASE_URL not set to a real database; skipping integration tests")
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", url)
        config = Config(str(API_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(API_ROOT / "alembic"))
        command.upgrade(config, "head")
    yield url


@pytest.fixture
def engine(migrated_db_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_db_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_ingest_queues(engine: Engine) -> Iterator[None]:
    """Each test starts with no pending acquire or parse jobs, so claims are predictable."""
    clear_caches()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM job_queue WHERE queue IN ('ingest.acquire', 'ingest.parse')")
        )
    yield


@pytest.fixture
def store(tmp_path: Path) -> LocalFolderObjectStore:
    return LocalFolderObjectStore(tmp_path / "objects")


def _unique_pdf() -> bytes:
    return f"%PDF-1.4\n% synthetic {uuid.uuid4()}\n".encode()


def _metadata_number() -> str:
    """A notification number unlikely to collide with earlier test runs."""
    return str(random.randint(100000, 999999))


def _submit_file(engine: Engine, path: Path, **metadata: str) -> uuid.UUID:
    request = LoadRequest(
        source_code="cbic_gst_portal",
        doc_type="notification",
        file_path=str(path),
        **metadata,
    )
    with engine.begin() as conn:
        return submit(conn, request)


def _run_next_acquire(engine: Engine, store: LocalFolderObjectStore, **handler_kwargs: Any) -> Job:  # noqa: ANN401
    queue = PostgresJobQueue(engine)
    job = queue.claim(ACQUIRE_QUEUE, "test-worker")
    assert job is not None, "no ingest.acquire job was queued"
    make_acquire_handler(engine, store, **handler_kwargs)(job)
    queue.complete(job.id)
    return job


def _job_row(engine: Engine, job_id: uuid.UUID) -> dict[str, Any]:
    with engine.connect() as conn:
        row = (
            conn.execute(select(db.ingestion_jobs).where(db.ingestion_jobs.c.id == job_id))
            .mappings()
            .one()
        )
    return dict(row)


def _versions(engine: Engine, document_id: uuid.UUID) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(db.document_versions)
            .where(db.document_versions.c.document_id == document_id)
            .order_by(db.document_versions.c.version_no)
        ).mappings()
        return [dict(row) for row in rows]


def _sources_for(engine: Engine, document_id: uuid.UUID) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(db.document_sources.c.url)
            .where(db.document_sources.c.document_id == document_id)
            .order_by(db.document_sources.c.url)
        )
        return [str(row[0]) for row in rows]


def test_file_is_acquired_end_to_end(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    """A file load stores the bytes, creates the document and version, and enqueues parse."""
    data = _unique_pdf()
    path = tmp_path / "ct-notification.pdf"
    path.write_bytes(data)
    job_id = _submit_file(engine, path)

    _run_next_acquire(engine, store)

    job = _job_row(engine, job_id)
    assert job["status"] == "done"
    assert job["stage"] == "acquire"
    assert job["attempt"] == 1
    assert job["finished_at"] is not None
    document_id = job["document_id"]
    assert document_id is not None

    with engine.connect() as conn:
        document = (
            conn.execute(select(db.documents).where(db.documents.c.id == document_id))
            .mappings()
            .one()
        )
    assert document["canonical_id"].startswith("unk:")
    assert document["doc_type"] == "notification"
    assert document["authority_rank"] == 5
    assert document["title"] == "ct-notification.pdf"
    assert document["review_state"] == "pending_review"

    sha = hashlib.sha256(data).hexdigest()
    versions = _versions(engine, document_id)
    assert len(versions) == 1
    version = versions[0]
    assert version["version_no"] == 1
    assert version["raw_sha256"] == sha
    assert version["raw_s3_key"] == raw_key(sha)
    assert version["mime"] == "application/pdf"
    assert document["current_version_id"] == version["id"]

    assert _sources_for(engine, document_id) == ["file://ct-notification.pdf"]
    assert store.get(raw_key(sha)) == data

    with engine.connect() as conn:
        parse_jobs = conn.execute(
            text(
                "SELECT payload, status FROM job_queue "
                "WHERE queue = :queue AND idempotency_key = :key"
            ),
            {"queue": PARSE_QUEUE, "key": f"{version['id']}:parse"},
        ).all()
    assert len(parse_jobs) == 1
    assert parse_jobs[0][1] == "queued"
    assert parse_jobs[0][0]["document_version_id"] == str(version["id"])


def test_same_bytes_again_are_skipped_and_add_a_source(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    """The same bytes under another file name: job skipped, URL added, no new version."""
    data = _unique_pdf()
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(data)
    second.write_bytes(data)

    first_job = _submit_file(engine, first)
    _run_next_acquire(engine, store)
    second_job = _submit_file(engine, second)
    _run_next_acquire(engine, store)

    first_row = _job_row(engine, first_job)
    second_row = _job_row(engine, second_job)
    assert second_row["status"] == "skipped"
    assert second_row["document_id"] == first_row["document_id"]

    document_id = first_row["document_id"]
    assert len(_versions(engine, document_id)) == 1
    assert _sources_for(engine, document_id) == ["file://first.pdf", "file://second.pdf"]

    with engine.connect() as conn:
        parse_count = conn.execute(
            text("SELECT count(*) FROM job_queue WHERE queue = :queue"),
            {"queue": PARSE_QUEUE},
        ).scalar_one()
    assert parse_count == 1


def test_same_canonical_id_with_new_bytes_adds_a_version(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    """Notification metadata gives one document; new bytes become version 2."""
    number = _metadata_number()
    metadata = {"series": "CT", "number": number, "year": "2017"}
    first = tmp_path / "v1.pdf"
    second = tmp_path / "v2.pdf"
    first.write_bytes(_unique_pdf())
    second.write_bytes(_unique_pdf())

    first_job = _submit_file(engine, first, **metadata)
    _run_next_acquire(engine, store)
    second_job = _submit_file(engine, second, **metadata)
    _run_next_acquire(engine, store)

    document_id = _job_row(engine, first_job)["document_id"]
    assert _job_row(engine, second_job)["document_id"] == document_id
    assert _job_row(engine, second_job)["status"] == "done"

    versions = _versions(engine, document_id)
    assert [v["version_no"] for v in versions] == [1, 2]

    with engine.connect() as conn:
        document = (
            conn.execute(select(db.documents).where(db.documents.c.id == document_id))
            .mappings()
            .one()
        )
    assert document["canonical_id"] == f"ntf:CT:{number}/2017"
    assert document["current_version_id"] == versions[1]["id"]


def test_missing_file_fails_permanently(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    """A missing file marks the job failed and raises PermanentError (not retried)."""
    job_id = _submit_file(engine, tmp_path / "does-not-exist.pdf")
    queue = PostgresJobQueue(engine)
    job = queue.claim(ACQUIRE_QUEUE, "test-worker")
    assert job is not None

    with pytest.raises(PermanentError, match="file not found"):
        make_acquire_handler(engine, store)(job)

    row = _job_row(engine, job_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "PermanentError"
    assert "file not found" in row["error_detail"]


def test_unsupported_bytes_fail_permanently(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    """A file that is neither PDF nor HTML is refused."""
    path = tmp_path / "archive.pdf"
    path.write_bytes(b"PK\x03\x04 not a pdf")
    job_id = _submit_file(engine, path)
    queue = PostgresJobQueue(engine)
    job = queue.claim(ACQUIRE_QUEUE, "test-worker")
    assert job is not None

    with pytest.raises(PermanentError, match="unsupported file type"):
        make_acquire_handler(engine, store)(job)
    assert _job_row(engine, job_id)["status"] == "failed"


def _url_transport(body: bytes) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=body)

    return httpx.MockTransport(handler)


def test_url_load_is_fetched_and_acquired(engine: Engine, store: LocalFolderObjectStore) -> None:
    """A URL on an allowed host is fetched, stored and recorded with that URL."""
    data = _unique_pdf()
    url = "https://www.cbic-gst.gov.in/gst/notifications/ct-11-2017.pdf"
    with engine.begin() as conn:
        job_id = submit(
            conn,
            LoadRequest(
                "cbic_gst_portal",
                "notification",
                url=url,
                series="CT",
                number=_metadata_number(),
                year="2017",
            ),
        )

    _run_next_acquire(
        engine,
        store,
        fetch_transport=_url_transport(data),
        resolver=lambda host: ["93.184.216.34"],
    )

    row = _job_row(engine, job_id)
    assert row["status"] == "done"
    assert row["url"] == url
    assert _sources_for(engine, row["document_id"]) == [url]
    assert store.get(raw_key(hashlib.sha256(data).hexdigest())) == data


def test_refused_url_fails_permanently(engine: Engine, store: LocalFolderObjectStore) -> None:
    """A URL whose host is not on the allow-list fails without a retry."""
    with engine.begin() as conn:
        job_id = submit(
            conn,
            LoadRequest("cbic_gst_portal", "notification", url="https://evil.example/a.pdf"),
        )
    queue = PostgresJobQueue(engine)
    job = queue.claim(ACQUIRE_QUEUE, "test-worker")
    assert job is not None

    with pytest.raises(PermanentError, match="host not allowed"):
        make_acquire_handler(engine, store, fetch_transport=_url_transport(b"%PDF-"))(job)

    row = _job_row(engine, job_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "FetchRefused"
