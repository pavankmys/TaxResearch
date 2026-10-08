"""Rule extractors on realistic header strings: fields, confidences, cross-checks, required."""

import uuid
from datetime import date

from worker.ingest.extractors import extract_metadata
from worker.ingest.metadata import CONFIDENCE_THRESHOLD, required_confidence
from worker.ingest.structure import SegBlock

TODAY = date(2026, 10, 8)


def _blocks(*texts: str, kind: str = "para") -> list[SegBlock]:
    return [SegBlock(kind=kind, text=text) for text in texts]


def _extract(
    doc_type: str,
    blocks: list[SegBlock],
    title: str = "upload.pdf",
    name: str | None = "upload.pdf",
):  # type: ignore[no-untyped-def]
    return extract_metadata(doc_type, blocks, title=title, file_name=name, today=TODAY)


def test_notification_header_gives_number_series_and_dates() -> None:
    proposal = _extract(
        "notification",
        _blocks(
            "Ministry of Finance (Department of Revenue)",
            "New Delhi, the 28th June, 2017",
            "Notification No. 11/2017-Central Tax (Rate)",
            "G.S.R. 690(E).- In exercise of the powers conferred by section 9 of the CGST Act,"
            " 2017",
            "1. The rate of tax shall be as specified.",
            "2. This notification shall come into force on the 1st July, 2017.",
        ),
        title="Notification No. 11/2017-Central Tax (Rate)",
    )
    fields = proposal.fields
    assert fields["number"] == "11"
    assert fields["year"] == 2017
    assert fields["series"] == "CT(R)"
    assert fields["doc_date"] == "2017-06-28"
    assert fields["effective_date"] == "2017-07-01"
    assert fields["in_force_date"] == "2017-07-01"
    assert fields["gazette_ref"] == "G.S.R. 690(E)"
    assert fields["issuing_authority"] == "Ministry of Finance (Department of Revenue)"
    assert fields["canonical_id"] == "ntf:CT(R):11/2017"
    assert proposal.confidence["number"] == 0.95
    assert proposal.confidence["doc_date"] == 0.95
    assert proposal.issues == []
    assert required_confidence("notification", fields, proposal.confidence) >= CONFIDENCE_THRESHOLD


def test_notification_numeric_date_and_plain_series_name() -> None:
    proposal = _extract(
        "notification",
        _blocks(
            "Notification No. 5/2018-Integrated Tax",
            "Dated 28.06.2018",
        ),
    )
    assert proposal.fields["series"] == "IT"
    assert proposal.fields["canonical_id"] == "ntf:IT:5/2018"
    assert proposal.fields["doc_date"] == "2018-06-28"


def test_notification_without_a_known_series_is_an_issue() -> None:
    proposal = _extract("notification", _blocks("Notification No. 7/2019-Mystery Tax"))
    assert "series" not in proposal.fields
    assert any(issue.startswith("unrecognised_series") for issue in proposal.issues)
    assert "missing:series" in proposal.issues
    assert proposal.fields.get("canonical_id") is None


def test_notification_fallback_number_and_series_from_body_lowers_confidence() -> None:
    proposal = _extract(
        "notification",
        _blocks(
            "Notf. No. 12/2019 dated 01-02-2019",
            "This notification amends the Central Tax (Rate) entries.",
        ),
    )
    assert proposal.fields["number"] == "12"
    assert proposal.confidence["number"] == 0.7
    assert proposal.fields["series"] == "CT(R)"
    assert proposal.confidence["series"] == 0.7
    assert proposal.fields["doc_date"] == "2019-02-01"
    assert proposal.confidence["doc_date"] == 0.95  # "dated" with a numeric date is exact


def test_cross_check_halves_number_when_title_disagrees() -> None:
    proposal = _extract(
        "notification",
        _blocks("Notification No. 11/2017-Central Tax (Rate)", "New Delhi, the 28th June, 2017"),
        title="Notification 12/2017 scan",
    )
    assert proposal.confidence["number"] == 0.475
    assert "crosscheck:number disagrees with title" in proposal.issues


def test_date_outside_gst_range_is_flagged_and_halved() -> None:
    proposal = _extract(
        "notification",
        _blocks("Notification No. 2/2016-Central Tax (Rate)", "New Delhi, the 28th June, 2016"),
    )
    assert proposal.confidence["doc_date"] == 0.475
    assert any(issue.startswith("crosscheck:doc_date") for issue in proposal.issues)


def test_missing_date_and_series_gives_zero_required_confidence() -> None:
    proposal = _extract("notification", _blocks("Notification No. 3/2018-Central Tax (Rate)"))
    assert "doc_date" not in proposal.fields
    assert "missing:doc_date" in proposal.issues
    assert required_confidence("notification", proposal.fields, proposal.confidence) == 0.0


def test_circular_header_din_subject_and_kind() -> None:
    proposal = _extract(
        "circular",
        _blocks(
            "Circular No. 183/15/2022-GST",
            "New Delhi, dated 31st August, 2022",
            "Subject: Clarification regarding refund of unutilised ITC",
            "DIN: 202208XXXXXXXXXXXXXX",
        ),
        title="183/15/2022 refund circular",
    )
    fields = proposal.fields
    assert fields["number"] == "183/15/2022"
    assert fields["canonical_id"] == "cir:183/15/2022"
    assert fields["doc_date"] == "2022-08-31"
    assert fields["subject"] == "Clarification regarding refund of unutilised ITC"
    assert fields["din"] == "202208XXXXXXXXXXXXXX"
    assert fields["circular_kind"] == "circular"
    assert fields["title"] == fields["subject"]
    assert proposal.confidence["number"] == 0.95
    assert proposal.issues == []


