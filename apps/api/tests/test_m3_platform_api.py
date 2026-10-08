"""Unit tests for the M3 platform routers: permissions, validation, responses and SQL effects.

The database session and the audit writer are replaced, so these tests need no Postgres. Storage
is a real LocalFolderObjectStore under tmp_path, and page rendering uses a real PDF from fpdf2.
The integration tests in test_m3_platform_db.py cover the same paths against Postgres.
"""

import datetime as dt
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.auth.deps import CurrentUser, get_current_user
from app.db import get_session
from app.main import create_app
from app.object_store import get_object_store
from app.routers import (
    ingestion,
    miss_reports,
    platform_documents,
    platform_jobs,
    platform_sources,
)
from fastapi.testclient import TestClient
from fpdf import FPDF
from taxresearch_storage import LocalFolderObjectStore

Answer = Callable[[str, dict[str, Any] | None], "FakeResult"]


class FakeResult:
    """Just enough of a SQLAlchemy result for the routers."""

    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:  # noqa: ANN401
        self._rows = list(rows) if rows is not None else []
        self._scalar = scalar

    def scalar_one(self) -> Any:  # noqa: ANN401
        return self._scalar

    def scalar_one_or_none(self) -> Any:  # noqa: ANN401
        return self._scalar

    def scalars(self) -> "FakeResult":
        return self

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> Any:  # noqa: ANN401
        return self._rows[0] if self._rows else None

    def one(self) -> Any:  # noqa: ANN401
        return self._rows[0]

    def all(self) -> list[Any]:
        return list(self._rows)

    def __iter__(self) -> Any:  # noqa: ANN401
        return iter(self._rows)


def route(*rules: tuple[str, Any]) -> Answer:
    """Answer each statement with the first rule whose text appears in it.

    A rule value is a FakeResult, or a function of the parameters that returns one.
    """

    def answer(sql: str, params: dict[str, Any] | None) -> FakeResult:
        for needle, value in rules:
            if needle in sql:
                return value(params) if callable(value) else value
        return FakeResult()

    return answer


class FakeSession:
    """Records every statement (whitespace collapsed) and answers it through a routing function."""

    def __init__(self, answer: Answer | None = None) -> None:
        self._answer = answer or route()
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:  # noqa: ANN401
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params))
        return self._answer(sql, params)

    def params_for(self, needle: str) -> list[dict[str, Any] | None]:
        return [params for sql, params in self.calls if needle in sql]

    def sql_for(self, needle: str) -> list[str]:
        return [sql for sql, _ in self.calls if needle in sql]


def _user(*roles: str) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        email="user@example.test",
        display_name="Test User",
        tenant_id=None,
        roles=frozenset(roles),
    )


def _client(
    user: CurrentUser,
    session: FakeSession,
    store: LocalFolderObjectStore | None = None,
) -> TestClient:
    app = create_app()

    async def override_user() -> CurrentUser:
        return user

    async def override_session() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_session] = override_session
    if store is not None:
        app.dependency_overrides[get_object_store] = lambda: store
    return TestClient(app)


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """One audit mock shared by every router that writes audit rows."""
    mock = AsyncMock()
    for module in (
        platform_documents,
        platform_sources,
        platform_jobs,
        miss_reports,
        ingestion,
    ):
        monkeypatch.setattr(module, "write_audit", mock)
    return mock


def _actions(audit: AsyncMock) -> list[str]:
    return [call.kwargs["action"] for call in audit.call_args_list]


def _pdf_bytes(pages: int = 1) -> bytes:
    pdf = FPDF()
    for number in range(1, pages + 1):
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(text=f"Page {number} of the synthetic fixture")
    return bytes(pdf.output())


DOC_ID = uuid.uuid4()
VERSION_ID = uuid.uuid4()
NOW = dt.datetime(2026, 10, 8, 9, 0, tzinfo=dt.UTC)


def _document_row(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "id": DOC_ID,
        "canonical_id": "notif:CT:11:2017",
        "doc_type": "notification",
        "authority_rank": 5,
        "title": "Central Tax Notification 11/2017",
        "number": "11",
        "series": "CT",
        "doc_date": dt.date(2017, 6, 28),
        "in_force_date": dt.date(2017, 7, 1),
        "issuing_authority": "Central Government",
        "status": "in_force",
        "review_state": "pending_review",
        "current_version_id": VERSION_ID,
        "court": None,
        "bench": None,
        "metadata": {"fields": {"title": "x"}},
        "meta_confidence": 0.9,
        "created_at": NOW,
        "updated_at": NOW,
    }
    row.update(overrides)
    return row


