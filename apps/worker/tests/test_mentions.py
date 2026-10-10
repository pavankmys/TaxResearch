"""Unit tests for mention indexer (no live database)."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from worker.ingest.mentions import (
    chapterless_pattern,
    extract_mentions_from_blocks,
    index_document_mentions,
)


def test_chapterless_pattern() -> None:
    p = chapterless_pattern("s16.2.c")
    assert p == r"^(ch[0-9]+\.)?s16\.2\.c$"

    with pytest.raises(ValueError, match="invalid characters"):
        chapterless_pattern("s16; DROP TABLE")


def test_extract_mentions_from_blocks() -> None:
    b1_id = uuid4()
    b2_id = uuid4()

    blocks = [
        {
            "id": b1_id,
            "text": "As per section 16(2)(c) of CGST Act, tax must be paid to Government.",
        },
        {
            "id": b2_id,
            "text": "This paragraph has no citations at all.",
        },
    ]

    mentions = extract_mentions_from_blocks(blocks, default_instrument="CGST_ACT")
    assert len(mentions) >= 1
    m0 = mentions[0]
    assert m0["source_block_id"] == b1_id
    assert m0["instrument_code"] == "CGST_ACT"
    assert "s16" in m0["target_path"]


def test_index_document_mentions_no_version() -> None:
    mock_conn = MagicMock()
    mock_conn.execute.return_value.first.return_value = None

    count = index_document_mentions(mock_conn, uuid4())
    assert count == 0


def test_index_document_mentions_success() -> None:
    doc_id = uuid4()
    ver_id = uuid4()
    b_id = uuid4()
    inst_id = uuid4()
    prov_id = uuid4()

    mock_conn = MagicMock()

    # 1. ver_row
    ver_row = (ver_id,)
    # 2. block_rows
    block_rows = [{"id": b_id, "text": "Under section 16(2)(c) of CGST Act, conditions apply."}]
    # 3. inst_rows
    inst_rows = [("CGST_ACT", inst_id)]
    # 4. prov_row
    prov_row = (prov_id,)

    mock_conn.execute.return_value.first.side_effect = [ver_row, prov_row]
    mock_conn.execute.return_value.mappings.return_value.all.return_value = block_rows
    mock_conn.execute.return_value.all.return_value = inst_rows

    count = index_document_mentions(mock_conn, doc_id)
    assert count == 1
    # Check that delete and insert into links were called
    assert mock_conn.execute.call_count >= 5
