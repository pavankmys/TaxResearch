"""End-to-end ingestion against Postgres: acquire, then parse, run in-process (``-m integration``).

Every test writes its own unique bytes (a random token in the content), so re-running the
suite never collides with earlier rows. The autouse fixture removes the rows a test created.
"""

import importlib.util
import io
import os
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from worker import db
from worker.config import clear_caches
from worker.ingest.acquire import make_acquire_handler
from worker.ingest.loaders import ACQUIRE_QUEUE, PARSE_QUEUE, LoadRequest, submit
from worker.ingest.ocr import tesseract_available
from worker.ingest.parse import make_parse_handler
from worker.objectstore import LocalFolderObjectStore
from worker.queue import Job
from worker.queue_postgres import PostgresJobQueue
from worker.runner import Runner
from worker.testing.pdf_fixtures import born_digital, cid_garbled, scanned, two_column, with_table

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"
_HARNESS = REPO_ROOT / "eval" / "extraction_recall.py"

_LONG = " ".join(["The rate of tax on the supply of goods shall be as notified"] * 6) + "."


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


@pytest.fixture
def store(tmp_path: Path) -> LocalFolderObjectStore:
    return LocalFolderObjectStore(tmp_path / "objects")


def _purge_since(engine: Engine, started: datetime) -> None:
    """Delete the rows that a test created (everything discovered or created after ``started``).

    Documents are removed only when no version is left for them, so a document that an
    earlier test created is never touched. Blocks and page rows go with their versions.
    """
    with engine.begin() as conn:
        doc_ids = (
            conn.execute(
                text(
                    "SELECT DISTINCT document_id FROM ingestion_jobs "
                    "WHERE discovered_at >= :t AND document_id IS NOT NULL"
                ),
                {"t": started},
            )
            .scalars()
            .all()
        )
        conn.execute(text("DELETE FROM review_tasks WHERE opened_at >= :t"), {"t": started})
        conn.execute(
            text("DELETE FROM job_queue WHERE queue IN ('ingest.acquire', 'ingest.parse')")
        )
        conn.execute(text("DELETE FROM ingestion_jobs WHERE discovered_at >= :t"), {"t": started})
        conn.execute(
            text(
                "UPDATE documents SET current_version_id = NULL WHERE current_version_id IN "
                "(SELECT id FROM document_versions WHERE created_at >= :t)"
            ),
            {"t": started},
        )
        conn.execute(text("DELETE FROM document_versions WHERE created_at >= :t"), {"t": started})
        conn.execute(text("DELETE FROM document_sources WHERE first_seen_at >= :t"), {"t": started})
        if doc_ids:
            conn.execute(
                text(
                    "DELETE FROM documents d WHERE d.id = ANY(:ids) "
                    "AND NOT EXISTS (SELECT 1 FROM document_versions v WHERE v.document_id = d.id)"
                ),
                {"ids": list(doc_ids)},
            )


@pytest.fixture(autouse=True)
def isolated_rows(engine: Engine) -> Iterator[None]:
    """Start with no pending ingest jobs, and remove this test's rows afterwards."""
    clear_caches()
    started = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM job_queue WHERE queue IN ('ingest.acquire', 'ingest.parse')")
        )
    yield
    _purge_since(engine, started)


def _token() -> str:
    return uuid.uuid4().hex


def _paragraphs(count: int) -> list[str]:
    return [f"{n}. {_LONG} Paragraph {n} ends here." for n in range(1, count + 1)]


def _metadata_number() -> str:
    return str(uuid.uuid4().int % 900000 + 100000)


def _merge_pdfs(parts: list[bytes]) -> bytes:
    """Concatenate PDFs page by page (pypdfium2 copies the pages)."""
    out = pdfium.PdfDocument.new()
    for part in parts:
        src = pdfium.PdfDocument(part)
        try:
            out.import_pages(src)
        finally:
            src.close()
    buffer = io.BytesIO()
    out.save(buffer)
    out.close()
    return buffer.getvalue()


def _acquire_next(engine: Engine, store: LocalFolderObjectStore) -> None:
    queue = PostgresJobQueue(engine)
    job = queue.claim(ACQUIRE_QUEUE, "test-worker")
    assert job is not None, "no ingest.acquire job was queued"
    make_acquire_handler(engine, store)(job)
    queue.complete(job.id)


def _parse_next(engine: Engine, store: LocalFolderObjectStore) -> None:
    queue = PostgresJobQueue(engine)
    job = queue.claim(PARSE_QUEUE, "test-worker")
    assert job is not None, "no ingest.parse job was queued"
    make_parse_handler(engine, store)(job)
    queue.complete(job.id)


