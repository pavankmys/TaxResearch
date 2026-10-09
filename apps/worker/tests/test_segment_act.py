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


# --- Layout seen in Acts and Rules published "as amended" (synthetic text) -------------------


def test_index_is_excluded_and_front_matter_is_preamble() -> None:
    texts = [
        "1. The Sample Amendment Act, 2020 (1 of 2020).",  # list of amending Acts, before the index
        "THE SAMPLE GOODS ACT, 2017",
        "ARRANGEMENT OF SECTIONS",
        "CHAPTER I",
        "PRELIMINARY",
        "1. Short title.",
        "2. Definitions.",
        "THE SAMPLE GOODS ACT, 2017",
        "ACT NO. 5 OF 2017",
        "An Act to provide for sample tax.",
        "CHAPTER I",
        "PRELIMINARY",
        "1. Short title.- (1) This Act may be called the Sample Act.",
        "2. Definitions.- In this Act,--",
    ]
    result = segment("act", [SegBlock(kind="para", text=t) for t in texts])
    assert list(result.paths) == [
        "pre",
        "pre",
        "toc",
        "toc",
        "toc",
        "toc",
        "toc",
        "pre",
        "pre",
        "pre",
        "ch1",
        "ch1",
        "ch1.s1",
        "ch1.s2",
    ]
    assert [(i.prefix, i.label) for i in result.numbered] == [("s", "1"), ("s", "2")]


def test_footnote_lines_do_not_move_the_position() -> None:
    texts = [
        "5. Levy of tax.- (1) Tax shall be levied.",
        '1. The words "sample" omitted by Act 26 of 2018, s. 2 (w.e.f. 1-2-2019).',
        "(2) Tax is payable monthly.",
        "6Inserted vide Notf no. 34/2017 - CT dt. 15.09.2017",
        "(3) Tax is payable quarterly.",
    ]
    assert _paths("act", texts) == ["s5", "s5.fn1", "s5.2", "s5.2.fn2", "s5.3"]


def test_out_of_sequence_markers_are_continuation_text() -> None:
    texts = [
        "4. Effective date.- (1) The option shall be effective from the date.",
        "(2) The intimation shall be considered after registration.",
        "(1) of the said rule.",  # a wrapped line, not a new subsection
        "12. Other.",  # not the next section either: 12 is within the jump limit, so it is one
        "3. A back-reference.",  # lower than the last section
    ]
    assert _paths("rules", texts) == ["r4", "r4.2", "r4.2", "r12", "r12"]


def test_spaced_and_bracketed_markers_are_found() -> None:
    texts = [
        "20. Manner of distribution.- ( 1 ) The distributor shall issue invoices.",
        "( 2 ) The credit shall be distributed.",
        "1[21. Other matters.- ( 1 ) Sample text.",
        "22 . Spaced number.- Sample text.",
        "23.Unspaced heading.- Sample text.",
    ]
    assert _paths("act", texts) == ["s20", "s20.2", "s21", "s22", "s23"]


def test_i_after_h_is_the_next_clause_not_a_subclause() -> None:
    texts = [
        "7. Sample.- (1) In this section,--",
        "(g) the seventh item;",
        "(h) the eighth item;",
        "(i) the ninth item;",
        "(j) the tenth item;",
    ]
    assert _paths("act", texts) == ["s7", "s7.g", "s7.h", "s7.i", "s7.j"]


def test_schedule_items_do_not_become_sections() -> None:
    texts = ["174. Repeal.", "SCHEDULE I", "1. Supply of sample goods.", "2. Another entry."]
    kinds = ["para", "heading", "para", "para"]
    assert _paths("act", texts, kinds) == ["s174", "sched1", "sched1", "sched1"]


def test_numbered_table_row_is_not_a_section() -> None:
    texts = ["138. Sample rule.", "150. | | Sample tariff heading and description"]
    assert _paths("rules", texts, ["para", "table"]) == ["r138", "r138"]


def test_table_rows_after_a_table_share_its_path() -> None:
    texts = ["108. Appeal.- (1) Sample text.", "108. Appeal. (1) Sample", "(2) Another text"]
    kinds = ["table", "table_row", "table_row"]
    result = segment("rules", [SegBlock(kind=k, text=t) for t, k in zip(texts, kinds, strict=True)])
    assert list(result.paths) == ["r108", "r108", "r108"]
    assert [i.label for i in result.numbered] == ["108"]
