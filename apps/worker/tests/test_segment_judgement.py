"""Judgement segmentation: header, labelled sections and printed paragraph numbers."""

from worker.ingest.structure import SegBlock, segment


def test_header_labels_and_printed_numbers() -> None:
    blocks = [
        SegBlock("para", "IN THE SUPREME COURT OF INDIA"),
        SegBlock("para", "CIVIL APPEAL NO. 1234 OF 2020"),
        SegBlock("para", "M/s ABC Pvt. Ltd. ...Appellant(s)"),
        SegBlock("para", "VERSUS"),
        SegBlock("para", "State of Kerala ...Respondent(s)"),
        SegBlock("para", "CORAM: Hon'ble Mr. Justice D.Y. Chandrachud, J."),
        SegBlock("heading", "FACTS"),
        SegBlock("para", "1. The appellant was a registered person."),
        SegBlock("para", "2. The refund was rejected."),
        SegBlock("heading", "ISSUES"),
        SegBlock("para", "3. Whether the refund is admissible."),
        SegBlock("heading", "ARGUMENTS"),
        SegBlock("para", "4. The appellant submits that the rule is ultra vires."),
        SegBlock("heading", "ANALYSIS"),
        SegBlock("para", "5. The rule is valid."),
        SegBlock("heading", "ORDER"),
        SegBlock("para", "40. The appeal is allowed."),
    ]
    paths = list(segment("judgement", blocks).paths)
    assert paths[:6] == ["hdr"] * 6
    assert paths[6] == "facts"
    assert paths[7:9] == ["facts.p1", "facts.p2"]
    assert paths[9] == "issues"
    assert paths[10] == "issues.p3"
    assert paths[11] == "arguments"
    assert paths[12] == "arguments.p4"
    assert paths[13] == "findings"
    assert paths[14] == "findings.p5"
    assert paths[15] == "order"
    assert paths[16] == "order.p40"


def test_paragraphs_before_a_label_use_body() -> None:
    blocks = [
        SegBlock("para", "IN THE HIGH COURT OF DELHI"),
        SegBlock("para", "1. Heard the parties."),
        SegBlock("para", "Unnumbered introductory paragraph."),
    ]
    paths = list(segment("judgement", blocks).paths)
    assert paths == ["hdr", "body.p1", "body.p2"]


def test_numbered_items_are_the_printed_numbers() -> None:
    blocks = [SegBlock("para", "1. a."), SegBlock("para", "2. b."), SegBlock("para", "3. c.")]
    numbered = [item.label for item in segment("judgement", blocks).numbered]
    assert numbered == ["1", "2", "3"]