def test_instruction_uses_its_own_canonical_id() -> None:
    proposal = _extract(
        "instruction",
        _blocks("Instruction No. 4/2022-GST", "New Delhi, dated 10th March, 2022"),
    )
    assert proposal.fields["circular_kind"] == "instruction"
    assert proposal.fields["canonical_id"] == "ins:4/2022"


def test_circular_title_number_mismatch_halves_number() -> None:
    proposal = _extract(
        "circular",
        _blocks("Circular No. 183/15/2022-GST", "New Delhi, dated 31st August, 2022"),
        title="circular 184/15/2022",
    )
    assert proposal.confidence["number"] == 0.475


def test_supreme_court_judgement_fields() -> None:
    proposal = _extract(
        "judgement",
        _blocks(
            "IN THE SUPREME COURT OF INDIA",
            "CIVIL APPEAL NO. 1234 OF 2020",
            "M/s ABC Pvt. Ltd. ...Appellant(s)",
            "VERSUS",
            "State of Kerala ...Respondent(s)",
            "CORAM: Hon'ble Mr. Justice D.Y. Chandrachud, J.",
            "FACTS",
            "1. The appellant was a registered person.",
            "ORDER",
            "40. The appeal is allowed.",
            "Dated: 15.03.2021",
        ),
        title="ABC v Kerala.pdf",
    )
    fields = proposal.fields
    assert fields["court_code"] == "SC"
    assert fields["court_level"] == "SC"
    assert fields["court_name"] == "Supreme Court of India"
    assert fields["case_numbers"] == ["CA 1234/2020"]
    assert fields["decision_date"] == "2021-03-15"
    assert fields["parties"] == {
        "petitioners": ["M/s ABC Pvt. Ltd"],
        "respondents": ["State of Kerala"],
    }
    assert fields["judges"] == ["D.Y. Chandrachud"]
    assert fields["canonical_id"] == "jdg:SC:CA1234/2020:2021-03-15"
    assert fields["title"] == "M/s ABC Pvt. Ltd v. State of Kerala"
    assert proposal.issues == []
    assert required_confidence("judgement", fields, proposal.confidence) == 0.95


def test_high_court_and_unknown_court() -> None:
    known = _extract(
        "judgement",
        _blocks(
            "IN THE HIGH COURT OF KARNATAKA",
            "WRIT PETITION NO. 555 OF 2021",
            "Dated: 10.05.2022",
        ),
    )
    assert known.fields["court_code"] == "HC-KA"
    assert known.fields["court_level"] == "HC"
    assert known.fields["case_numbers"] == ["WP 555/2021"]

    unknown = _extract(
        "judgement",
        _blocks("IN THE COURT OF SOMEWHERE", "CIVIL APPEAL NO. 9 OF 2021", "Dated: 01.01.2022"),
    )
    assert "court_code" not in unknown.fields
    assert "missing:court_code" in unknown.issues
    assert required_confidence("judgement", unknown.fields, unknown.confidence) == 0.0


def test_tail_dated_line_beats_header_date() -> None:
    proposal = _extract(
        "judgement",
        _blocks(
            "IN THE SUPREME COURT OF INDIA",
            "CIVIL APPEAL NO. 77 OF 2019",
            "Dated: 01.02.2019 hearing listed",
            *[f"{n}. paragraph text." for n in range(1, 12)],
            "Dated: 20.09.2019",
        ),
    )
    assert proposal.fields["decision_date"] == "2019-09-20"


def test_judgement_decision_date_before_1950_is_flagged() -> None:
    proposal = _extract(
        "judgement",
        _blocks("IN THE SUPREME COURT OF INDIA", "CIVIL APPEAL NO. 3 OF 1920", "Dated: 01.01.1920"),
    )
    assert any(issue.startswith("crosscheck:decision_date") for issue in proposal.issues)


def test_act_title_is_the_header_line() -> None:
    proposal = _extract(
        "act",
        _blocks("THE CENTRAL GOODS AND SERVICES TAX ACT, 2017", "CHAPTER I", "PRELIMINARY"),
    )
    assert proposal.fields["title"] == "THE CENTRAL GOODS AND SERVICES TAX ACT, 2017"
    assert proposal.confidence["title"] == 0.95
    assert "canonical_id" not in proposal.fields
    assert proposal.issues == []


def test_other_type_falls_back_to_the_file_name() -> None:
    proposal = _extract("other", _blocks("Some uploaded note without a heading."), name="note.pdf")
    assert proposal.fields["title"] == "note.pdf"
    assert proposal.confidence["title"] == 0.5
    assert required_confidence("other", proposal.fields, proposal.confidence) == 0.5


def test_proposal_json_has_the_contract_keys() -> None:
    proposal = _extract(
        "circular",
        _blocks("Circular No. 183/15/2022-GST", "New Delhi, dated 31st August, 2022"),
    )
    body = proposal.to_json()
    assert set(body) == {"fields", "confidence", "issues", "extractor_version"}
    assert body["extractor_version"] == "meta-1"
    assert set(body["confidence"]) <= set(body["fields"])


def test_random_document_id_is_not_needed_for_extraction() -> None:
    # The extractors are pure: the same input always gives the same proposal.
    blocks = _blocks("Circular No. 183/15/2022-GST", "New Delhi, dated 31st August, 2022")
    first = _extract("circular", blocks).to_json()
    second = _extract("circular", blocks).to_json()
    assert first == second
    assert uuid.UUID(int=0) is not None
