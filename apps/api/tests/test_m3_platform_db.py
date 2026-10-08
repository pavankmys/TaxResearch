"""M3a platform integration tests against a real Postgres (run with ``-m integration``).

Skipped unless DATABASE_URL points at a real database. The module runs ``alembic upgrade head``
once and ``downgrade base`` at the end, so the database is left as it was found. Storage is a
LocalFolderObjectStore under tmp_path (OBJECT_STORE=local, LOCAL_STORE_PATH).
"""

import hashlib
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import app.db as app_db
import pytest
from alembic import command
from alembic.config import Config
from app.auth.ratelimit import get_login_rate_limiter
from app.auth.tokens import issue_token
from app.main import create_app
from app.object_store import get_object_store
from app.settings import get_settings
from fastapi.testclient import TestClient
from fpdf import FPDF
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from taxresearch_storage import LocalFolderObjectStore

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parent.parent
JWT_SECRET = "integration-test-jwt-secret-0123456789ab"  # 40 characters
VIEWS = (
    "v_ingest_daily",
    "v_ingest_freshness",
    "v_source_health",
    "v_review_queue",
    "v_page_accounting",
    "v_cross_check_disagreements",
    "v_queue_lag",
)
NEW_COLUMNS = {
    "document_versions": {"segmenter_version", "extractor_version", "segmented_at", "extracted_at"},
    "documents": {"metadata", "meta_confidence"},
}


def _alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def _reset_app_state() -> None:
    get_settings.cache_clear()
    get_object_store.cache_clear()
    get_login_rate_limiter.cache_clear()
    app_db._engine = None


def _pdf_bytes(pages: int) -> bytes:
    pdf = FPDF()
    for number in range(1, pages + 1):
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(text=f"Synthetic notification page {number}")
    return bytes(pdf.output())


