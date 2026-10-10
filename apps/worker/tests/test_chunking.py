"""Unit tests for legal-structure chunking (TSD 6.2)."""

from datetime import date
from uuid import uuid4

from worker.ingest.chunking import (
    chunk_document_blocks,
    chunk_provision_versions,
    count_tokens,
    format_provision_heading_path,
    sha256_text,
)


def test_count_tokens_and_sha256() -> None:
    assert count_tokens("") == 0
    assert count_tokens("one two three") > 0
    h1 = sha256_text("hello world")
    h2 = sha256_text("hello world")
    h3 = sha256_text("different")
    assert h1 == h2
    assert h1 != h3


def test_format_provision_heading_path() -> None:
    formatted = format_provision_heading_path("CGST Act", "ch5.s16.2.c", "Eligibility for ITC")
    assert formatted == "CGST Act > Chapter 5 > s.16 > (2) > (c) - Eligibility for ITC"

    rule_formatted = format_provision_heading_path("CGST Rules", "r36.4")
    assert rule_formatted == "CGST Rules > r.36 > (4)"


def test_chunk_provision_versions_leaf_and_summary() -> None:
    doc_id = uuid4()
    doc_ver_id = uuid4()
    prov_id = uuid4()
    pv_id = uuid4()

    provisions_data = [
        {
            "provision_id": prov_id,
            "provision_version_id": pv_id,
            "path": "ch5.s16",
            "heading": "Eligibility and conditions for taking input tax credit",
            "text": "Every registered person shall be entitled to take credit of input tax...",
            "level": "section",
            "valid_from": date(2017, 7, 1),
            "valid_to": None,
            "rec_to": None,
            "block_ids": [uuid4()],
        },
        {
            "provision_id": uuid4(),
            "provision_version_id": uuid4(),
            "path": "ch5.s16.2.c",
            "heading": None,
            "text": "The tax charged in respect of such supply has been actually paid...",
            "level": "clause",
            "valid_from": date(2017, 7, 1),
            "valid_to": None,
            "rec_to": None,
            "block_ids": [uuid4()],
        },
    ]

    chunks = chunk_provision_versions(
        instrument_name="CGST Act",
        instrument_kind="act",
        document_id=doc_id,
        document_version_id=doc_ver_id,
        provisions_data=provisions_data,
    )

    # 1 leaf chunk for s16, 1 section_summary chunk for s16, 1 leaf chunk for s16.2.c
    assert len(chunks) == 3
    kinds = [c.chunk_kind for c in chunks]
    assert kinds == ["provision", "section_summary", "provision"]

    # Verify attributes
    c_summary = chunks[1]
    assert c_summary.chunk_kind == "section_summary"
    assert c_summary.authority_rank == 2
    assert c_summary.doc_type == "act"
    assert c_summary.is_current is True


def test_chunk_notification_preamble_and_paras() -> None:
    doc_id = uuid4()
    ver_id = uuid4()
    b1_id = uuid4()
    b2_id = uuid4()
    b3_id = uuid4()

    doc_meta = {
        "title": "Notification No. 11/2017-Central Tax (Rate)",
        "doc_type": "notification",
        "authority_rank": 5,
        "valid_from": date(2017, 6, 28),
        "valid_to": None,
        "status": "in_force",
    }

    blocks = [
        {
            "id": b1_id,
            "seq": 1,
            "kind": "paragraph",
            "page": 1,
            "structure_path": "pre",
            "para_label": None,
            "text": "G.S.R. (E).- In exercise of the powers conferred by sub-section (1)...",
            "is_boilerplate": False,
        },
        {
            "id": b2_id,
            "seq": 2,
            "kind": "paragraph",
            "page": 1,
            "structure_path": "p1",
            "para_label": "1",
            "text": "1. This notification may be called the Central Goods and Services Tax...",
            "is_boilerplate": False,
        },
        {
            "id": b3_id,
            "seq": 3,
            "kind": "paragraph",
            "page": 2,
            "structure_path": "p2.i1",
            "para_label": "2(i)",
            "text": "2. The Central Government hereby notifies the following rates...",
            "is_boilerplate": False,
        },
    ]

    chunks = chunk_document_blocks(doc_id, ver_id, doc_meta, blocks)
    assert len(chunks) == 3

    assert chunks[0].chunk_kind == "preamble"
    assert chunks[0].page_start == 1
    assert chunks[1].chunk_kind == "paragraph"
    assert chunks[1].para_label == "1"
    assert chunks[2].chunk_kind == "amendment_instruction"
    assert chunks[2].page_start == 2


