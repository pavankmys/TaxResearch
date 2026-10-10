"""Unit tests for the consolidation engine (no live database)."""

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from worker.errors import PermanentError
from worker.ingest.consolidate import (
    consolidate_for,
    consolidate_provision,
    op_to_link_type,
)


def test_op_to_link_type() -> None:
    assert op_to_link_type("insert") == "inserts"
    assert op_to_link_type("substitute") == "substitutes"
    assert op_to_link_type("omit") == "omits"
    assert op_to_link_type("amend") == "amends"
    assert op_to_link_type("rescind") == "rescinds"
    assert op_to_link_type("supersede") == "supersedes"
    assert op_to_link_type("unknown") == "amends"


def test_consolidate_for_missing_payload() -> None:
    mock_conn = MagicMock()
    with pytest.raises(PermanentError, match="needs provision_id or amendment_id"):
        consolidate_for(mock_conn, {})


def test_consolidate_provision_not_found() -> None:
    mock_conn = MagicMock()
    mock_conn.execute.return_value.first.return_value = None
    with pytest.raises(PermanentError, match="provision not found"):
        consolidate_provision(mock_conn, uuid4())


def test_consolidate_provision_success() -> None:
    prov_id = uuid4()
    inst_id = uuid4()
    amend_id = uuid4()
    source_doc_id = uuid4()
    source_block_id = uuid4()

    mock_conn = MagicMock()

    # 1. prov_row
    prov_row = (prov_id, inst_id, "s10")
    # 2. baseline_row
    baseline_row = (
        uuid4(),
        "The registered person shall pay tax at twenty per cent.",
        date(2017, 7, 1),
        [uuid4()],
    )

    mock_conn.execute.return_value.first.side_effect = [
        prov_row,
        baseline_row,
        None,  # existing_link check (first() returns None -> link inserted)
    ]

    # amend_rows
    amend_row = (
        amend_id,
        "substitute",
        "twenty per cent.",
        "ten per cent.",
        date(2026, 1, 1),
        "on_date",
        {"kind": "words", "instrument": "CGST_ACT"},
        source_doc_id,
        source_block_id,
        uuid4(),  # reviewer_id
        date(2025, 12, 15),  # doc_date
        source_doc_id,  # doc_id
    )

    # active_rows before consolidation
    active_row = (
        baseline_row[0],
        date(2017, 7, 1),
        None,
        "The registered person shall pay tax at twenty per cent.",
        None,
    )

    mock_conn.execute.return_value.all.side_effect = [
        [amend_row],
        [active_row],
    ]

    res = consolidate_provision(mock_conn, prov_id, triggering_amendment_id=amend_id)
    assert res["provision_id"] == str(prov_id)
    assert res["intervals_count"] == 2
    assert res["versions_written"] == 2
    assert res["failures"] == []


def test_consolidate_provision_idempotent() -> None:
    prov_id = uuid4()
    inst_id = uuid4()
    amend_id = uuid4()
    source_doc_id = uuid4()

    mock_conn = MagicMock()

    prov_row = (prov_id, inst_id, "s10")
    baseline_row = (
        uuid4(),
        "The registered person shall pay tax at twenty per cent.",
        date(2017, 7, 1),
        [],
    )

    mock_conn.execute.return_value.first.side_effect = [
        prov_row,
        baseline_row,
        (uuid4(),),  # existing_link found
    ]

    amend_row = (
        amend_id,
        "substitute",
        "twenty per cent.",
        "ten per cent.",
        date(2026, 1, 1),
        "on_date",
        {"kind": "words", "instrument": "CGST_ACT"},
        source_doc_id,
        None,
        None,
        date(2025, 12, 15),
        source_doc_id,
    )

    # Already active rows match planned intervals
    active_rows = [
        (
            uuid4(),
            date(2017, 7, 1),
            date(2026, 1, 1),
            "The registered person shall pay tax at twenty per cent.",
            None,
        ),
        (
            uuid4(),
            date(2026, 1, 1),
            None,
            "The registered person shall pay tax at ten per cent.",
            amend_id,
        ),
    ]

    mock_conn.execute.return_value.all.side_effect = [
        [amend_row],
        active_rows,
    ]

    res = consolidate_provision(mock_conn, prov_id)
    assert res["versions_written"] == 0