def _ingest(
    engine: Engine,
    store: LocalFolderObjectStore,
    tmp_path: Path,
    data: bytes,
    name: str,
    **metadata: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Submit a file, acquire it, parse it. Returns (ingestion job id, document version id)."""
    path = tmp_path / name
    path.write_bytes(data)
    with engine.begin() as conn:
        job_id = submit(
            conn,
            LoadRequest(
                source_code="cbic_gst_portal",
                doc_type="notification",
                file_path=str(path),
                **metadata,
            ),
        )
    _acquire_next(engine, store)
    queue = PostgresJobQueue(engine)
    parse_job = queue.claim(PARSE_QUEUE, "test-worker")
    assert parse_job is not None, "acquire did not enqueue the parse stage"
    make_parse_handler(engine, store)(parse_job)
    queue.complete(parse_job.id)
    return job_id, uuid.UUID(parse_job.payload["document_version_id"])


def _one(engine: Engine, sql: str, **params: Any) -> dict[str, Any]:  # noqa: ANN401
    with engine.connect() as conn:
        row = conn.execute(text(sql), params).mappings().one()
    return dict(row)


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), params).mappings()]


def _job(engine: Engine, job_id: uuid.UUID) -> dict[str, Any]:
    return _one(engine, "SELECT * FROM ingestion_jobs WHERE id = :id", id=job_id)


def _version(engine: Engine, version_id: uuid.UUID) -> dict[str, Any]:
    return _one(engine, "SELECT * FROM document_versions WHERE id = :id", id=version_id)


def _pages(engine: Engine, version_id: uuid.UUID) -> list[dict[str, Any]]:
    return _rows(
        engine,
        "SELECT * FROM page_extractions WHERE document_version_id = :v ORDER BY page_no",
        v=version_id,
    )


def _blocks(engine: Engine, version_id: uuid.UUID) -> list[dict[str, Any]]:
    return _rows(
        engine,
        "SELECT * FROM blocks WHERE document_version_id = :v ORDER BY seq",
        v=version_id,
    )


def _parse_failures(engine: Engine, version_id: uuid.UUID) -> list[dict[str, Any]]:
    return _rows(
        engine,
        "SELECT * FROM review_tasks WHERE kind = 'parse_failure' "
        "AND subject_type = 'document_version' AND subject_id = :v",
        v=version_id,
    )


def _counts(engine: Engine, version_id: uuid.UUID) -> tuple[int, int, int]:
    row = _one(
        engine,
        "SELECT (SELECT count(*) FROM page_extractions WHERE document_version_id = :v) AS pages,"
        " (SELECT count(*) FROM page_texts WHERE document_version_id = :v) AS texts,"
        " (SELECT count(*) FROM blocks WHERE document_version_id = :v) AS blocks",
        v=version_id,
    )
    return int(row["pages"]), int(row["texts"]), int(row["blocks"])


def _load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("extraction_recall", _HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["extraction_recall"] = module
    spec.loader.exec_module(module)
    return module


def _born_digital_fixture(pages: int = 3) -> tuple[bytes, list[str]]:
    """A text PDF with a unique header, so its bytes are new on every run."""
    paragraphs = _paragraphs(pages)
    data = born_digital(paragraphs, pages=pages, header=f"CBIC Notification {_token()}")
    return data, paragraphs


def test_born_digital_pdf_is_parsed_end_to_end(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    data, _ = _born_digital_fixture(3)
    number = _metadata_number()
    job_id, version_id = _ingest(
        engine,
        store,
        tmp_path,
        data,
        "ct-notification.pdf",
        series="CT",
        number=number,
        year="2017",
    )

    document = _one(
        engine,
        "SELECT d.* FROM documents d JOIN document_versions v ON v.document_id = d.id "
        "WHERE v.id = :v",
        v=version_id,
    )
    assert document["canonical_id"] == f"ntf:CT:{number}/2017"

    version = _version(engine, version_id)
    assert version["parsed_at"] is not None
    assert version["page_count"] == 3
    assert version["parser_version"] == "pdf-1"
    assert version["simhash"] is not None
    assert version["text_sha256"] is not None

    pages = _pages(engine, version_id)
    assert [p["page_no"] for p in pages] == [1, 2, 3]
    assert {p["method"] for p in pages} == {"text"}
    assert {p["status"] for p in pages} == {"ok"}
    assert not any(p["flagged"] for p in pages)

    texts = _rows(
        engine,
        "SELECT page_no, tsv IS NOT NULL AS indexed FROM page_texts "
        "WHERE document_version_id = :v ORDER BY page_no",
        v=version_id,
    )
    assert [(t["page_no"], t["indexed"]) for t in texts] == [(1, True), (2, True), (3, True)]

    blocks = _blocks(engine, version_id)
    assert [b["seq"] for b in blocks] == list(range(len(blocks)))
    page_numbers = [b["page"] for b in blocks]
    assert page_numbers == sorted(page_numbers)
    boilerplate = [b for b in blocks if b["is_boilerplate"]]
    assert len(boilerplate) == 6  # header and footer on each of the three pages
    assert all(b["text"].startswith(("CBIC Notification", "Page ")) for b in boilerplate)
    body = [b for b in blocks if not b["is_boilerplate"]]
    assert [b["para_label"] for b in body] == ["1", "2", "3"]

    job = _job(engine, job_id)
    assert job["status"] == "done"
    assert job["stage"] == "parse"
    assert job["published_at"] is None
    assert job["finished_at"] is not None
    assert _parse_failures(engine, version_id) == []


def test_same_file_again_is_skipped_and_adds_a_source(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    data, _ = _born_digital_fixture(2)
    first_job, version_id = _ingest(engine, store, tmp_path, data, "first.pdf")

    (tmp_path / "second.pdf").write_bytes(data)
    with engine.begin() as conn:
        second_job = submit(
            conn,
            LoadRequest(
                source_code="cbic_gst_portal",
                doc_type="notification",
                file_path=str(tmp_path / "second.pdf"),
            ),
        )
    _acquire_next(engine, store)

    second = _job(engine, second_job)
    assert second["status"] == "skipped"
    assert second["document_id"] == _job(engine, first_job)["document_id"]
    assert PostgresJobQueue(engine).claim(PARSE_QUEUE, "test-worker") is None

    document_id = second["document_id"]
    versions = _rows(
        engine,
        "SELECT id FROM document_versions WHERE document_id = :d",
        d=document_id,
    )
    assert [v["id"] for v in versions] == [version_id]
    sources = _rows(
        engine,
        "SELECT url FROM document_sources WHERE document_id = :d ORDER BY url",
        d=document_id,
    )
    assert [s["url"] for s in sources] == ["file://first.pdf", "file://second.pdf"]


@pytest.mark.skipif(not tesseract_available(), reason="tesseract binary is not installed")
def test_mixed_pdf_flags_the_garbled_page_and_ocrs_the_scan(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    born, _ = _born_digital_fixture(1)
    data = _merge_pdfs([born, cid_garbled(), scanned("Rule 42 Scanned page " + _token())])
    _, version_id = _ingest(engine, store, tmp_path, data, "mixed.pdf")

    pages = _pages(engine, version_id)
    assert [p["page_no"] for p in pages] == [1, 2, 3]
    assert pages[0]["method"] == "text" and pages[0]["status"] == "ok"
    assert pages[1]["flagged"] is True
    assert pages[2]["method"] == "ocr" and pages[2]["status"] == "ok"
    assert any(b["page"] == 3 for b in _blocks(engine, version_id))

    problem = [p["page_no"] for p in pages if p["flagged"] or p["status"] == "failed"]
    assert 2 in problem
    tasks = _parse_failures(engine, version_id)
    assert len(tasks) == 1
    assert [p["page_no"] for p in tasks[0]["resolution"]["pages"]] == problem


def test_two_column_reading_order_and_table_rows(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    token = _token()
    column_data = two_column(
        [f"{n}. " + f"Left column text about registration {token}. " * 6 for n in (1, 3)],
        [f"{n}. " + "Right column text about returns and the dates. " * 6 for n in (2, 4)],
    )
    _, column_version = _ingest(engine, store, tmp_path, column_data, "columns.pdf")
    labels = [
        b["para_label"] for b in _blocks(engine, column_version) if b["para_label"] is not None
    ]
    assert labels == ["1", "3", "2", "4"]

    table_data = with_table(
        ["Item", f"Rate {token}"],
        [["Cement", "28%"], ["Steel", "18%"]],
    )
    _, table_version = _ingest(engine, store, tmp_path, table_data, "table.pdf")
    blocks = _blocks(engine, table_version)
    tables = [b for b in blocks if b["kind"] == "table"]
    rows = [b["text"] for b in blocks if b["kind"] == "table_row"]
    assert len(tables) == 1
    assert "Item | " in tables[0]["text"]
    assert any(text_.startswith("Item: Cement; ") and "28%" in text_ for text_ in rows)
    assert any(text_.startswith("Item: Steel; ") and "18%" in text_ for text_ in rows)
    intro = [b for b in blocks if b["kind"] == "para"]
    assert intro and intro[0]["seq"] < tables[0]["seq"]


def test_html_file_is_parsed_into_blocks(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    token = _token()
    html = (
        "<!DOCTYPE html><html><head><title>Order</title></head><body>"
        "<h1>Notification 11/2017</h1>"
        f"<p>1. The rate of tax on goods is as notified. Reference {token}.</p>"
        "<table><tr><th>Item</th><th>Rate</th></tr>"
        "<tr><td>Cement</td><td>28%</td></tr></table>"
        "</body></html>"
    ).encode()
    _, version_id = _ingest(engine, store, tmp_path, html, "order.html")

    version = _version(engine, version_id)
    assert version["mime"] == "text/html"
    assert version["page_count"] == 1
    assert [p["method"] for p in _pages(engine, version_id)] == ["text"]
    blocks = _blocks(engine, version_id)
    kinds = {b["kind"] for b in blocks}
    assert {"heading", "para", "table", "table_row"} <= kinds
    headings = [b["text"] for b in blocks if b["kind"] == "heading"]
    assert headings == ["Notification 11/2017"]
    assert any(b["text"].startswith("Item: Cement") for b in blocks if b["kind"] == "table_row")


def test_unreadable_pdf_opens_a_review_task_without_raising(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    data = b"%PDF-1.4 garbage " + _token().encode()
    job_id, version_id = _ingest(engine, store, tmp_path, data, "broken.pdf")

    job = _job(engine, job_id)
    assert job["status"] == "failed"
    assert job["stage"] == "parse"
    assert job["error_code"] == "unreadable_pdf"
    version = _version(engine, version_id)
    assert version["parsed_at"] is None
    assert _counts(engine, version_id) == (0, 0, 0)

    tasks = _parse_failures(engine, version_id)
    assert len(tasks) == 1
    assert tasks[0]["resolution"]["reason"] == "unreadable_pdf"
    assert tasks[0]["status"] == "open"
    assert tasks[0]["priority"] == 2


def test_reparse_does_not_duplicate_rows(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    data, _ = _born_digital_fixture(2)
    job_id, version_id = _ingest(engine, store, tmp_path, data, "reparse.pdf")
    before = _counts(engine, version_id)
    assert before == (2, 2, before[2]) and before[2] > 0

    handler = make_parse_handler(engine, store)
    payload = {"ingestion_job_id": str(job_id), "document_version_id": str(version_id)}
    handler(Job(id="manual", queue=PARSE_QUEUE, payload=payload, attempts=1, status="running"))
    assert _counts(engine, version_id) == before
    assert _job(engine, job_id)["status"] == "done"

    # A new parser version replaces the derived rows instead of adding to them.
    with engine.begin() as conn:
        db.update_version(conn, version_id, parser_version="pdf-0")
    handler(Job(id="manual", queue=PARSE_QUEUE, payload=payload, attempts=1, status="running"))
    assert _counts(engine, version_id) == before
    assert _version(engine, version_id)["parser_version"] == "pdf-1"


def test_runner_processes_a_submitted_file_end_to_end(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    data, _ = _born_digital_fixture(2)
    path = tmp_path / "runner.pdf"
    path.write_bytes(data)
    with engine.begin() as conn:
        job_id = submit(
            conn,
            LoadRequest(
                source_code="cbic_gst_portal", doc_type="notification", file_path=str(path)
            ),
        )

    runner = Runner(
        queue=PostgresJobQueue(engine),
        handlers={
            "ingest.acquire": make_acquire_handler(engine, store),
            "ingest.parse": make_parse_handler(engine, store),
        },
        worker_id="test-worker",
        poll_interval_seconds=0,
        retry_base_seconds=1,
    )
    assert runner.run_once() is True  # acquire
    assert runner.run_once() is True  # parse
    assert runner.run_once() is False

    job = _job(engine, job_id)
    assert job["status"] == "done"
    version_id = _one(
        engine,
        "SELECT id FROM document_versions WHERE document_id = :d",
        d=job["document_id"],
    )["id"]
    assert _version(engine, version_id)["page_count"] == 2


def test_born_digital_text_reaches_the_recall_gate(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    harness = _load_harness()
    data, paragraphs = _born_digital_fixture(3)
    _, version_id = _ingest(engine, store, tmp_path, data, "recall.pdf")

    stored = "\n".join(b["text"] for b in _blocks(engine, version_id) if not b["is_boilerplate"])
    recall = harness.word_recall("\n".join(paragraphs), stored)
    assert recall >= harness.DEFAULT_MIN, f"word recall {recall:.4f} below the gate"
