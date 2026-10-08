"""Circular segmentation: header, numbered paragraphs and sub-numbered paragraphs."""

from worker.ingest.structure import SegBlock, segment


def test_header_then_numbered_and_sub_numbered_paragraphs() -> None:
    blocks = [
        SegBlock("para", "Circular No. 183/15/2022-GST"),
        SegBlock("para", "New Delhi, dated 31st August, 2022"),
        SegBlock("para", "Subject: Clarification regarding refund."),
        SegBlock("para", "1. Background text."),
        SegBlock("para", "4. Refund conditions."),
        SegBlock("para", "4.1 The first condition applies."),
        SegBlock("para", "4.2 The second condition applies."),
        SegBlock("para", "continuation of 4.2."),
        SegBlock("para", "5. Conclusion."),
    ]
    result = segment("circular", blocks)
    assert list(result.paths) == [
        "hdr",
        "hdr",
        "hdr",
        "p1",
        "p4",
        "p4.1",
        "p4.2",
        "p4.2",
        "p5",
    ]
    assert [(item.prefix, item.label) for item in result.numbered] == [
        ("p", "1"),
        ("p", "4"),
        ("p", "4.1"),
        ("p", "4.2"),
        ("p", "5"),
    ]


def test_instruction_and_order_use_the_circular_layout() -> None:
    blocks = [SegBlock("para", "Instruction No. 1/2022-GST"), SegBlock("para", "1. Text.")]
    assert list(segment("instruction", blocks).paths) == ["hdr", "p1"]
    assert list(segment("order", blocks).paths) == ["hdr", "p1"]