def _version_row(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "id": VERSION_ID,
        "document_id": DOC_ID,
        "raw_s3_key": "raw/ab/abcdef",
        "raw_sha256": "abcdef",
        "mime": "application/pdf",
        "page_count": 2,
        "canonical_id": "notif:CT:11:2017",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------- documents


class TestDocumentsList:
    def test_professional_is_forbidden(self, audit: AsyncMock) -> None:
        client = _client(_user("professional"), FakeSession())
        assert client.get("/v1/platform/documents").status_code == 403

    def test_filters_escape_like_and_page_by_id(self, audit: AsyncMock) -> None:
        rows = [_document_row(id=uuid.uuid4()) for _ in range(3)]
        session = FakeSession(route(("FROM documents", FakeResult(rows=rows))))
        client = _client(_user("platform_content_editor"), session)
        response = client.get(
            "/v1/platform/documents",
            params={"doc_type": "notification", "q": " 50%_x ", "limit": 2},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        assert body["next_cursor"] == str(rows[1]["id"])
        assert response.headers["cache-control"] == "private, no-store"
        (params,) = session.params_for("FROM documents")
        assert params is not None
        assert params["doc_type"] == "notification"
        assert params["contains"] == "%50\\%\\_x%"
        assert params["prefix"] == "50\\%\\_x%"
        assert params["limit"] == 3

    def test_last_page_has_no_cursor(self, audit: AsyncMock) -> None:
        session = FakeSession(route(("FROM documents", FakeResult(rows=[_document_row()]))))
        client = _client(_user("platform_admin"), session)
        body = client.get("/v1/platform/documents").json()
        assert body["next_cursor"] is None
        assert len(body["items"]) == 1

    def test_limit_above_maximum_is_rejected(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_admin"), FakeSession())
        assert client.get("/v1/platform/documents", params={"limit": 500}).status_code == 422


class TestDocumentDetail:
    def test_missing_document_is_404(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_admin"), FakeSession())
        assert client.get(f"/v1/platform/documents/{DOC_ID}").status_code == 404

    def test_returns_typed_row_versions_sources_and_open_tasks(self, audit: AsyncMock) -> None:
        task_id = uuid.uuid4()
        session = FakeSession(
            route(
                ("FROM documents WHERE id", FakeResult(rows=[_document_row()])),
                (
                    "FROM notifications",
                    FakeResult(rows=[{"document_id": DOC_ID, "series": "CT", "number": "11"}]),
                ),
                (
                    "FROM document_versions WHERE document_id",
                    FakeResult(
                        rows=[
                            {
                                "id": VERSION_ID,
                                "version_no": 1,
                                "mime": "application/pdf",
                                "page_count": 2,
                                "parsed_at": NOW,
                                "parser_version": "p1",
                                "segmenter_version": None,
                                "extractor_version": None,
                                "ocr_used": False,
                            }
                        ]
                    ),
                ),
                (
                    "FROM document_sources ds",
                    FakeResult(
                        rows=[
                            {
                                "source_code": "cbic_gst_portal",
                                "url": "https://www.cbic-gst.gov.in/x.pdf",
                                "first_seen_at": NOW,
                                "last_seen_at": NOW,
                            }
                        ]
                    ),
                ),
                (
                    "FROM document_status_history",
                    FakeResult(
                        rows=[
                            {
                                "status": "in_force",
                                "valid_from": dt.date(2017, 7, 1),
                                "valid_to": None,
                                "set_by": None,
                                "created_at": NOW,
                            }
                        ]
                    ),
                ),
                ("FROM review_tasks", FakeResult(rows=[task_id])),
            )
        )
        client = _client(_user("platform_content_editor"), session)
        response = client.get(f"/v1/platform/documents/{DOC_ID}")
        assert response.status_code == 200
        body = response.json()
        assert body["typed_table"] == "notifications"
        assert body["typed_row"]["number"] == "11"
        assert body["metadata"] == {"fields": {"title": "x"}}
        assert body["versions"][0]["parser_version"] == "p1"
        assert body["sources"][0]["source_code"] == "cbic_gst_portal"
        assert body["status_history"][0]["status"] == "in_force"
        assert body["open_review_task_ids"] == [str(task_id)]
        assert response.headers["cache-control"] == "private, no-store"


class TestBlocksAndPages:
    def test_blocks_404_for_version_of_another_document(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_admin"), FakeSession())
        response = client.get(f"/v1/platform/documents/{DOC_ID}/versions/{VERSION_ID}/blocks")
        assert response.status_code == 404

    def test_blocks_filter_by_page_and_page_by_seq(self, audit: AsyncMock) -> None:
        block_rows = [
            {
                "id": uuid.uuid4(),
                "seq": seq,
                "kind": "para",
                "page": 2,
                "bbox": [1, 2, 3, 4],
                "para_label": "1",
                "structure_path": "p1",
                "is_boilerplate": False,
                "lang": "en",
                "text": f"block {seq}",
            }
            for seq in (5, 6, 7)
        ]
        session = FakeSession(
            route(
                ("WHERE dv.id = :version_id", FakeResult(rows=[_version_row()])),
                ("FROM blocks b", FakeResult(rows=block_rows)),
            )
        )
        client = _client(_user("platform_content_editor"), session)
        response = client.get(
            f"/v1/platform/documents/{DOC_ID}/versions/{VERSION_ID}/blocks",
            params={"page": 2, "after": 4, "limit": 2},
        )
        assert response.status_code == 200
        body = response.json()
        assert [item["seq"] for item in body["items"]] == [5, 6]
        assert body["next_cursor"] == 6
        (sql,) = session.sql_for("FROM blocks b")
        assert "AND b.page = :page" in sql
        assert "AND b.seq > :after" in sql
        assert "ORDER BY b.seq" in sql

    def test_pages_lists_extraction_outcomes(self, audit: AsyncMock) -> None:
        page_rows = [
            {
                "page_no": 1,
                "method": "text",
                "chars_engine_a": 900,
                "chars_engine_b": 880,
                "garble_score": 0.01,
                "ocr_conf": None,
                "status": "ok",
                "flagged": False,
            }
        ]
        session = FakeSession(
            route(
                ("WHERE dv.id = :version_id", FakeResult(rows=[_version_row()])),
                ("FROM page_extractions pe", FakeResult(rows=page_rows)),
            )
        )
        client = _client(_user("platform_admin"), session)
        response = client.get(f"/v1/platform/documents/{DOC_ID}/versions/{VERSION_ID}/pages")
        assert response.status_code == 200
        assert response.json()["items"][0]["method"] == "text"


class TestPageImage:
    def _store(self, tmp_path: Path, data: bytes) -> LocalFolderObjectStore:
        store = LocalFolderObjectStore(tmp_path / "store")
        store.put("raw/ab/abcdef", data, "application/pdf")
        return store

    def test_html_version_has_no_page_image(self, tmp_path: Path, audit: AsyncMock) -> None:
        version = _version_row(mime="text/html", page_count=None)
        session = FakeSession(route(("WHERE dv.id = :version_id", FakeResult(rows=[version]))))
        store = LocalFolderObjectStore(tmp_path / "store")
        client = _client(_user("platform_admin"), session, store)
        response = client.get(f"/v1/platform/documents/{DOC_ID}/versions/{VERSION_ID}/pages/1.png")
        assert response.status_code == 404

    def test_page_past_the_end_is_404(self, tmp_path: Path, audit: AsyncMock) -> None:
        session = FakeSession(
            route(("WHERE dv.id = :version_id", FakeResult(rows=[_version_row(page_count=2)])))
        )
        store = self._store(tmp_path, _pdf_bytes(2))
        client = _client(_user("platform_admin"), session, store)
        response = client.get(f"/v1/platform/documents/{DOC_ID}/versions/{VERSION_ID}/pages/3.png")
        assert response.status_code == 404

    def test_renders_once_then_serves_from_cache(self, tmp_path: Path, audit: AsyncMock) -> None:
        session = FakeSession(
            route(("WHERE dv.id = :version_id", FakeResult(rows=[_version_row(page_count=2)])))
        )
        store = self._store(tmp_path, _pdf_bytes(2))
        client = _client(_user("platform_admin"), session, store)
        url = f"/v1/platform/documents/{DOC_ID}/versions/{VERSION_ID}/pages/1.png"

        first = client.get(url)
        assert first.status_code == 200
        assert first.headers["content-type"] == "image/png"
        assert first.headers["cache-control"] == "private, max-age=3600"
        assert first.content[:8] == b"\x89PNG\r\n\x1a\n"
        cache_key = "derived/pages/abcdef/1-110.png"
        assert store.exists(cache_key)

        # A second request must not render again: break the renderer and expect the same bytes.
        original = platform_documents._render_page_png

        def fail(*_args: object) -> bytes:
            raise AssertionError("page should come from the cache")

        platform_documents._render_page_png = fail  # type: ignore[assignment]
        try:
            second = client.get(url)
        finally:
            platform_documents._render_page_png = original  # type: ignore[assignment]
        assert second.status_code == 200
        assert second.content == first.content

    def test_unreadable_pdf_is_404(self, tmp_path: Path, audit: AsyncMock) -> None:
        session = FakeSession(
            route(("WHERE dv.id = :version_id", FakeResult(rows=[_version_row(page_count=None)])))
        )
        store = self._store(tmp_path, b"%PDF-1.4 this is not a real pdf")
        client = _client(_user("platform_admin"), session, store)
        response = client.get(f"/v1/platform/documents/{DOC_ID}/versions/{VERSION_ID}/pages/1.png")
        assert response.status_code == 404


class TestRawFile:
    def test_streams_original_as_attachment(self, tmp_path: Path, audit: AsyncMock) -> None:
        data = _pdf_bytes(1)
        session = FakeSession(
            route(("WHERE dv.id = :version_id", FakeResult(rows=[_version_row(page_count=1)])))
        )
        store = LocalFolderObjectStore(tmp_path / "store")
        store.put("raw/ab/abcdef", data, "application/pdf")
        client = _client(_user("platform_admin"), session, store)
        response = client.get(f"/v1/platform/documents/{DOC_ID}/versions/{VERSION_ID}/raw")
        assert response.status_code == 200
        assert response.content == data
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == (
            'attachment; filename="notif_CT_11_2017.pdf"'
        )

    def test_missing_object_is_404(self, tmp_path: Path, audit: AsyncMock) -> None:
        session = FakeSession(
            route(("WHERE dv.id = :version_id", FakeResult(rows=[_version_row()])))
        )
        store = LocalFolderObjectStore(tmp_path / "store")
        client = _client(_user("platform_admin"), session, store)
        response = client.get(f"/v1/platform/documents/{DOC_ID}/versions/{VERSION_ID}/raw")
        assert response.status_code == 404


class TestDocumentPatch:
    def _session(self, status: str = "in_force", open_from: Any = None) -> FakeSession:  # noqa: ANN401
        return FakeSession(
            route(
                ("FROM documents WHERE id", FakeResult(rows=[_document_row(status=status)])),
                ("SELECT valid_from FROM document_status_history", FakeResult(scalar=open_from)),
            )
        )

    def test_professional_is_forbidden(self, audit: AsyncMock) -> None:
        client = _client(_user("professional"), self._session())
        response = client.patch(
            f"/v1/platform/documents/{DOC_ID}", json={"fields": {"title": "x"}, "reason": "fix"}
        )
        assert response.status_code == 403

    @pytest.mark.parametrize(
        "body",
        [
            {"fields": {"title": "x"}, "reason": "no"},  # reason too short
            {"fields": {"not_a_field": 1}, "reason": "typo fix"},  # unknown field
            {"fields": {}, "reason": "nothing here"},  # nothing to change
            {"reason": "status date only", "status_valid_from": "2026-01-01"},
        ],
    )
    def test_invalid_bodies_are_422(self, body: dict[str, Any], audit: AsyncMock) -> None:
        client = _client(_user("platform_content_editor"), self._session())
        response = client.patch(f"/v1/platform/documents/{DOC_ID}", json=body)
        assert response.status_code == 422

    def test_missing_document_is_404(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_content_editor"), FakeSession())
        response = client.patch(
            f"/v1/platform/documents/{DOC_ID}", json={"fields": {"title": "x"}, "reason": "fix"}
        )
        assert response.status_code == 404

    def test_field_edit_is_queued_and_audited_without_values(self, audit: AsyncMock) -> None:
        session = self._session()
        actor = _user("platform_content_editor")
        client = _client(actor, session)
        response = client.patch(
            f"/v1/platform/documents/{DOC_ID}",
            json={"fields": {"title": "A long new title", "number": "12"}, "reason": "typo fix"},
        )
        assert response.status_code == 202
        assert response.json() == {"queued": True, "status_changed": False}
        (queued,) = session.params_for("INSERT INTO job_queue")
        assert queued is not None
        payload = json.loads(queued["payload"])
        assert payload == {
            "document_id": str(DOC_ID),
            "fields": {"title": "A long new title", "number": "12"},
            "actor_user_id": str(actor.id),
            "reason": "typo fix",
            "review_task_id": None,
        }
        assert "ingest.apply_metadata" in session.sql_for("INSERT INTO job_queue")[0]
        audit.assert_awaited_once()
        assert audit.call_args.kwargs["action"] == "document.edit"
        assert audit.call_args.kwargs["detail"] == {
            "fields": ["number", "title"],
            "reason": "typo fix",
        }

    def test_status_change_closes_the_open_row(self, audit: AsyncMock) -> None:
        session = self._session(status="in_force", open_from=dt.date(2017, 7, 1))
        actor = _user("platform_admin")
        client = _client(actor, session)
        response = client.patch(
            f"/v1/platform/documents/{DOC_ID}",
            json={
                "reason": "Stayed by High Court",
                "status": "stayed",
                "status_valid_from": "2026-09-01",
            },
        )
        assert response.status_code == 202
        assert response.json() == {"queued": False, "status_changed": True}
        (close,) = session.params_for("UPDATE document_status_history")
        assert close == {"id": DOC_ID, "valid_from": dt.date(2026, 9, 1)}
        (insert,) = session.params_for("INSERT INTO document_status_history")
        assert insert is not None
        assert insert["status"] == "stayed"
        assert insert["valid_from"] == dt.date(2026, 9, 1)
        assert insert["actor"] == actor.id
        assert session.params_for("UPDATE documents SET status")[0] == {
            "id": DOC_ID,
            "status": "stayed",
        }
        assert not session.params_for("INSERT INTO job_queue")
        assert audit.call_args.kwargs["action"] == "document.status_change"
        assert audit.call_args.kwargs["detail"]["from"] == "in_force"

    def test_status_cannot_predate_the_open_row(self, audit: AsyncMock) -> None:
        session = self._session(open_from=dt.date(2026, 9, 1))
        client = _client(_user("platform_admin"), session)
        response = client.patch(
            f"/v1/platform/documents/{DOC_ID}",
            json={"reason": "too early", "status": "amended", "status_valid_from": "2026-01-01"},
        )
        assert response.status_code == 422
        assert not session.params_for("UPDATE document_status_history")

    def test_same_status_is_rejected(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_admin"), self._session(status="in_force"))
        response = client.patch(
            f"/v1/platform/documents/{DOC_ID}",
            json={"reason": "no change", "status": "in_force"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------- sources


class TestSources:
    def test_list_merges_config_with_table_rows(self, audit: AsyncMock) -> None:
        session = FakeSession(
            route(
                (
                    "SELECT code, kind, enabled, expected_cadence_hours, last_success_at",
                    FakeResult(
                        rows=[
                            {
                                "code": "cbic_gst_portal",
                                "kind": "manual",
                                "enabled": True,
                                "expected_cadence_hours": 24,
                                "last_success_at": NOW,
                                "last_new_doc_at": NOW,
                                "health": "ok",
                            }
                        ]
                    ),
                ),
            )
        )
        client = _client(_user("platform_content_editor"), session)
        response = client.get("/v1/platform/sources")
        assert response.status_code == 200
        items = {item["code"]: item for item in response.json()["items"]}
        portal = items["cbic_gst_portal"]
        assert portal["in_config"] is True
        assert portal["expected_cadence_hours"] == 24
        assert "cbic-gst.gov.in" in portal["allowed_hosts"]
        assert items["gst_council"]["enabled"] is False
        assert items["gst_council"]["config_enabled"] is False
        assert items["gst_council"]["last_success_at"] is None

    def test_list_forbidden_for_professional(self, audit: AsyncMock) -> None:
        client = _client(_user("professional"), FakeSession())
        assert client.get("/v1/platform/sources").status_code == 403

    def test_patch_needs_a_field(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_admin"), FakeSession())
        assert client.patch("/v1/platform/sources/supreme_court", json={}).status_code == 422

    def test_patch_unknown_code_is_404(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_admin"), FakeSession())
        response = client.patch("/v1/platform/sources/nowhere", json={"enabled": False})
        assert response.status_code == 404

    def test_content_editor_cannot_manage_sources(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_content_editor"), FakeSession())
        response = client.patch("/v1/platform/sources/supreme_court", json={"enabled": False})
        assert response.status_code == 403

    def test_patch_upserts_row_and_audits(self, audit: AsyncMock) -> None:
        upserted = {
            "code": "gst_council",
            "kind": "manual",
            "enabled": True,
            "expected_cadence_hours": 48,
            "last_success_at": None,
            "last_new_doc_at": None,
            "health": None,
        }
        session = FakeSession(
            route(
                ("WHERE code = :code", FakeResult(rows=[])),
                ("INSERT INTO sources", FakeResult(rows=[upserted])),
            )
        )
        actor = _user("platform_admin")
        client = _client(actor, session)
        response = client.patch(
            "/v1/platform/sources/gst_council",
            json={"enabled": True, "expected_cadence_hours": 48},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert body["expected_cadence_hours"] == 48
        assert body["config_enabled"] is False
        (upsert,) = session.params_for("INSERT INTO sources")
        assert upsert is not None
        assert upsert["enabled"] is True
        assert upsert["config_enabled"] is False
        assert upsert["cadence"] == 48
        assert upsert["actor"] == actor.id
        assert audit.call_args.kwargs["action"] == "source.update"
        assert audit.call_args.kwargs["object_id"] == "gst_council"
        assert audit.call_args.kwargs["detail"]["enabled"] == {"before": None, "after": True}


# ---------------------------------------------------------------------------- jobs


JOB_ID = uuid.uuid4()


def _job_row(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "id": JOB_ID,
        "stage": "parse",
        "status": "failed",
        "document_id": DOC_ID,
    }
    row.update(overrides)
    return row


class TestJobRetry:
    def test_professional_is_forbidden(self, audit: AsyncMock) -> None:
        client = _client(_user("professional"), FakeSession())
        assert client.post(f"/v1/platform/jobs/{JOB_ID}/retry").status_code == 403

    def test_unknown_job_is_404(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_content_editor"), FakeSession())
        assert client.post(f"/v1/platform/jobs/{JOB_ID}/retry").status_code == 404

    def test_only_failed_jobs_retry(self, audit: AsyncMock) -> None:
        session = FakeSession(route(("FOR UPDATE", FakeResult(rows=[_job_row(status="queued")]))))
        client = _client(_user("platform_content_editor"), session)
        assert client.post(f"/v1/platform/jobs/{JOB_ID}/retry").status_code == 409
        assert not session.params_for("INSERT INTO job_queue")

    def test_parse_retry_enqueues_with_current_version(self, audit: AsyncMock) -> None:
        session = FakeSession(
            route(
                ("FOR UPDATE", FakeResult(rows=[_job_row()])),
                ("SELECT current_version_id FROM documents", FakeResult(scalar=VERSION_ID)),
            )
        )
        client = _client(_user("platform_content_editor"), session)
        response = client.post(f"/v1/platform/jobs/{JOB_ID}/retry")
        assert response.status_code == 202
        assert response.json() == {"ingestion_job_id": str(JOB_ID), "queue": "ingest.parse"}
        (queued,) = session.params_for("INSERT INTO job_queue")
        assert queued is not None
        assert queued["queue"] == "ingest.parse"
        assert json.loads(queued["payload"]) == {
            "ingestion_job_id": str(JOB_ID),
            "document_version_id": str(VERSION_ID),
        }
        (reset,) = session.sql_for("UPDATE ingestion_jobs")
        assert "attempt" not in reset  # the attempt count is kept
        assert "error_code = NULL" in reset
        assert audit.call_args.kwargs["action"] == "ingest.retry"

    def test_retry_without_a_version_is_409(self, audit: AsyncMock) -> None:
        session = FakeSession(
            route(
                ("FOR UPDATE", FakeResult(rows=[_job_row(document_id=None)])),
            )
        )
        client = _client(_user("platform_content_editor"), session)
        assert client.post(f"/v1/platform/jobs/{JOB_ID}/retry").status_code == 409

    def test_acquire_retry_reuses_the_original_request(self, audit: AsyncMock) -> None:
        original = {
            "ingestion_job_id": str(JOB_ID),
            "source_code": "cbic_gst_portal",
            "doc_type": "notification",
            "url": None,
            "file_path": None,
            "object_key": "raw/ab/abcdef",
            "file_name": "ct11.pdf",
        }
        session = FakeSession(
            route(
                ("FOR UPDATE", FakeResult(rows=[_job_row(stage="acquire", document_id=None)])),
                (
                    "WHERE queue = 'ingest.acquire'",
                    FakeResult(scalar=json.dumps(original)),
                ),
            )
        )
        client = _client(_user("platform_content_editor"), session)
        response = client.post(f"/v1/platform/jobs/{JOB_ID}/retry")
        assert response.status_code == 202
        (queued,) = session.params_for("INSERT INTO job_queue")
        assert queued is not None
        assert queued["queue"] == "ingest.acquire"
        assert json.loads(queued["payload"]) == original

    def test_acquire_retry_without_original_is_409(self, audit: AsyncMock) -> None:
        session = FakeSession(route(("FOR UPDATE", FakeResult(rows=[_job_row(stage="acquire")]))))
        client = _client(_user("platform_content_editor"), session)
        assert client.post(f"/v1/platform/jobs/{JOB_ID}/retry").status_code == 409


# ---------------------------------------------------------------------------- dashboard


def _dashboard_session(overdue: int = 0, failed: int = 0, total: int = 10) -> FakeSession:
    return FakeSession(
        route(
            (
                "FILTER (WHERE status = 'failed') AS failed",
                FakeResult(rows=[{"total": total, "failed": failed}]),
            ),
            ("FROM v_ingest_daily", FakeResult(rows=[])),
            (
                "FROM v_ingest_freshness",
                FakeResult(
                    rows=[{"source_code": None, "samples": 3, "p50_hours": 2.0, "p95_hours": 14.0}]
                ),
            ),
            (
                "FROM v_source_health",
                FakeResult(
                    rows=[
                        {
                            "code": "gstat",
                            "enabled": True,
                            "expected_cadence_hours": 24,
                            "last_success_at": None,
                            "last_new_doc_at": None,
                            "hours_since_new_doc": 100.0,
                            "stale": True,
                        }
                    ]
                ),
            ),
            (
                "FROM v_review_queue",
                FakeResult(
                    rows=[
                        {
                            "kind": "amendment",
                            "status": "open",
                            "count": 1,
                            "oldest_opened_at": NOW,
                            "overdue_count": overdue,
                        }
                    ]
                ),
            ),
            ("FROM v_page_accounting", FakeResult(rows=[])),
            (
                "FROM v_cross_check_disagreements",
                FakeResult(rows=[{"compared_pages": 0, "disagreements": 0}]),
            ),
            (
                "FROM v_queue_lag",
                FakeResult(
                    rows=[
                        {
                            "queue": "ingest.parse",
                            "queued": 2,
                            "oldest_run_after": NOW,
                            "oldest_created_at": NOW,
                            "lag_minutes": 45.0,
                        }
                    ]
                ),
            ),
        )
    )


class TestDashboard:
    def test_professional_is_forbidden(self, audit: AsyncMock) -> None:
        client = _client(_user("professional"), FakeSession())
        assert client.get("/v1/platform/ingestion/dashboard").status_code == 403

    def test_all_sections_and_alerts(self, audit: AsyncMock) -> None:
        client = _client(_user("platform_content_editor"), _dashboard_session(overdue=1, failed=2))
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
        kinds = {alert["kind"] for alert in body["alerts"]}
        assert kinds == {
            "failure_rate",
            "freshness_p95",
            "stale_source",
            "overdue_review",
            "queue_lag",
        }
        overdue = next(a for a in body["alerts"] if a["kind"] == "overdue_review")
        assert overdue["subject"] == "amendment"

    def test_quiet_system_has_no_alerts(self, audit: AsyncMock) -> None:
        session = FakeSession(
            route(
                (
                    "FILTER (WHERE status = 'failed') AS failed",
                    FakeResult(rows=[{"total": 0, "failed": 0}]),
                ),
                ("FROM v_source_health", FakeResult(rows=[])),
                ("FROM v_queue_lag", FakeResult(rows=[])),
                ("FROM v_review_queue", FakeResult(rows=[])),
                ("FROM v_ingest_freshness", FakeResult(rows=[])),
                (
                    "FROM v_cross_check_disagreements",
                    FakeResult(rows=[{"compared_pages": 0, "disagreements": 0}]),
                ),
            )
        )
        client = _client(_user("platform_admin"), session)
        assert client.get("/v1/platform/ingestion/dashboard").json()["alerts"] == []


# ---------------------------------------------------------------------------- miss reports


class TestMissReports:
    def test_user_without_roles_is_forbidden(self, audit: AsyncMock) -> None:
        client = _client(_user(), FakeSession())
        response = client.post("/v1/miss-reports", json={"query": "section 16"})
        assert response.status_code == 403

    def test_empty_query_is_422(self, audit: AsyncMock) -> None:
        client = _client(_user("client_viewer"), FakeSession())
        assert client.post("/v1/miss-reports", json={"query": ""}).status_code == 422

    def test_round_robin_between_two_editors(self, audit: AsyncMock) -> None:
        first, second = sorted([uuid.uuid4(), uuid.uuid4()], key=str)
        last_assignee: dict[str, Any] = {"value": None}

        def last(_params: dict[str, Any] | None) -> FakeResult:
            return FakeResult(scalar=last_assignee["value"])

        def insert(params: dict[str, Any] | None) -> FakeResult:
            assert params is not None
            last_assignee["value"] = params["assignee"]
            return FakeResult(scalar=uuid.uuid4())

        session = FakeSession(
            route(
                ("SELECT DISTINCT u.id", FakeResult(rows=[first, second])),
                ("ORDER BY created_at DESC, id DESC LIMIT 1", last),
                ("INSERT INTO review_tasks", insert),
            )
        )
        client = _client(_user("junior"), session)
        payload = {"query": "section 16 refund", "filters": {"series": "CT"}, "as_on": "2026-03-31"}

        created = client.post("/v1/miss-reports", json=payload)
        assert created.status_code == 201
        assert uuid.UUID(created.json()["id"])

        client.post("/v1/miss-reports", json=payload)
        client.post("/v1/miss-reports", json=payload)

        assignees = [p["assignee"] for p in session.params_for("INSERT INTO review_tasks")]
        assert assignees == [first, second, first]

        insert_params = session.params_for("INSERT INTO review_tasks")[0]
        assert insert_params is not None
        assert insert_params["priority"] == 4
        report = json.loads(insert_params["resolution"])["report"]
        assert report["query"] == "section 16 refund"
        assert report["filters"] == {"series": "CT"}
        assert report["as_on"] == "2026-03-31"
        assert report["reported_by"] is not None
        assert audit.call_args.kwargs["action"] == "miss_report.create"

    def test_no_editors_leaves_task_unassigned(self, audit: AsyncMock) -> None:
        session = FakeSession(route(("INSERT INTO review_tasks", FakeResult(scalar=uuid.uuid4()))))
        client = _client(_user("partner"), session)
        assert client.post("/v1/miss-reports", json={"query": "x"}).status_code == 201
        (insert_params,) = session.params_for("INSERT INTO review_tasks")
        assert insert_params is not None
        assert insert_params["assignee"] is None


# ---------------------------------------------------------------------------- manual upload


SOURCE_ID = uuid.uuid4()
NEW_JOB_ID = uuid.uuid4()


def _upload_session(enabled: Any = True) -> FakeSession:  # noqa: ANN401
    return FakeSession(
        route(
            ("INSERT INTO sources", FakeResult(scalar=SOURCE_ID)),
            ("SELECT enabled FROM sources", FakeResult(scalar=enabled)),
            ("INSERT INTO ingestion_jobs", FakeResult(scalar=NEW_JOB_ID)),
        )
    )


class TestManualUpload:
    FORM: dict[str, str] = {
        "source": "cbic_gst_portal",
        "doc_type": "notification",
        "series": "CT",
        "number": "11",
        "year": "2017",
    }

    def test_professional_is_forbidden(self, tmp_path: Path, audit: AsyncMock) -> None:
        store = LocalFolderObjectStore(tmp_path / "store")
        client = _client(_user("professional"), FakeSession(), store)
        response = client.post(
            "/v1/platform/ingestion/manual",
            data=self.FORM,
            files={"file": ("ct11.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert response.status_code == 403

    def test_unknown_doc_type_is_422(self, tmp_path: Path, audit: AsyncMock) -> None:
        store = LocalFolderObjectStore(tmp_path / "store")
        client = _client(_user("platform_content_editor"), FakeSession(), store)
        response = client.post(
            "/v1/platform/ingestion/manual",
            data={**self.FORM, "doc_type": "poem"},
            files={"file": ("ct11.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert response.status_code == 422

    def test_text_file_is_415(self, tmp_path: Path, audit: AsyncMock) -> None:
        store = LocalFolderObjectStore(tmp_path / "store")
        session = _upload_session()
        client = _client(_user("platform_content_editor"), session, store)
        response = client.post(
            "/v1/platform/ingestion/manual",
            data=self.FORM,
            files={"file": ("notes.txt", b"just some words", "text/plain")},
        )
        assert response.status_code == 415
        assert not session.params_for("INSERT INTO ingestion_jobs")

    def test_file_over_the_cap_is_413(
        self, tmp_path: Path, audit: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ingestion, "MAX_UPLOAD_BYTES", 1000)
        store = LocalFolderObjectStore(tmp_path / "store")
        session = _upload_session()
        client = _client(_user("platform_content_editor"), session, store)
        response = client.post(
            "/v1/platform/ingestion/manual",
            data=self.FORM,
            files={"file": ("big.pdf", b"%PDF-1.4" + b"0" * 2000, "application/pdf")},
        )
        assert response.status_code == 413
        assert not session.params_for("INSERT INTO ingestion_jobs")

    def test_pdf_is_stored_once_and_acquire_is_queued(
        self, tmp_path: Path, audit: AsyncMock
    ) -> None:
        store = LocalFolderObjectStore(tmp_path / "store")
        data = _pdf_bytes(1)
        session = _upload_session()
        client = _client(_user("platform_content_editor"), session, store)
        response = client.post(
            "/v1/platform/ingestion/manual",
            data={**self.FORM, "title": "  Notification 11  "},
            files={"file": ("C:\\\\uploads\\\\ct11.pdf", data, "application/pdf")},
        )
        assert response.status_code == 202
        assert response.json() == {"ingestion_job_id": str(NEW_JOB_ID)}

        sha = hashlib.sha256(data).hexdigest()
        key = f"raw/{sha[:2]}/{sha}"
        assert store.get(key) == data

        (queued,) = session.params_for("INSERT INTO job_queue")
        assert queued is not None
        payload = json.loads(queued["payload"])
        assert payload["object_key"] == key
        assert payload["file_name"] == "ct11.pdf"
        assert payload["url"] is None
        assert payload["doc_type"] == "notification"
        assert payload["title"] == "Notification 11"
        assert payload["ingestion_job_id"] == str(NEW_JOB_ID)
        assert queued["idempotency_key"] == str(NEW_JOB_ID)
        assert "ingest.acquire" in session.sql_for("INSERT INTO job_queue")[0]
        assert audit.call_args.kwargs["action"] == "ingest.upload"
        assert audit.call_args.kwargs["detail"]["sha256"] == sha

    def test_disabled_in_the_table_is_422(self, tmp_path: Path, audit: AsyncMock) -> None:
        store = LocalFolderObjectStore(tmp_path / "store")
        client = _client(_user("platform_content_editor"), _upload_session(enabled=False), store)
        response = client.post(
            "/v1/platform/ingestion/manual",
            data=self.FORM,
            files={"file": ("ct11.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert response.status_code == 422
        assert "disabled" in response.json()["detail"]


class TestUrlSubmissionRespectsTableFlag:
    def test_url_submit_rejected_when_disabled_in_the_table(self, audit: AsyncMock) -> None:
        session = _upload_session(enabled=False)
        client = _client(_user("platform_admin"), session)
        response = client.post(
            "/v1/platform/ingestion/url",
            json={
                "source": "cbic_gst_portal",
                "doc_type": "notification",
                "url": "https://www.cbic-gst.gov.in/gst/notifications/ct11-2017.pdf",
            },
        )
        assert response.status_code == 422
        assert "disabled" in response.json()["detail"]
        assert not session.params_for("INSERT INTO ingestion_jobs")