@pytest.fixture(scope="module")
def db_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Upgrade to head for the module and downgrade to base afterwards."""
    url = os.environ.get("DATABASE_URL", "")
    if not url or "localhost/test" in url:
        pytest.skip("DATABASE_URL not set to a real database; skipping integration tests")
    store_root = tmp_path_factory.mktemp("store")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        mp.setenv("JWT_SECRET", JWT_SECRET)
        mp.setenv("OBJECT_STORE", "local")
        mp.setenv("LOCAL_STORE_PATH", str(store_root))
        _reset_app_state()
        config = _alembic_config()
        command.upgrade(config, "head")
        try:
            yield url
        finally:
            command.downgrade(config, "base")
            _reset_app_state()


@pytest.fixture(autouse=True)
def _fresh_app_state(db_env: str) -> Iterator[None]:
    _reset_app_state()
    yield
    _reset_app_state()


@pytest.fixture(scope="module")
def engine(db_env: str) -> Iterator[Engine]:
    sync_engine = create_engine(_psycopg_url(db_env))
    try:
        yield sync_engine
    finally:
        sync_engine.dispose()


def _role_id(conn: Any, code: str) -> uuid.UUID:  # noqa: ANN401
    return conn.execute(
        text("SELECT id FROM roles WHERE code = :code"), {"code": code}
    ).scalar_one()


def _make_user(conn: Any, role: str, label: str) -> uuid.UUID:  # noqa: ANN401
    user_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO users (id, email, display_name, status) "
            "VALUES (:id, :email, :name, 'active')"
        ),
        {"id": user_id, "email": f"{label}-{user_id.hex}@example.test", "name": label},
    )
    conn.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:user, :role)"),
        {"user": user_id, "role": _role_id(conn, role)},
    )
    return user_id


@pytest.fixture
def seeded(engine: Engine) -> dict[str, Any]:
    """One document with a typed row, blocks, page accounting, a real PDF, and a failed job.

    The store is the one the app uses (LOCAL_STORE_PATH), so the page images and raw files the
    API serves are the ones written here.
    """
    store = LocalFolderObjectStore(os.environ["LOCAL_STORE_PATH"])
    data = _pdf_bytes(2)
    sha = hashlib.sha256(data).hexdigest()
    raw_key = f"raw/{sha[:2]}/{sha}"
    store.put(raw_key, data, "application/pdf")

    with engine.begin() as conn:
        admin = _make_user(conn, "platform_admin", "admin")
        editor_a = _make_user(conn, "platform_content_editor", "editor-a")
        editor_b = _make_user(conn, "platform_content_editor", "editor-b")
        professional = _make_user(conn, "professional", "pro")

        document_id = conn.execute(
            text(
                """
                INSERT INTO documents (canonical_id, doc_type, authority_rank, title, number,
                                       series, status, review_state)
                VALUES (:canonical, 'notification', 5,
                        'Central Tax (Rate) Notification No. 11/2017', '11', 'CT',
                        'in_force', 'pending_review')
                RETURNING id
                """
            ),
            {"canonical": f"notif:CT:{uuid.uuid4().hex[:10]}:2017"},
        ).scalar_one()
        version_id = conn.execute(
            text(
                """
                INSERT INTO document_versions (document_id, version_no, raw_s3_key, raw_sha256,
                                               mime, page_count, parser_version, parsed_at)
                VALUES (:doc, 1, :key, :sha, 'application/pdf', 2, 'parse-1', now())
                RETURNING id
                """
            ),
            {"doc": document_id, "key": raw_key, "sha": sha},
        ).scalar_one()
        conn.execute(
            text("UPDATE documents SET current_version_id = :v WHERE id = :d"),
            {"v": version_id, "d": document_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO notifications (document_id, series, number, year, issue_date)
                VALUES (:doc, 'CT', '11', 2017, '2017-06-28')
                """
            ),
            {"doc": document_id},
        )
        for seq in range(1, 4):
            conn.execute(
                text(
                    """
                    INSERT INTO blocks (document_version_id, seq, kind, page, bbox,
                                        structure_path, text, text_sha256)
                    VALUES (:v, :seq, 'para', :page, CAST(:bbox AS JSONB), :path,
                            :text, :sha)
                    """
                ),
                {
                    "v": version_id,
                    "seq": seq,
                    "page": 1 if seq < 3 else 2,
                    "bbox": json.dumps([10, 10 * seq, 200, 10 * seq + 8]),
                    "path": f"p{seq}",
                    "text": f"Block {seq} text",
                    "sha": hashlib.sha256(f"block {seq}".encode()).hexdigest(),
                },
            )
        for page_no in (1, 2):
            conn.execute(
                text(
                    """
                    INSERT INTO page_extractions (document_version_id, page_no, method,
                                                  chars_engine_a, chars_engine_b, status,
                                                  flagged)
                    VALUES (:v, :p, 'text', 900, :b, 'ok', :flag)
                    """
                ),
                {
                    "v": version_id,
                    "p": page_no,
                    "b": 880 if page_no == 1 else 400,
                    "flag": page_no == 2,
                },
            )

        source_id = conn.execute(
            text(
                "INSERT INTO sources (code, kind, enabled) "
                "VALUES ('cbic_gst_portal', 'manual', true) "
                "ON CONFLICT (code) DO UPDATE SET enabled = true RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO document_sources (document_id, source_id, url)
                VALUES (:d, :s, 'https://www.cbic-gst.gov.in/gst/ct11.pdf')
                """
            ),
            {"d": document_id, "s": source_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO document_status_history (document_id, status, valid_from, valid_to)
                VALUES (:d, 'in_force', '2017-07-01', NULL)
                """
            ),
            {"d": document_id},
        )
        failed_job = conn.execute(
            text(
                """
                INSERT INTO ingestion_jobs (source_id, document_id, url, stage, status, attempt,
                                            error_code, discovered_at)
                VALUES (:s, :d, 'https://www.cbic-gst.gov.in/gst/ct11.pdf', 'parse', 'failed',
                        2, 'PermanentError', now() - interval '2 hours')
                RETURNING id
                """
            ),
            {"s": source_id, "d": document_id},
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO review_tasks (kind, subject_type, subject_id, priority, status,
                                          sla_due_at, opened_at)
                VALUES ('amendment', 'document', :d, 2, 'open', now() - interval '1 hour',
                        now() - interval '9 hours')
                """
            ),
            {"d": document_id},
        )

    return {
        "store": store,
        "document_id": document_id,
        "version_id": version_id,
        "sha": sha,
        "raw_key": raw_key,
        "failed_job": failed_job,
        "users": {"admin": admin, "editor_a": editor_a, "editor_b": editor_b},
        "professional": professional,
        "data": data,
    }


def _client(user_id: uuid.UUID) -> TestClient:
    token, _ = issue_token(user_id, get_settings())
    client = TestClient(create_app())
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _audit_rows(engine: Engine, object_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT action, detail FROM audit_log WHERE object_id = :id ORDER BY seq"),
            {"id": object_id},
        ).mappings()
        return [dict(row) for row in rows]


def _queue_rows(engine: Engine, queue: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT payload, status, idempotency_key FROM job_queue WHERE queue = :q"),
            {"q": queue},
        ).mappings()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------- migrations


def test_views_and_columns_survive_downgrade_and_upgrade(db_env: str, engine: Engine) -> None:
    config = _alembic_config()
    command.downgrade(config, "0006")
    with engine.connect() as conn:
        present = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.views "
                    "WHERE table_schema = 'public' AND table_name = ANY(:names)"
                ),
                {"names": list(VIEWS)},
            ).scalars()
        )
        assert present == set()
        for table, columns in NEW_COLUMNS.items():
            found = set(
                conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :t AND column_name = ANY(:c)"
                    ),
                    {"t": table, "c": list(columns)},
                ).scalars()
            )
            assert found == set()

    command.upgrade(config, "head")
    with engine.connect() as conn:
        for view in VIEWS:
            # Each view is selectable on an empty or populated database.
            conn.execute(text(f"SELECT * FROM {view}")).fetchall()  # noqa: S608
        for table, columns in NEW_COLUMNS.items():
            found = set(
                conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :t AND column_name = ANY(:c)"
                    ),
                    {"t": table, "c": list(columns)},
                ).scalars()
            )
            assert found == columns
        metadata_default = conn.execute(
            text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'documents' AND column_name = 'metadata'"
            )
        ).one()
        assert metadata_default[0] == "NO"
        assert "'{}'" in metadata_default[1]


# ---------------------------------------------------------------------------- documents


def test_documents_list_and_detail(seeded: dict[str, Any]) -> None:
    with _client(seeded["users"]["editor_a"]) as client:
        listing = client.get("/v1/platform/documents", params={"q": "Central Tax"})
        assert listing.status_code == 200
        ids = [item["id"] for item in listing.json()["items"]]
        assert str(seeded["document_id"]) in ids

        detail = client.get(f"/v1/platform/documents/{seeded['document_id']}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["typed_table"] == "notifications"
        assert body["typed_row"]["number"] == "11"
        assert body["metadata"] == {}
        assert body["versions"][0]["parser_version"] == "parse-1"
        assert body["sources"][0]["source_code"] == "cbic_gst_portal"
        assert len(body["open_review_task_ids"]) == 1
        assert [row["status"] for row in body["status_history"]] == ["in_force"]


def test_blocks_pages_and_png_are_served_and_cached(seeded: dict[str, Any]) -> None:
    base = f"/v1/platform/documents/{seeded['document_id']}/versions/{seeded['version_id']}"
    with _client(seeded["users"]["editor_a"]) as client:
        blocks = client.get(f"{base}/blocks", params={"page": 1})
        assert blocks.status_code == 200
        assert [item["seq"] for item in blocks.json()["items"]] == [1, 2]
        assert blocks.json()["items"][0]["structure_path"] == "p1"
        assert blocks.json()["items"][0]["bbox"] == [10, 10, 200, 18]

        pages = client.get(f"{base}/pages")
        assert [item["page_no"] for item in pages.json()["items"]] == [1, 2]
        assert pages.json()["items"][1]["flagged"] is True

        first = client.get(f"{base}/pages/1.png")
        assert first.status_code == 200
        assert first.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert first.headers["cache-control"] == "private, max-age=3600"
        cache_key = f"derived/pages/{seeded['sha']}/1-110.png"
        assert seeded["store"].exists(cache_key)

        second = client.get(f"{base}/pages/1.png")
        assert second.content == first.content

        missing = client.get(f"{base}/pages/9.png")
        assert missing.status_code == 404


def test_raw_download_is_the_original_bytes(seeded: dict[str, Any]) -> None:
    url = f"/v1/platform/documents/{seeded['document_id']}/versions/{seeded['version_id']}/raw"
    with _client(seeded["users"]["editor_a"]) as client:
        response = client.get(url)
    assert response.status_code == 200
    assert response.content == seeded["data"]
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")


def test_patch_fields_is_queued_and_audited(seeded: dict[str, Any], engine: Engine) -> None:
    editor = seeded["users"]["editor_a"]
    with _client(editor) as client:
        response = client.patch(
            f"/v1/platform/documents/{seeded['document_id']}",
            json={"fields": {"title": "Corrected title"}, "reason": "typo in title"},
        )
    assert response.status_code == 202
    assert response.json() == {"queued": True, "status_changed": False}

    queued = [
        row
        for row in _queue_rows(engine, "ingest.apply_metadata")
        if row["payload"]["document_id"] == str(seeded["document_id"])
    ]
    assert len(queued) == 1
    assert queued[0]["payload"]["fields"] == {"title": "Corrected title"}
    assert queued[0]["payload"]["actor_user_id"] == str(editor)
    assert queued[0]["payload"]["review_task_id"] is None

    audit = _audit_rows(engine, str(seeded["document_id"]))
    edit = [row for row in audit if row["action"] == "document.edit"]
    assert edit
    assert edit[-1]["detail"] == {"fields": ["title"], "reason": "typo in title"}


def test_patch_status_writes_history_and_audit(seeded: dict[str, Any], engine: Engine) -> None:
    doc = str(seeded["document_id"])
    with _client(seeded["users"]["admin"]) as client:
        response = client.patch(
            f"/v1/platform/documents/{doc}",
            json={
                "reason": "Stayed by High Court",
                "status": "stayed",
                "status_valid_from": "2026-09-01",
            },
        )
        assert response.status_code == 202
        assert response.json() == {"queued": False, "status_changed": True}

        detail = client.get(f"/v1/platform/documents/{doc}").json()

    history = detail["status_history"]
    assert [row["status"] for row in history] == ["in_force", "stayed"]
    assert history[0]["valid_from"] == "2017-07-01"
    assert history[0]["valid_to"] == "2026-09-01"
    assert history[1]["valid_from"] == "2026-09-01"
    assert history[1]["valid_to"] is None
    assert history[1]["set_by"] == str(seeded["users"]["admin"])
    assert detail["status"] == "stayed"

    with engine.connect() as conn:
        open_rows = conn.execute(
            text(
                "SELECT count(*) FROM document_status_history "
                "WHERE document_id = :d AND valid_to IS NULL"
            ),
            {"d": seeded["document_id"]},
        ).scalar_one()
    assert open_rows == 1
    assert any(row["action"] == "document.status_change" for row in _audit_rows(engine, doc))


def test_patch_by_professional_is_forbidden(seeded: dict[str, Any]) -> None:
    with _client(seeded["professional"]) as client:
        response = client.patch(
            f"/v1/platform/documents/{seeded['document_id']}",
            json={"fields": {"title": "x"}, "reason": "not allowed"},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------- sources and jobs


def test_sources_get_and_patch_are_audited(seeded: dict[str, Any], engine: Engine) -> None:
    with _client(seeded["users"]["admin"]) as client:
        listing = client.get("/v1/platform/sources").json()
        codes = {item["code"]: item for item in listing["items"]}
        assert codes["gst_council"]["enabled"] is False

        response = client.patch(
            "/v1/platform/sources/supreme_court",
            json={"expected_cadence_hours": 48},
        )
        assert response.status_code == 200
        assert response.json()["expected_cadence_hours"] == 48
        assert response.json()["enabled"] is True

        forbidden = _client(seeded["users"]["editor_a"]).patch(
            "/v1/platform/sources/supreme_court", json={"enabled": False}
        )
        assert forbidden.status_code == 403

    rows = _audit_rows(engine, "supreme_court")
    assert [row["action"] for row in rows] == ["source.update"]
    assert rows[0]["detail"]["expected_cadence_hours"] == {"before": None, "after": 48}


def test_retry_requeues_a_failed_job_once(seeded: dict[str, Any], engine: Engine) -> None:
    job = str(seeded["failed_job"])
    with _client(seeded["users"]["editor_a"]) as client:
        first = client.post(f"/v1/platform/jobs/{job}/retry")
        assert first.status_code == 202
        assert first.json()["queue"] == "ingest.parse"
        second = client.post(f"/v1/platform/jobs/{job}/retry")
        assert second.status_code == 409

    with engine.connect() as conn:
        row = (
            conn.execute(
                text("SELECT status, attempt, error_code FROM ingestion_jobs WHERE id = :id"),
                {"id": seeded["failed_job"]},
            )
            .mappings()
            .one()
        )
    assert row["status"] == "queued"
    assert row["attempt"] == 2
    assert row["error_code"] is None
    queued = [
        row
        for row in _queue_rows(engine, "ingest.parse")
        if row["payload"].get("ingestion_job_id") == job
    ]
    assert queued[0]["payload"]["document_version_id"] == str(seeded["version_id"])
    assert any(row["action"] == "ingest.retry" for row in _audit_rows(engine, job))


# ---------------------------------------------------------------------------- uploads


def test_manual_upload_stores_the_file_and_queues_acquire(
    seeded: dict[str, Any], engine: Engine
) -> None:
    data = _pdf_bytes(1)
    sha = hashlib.sha256(data).hexdigest()
    with _client(seeded["users"]["editor_a"]) as client:
        response = client.post(
            "/v1/platform/ingestion/manual",
            data={"source": "cbic_gst_portal", "doc_type": "notification", "number": "12"},
            files={"file": ("ct12.pdf", data, "application/pdf")},
        )
    assert response.status_code == 202
    job_id = response.json()["ingestion_job_id"]
    assert seeded["store"].get(f"raw/{sha[:2]}/{sha}") == data

    queued = [
        row
        for row in _queue_rows(engine, "ingest.acquire")
        if row["payload"].get("ingestion_job_id") == job_id
    ]
    assert len(queued) == 1
    assert queued[0]["payload"]["object_key"] == f"raw/{sha[:2]}/{sha}"
    assert queued[0]["payload"]["file_name"] == "ct12.pdf"
    assert queued[0]["payload"]["number"] == "12"
    assert any(row["action"] == "ingest.upload" for row in _audit_rows(engine, job_id))


# ---------------------------------------------------------------------------- dashboard


def test_dashboard_has_every_section_and_the_overdue_alert(seeded: dict[str, Any]) -> None:
    with _client(seeded["users"]["editor_a"]) as client:
        response = client.get("/v1/platform/ingestion/dashboard")
    assert response.status_code == 200
    body = response.json()
    for key in (
        "daily",
        "freshness",
        "source_health",
        "review_queue",
        "page_accounting",
        "cross_check_disagreements",
        "queue_lag",
        "numbering_gaps",
        "alerts",
    ):
        assert key in body
    assert body["numbering_gaps"] == {"status": "not_measured_until_M7"}
    assert body["cross_check_disagreements"]["disagreements"] >= 1
    assert any(row["kind"] == "amendment" for row in body["review_queue"])
    assert any(alert["kind"] == "overdue_review" for alert in body["alerts"])


def test_miss_reports_alternate_between_two_editors(seeded: dict[str, Any], engine: Engine) -> None:
    filer = seeded["professional"]
    payload = {"query": "refund of unutilised ITC", "filters": {"doc_type": "notification"}}
    with _client(filer) as client:
        ids = [client.post("/v1/miss-reports", json=payload).json()["id"] for _ in range(3)]

    with engine.connect() as conn:
        editors = sorted(
            conn.execute(
                text(
                    "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
                    "JOIN roles r ON r.id = ur.role_id "
                    "WHERE r.code = 'platform_content_editor' AND u.status = 'active'"
                )
            ).scalars(),
            key=str,
        )
        assignees = [
            conn.execute(
                text("SELECT assignee_id FROM review_tasks WHERE id = :id"), {"id": task_id}
            ).scalar_one()
            for task_id in ids
        ]
        kinds = (
            conn.execute(
                text(
                    "SELECT kind, priority, subject_type, subject_id, status FROM review_tasks "
                    "WHERE id = :id"
                ),
                {"id": ids[0]},
            )
            .mappings()
            .one()
        )

    assert len(editors) >= 2
    # Tasks go round-robin over the editors ordered by id, starting from the first one.
    assert assignees == [editors[i % len(editors)] for i in range(3)]
    assert kinds["kind"] == "miss_report"
    assert kinds["priority"] == 4
    assert kinds["subject_type"] == "search"
    assert kinds["subject_id"] is None
    assert kinds["status"] == "open"
    assert any(row["action"] == "miss_report.create" for row in _audit_rows(engine, ids[0]))