def test_chunk_circular_merges_small_paragraphs() -> None:
    doc_id = uuid4()
    ver_id = uuid4()

    doc_meta = {
        "title": "Circular No. 183/15/2022-GST",
        "doc_type": "circular",
        "authority_rank": 8,
        "subject": "Clarification on ITC mismatch between GSTR-2A and GSTR-3B",
        "valid_from": date(2022, 12, 27),
    }

    # Three short paragraphs (<80 words each) should be merged together
    blocks = [
        {
            "id": uuid4(),
            "seq": 1,
            "kind": "paragraph",
            "page": 1,
            "structure_path": "hdr",
            "para_label": None,
            "text": "F. No. CBIC-20001/2/2022-GST\nGovernment of India\nMinistry of Finance",
            "is_boilerplate": False,
        },
        {
            "id": uuid4(),
            "seq": 2,
            "kind": "paragraph",
            "page": 1,
            "structure_path": "p1",
            "para_label": "1",
            "text": "Representations have been received from the trade seeking clarification.",
            "is_boilerplate": False,
        },
        {
            "id": uuid4(),
            "seq": 3,
            "kind": "paragraph",
            "page": 1,
            "structure_path": "p2",
            "para_label": "2",
            "text": "The issue has been examined by the GST Policy Wing.",
            "is_boilerplate": False,
        },
    ]

    chunks = chunk_document_blocks(doc_id, ver_id, doc_meta, blocks)
    # 1 header chunk + 1 merged body paragraph chunk
    assert len(chunks) == 2
    assert chunks[0].chunk_kind == "header"
    assert chunks[1].chunk_kind == "paragraph"
    assert "Subject: Clarification on ITC mismatch" in chunks[1].text
    assert "Representations have been received" in chunks[1].text
    assert "examined by the GST Policy Wing" in chunks[1].text


def test_chunk_judgement_groups_by_section() -> None:
    doc_id = uuid4()
    ver_id = uuid4()

    doc_meta = {
        "title": "Safari Retreats Pvt. Ltd. v. Chief Commissioner",
        "doc_type": "judgement",
        "authority_rank": 3,
        "court_level": "SC",
        "valid_from": date(2024, 10, 3),
    }

    blocks = [
        {
            "id": uuid4(),
            "seq": 1,
            "kind": "paragraph",
            "page": 1,
            "structure_path": "hdr",
            "para_label": None,
            "text": "IN THE SUPREME COURT OF INDIA\nCIVIL APPELLATE JURISDICTION",
            "is_boilerplate": False,
        },
        {
            "id": uuid4(),
            "seq": 2,
            "kind": "paragraph",
            "page": 2,
            "structure_path": "facts.p1",
            "para_label": "1",
            "text": "The respondent constructed a shopping mall for letting out.",
            "is_boilerplate": False,
        },
        {
            "id": uuid4(),
            "seq": 3,
            "kind": "paragraph",
            "page": 2,
            "structure_path": "facts.p2",
            "para_label": "2",
            "text": "They claimed input tax credit on goods and services used in construction.",
            "is_boilerplate": False,
        },
        {
            "id": uuid4(),
            "seq": 4,
            "kind": "paragraph",
            "page": 3,
            "structure_path": "order.p10",
            "para_label": "10",
            "text": "Accordingly, the appeals are dismissed with no order as to costs.",
            "is_boilerplate": False,
        },
    ]

    chunks = chunk_document_blocks(doc_id, ver_id, doc_meta, blocks)
    assert len(chunks) == 3
    kinds = [c.chunk_kind for c in chunks]
    assert kinds == ["header", "facts", "order"]
    assert chunks[1].para_label == "paras 1-2"
    assert chunks[2].para_label == "10"
