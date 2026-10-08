"""Notification segmentation: preamble, numbered paragraphs, amending units, schedules, rows."""

from worker.ingest.structure import SegBlock, segment


def _paths(blocks: list[tuple[str, str]]) -> list[str]:
    return list(segment("notification", [SegBlock(kind=k, text=t) for k, t in blocks]).paths)


def test_preamble_then_numbered_paragraphs() -> None:
    blocks = [
        ("para", "New Delhi, the 28th June, 2017"),
        ("para", "Notification No. 11/2017-Central Tax (Rate)"),
        (
            "para",
            "In exercise of the powers conferred by section 9, the Government hereby notifies.",
        ),
        ("para", "1. The rate of tax on the goods specified shall be 9 per cent."),
        ("para", "2. This notification shall come into force on the 1st July, 2017."),
    ]
    assert _paths(blocks) == ["pre", "pre", "pre", "p1", "p2"]


def test_amending_paragraph_splits_into_units() -> None:
    blocks = [
        ("para", "1. In the said notification, —"),
        ("para", "(a) in rule 3, the entry is substituted by the following entry:"),
        ("para", "(b) in the Schedule, the entry is omitted."),
        ("para", "the substituted entry shall read as follows."),
        ("para", "2. The notification shall come into force on 1st October."),
    ]
    assert _paths(blocks) == ["p1", "p1.i1", "p1.i2", "p1.i2", "p2"]


def test_in_rule_sentence_starts_an_amending_unit() -> None:
    blocks = [
        ("para", "3. In the said notification,"),
        (
            "para",
            "in rule 5, for the words 'ten per cent' the words 'five per cent' shall be inserted.",
        ),
    ]
    assert _paths(blocks) == ["p3", "p3.i1"]


def test_schedule_heading_and_rows() -> None:
    blocks = [
        ("para", "2. Amendments are as follows."),
        ("heading", "SCHEDULE I"),
        ("para", "Rate of tax on goods."),
        ("table_row", "Chapter 1 | 0%"),
        ("table_row", "Chapter 2 | 5%"),
        ("heading", "SCHEDULE II"),
        ("table_row", "Chapter 9 | 18%"),
    ]
    assert _paths(blocks) == [
        "p2",
        "sched1",
        "sched1",
        "sched1.row1",
        "sched1.row2",
        "sched2",
        "sched2.row1",
    ]


def test_table_row_without_heading_opens_a_schedule() -> None:
    blocks = [("para", "1. Text."), ("table_row", "Row | value")]
    assert _paths(blocks) == ["p1", "sched1.row1"]


def test_numbered_paragraph_ends_a_schedule() -> None:
    blocks = [
        ("heading", "SCHEDULE"),
        ("table_row", "Row"),
        ("para", "3. Back in the body."),
    ]
    assert _paths(blocks) == ["sched1", "sched1.row1", "p3"]


def test_numbered_items_for_gate() -> None:
    blocks = [("para", "1. a."), ("para", "2. b."), ("para", "2.1 sub-text is not a paragraph")]
    numbered = [
        item.label
        for item in segment("notification", [SegBlock("para", t) for _, t in blocks]).numbered
    ]
    assert numbered == ["1", "2"]
