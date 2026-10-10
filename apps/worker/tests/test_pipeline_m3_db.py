"""M3 pipeline against Postgres (``-m integration``): acquire through publish, run in-process.

Each test writes its own unique numbers and text, so re-running never collides with earlier rows.
The autouse fixture removes the rows a test created. Needs migration 0007 (M3 columns).
"""

import io
import os
import random
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from worker import db, review
from worker.config import clear_caches
from worker.ingest.acquire import make_acquire_handler
from worker.ingest.apply_metadata import apply_metadata
from worker.ingest.classify import make_classify_handler
from worker.ingest.extract_meta import make_extract_meta_handler
from worker.ingest.loaders import LoadRequest, submit
from worker.ingest.parse import make_parse_handler
from worker.ingest.publish import make_publish_handler
from worker.ingest.queues import (
    APPLY_METADATA_QUEUE,
    CLASSIFY_QUEUE,
    EXTRACT_META_QUEUE,
    PUBLISH_QUEUE,
    SEGMENT_QUEUE,
)
from worker.ingest.segment import make_segment_handler
from worker.objectstore import LocalFolderObjectStore
from worker.queue import Job
from worker.queue_postgres import PostgresJobQueue
from worker.testing.pdf_fixtures import born_digital, with_table

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"
EDITOR_EMAIL_PREFIX = "m3-worker-test-"
LONG = " ".join(["The rate of tax on the supply of goods shall be as notified"] * 6) + "."


@pytest.fixture(scope="module")
def migrated_db_url() -> Iterator[str]:
    """Migrate the test database to head once per module and yield its SQLAlchemy URL."""
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


PIPELINE_QUEUES = (
    "ingest.acquire",
    "ingest.parse",
    CLASSIFY_QUEUE,
    SEGMENT_QUEUE,
    EXTRACT_META_QUEUE,
    APPLY_METADATA_QUEUE,
    PUBLISH_QUEUE,
    "ingest.index",
)


