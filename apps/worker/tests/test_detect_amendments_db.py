"""Integration tests for detect_amendments_for (against Postgres, ``-m integration``).

Each test creates a synthetic document with blocks, a synthetic instrument+provisions tree,
runs detect_amendments_for, and verifies the database state. The autouse fixture cleans up
what the test created.
"""

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from worker import db
from worker.ingest.detect_amendments import detect_amendments_for

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"


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


def _purge(engine: Engine, started: datetime) -> None:
    """Clean up what a test created."""
    with engine.begin() as conn:
        # Delete in reverse dependency order
        conn.execute(text("DELETE FROM review_tasks WHERE created_at >= :t"), {"t": started})
        conn.execute(text("DELETE FROM amendments WHERE created_at >= :t"), {"t": started})
        conn.execute(text("DELETE FROM provision_versions WHERE created_at >= :t"), {"t": started})
        conn.execute(text("DELETE FROM provisions WHERE created_at >= :t"), {"t": started})
        conn.execute(
            text("DELETE FROM instruments WHERE code LIKE :code AND created_at >= :t"),
            {"code": "TEST_%", "t": started},
        )
        conn.execute(
            text(
                "DELETE FROM blocks WHERE document_version_id IN "
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
            text("DELETE FROM links WHERE created_at >= :t"),
            {"t": started},
        )
        conn.execute(text("DELETE FROM document_versions WHERE created_at >= :t"), {"t": started})
        conn.execute(text("DELETE FROM documents WHERE created_at >= :t"), {"t": started})


@pytest.fixture(autouse=True)
def isolated_rows(engine: Engine) -> Iterator[None]:
    started = datetime.now(UTC)
    yield
    _purge(engine, started)


def _insert_document(engine: Engine, canonical_id: str, doc_type: str, doc_date: date) -> UUID:
    """Insert a test document and return its ID."""
    with engine.begin() as conn:
        doc_id = UUID(
            str(
                conn.execute(
                    db.documents.insert()
                    .values(
                        canonical_id=canonical_id,
                        doc_type=doc_type,
                        authority_rank=1,
                        title="Test Notification",
                        status="in_force",
                        review_state="pending_review",
                        doc_date=doc_date,
                        updated_at=datetime.now(UTC),
                    )
                    .returning(db.documents.c.id),
                ).scalar_one()
            )
        )
    return doc_id


_PREAMBLE = [
    "In exercise of the powers conferred by section 164 of the Central Goods and Services Tax "
    "Act, 2017 (12 of 2017), the Central Government hereby makes the following rules further to "
    "amend the Central Goods and Services Tax Rules, 2017, namely:-",
    "1. (1) These rules may be called the Sample (Amendment) Rules, 2026.",
    "(2) They shall come into force on the date of their publication in the Official Gazette.",
    "2. In the said rules,-",
]


def _substitute(rule: str) -> str:
    return (
        f"(i) in rule {rule}, in sub-rule (4), for the words “twenty per cent.”, "
        "the words “ten per cent.” shall be substituted;"
    )


def _insert_version(engine: Engine, document_id: UUID, texts: list[str]) -> UUID:
    """Insert a version for a document with one block per text, set it as current."""
    with engine.begin() as conn:
        version_id, _ = db.insert_version(
            conn,
            document_id=document_id,
            raw_s3_key="s3://test/file.pdf",
            raw_sha256="abc123",
            mime="application/pdf",
        )
        for seq, block_text in enumerate(texts, start=1):
            conn.execute(
                db.blocks.insert().values(
                    document_version_id=version_id,
                    seq=seq,
                    kind="para",
                    text=block_text,
                    text_sha256=f"sha{seq}",
                    is_boilerplate=False,
                )
            )
        db.set_current_version(conn, document_id, version_id)
    return version_id


def _insert_target(engine: Engine, path: str) -> UUID:
    """Insert a provision under the seeded CGST_RULES instrument (path is an ltree)."""
    with engine.begin() as conn:
        return UUID(
            str(
                conn.execute(
                    text(
                        "INSERT INTO provisions (instrument_id, path, level, ordinal, "
                        "created_at, updated_at) "
                        "SELECT id, CAST(:path AS ltree), 'subsection', 4, now(), now() "
                        "FROM instruments WHERE code = 'CGST_RULES' RETURNING id"
                    ),
                    {"path": path},
                ).scalar_one()
            )
        )


def _amendments(engine: Engine, doc_id: UUID) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT id, op, review_status, target_provision_id, old_text, new_text, "
                    "target_locator FROM amendments WHERE source_document_id = :id "
                    "ORDER BY created_at"
                ),
                {"id": str(doc_id)},
            )
            .mappings()
            .all()
        )


