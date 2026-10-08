"""Unit tests for the pure helpers of the parse stage (no database)."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from worker.errors import PermanentError
from worker.ingest.html import PARSER_VERSION as HTML_VERSION
from worker.ingest.parse import (
    block_rows,
    check_page_accounting,
    current_parser_version,
    page_extraction_rows,
    parse_config_from,
    problem_pages,
)
from worker.ingest.types import Block, PageResult, ParseConfig, ParseResult

_VERSION_ID = UUID("0195c0de-0000-7000-8000-000000000001")
_NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _page(page_no: int, status: str = "ok", flagged: bool = False, text: str = "t") -> PageResult:
    return PageResult(
        page_no=page_no,
        method="text",
        chars_engine_a=len(text),
        chars_engine_b=len(text),
        garble_score=0.0,
        ocr_conf=None,
        status=status,
        flagged=flagged,
        text=text,
        reason="garbled" if flagged else None,
    )


def test_block_rows_hash_text_and_keep_layout() -> None:
    block = Block(
        seq=4,
        kind="para",
        page=2,
        bbox={"x0": 1.0, "top": 2.0, "x1": 3.0, "bottom": 4.0},
        para_label="23",
        text="23. Hello",
        is_boilerplate=False,
        lang="en",
    )
    [row] = block_rows(_VERSION_ID, [block])
    assert row["document_version_id"] == _VERSION_ID
    assert row["seq"] == 4
    assert row["page"] == 2
    assert row["bbox"] == block.bbox
    assert row["para_label"] == "23"
    assert row["structure_path"] is None
    assert row["text_sha256"] == hashlib.sha256(b"23. Hello").hexdigest()


def test_page_extraction_rows_carry_one_row_per_page() -> None:
    rows = page_extraction_rows(_VERSION_ID, [_page(1), _page(2, "flagged", True)], _NOW)
    assert [row["page_no"] for row in rows] == [1, 2]
    assert rows[1]["status"] == "flagged"
    assert rows[1]["flagged"] is True
    assert rows[0]["updated_at"] == _NOW


def test_problem_pages_lists_failed_or_flagged_only() -> None:
    failed = PageResult(
        page_no=3,
        method="failed",
        chars_engine_a=None,
        chars_engine_b=None,
        garble_score=None,
        ocr_conf=None,
        status="failed",
        flagged=True,
        text="",
        reason="exception: ValueError",
    )
    pages = [_page(1), _page(2, "flagged", True), failed]
    assert problem_pages(pages) == [
        {"page_no": 2, "status": "flagged", "reason": "garbled"},
        {"page_no": 3, "status": "failed", "reason": "exception: ValueError"},
    ]
    assert problem_pages([_page(1)]) == []


def _result(page_count: int, pages: int) -> ParseResult:
    return ParseResult(
        page_count=page_count,
        pages=[_page(n) for n in range(1, pages + 1)],
        blocks=[],
        ocr_used=False,
        ocr_conf=None,
        parser_version="pdf-1",
    )


def test_page_accounting_accepts_matching_counts() -> None:
    check_page_accounting(_result(2, 2), stored_rows=2)


@pytest.mark.parametrize(("page_count", "pages", "stored"), [(3, 2, 2), (2, 2, 1), (2, 1, 2)])
def test_page_accounting_rejects_mismatch(page_count: int, pages: int, stored: int) -> None:
    with pytest.raises(RuntimeError, match="page accounting mismatch"):
        check_page_accounting(_result(page_count, pages), stored_rows=stored)


def test_parse_config_ignores_unknown_keys() -> None:
    cfg = parse_config_from({"garble_threshold": 0.2, "ocr_dpi": 200, "unknown_key": 1})
    assert cfg == ParseConfig(garble_threshold=0.2, ocr_dpi=200)


def test_current_parser_version_by_mime() -> None:
    cfg = ParseConfig()
    assert current_parser_version("application/pdf", cfg) == cfg.parser_version
    assert current_parser_version("text/html", cfg) == HTML_VERSION
    assert current_parser_version("application/xhtml+xml", cfg) == HTML_VERSION
    with pytest.raises(PermanentError, match="no parser"):
        current_parser_version("application/msword", cfg)
