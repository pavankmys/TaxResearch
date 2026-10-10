"""Unit tests for amendment dry-run diff generation (no database)."""

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from worker.ingest.amend_apply import apply_op, op_from_amendment
from worker.ingest.detect_amendments import detect_amendments_for


def test_dry_run_diff_substitute_words_success() -> None:
    current_text = "The registered person shall pay interest at twenty per cent."
    locator = {"kind": "words", "instrument": "CGST_ACT"}
    op = op_from_amendment("substitute", "twenty per cent.", "ten per cent.", locator)
    assert op is not None
    result = apply_op(current_text, op)
    assert result.ok is True
    assert "[-twenty-]{+ten+} per cent." in result.diff


def test_dry_run_diff_substitute_words_failure() -> None:
    current_text = "The registered person shall pay interest at twenty per cent."
    locator = {"kind": "words", "instrument": "CGST_ACT"}
    op = op_from_amendment("substitute", "thirty per cent.", "ten per cent.", locator)
    assert op is not None
    result = apply_op(current_text, op)
    assert result.ok is False
    assert result.reason == "old_text_not_found"


def test_dry_run_diff_insert_words_success() -> None:
    current_text = "Every person who is liable to be registered under law."
    locator = {
        "kind": "words",
        "instrument": "CGST_ACT",
        "anchor_text": "registered",
        "position": "after",
    }
    op = op_from_amendment("insert", None, "with GSTN", locator)
    assert op is not None
    result = apply_op(current_text, op)
    assert result.ok is True
    assert "{+with GSTN+}" in result.diff


def test_dry_run_diff_omit_words_success() -> None:
    current_text = "The tax shall be paid in cash or credit immediately."
    locator = {"kind": "words", "instrument": "CGST_ACT"}
    op = op_from_amendment("omit", "or credit", None, locator)
    assert op is not None
    result = apply_op(current_text, op)
    assert result.ok is True
    assert "[-or credit-]" in result.diff


def test_dry_run_in_detect_amendments_for_mocked_conn() -> None:
    """Test detect_amendments_for dry-run diff integration with mock connection."""
    doc_id = uuid4()
    version_id = uuid4()
    prov_id = uuid4()
    inst_id = uuid4()

    mock_conn = MagicMock()

    # 1. doc_row
    # 2. instrument_row
    # 3. prov_version_row
    mock_conn.execute.return_value.first.side_effect = [
        (version_id, date(2026, 6, 1)),  # doc_row
        (inst_id,),  # instrument_row
        ("The registered person shall pay tax at twenty per cent.",),  # prov_version_row
        None,  # has_open_review_task
    ]

    # blocks query, kept query (empty), editor_ids query
    text = (
        "In exercise of the powers conferred by section 164 of the Central Goods and Services Tax "
        "Act, 2017, the Central Government hereby makes the following rules further to "
        "amend the Central Goods and Services Tax Rules, 2017, namely:-\n"
        "2. In the said rules,-\n"
        '(i) in rule 36, in sub-rule (4), for the words "twenty per cent.", '
        'the words "ten per cent." shall be substituted;'
    )
    mock_conn.execute.return_value.all.side_effect = [
        [(uuid4(), text)],
        [],  # kept query
        [],  # _editor_ids query
    ]

    # scalar_one for existing count, inserted amendment_id, inserted task_id
    mock_conn.execute.return_value.scalar_one.side_effect = [
        0,  # existing count
        uuid4(),  # inserted amendment_id
        uuid4(),  # inserted review_task_id
    ]

    mock_conn.execute.return_value.scalar.return_value = None
    mock_conn.execute.return_value.scalars.return_value.all.return_value = [prov_id]

    # Run detection
    counts = detect_amendments_for(mock_conn, {"document_id": str(doc_id)})
    assert counts["proposals"] == 1
    assert counts["resolved_targets"] == 1