class TestDetectAmendmentsBasic:
    """Detection against a real database: rows, review tasks, idempotency and force."""

    def _doc(self, engine: Engine, canonical_id: str, rule: str = "36") -> UUID:
        doc_id = _insert_document(engine, canonical_id, "notification", date(2026, 1, 10))
        _insert_version(engine, doc_id, [*_PREAMBLE, _substitute(rule)])
        return doc_id

    def test_stores_amendment_and_opens_a_review_task(self, engine: Engine) -> None:
        prov_id = _insert_target(engine, "r36.4")
        doc_id = self._doc(engine, "TEST_NOTIF_1")

        with engine.begin() as conn:
            result = detect_amendments_for(conn, {"document_id": str(doc_id)})

        assert result["proposals"] == 1
        assert result["parsed"] == 1
        assert result["resolved_targets"] == 1
        assert result["needs_info"] == 0
        assert result["tasks"] == 1
        rows = _amendments(engine, doc_id)
        assert len(rows) == 1
        row = rows[0]
        assert (row["op"], row["review_status"]) == ("substitute", "proposed")
        assert row["target_provision_id"] == prov_id
        assert (row["old_text"], row["new_text"]) == ("twenty per cent.", "ten per cent.")
        with engine.connect() as conn:
            task = (
                conn.execute(
                    text(
                        "SELECT kind, status FROM review_tasks "
                        "WHERE subject_type = 'amendment' AND subject_id = :id"
                    ),
                    {"id": str(row["id"])},
                )
                .mappings()
                .one()
            )
        assert (task["kind"], task["status"]) == ("amendment", "open")

    def test_second_run_is_skipped(self, engine: Engine) -> None:
        _insert_target(engine, "r36.4")
        doc_id = self._doc(engine, "TEST_NOTIF_2")
        with engine.begin() as conn:
            detect_amendments_for(conn, {"document_id": str(doc_id)})
        with engine.begin() as conn:
            again = detect_amendments_for(conn, {"document_id": str(doc_id)})

        assert again["skipped"] == 1
        assert len(_amendments(engine, doc_id)) == 1

    def test_force_keeps_a_reviewed_amendment_and_does_not_duplicate_it(
        self, engine: Engine
    ) -> None:
        _insert_target(engine, "r36.4")
        doc_id = self._doc(engine, "TEST_NOTIF_3")
        with engine.begin() as conn:
            detect_amendments_for(conn, {"document_id": str(doc_id)})
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE amendments SET review_status = 'approved', reviewed_at = now() "
                    "WHERE source_document_id = :id"
                ),
                {"id": str(doc_id)},
            )
        with engine.begin() as conn:
            detect_amendments_for(conn, {"document_id": str(doc_id), "force": True})

        rows = _amendments(engine, doc_id)
        assert [r["review_status"] for r in rows] == ["approved"]

    def test_force_recreates_an_unreviewed_amendment(self, engine: Engine) -> None:
        _insert_target(engine, "r36.4")
        doc_id = self._doc(engine, "TEST_NOTIF_4")
        with engine.begin() as conn:
            detect_amendments_for(conn, {"document_id": str(doc_id)})
        first = _amendments(engine, doc_id)[0]["id"]
        with engine.begin() as conn:
            result = detect_amendments_for(conn, {"document_id": str(doc_id), "force": True})

        rows = _amendments(engine, doc_id)
        assert len(rows) == 1
        assert rows[0]["id"] != first
        assert result["tasks"] == 1

    def test_unresolved_target_needs_info(self, engine: Engine) -> None:
        doc_id = self._doc(engine, "TEST_NOTIF_5", rule="999")
        with engine.begin() as conn:
            result = detect_amendments_for(conn, {"document_id": str(doc_id)})

        assert result["resolved_targets"] == 0
        assert result["needs_info"] == 1
        row = _amendments(engine, doc_id)[0]
        assert row["review_status"] == "needs_info"
        assert row["target_provision_id"] is None
        assert "target_not_found" in row["target_locator"]["problems"]


class TestDetectAmendmentsErrorHandling:
    """Tests for error cases."""

    def test_detect_amendments_missing_document(self, engine: Engine) -> None:
        """Test error handling for missing document."""
        from worker.errors import PermanentError

        fake_id = "00000000-0000-0000-0000-000000000001"
        with engine.begin() as conn:
            with pytest.raises(PermanentError, match="document not found"):
                detect_amendments_for(conn, {"document_id": fake_id})

    def test_detect_amendments_no_current_version(self, engine: Engine) -> None:
        """Test error handling for document with no current version."""
        from worker.errors import PermanentError

        doc_id = _insert_document(engine, "TEST_NOTIF_6", "notification", date(2026, 1, 10))
        # Don't create a version

        with engine.begin() as conn:
            with pytest.raises(PermanentError, match="no current version"):
                detect_amendments_for(conn, {"document_id": str(doc_id)})

    def test_detect_amendments_no_blocks(self, engine: Engine) -> None:
        """Test error handling for document with no blocks."""
        from worker.errors import PermanentError

        doc_id = _insert_document(engine, "TEST_NOTIF_7", "notification", date(2026, 1, 10))
        # Create a version but don't add blocks
        with engine.begin() as conn:
            version_id, _ = db.insert_version(
                conn,
                document_id=doc_id,
                raw_s3_key="s3://test/file.pdf",
                raw_sha256="abc123",
                mime="application/pdf",
            )
            db.set_current_version(conn, doc_id, version_id)

        with engine.begin() as conn:
            with pytest.raises(PermanentError, match="no blocks"):
                detect_amendments_for(conn, {"document_id": str(doc_id)})

    def test_detect_amendments_bad_payload(self, engine: Engine) -> None:
        """Test error handling for bad payload."""
        from worker.errors import PermanentError

        with engine.begin() as conn:
            with pytest.raises(PermanentError, match="document_id"):
                detect_amendments_for(conn, {})  # Missing document_id
