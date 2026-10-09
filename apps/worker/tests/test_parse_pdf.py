"""Tests for the PDF parser on synthetic fixtures (no database)."""

import pytest
from worker.ingest.ocr import tesseract_available
from worker.ingest.pdf import parse_pdf
from worker.ingest.types import ParseConfig
from worker.testing.pdf_fixtures import (
    born_digital,
    cid_garbled,
    scanned,
    two_column,
    with_diagonal_watermark,
    with_table,
)

_LONG = " ".join(["The rate of tax on the supply of goods shall be as notified"] * 6) + "."


def _paragraphs(count: int) -> list[str]:
    return [f"{n}. {_LONG} Paragraph {n} ends here." for n in range(1, count + 1)]


def _fixtures() -> dict[str, bytes]:
    return {
        "born_digital": born_digital(_paragraphs(3), pages=3),
        "two_column": two_column(
            [
                f"{n}. " + "Left column text about registration and the periods. " * 6
                for n in (1, 3)
            ],
            [f"{n}. " + "Right column text about returns and the dates. " * 6 for n in (2, 4)],
        ),
        "table": with_table(["Item", "Rate"], [["Cement", "28%"], ["Steel", "18%"]]),
        "cid": cid_garbled(),
    }


@pytest.mark.parametrize("name", ["born_digital", "two_column", "table", "cid"])
def test_page_accounting_matches_page_count(name: str) -> None:
    result = parse_pdf(_fixtures()[name], ParseConfig())
    assert result.page_count >= 1
    assert len(result.pages) == result.page_count
    assert [p.page_no for p in result.pages] == list(range(1, result.page_count + 1))


def test_born_digital_reading_order_and_labels() -> None:
    result = parse_pdf(born_digital(_paragraphs(3), pages=3), ParseConfig())
    assert [p.method for p in result.pages] == ["text", "text", "text"]
    body = [b for b in result.blocks if b.kind == "para" and not b.is_boilerplate]
    assert [b.para_label for b in body] == ["1", "2", "3"]
    assert [b.page for b in body] == [1, 2, 3]
    assert [b.seq for b in result.blocks] == list(range(len(result.blocks)))
    assert all(b.lang == "en" for b in body)
    assert all(b.bbox is not None for b in body)


def test_header_and_footer_are_flagged_boilerplate_but_kept() -> None:
    result = parse_pdf(born_digital(_paragraphs(3), pages=3), ParseConfig())
    header = [b for b in result.blocks if b.text == "CBIC Notification"]
    footer = [b for b in result.blocks if b.text.startswith("Page ")]
    assert len(header) == 3 and all(b.is_boilerplate for b in header)
    assert len(footer) == 3 and all(b.is_boilerplate for b in footer)
    assert all(not b.is_boilerplate for b in result.blocks if b.para_label)


def test_two_page_document_has_no_boilerplate() -> None:
    # The boilerplate rule needs at least three pages.
    result = parse_pdf(born_digital(_paragraphs(2), pages=2), ParseConfig())
    assert not any(b.is_boilerplate for b in result.blocks)


def test_two_column_reads_left_then_right() -> None:
    result = parse_pdf(_fixtures()["two_column"], ParseConfig())
    paragraphs = [b for b in result.blocks if b.kind == "para"]
    labels = [b.para_label for b in paragraphs]
    assert labels == ["1", "3", "2", "4"]
    left_xs = [b.bbox["x0"] for b in paragraphs if b.para_label in ("1", "3")]
    right_xs = [b.bbox["x0"] for b in paragraphs if b.para_label in ("2", "4")]
    assert max(left_xs) < min(right_xs)


def test_table_emits_table_and_rows_with_header_prefix() -> None:
    result = parse_pdf(_fixtures()["table"], ParseConfig())
    tables = [b for b in result.blocks if b.kind == "table"]
    rows = [b for b in result.blocks if b.kind == "table_row"]
    assert len(tables) == 1
    assert "Item | Rate" in tables[0].text
    assert tables[0].bbox is not None
    assert [r.text for r in rows] == ["Item: Cement; Rate: 28%", "Item: Steel; Rate: 18%"]
    # Table words are not repeated as paragraph blocks.
    assert not any("Cement" in b.text for b in result.blocks if b.kind == "para")


def test_broken_text_layer_is_not_text_method_and_is_flagged() -> None:
    result = parse_pdf(cid_garbled(), ParseConfig(ocr_enabled=False))
    page = result.pages[0]
    assert page.method != "text"
    assert page.flagged is True
    assert page.status in ("failed", "flagged")


def test_broken_text_layer_with_ocr_disabled_reports_unavailable() -> None:
    result = parse_pdf(cid_garbled(), ParseConfig(ocr_enabled=False))
    page = result.pages[0]
    assert page.method == "failed"
    assert page.status == "failed"
    assert page.reason is not None and page.reason.startswith("ocr_unavailable")
    assert result.blocks == []


def test_scanned_page_without_ocr_is_failed() -> None:
    result = parse_pdf(
        scanned("The Central Goods and Services Tax Act"), ParseConfig(ocr_enabled=False)
    )
    assert len(result.pages) == 1
    page = result.pages[0]
    assert page.method == "failed"
    assert page.status == "failed"
    assert page.flagged is True
    assert page.reason == "ocr_unavailable:no_text"
    assert result.ocr_used is False


@pytest.mark.skipif(not tesseract_available(), reason="tesseract is not installed")
def test_scanned_page_is_ocred() -> None:
    result = parse_pdf(
        scanned("The Central Goods and Services Tax Act\nSection 16 input tax credit"),
        ParseConfig(),
    )
    page = result.pages[0]
    assert page.method == "ocr"
    assert page.ocr_conf is not None and page.ocr_conf >= 60
    assert page.status == "ok"
    assert page.flagged is False
    text = page.text.lower()
    assert "goods" in text and "services" in text and "credit" in text
    assert result.ocr_used is True
    assert result.ocr_conf is not None and result.ocr_conf >= 60
    assert any(b.kind == "para" and b.page == 1 and b.bbox is None for b in result.blocks)


def test_diagonal_watermark_is_dropped_from_blocks() -> None:
    result = parse_pdf(with_diagonal_watermark(_paragraphs(2)), ParseConfig())
    text = " ".join(b.text for b in result.blocks)
    assert "SampleMark" not in text
    assert not any(len(b.text.strip()) == 1 for b in result.blocks)
    body = [b for b in result.blocks if b.kind == "para" and not b.is_boilerplate]
    assert [b.para_label for b in body] == ["1", "2"]