def _purge(engine: Engine, started: datetime) -> None:
    """Delete what a test created: review tasks, jobs, versions, documents, test editors."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM review_tasks WHERE opened_at >= :t "
                "OR assignee_id IN (SELECT id FROM users WHERE email LIKE :p)"
            ),
            {"t": started, "p": f"{EDITOR_EMAIL_PREFIX}%"},
        )
        conn.execute(
            text("DELETE FROM job_queue WHERE queue = ANY(:queues)"),
            {"queues": list(PIPELINE_QUEUES)},
        )
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
        conn.execute(text("DELETE FROM ingestion_jobs WHERE discovered_at >= :t"), {"t": started})
        conn.execute(
            text(
                "UPDATE documents SET current_version_id = NULL WHERE current_version_id IN "
                "(SELECT id FROM document_versions WHERE created_at >= :t)"
            ),
            {"t": started},
        )
        conn.execute(
            text(
                "DELETE FROM chunks WHERE document_version_id IN "
                "(SELECT id FROM document_versions WHERE created_at >= :t) "
                "OR document_id IN (SELECT id FROM documents WHERE created_at >= :t)"
            ),
            {"t": started},
        )
        conn.execute(
            text(
                "DELETE FROM links WHERE document_id IN "
                "(SELECT id FROM documents WHERE created_at >= :t)"
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
        conn.execute(
            text(
                "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE email LIKE :p)"
            ),
            {"p": f"{EDITOR_EMAIL_PREFIX}%"},
        )
        conn.execute(
            text("DELETE FROM users WHERE email LIKE :p"), {"p": f"{EDITOR_EMAIL_PREFIX}%"}
        )


@pytest.fixture(autouse=True)
def isolated_rows(engine: Engine) -> Iterator[None]:
    clear_caches()
    started = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM job_queue WHERE queue = ANY(:queues)"),
            {"queues": list(PIPELINE_QUEUES)},
        )
    yield
    _purge(engine, started)


def _token() -> str:
    return uuid.uuid4().hex


def _number() -> int:
    """A random number of at most four digits (notification numbers have at most four)."""
    return random.SystemRandom().randint(1000, 9999)


def _merge_pdfs(parts: list[bytes]) -> bytes:
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


def _handlers(engine: Engine, store: LocalFolderObjectStore) -> dict[str, Any]:
    return {
        "ingest.acquire": make_acquire_handler(engine, store),
        "ingest.parse": make_parse_handler(engine, store),
        CLASSIFY_QUEUE: make_classify_handler(engine, store),
        SEGMENT_QUEUE: make_segment_handler(engine, store),
        EXTRACT_META_QUEUE: make_extract_meta_handler(engine, store),
        APPLY_METADATA_QUEUE: _apply_handler(engine),
        PUBLISH_QUEUE: make_publish_handler(engine, store),
    }


def _apply_handler(engine: Engine) -> Any:  # noqa: ANN401 - returns a Job handler
    def handle(job: Job) -> None:
        with engine.begin() as conn:
            apply_metadata(conn, job.payload)

    return handle


def drain(engine: Engine, store: LocalFolderObjectStore) -> int:
    """Run jobs from every pipeline queue until none is left. Returns the number run."""
    queue = PostgresJobQueue(engine)
    handlers = _handlers(engine, store)
    ran = 0
    while True:
        progressed = False
        for name, handler in handlers.items():
            job = queue.claim(name, "test-worker")
            if job is None:
                continue
            handler(job)
            queue.complete(job.id)
            ran += 1
            progressed = True
        if not progressed:
            return ran


def _submit_file(engine: Engine, tmp_path: Path, data: bytes, name: str, **meta: str) -> uuid.UUID:
    path = tmp_path / name
    path.write_bytes(data)
    with engine.begin() as conn:
        return submit(
            conn,
            LoadRequest(
                source_code="cbic_gst_portal",
                doc_type=str(meta.pop("doc_type")),
                file_path=str(path),
                **meta,
            ),
        )


def _one(engine: Engine, sql: str, **params: Any) -> dict[str, Any]:  # noqa: ANN401
    with engine.connect() as conn:
        return dict(conn.execute(text(sql), params).mappings().one())


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), params).mappings()]


def _job_document(engine: Engine, job_id: uuid.UUID) -> uuid.UUID:
    return uuid.UUID(
        str(
            _one(engine, "SELECT document_id FROM ingestion_jobs WHERE id = :id", id=job_id)[
                "document_id"
            ]
        )
    )


def _document(engine: Engine, document_id: uuid.UUID) -> dict[str, Any]:
    return _one(engine, "SELECT * FROM documents WHERE id = :id", id=document_id)


def _open_tasks(engine: Engine, document_id: uuid.UUID) -> list[dict[str, Any]]:
    return _rows(
        engine,
        "SELECT r.* FROM review_tasks r WHERE r.status = 'open' AND ("
        "(r.subject_type = 'document' AND r.subject_id = :d) OR "
        "(r.subject_type = 'document_version' AND r.subject_id IN "
        "(SELECT id FROM document_versions WHERE document_id = :d)))",
        d=document_id,
    )


def _paths(engine: Engine, document_id: uuid.UUID) -> dict[str, str]:
    """Block text prefix (first 25 chars) to structure path, for the current version."""
    rows = _rows(
        engine,
        "SELECT b.text, b.structure_path FROM blocks b JOIN document_versions v "
        "ON v.id = b.document_version_id WHERE v.id = (SELECT current_version_id FROM documents "
        "WHERE id = :d) ORDER BY b.seq",
        d=document_id,
    )
    return {str(row["text"])[:25]: str(row["structure_path"]) for row in rows}


def _random_date() -> str:
    """A random day in 2018 to 2025, as dd.mm.yyyy. Random dates keep tests from matching
    near-duplicates left behind by other tests."""
    rng = random.SystemRandom()
    day = date(rng.randint(2018, 2025), rng.randint(1, 12), rng.randint(1, 28))
    return day.strftime("%d.%m.%Y")


def _notification_pdf(number: int, title: str = "", when: str = "") -> bytes:
    text_paragraphs = [
        f"New Delhi, dated {when or _random_date()}",
        f"Notification No. {number}/2017-Central Tax (Rate)",
        "G.S.R. 690(E).- In exercise of the powers conferred by section 9 of the Central Goods "
        "and Services Tax Act, 2017, the Central Government hereby notifies the following "
        "amendments in the notification.",
        "1. In the said notification, in the Table, the following amendments are made:",
        "(a) in serial number 5, the entry is substituted by the following entry; " + LONG,
        "(b) in serial number 7, the entry is omitted. " + LONG,
        "2. This notification shall come into force on the 1st July, 2017. " + LONG,
        "SCHEDULE I",
    ]
    schedule = with_table(["Chapter", "Rate"], [["1001", "0%"], ["1002", "5%"]])
    return _merge_pdfs([born_digital(text_paragraphs, title=title), schedule])


def _circular_pdf(number: int) -> bytes:
    return born_digital(
        [
            f"Circular No. {number}/15/2022-GST",
            f"New Delhi, dated {_random_date()}",
            "Subject: Clarification regarding refund of unutilised input tax credit",
            "DIN: 202208" + f"{number:014d}"[:14],
            "1. " + LONG,
            "2. " + LONG,
            "2.1 " + LONG,
            "3. " + LONG,
        ],
        header="CBIC Circular",
    )


def _judgement_pdf(case: int, when: str) -> bytes:
    return born_digital(
        [
            "IN THE SUPREME COURT OF INDIA",
            f"CIVIL APPEAL NO. {case} OF 2020",
            "M/s ABC Pvt. Ltd. ...Appellant(s)",
            "VERSUS",
            "State of Kerala ...Respondent(s)",
            "CORAM: Hon'ble Mr. Justice D.Y. Chandrachud, J.",
            "FACTS",
            "1. " + LONG,
            "2. " + LONG,
            "ORDER",
            "3. " + LONG,
            f"Dated: {when}",
        ],
        header="Supreme Court",
    )


def _act_pdf() -> bytes:
    return born_digital(
        [
            "THE CENTRAL GOODS AND SERVICES TAX ACT, 2017",
            "CHAPTER V",
            "INPUT TAX CREDIT",
            "16. Eligibility and conditions for taking input tax credit. " + LONG,
            "(1) Every registered person shall be entitled to take credit. " + LONG,
            "(2) Subject to the conditions, no credit shall be available unless: " + LONG,
            "(a) the goods have been received; " + LONG,
            "(b) the tax has been paid. " + LONG,
            "Provided that no credit shall be allowed after the time limit. " + LONG,
            "17. Apportionment of credit. " + LONG,
        ],
        header="Central Goods and Services Tax Act",
    )


def _editor(engine: Engine) -> uuid.UUID:
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, status) VALUES "
                "(uuid_generate_v7(), :email, 'M3 editor', 'active') RETURNING id"
            ),
            {"email": f"{EDITOR_EMAIL_PREFIX}{_token()}@example.test"},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) SELECT :u, id FROM roles "
                "WHERE code = 'platform_content_editor'"
            ),
            {"u": user_id},
        )
    return uuid.UUID(str(user_id))


def test_notification_flows_to_auto_published_with_structure_and_typed_row(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    number = _number()
    job_id = _submit_file(
        engine, tmp_path, _notification_pdf(number), f"ntf_{_token()}.pdf", doc_type="notification"
    )
    drain(engine, store)

    document_id = _job_document(engine, job_id)
    document = _document(engine, document_id)
    assert document["canonical_id"] == f"ntf:CT(R):{number}/2017"
    assert document["doc_type"] == "notification"
    assert document["review_state"] == "auto_published"
    assert document["meta_confidence"] >= 0.85
    assert document["metadata"]["fields"]["gazette_ref"] == "G.S.R. 690(E)"
    assert _open_tasks(engine, document_id) == []

    typed = _one(engine, "SELECT * FROM notifications WHERE document_id = :d", d=document_id)
    assert (typed["series"], typed["number"], typed["year"]) == ("CT(R)", str(number), 2017)

    paths = _paths(engine, document_id)
    assert any(path.startswith("p1") and path == "p1" for path in paths.values())
    assert "p1.i1" in paths.values()
    assert any(path.startswith("sched1") for path in paths.values())
    assert "pre" in paths.values()

    status = _one(
        engine, "SELECT * FROM document_status_history WHERE document_id = :d", d=document_id
    )
    assert status["status"] == "in_force"
    job = _one(engine, "SELECT * FROM ingestion_jobs WHERE id = :id", id=job_id)
    assert job["published_at"] is not None
    assert job["status"] == "done"


def test_circular_flows_with_din_subject_and_canonical_id(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    number = _number()
    job_id = _submit_file(
        engine, tmp_path, _circular_pdf(number), f"cir_{_token()}.pdf", doc_type="circular"
    )
    drain(engine, store)

    document_id = _job_document(engine, job_id)
    document = _document(engine, document_id)
    assert document["canonical_id"] == f"cir:{number}/15/2022"
    typed = _one(engine, "SELECT * FROM circulars WHERE document_id = :d", d=document_id)
    assert typed["kind"] == "circular"
    assert typed["subject"].startswith("Clarification regarding refund")
    assert typed["din"].startswith("202208")
    assert document["review_state"] == "auto_published"
    paths = _paths(engine, document_id)
    assert "hdr" in paths.values()
    assert "p3" in paths.values()


def test_supreme_court_judgement_flows_with_labelled_paragraphs(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    case = _number()
    when = _random_date()  # dd.mm.yyyy
    iso = f"{when[6:]}-{when[3:5]}-{when[:2]}"
    job_id = _submit_file(
        engine, tmp_path, _judgement_pdf(case, when), f"jdg_{_token()}.pdf", doc_type="judgement"
    )
    drain(engine, store)

    document_id = _job_document(engine, job_id)
    document = _document(engine, document_id)
    assert document["canonical_id"] == f"jdg:SC:CA{case}/2020:{iso}"
    assert document["authority_rank"] == 3
    typed = _one(engine, "SELECT * FROM judgements WHERE document_id = :d", d=document_id)
    assert typed["court_level"] == "SC"
    assert typed["decision_date"].isoformat() == iso
    assert typed["case_numbers"] == [f"CA {case}/2020"]
    paths = _paths(engine, document_id)
    assert "hdr" in paths.values()
    assert any(path.startswith("facts.p") for path in paths.values())
    assert any(path.startswith("order.p") for path in paths.values())


def test_act_is_segmented_into_chapters_sections_and_clauses(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    job_id = _submit_file(engine, tmp_path, _act_pdf(), f"act_{_token()}.pdf", doc_type="act")
    drain(engine, store)

    document_id = _job_document(engine, job_id)
    document = _document(engine, document_id)
    assert document["doc_type"] == "act"
    assert document["title"] == "THE CENTRAL GOODS AND SERVICES TAX ACT, 2017"
    paths = set(_paths(engine, document_id).values())
    assert {"ch5", "ch5.s16", "ch5.s16.1", "ch5.s16.2", "ch5.s16.2.a", "ch5.s16.2.b"} <= paths
    assert "ch5.s17" in paths
    assert document["review_state"] == "auto_published"


def test_numbering_gap_opens_parse_failure_and_keeps_pipeline_going(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    number = _number()
    gap = born_digital(
        [
            f"New Delhi, dated {_random_date()}",
            f"Notification No. {number}/2017-Central Tax (Rate)",
            "1. " + LONG,
            "2. " + LONG,
            "4. " + LONG,
        ],
        header="CBIC Notification",
    )
    job_id = _submit_file(engine, tmp_path, gap, f"gap_{_token()}.pdf", doc_type="notification")
    drain(engine, store)

    document_id = _job_document(engine, job_id)
    version = _one(engine, "SELECT current_version_id FROM documents WHERE id = :d", d=document_id)
    tasks = _rows(
        engine,
        "SELECT * FROM review_tasks WHERE kind = 'parse_failure' "
        "AND subject_type = 'document_version' AND subject_id = :v",
        v=version["current_version_id"],
    )
    assert len(tasks) == 1
    problems = tasks[0]["resolution"]["numbering"]
    assert {"path": "p3", "problem": "gap", "detail": "no p3 between 1 and 4"} in problems
    assert _document(engine, document_id)["review_state"] == "pending_review"


def test_unknown_court_judgement_gets_metadata_task_and_pending_review(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    case = _number()
    unknown = born_digital(
        [
            "IN THE COURT OF A DISTRICT JUDGE",
            f"CIVIL APPEAL NO. {case} OF 2020",
            f"Dated: {_random_date()}",
            "1. " + LONG,
        ],
        header="Judgement",
    )
    job_id = _submit_file(engine, tmp_path, unknown, f"unk_{_token()}.pdf", doc_type="judgement")
    drain(engine, store)

    document_id = _job_document(engine, job_id)
    document = _document(engine, document_id)
    assert document["review_state"] == "pending_review"
    assert document["meta_confidence"] == 0
    tasks = _open_tasks(engine, document_id)
    metadata_tasks = [task for task in tasks if task["kind"] == "metadata"]
    assert metadata_tasks
    assert "missing:court_code" in metadata_tasks[0]["resolution"]["issues"]


def test_near_duplicate_with_same_number_is_merged_into_one_document(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    number = _number()
    same_day = _random_date()
    first_job = _submit_file(
        engine,
        tmp_path,
        _notification_pdf(number, when=same_day),
        f"dup1_{_token()}.pdf",
        doc_type="notification",
    )
    drain(engine, store)
    first_document = _job_document(engine, first_job)

    second_job = _submit_file(
        engine,
        tmp_path,
        _notification_pdf(number, title=f"copy {_token()}", when=same_day),
        f"dup2_{_token()}.pdf",
        doc_type="notification",
    )
    drain(engine, store)

    assert _job_document(engine, second_job) == first_document
    versions = _rows(
        engine,
        "SELECT version_no FROM document_versions WHERE document_id = :d ORDER BY version_no",
        d=first_document,
    )
    assert [row["version_no"] for row in versions] == [1, 2]
    count = _one(
        engine,
        "SELECT count(*) AS n FROM documents WHERE canonical_id = :c",
        c=f"ntf:CT(R):{number}/2017",
    )
    assert count["n"] == 1


def test_round_robin_assignment_alternates_between_two_editors(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    _editor(engine)
    _editor(engine)
    numbers = [_number(), _number()]
    jobs = [
        _submit_file(
            engine,
            tmp_path,
            born_digital(
                [
                    f"New Delhi, dated {_random_date()}",
                    f"Notification No. {number}/2017-Central Tax (Rate)",
                    "1. " + LONG,
                    "3. " + LONG,
                ],
                header="CBIC Notification",
            ),
            f"rr_{_token()}.pdf",
            doc_type="notification",
        )
        for number in numbers
    ]
    drain(engine, store)

    tasks = _rows(
        engine,
        "SELECT t.assignee_id FROM review_tasks t WHERE t.kind IN ('parse_failure', 'metadata') "
        "AND t.opened_at >= (SELECT min(discovered_at) FROM ingestion_jobs WHERE id = ANY(:ids)) "
        "ORDER BY t.created_at, t.id",
        ids=[str(job) for job in jobs],
    )
    assignees = [row["assignee_id"] for row in tasks]
    assert len(assignees) >= 2
    assert all(assignee is not None for assignee in assignees)
    assert all(a != b for a, b in zip(assignees, assignees[1:], strict=False))


def test_apply_metadata_with_actor_stores_override(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    number = _number()
    job_id = _submit_file(
        engine, tmp_path, _notification_pdf(number), f"ov_{_token()}.pdf", doc_type="notification"
    )
    drain(engine, store)
    document_id = _job_document(engine, job_id)
    actor = _editor(engine)

    with engine.begin() as conn:
        apply_metadata(
            conn,
            {
                "document_id": str(document_id),
                "fields": {"title": "Edited title for the notification"},
                "actor_user_id": str(actor),
                "reason": "edit_approve",
                "review_task_id": None,
            },
        )
    drain(engine, store)

    document = _document(engine, document_id)
    assert document["title"] == "Edited title for the notification"
    override = document["metadata"]["overrides"]["title"]
    assert override["value"] == "Edited title for the notification"
    assert override["by"] == str(actor)
    assert override["reason"] == "edit_approve"
    assert document["meta_confidence"] >= 0.85


def test_upload_object_is_acquired_with_upload_source_and_file_name(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    name = f"scan_{_token()}.pdf"
    key = f"uploads/{_token()}.pdf"
    store.put(
        key, born_digital(["Some uploaded note about GST refunds. " + LONG]), "application/pdf"
    )
    with engine.begin() as conn:
        source_id = db.ensure_source(conn, "cbic_gst_portal", "manual")
        job_id = db.create_ingestion_job(conn, source_id=source_id, url=f"upload://{name}")
        db.enqueue(
            conn,
            "ingest.acquire",
            {
                "ingestion_job_id": str(job_id),
                "source_code": "cbic_gst_portal",
                "doc_type": "other",
                "object_key": key,
                "file_name": name,
            },
            idempotency_key=str(job_id),
        )
    drain(engine, store)

    document_id = _job_document(engine, job_id)
    document = _document(engine, document_id)
    assert document["title"] == name
    sources = _rows(
        engine, "SELECT url FROM document_sources WHERE document_id = :d", d=document_id
    )
    assert [row["url"] for row in sources] == [f"upload://{name}"]
    assert document["review_state"] in {"auto_published", "pending_review"}


def test_review_helper_matches_api_round_robin_when_tasks_are_opened(engine: Engine) -> None:
    editors = [_editor(engine), _editor(engine)]
    with engine.begin() as conn:
        first = review.open_review_task(conn, "metadata", "document", None, {"note": "a"})
        second = review.open_review_task(conn, "metadata", "document", None, {"note": "b"})
    assignees = _rows(
        engine,
        "SELECT id, assignee_id FROM review_tasks WHERE id = ANY(:ids) ORDER BY created_at, id",
        ids=[str(first), str(second)],
    )
    got = [uuid.UUID(str(row["assignee_id"])) for row in assignees]
    assert got[0] != got[1]
    assert set(got) == set(editors)


def test_sample_audit_opens_spot_check_tasks_for_auto_published_documents(
    engine: Engine, store: LocalFolderObjectStore, tmp_path: Path
) -> None:
    from worker.cli import sample_audit

    job_id = _submit_file(engine, tmp_path, _act_pdf(), f"audit_{_token()}.pdf", doc_type="act")
    drain(engine, store)
    document_id = _job_document(engine, job_id)
    assert _document(engine, document_id)["review_state"] == "auto_published"

    sampled = sample_audit(engine, percent=100, days=1, rng=random.Random(1))

    assert document_id in sampled
    tasks = _open_tasks(engine, document_id)
    spot = [task for task in tasks if task["kind"] == "metadata"]
    assert spot
    assert spot[0]["resolution"]["spot_check"] is True
    assert spot[0]["resolution"]["proposal"]["fields"]["title"] == (
        "THE CENTRAL GOODS AND SERVICES TAX ACT, 2017"
    )
