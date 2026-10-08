"""Act and Rules segmentation: structure paths from synthetic block text (no database)."""

import pytest
from worker.ingest.numbering import read_numbering
from worker.ingest.structure import SegBlock, segment


def _paths(doc_type: str, texts: list[str], kinds: list[str] | None = None) -> list[str]:
    blocks = [
        SegBlock(kind=(kinds[i] if kinds else "para"), text=text) for i, text in enumerate(texts)
    ]
    return list(segment(doc_type, blocks).paths)


def test_chapter_sections_subsections_and_clauses() -> None:
    texts = [
        "CHAPTER V",
        "INPUT TAX CREDIT",
        "16. Eligibility and conditions for taking input tax credit.",
        "(1) Every registered person shall be entitled to take credit.",
        "(2) Subject to the conditions, no credit shall be available unless:",
        "(a) the goods have been received;",
        "(b) the tax has been paid.",
        "17. Apportionment of credit.",
        "(1) Where goods are used partly for business.",
    ]
    assert _paths("act", texts) == [
        "ch5",
        "ch5",  # heading text inherits the chapter
        "ch5.s16",
        "ch5.s16.1",
        "ch5.s16.2",
        "ch5.s16.2.a",
        "ch5.s16.2.b",
        "ch5.s17",
        "ch5.s17.1",
    ]


def test_roman_subclause_under_clause_and_letter_after_it() -> None:
    texts = [
        "16. Eligibility.",
        "(2) Subject to conditions:",
        "(c) the goods are received, namely:",
        "(i) by the registered person;",
        "(ii) by an agent;",
        "(d) the tax is paid.",
    ]
    assert _paths("act", texts) == [
        "s16",
        "s16.2",
        "s16.2.c",
        "s16.2.c.i",
        "s16.2.c.ii",
        "s16.2.d",
    ]


def test_roman_i_without_clause_is_a_clause() -> None:
    # (i) directly under a subsection: the current level is not a clause, so it is a clause.
    texts = ["16. Eligibility.", "(2) Subject to conditions:", "(i) first point;"]
    assert _paths("act", texts) == ["s16", "s16.2", "s16.2.i"]


def test_provisos_and_explanations_attach_to_the_deepest_node() -> None:
    texts = [
        "16. Eligibility.",
        "(2) Subject to conditions:",
        "(c) the goods are received;",
        "Provided that no credit shall be allowed after one year.",
        "Provided further that the Commissioner may extend the time.",
        "Explanation 1.—For the purposes of this section, the expression goods means property.",
        "17. Next section.",
        "Provided that the next section has its own provisos.",
        "Explanation.—Second explanation of section 17.",
    ]
    assert _paths("act", texts) == [
        "s16",
        "s16.2",
        "s16.2.c",
        "s16.2.c.prov1",
        "s16.2.c.prov2",
        "s16.2.c.expl1",
        "s17",
        "s17.prov1",
        "s17.expl1",
    ]


def test_explanation_after_section_only() -> None:
    texts = ["16. Eligibility.", "Explanation.—The expression means a thing."]
    assert _paths("act", texts) == ["s16", "s16.expl1"]


def test_amended_section_label_keeps_letter_suffix() -> None:
    texts = ["16. Eligibility.", "16A. Special case.", "(1) Text of 16A."]
    assert _paths("act", texts) == ["s16", "s16A", "s16A.1"]


def test_text_before_any_numbering_is_preamble() -> None:
    texts = ["THE CENTRAL GOODS AND SERVICES TAX ACT, 2017", "An Act to make a law."]
    assert _paths("act", texts) == ["pre", "pre"]


def test_boilerplate_inherits_path_and_does_not_change_state() -> None:
    blocks = [
        SegBlock(kind="para", text="16. Eligibility."),
        SegBlock(kind="para", text="Page 3 of 90", is_boilerplate=True),
        SegBlock(kind="para", text="(1) Every registered person."),
    ]
    result = segment("act", blocks)
    assert result.paths == ("s16", "s16", "s16.1")


def test_rules_use_rule_prefix() -> None:
    texts = ["36. Documents for refund.", "(4) The refund claim shall include:", "(a) an invoice;"]
    assert _paths("rules", texts) == ["r36", "r36.4", "r36.4.a"]


def test_forms_and_annexures_are_separate_units() -> None:
    texts = [
        "36. Documents.",
        "FORM GST RFD-01 [See rule 89]",
        "Application for refund",
        "ANNEXURE I",
        "List of invoices",
    ]
    assert _paths("rules", texts) == ["r36", "form1", "form1", "annex1", "annex1"]


def test_numbered_items_feed_the_gate() -> None:
    blocks = [
        SegBlock(kind="para", text="1. First."),
        SegBlock(kind="para", text="(1) sub."),
        SegBlock(kind="para", text="16A. Inserted section."),
        SegBlock(kind="para", text="17. Next."),
    ]
    numbered = [(item.prefix, item.label) for item in segment("act", blocks).numbered]
    assert numbered == [("s", "1"), ("s", "16A"), ("s", "17")]


@pytest.mark.parametrize(
    ("text", "kinds"),
    [
        ("CHAPTER IV", ["CHAPTER"]),
        ("16. Heading", ["NUMBER"]),
        ("(2) Text", ["PAREN"]),
        ("Provided that x", ["PROVISO"]),
        ("Explanation 2. x", ["EXPLANATION"]),
        ("FORM GST REG-01", ["FORM"]),
        ("ANNEXURE II", ["ANNEX"]),
    ],
)
def test_grammar_reads_each_marker_kind(text: str, kinds: list[str]) -> None:
    numbering = read_numbering(text)
    assert [marker.kind for marker in numbering.markers] == kinds


def test_grammar_leaves_plain_text_as_tail() -> None:
    numbering = read_numbering("Some text that starts without numbering.")
    assert numbering.markers == ()
    assert numbering.tail == "Some text that starts without numbering."
