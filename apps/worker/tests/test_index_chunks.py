"""Unit tests for worker indexing stage (no live database)."""

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from worker.errors import PermanentError
from worker.ingest.index_chunks import (
    index_document,
    index_provisions,
    make_index_handler,
)
from worker.queue import Job


def test_index_document_not_found() -> None:
    mock_conn = MagicMock()
    mock_conn.execute.return_value.first.return_value = None

    with pytest.raises(PermanentError, match="document not found"):
        index_document(mock_conn, uuid4())


def test_index_document_no_blocks() -> None:
    doc_id = uuid4()
    ver_id = uuid4()
    mock_conn = MagicMock()

    # 1. doc_row
    doc_row = (
        doc_id,
        "Notification 11/2017",
        "notification",
        5,
        "in_force",
        date(2017, 6, 28),
        None,
        None,
    )
    # 2. ver_row
    ver_row = (ver_id,)

    mock_conn.execute.return_value.first.side_effect = [doc_row, ver_row]
    # blocks is empty
    mock_conn.execute.return_value.mappings.return_value.all.return_value = []

    count = index_document(mock_conn, doc_id)
    assert count == 0


def test_index_document_success() -> None:
    doc_id = uuid4()
    ver_id = uuid4()
    b_id = uuid4()
    mock_conn = MagicMock()
    mock_conn.dialect.name = "postgresql"

    doc_row = (doc_id, "Circular 183", "circular", 8, "in_force", date(2022, 12, 27), None, None)
    circ_row = ("Subject clarification",)

    mock_conn.execute.return_value.first.side_effect = [doc_row, circ_row]
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "id": b_id,
            "seq": 1,
            "kind": "paragraph",
            "page": 1,
            "para_label": "1",
            "structure_path": "p1",
            "text": "This is a detailed paragraph explaining input tax credit rules.",
            "is_boilerplate": False,
        }
    ]

    count = index_document(mock_conn, doc_id, ver_id)
    assert count == 1
    # Check that update and insert were executed
    assert mock_conn.execute.call_count >= 3


def test_index_provisions_empty() -> None:
    mock_conn = MagicMock()
    mock_conn.execute.return_value.mappings.return_value.all.return_value = []

    count = index_provisions(mock_conn, instrument_id=uuid4())
    assert count == 0


def test_index_provisions_success() -> None:
    inst_id = uuid4()
    prov_id = uuid4()
    pv_id = uuid4()
    mock_conn = MagicMock()
    mock_conn.dialect.name = "postgresql"

    prov_row = {
        "provision_id": prov_id,
        "instrument_id": inst_id,
        "path": "ch5.s16",
        "level": "section",
        "instrument_name": "CGST Act",
        "instrument_kind": "act",
        "baseline_document_id": uuid4(),
        "provision_version_id": pv_id,
        "heading": "Eligibility for credit",
        "text": "Every registered person is entitled...",
        "valid_from": date(2017, 7, 1),
        "valid_to": None,
        "rec_to": None,
        "block_ids": [uuid4()],
    }

    mock_conn.execute.return_value.mappings.return_value.all.return_value = [prov_row]

    count = index_provisions(mock_conn, instrument_id=inst_id)
    # 1 leaf + 1 section summary = 2 chunks
    assert count == 2


def test_make_index_handler_dispatch() -> None:
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    handler = make_index_handler(mock_engine)

    # Invalid payload
    with pytest.raises(PermanentError, match="index payload requires"):
        handler(Job(id="1", queue="ingest.index", payload={}, attempts=1, status="running"))
