"""Tests for loader validation, canonical IDs and payloads (no database)."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from worker.config import clear_caches
from worker.ingest.loaders import (
    LoadError,
    LoadRequest,
    canonical_id_for,
    default_title,
    request_from_payload,
    request_to_payload,
    submit,
    validate_request,
)


@pytest.fixture(autouse=True)
def fresh_caches() -> None:
    clear_caches()


class _NoConnection:
    """Stands in for a connection. Any use of it fails the test."""

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        raise AssertionError(f"database used during validation: {name}")


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        (
            LoadRequest("nope", "notification", url="https://cbic-gst.gov.in/a.pdf"),
            "unknown source",
        ),
        (
            LoadRequest("gst_council", "notification", url="https://cbic-gst.gov.in/a.pdf"),
            "disabled",
        ),
        (LoadRequest("cbic_gst_portal", "poem", url="https://cbic-gst.gov.in/a.pdf"), "doc_type"),
        (LoadRequest("cbic_gst_portal", "notification"), "exactly one"),
        (
            LoadRequest(
                "cbic_gst_portal",
                "notification",
                url="https://cbic-gst.gov.in/a.pdf",
                file_path="/tmp/a.pdf",
            ),
            "exactly one",
        ),
    ],
)
def test_invalid_requests_are_refused_before_any_write(request_: LoadRequest, message: str) -> None:
    """Bad source, doc_type or input choice raises LoadError and never touches the database."""
    with pytest.raises(LoadError, match=message):
        submit(_NoConnection(), request_)  # type: ignore[arg-type]


def test_valid_request_returns_source() -> None:
    """A valid request validates and returns its source config."""
    source = validate_request(LoadRequest("cbic_gst_portal", "act", file_path="/x/act.pdf"))
    assert source.code == "cbic_gst_portal"


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        (
            LoadRequest("cbic_gst_portal", "notification", series="ct", number="11", year="2017"),
            "ntf:CT:11/2017",
        ),
        (
            LoadRequest("cbic_gst_portal", "notification", series="CT(R)", number="5", year="2019"),
            "ntf:CT(R):5/2019",
        ),
        (
            LoadRequest(
                "cbic_gst_portal", "circular", circular_a="183", circular_b="15", year="2022"
            ),
            "cir:183/15/2022",
        ),
        (
            LoadRequest("cbic_gst_portal", "instruction", number="123", year="2022"),
            "ins:123/2022",
        ),
        (LoadRequest("cbic_gst_portal", "order", number="456", year="2022"), "ord:456/2022"),
        (
            LoadRequest(
                "supreme_court",
                "judgement",
                court_code="sc",
                case_number="2023/123/SC",
                decision_date="2023-10-08",
            ),
            "jdg:SC:2023/123/SC:2023-10-08",
        ),
    ],
)
def test_canonical_id_for_each_type(request_: LoadRequest, expected: str) -> None:
    """Complete metadata gives the legal_core canonical ID."""
    assert canonical_id_for(request_) == expected


@pytest.mark.parametrize(
    "request_",
    [
        LoadRequest("cbic_gst_portal", "notification", series="CT", number="11"),
        LoadRequest("cbic_gst_portal", "circular", circular_a="183", year="2022"),
        LoadRequest("cbic_gst_portal", "instruction", number="123"),
        LoadRequest("cbic_gst_portal", "judgement", court_code="SC", case_number="1/2023"),
        LoadRequest("cbic_gst_portal", "act", series="CT", number="11", year="2017"),
        LoadRequest("cbic_gst_portal", "other", title="Circular text"),
    ],
)
def test_incomplete_or_untyped_metadata_has_no_canonical_id(request_: LoadRequest) -> None:
    """Without the fields a type needs, the canonical ID is None (the provisional ID applies)."""
    assert canonical_id_for(request_) is None


def test_bad_metadata_raises_value_error() -> None:
    """Metadata that is present but invalid is an error, not a silent None."""
    with pytest.raises(ValueError, match="unknown notification series"):
        canonical_id_for(
            LoadRequest("cbic_gst_portal", "notification", series="ZZ", number="1", year="2017")
        )
    with pytest.raises(ValueError):
        canonical_id_for(
            LoadRequest("cbic_gst_portal", "notification", series="CT", number="11", year="17")
        )


def test_payload_round_trip() -> None:
    """The acquire payload rebuilds the same request."""
    req = LoadRequest(
        "cbic_gst_portal",
        "notification",
        file_path="/watch/a.pdf",
        series="CT",
        number="11",
        year="2017",
        title="Notification 11",
    )
    job_id = uuid.uuid4()
    payload = request_to_payload(req, job_id)
    assert payload["ingestion_job_id"] == str(job_id)
    assert request_from_payload(payload) == req


@pytest.mark.parametrize(
    ("req", "expected"),
    [
        (LoadRequest("s", "act", file_path="/watch/x/CGST Act 2017.pdf"), "CGST Act 2017.pdf"),
        (
            LoadRequest(
                "s",
                "act",
                file_path="/watch/.done/20261008/3f2a1c9e-0000-4000-8000-000000000001__act.pdf",
            ),
            "act.pdf",
        ),
        (LoadRequest("s", "act", url="https://a.example/docs/Notice%2011.pdf"), "Notice 11.pdf"),
        (LoadRequest("s", "act", url="https://a.example/"), "Untitled"),
        (LoadRequest("s", "act", url="https://a.example/x.pdf", title="Chosen"), "Chosen"),
    ],
)
def test_default_title(req: LoadRequest, expected: str) -> None:
    """File name, last URL segment, or the title given."""
    assert default_title(req) == expected


def test_watch_prefix_is_only_removed_from_names(tmp_path: Path) -> None:
    """A name that merely looks like a watch prefix keeps its text when it is not a UUID."""
    req = LoadRequest("s", "act", file_path=str(tmp_path / "not-a-uuid__act.pdf"))
    assert default_title(req) == "not-a-uuid__act.pdf"
