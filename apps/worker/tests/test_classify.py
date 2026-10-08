"""Classification cues: each strong cue, the earliest cue wins, and no cue keeps the loader type."""

import pytest
from worker.ingest.classify import classify_texts


@pytest.mark.parametrize(
    ("texts", "doc_type", "rank", "cue"),
    [
        (
            ["Notification No. 11/2017-Central Tax (Rate)", "text"],
            "notification",
            5,
            "notification",
        ),
        (["CBIC", "Circular No. 183/15/2022-GST"], "circular", 8, "circular"),
        (["Instruction No. 1/2022-GST"], "instruction", 8, "instruction"),
        (["Order No. 5/2022-GST"], "order", 8, "order"),
        (["IN THE SUPREME COURT OF INDIA", "CIVIL APPEAL"], "judgement", 3, "judgement_sc"),
        (["IN THE HIGH COURT OF DELHI", "W.P.(C)"], "judgement", 6, "judgement_hc"),
        (["GOODS AND SERVICES TAX APPELLATE TRIBUNAL"], "judgement", 7, "judgement_gstat"),
        (["AUTHORITY FOR ADVANCE RULING, GUJARAT"], "judgement", 9, "judgement_aar"),
        (["THE CENTRAL GOODS AND SERVICES TAX ACT, 2017", "CHAPTER I"], "act", 2, "act"),
        (["CENTRAL GOODS AND SERVICES TAX RULES, 2017"], "rules", 4, "rules"),
    ],
)
def test_each_strong_cue(texts: list[str], doc_type: str, rank: int, cue: str) -> None:
    result = classify_texts(texts)
    assert (result.doc_type, result.authority_rank, result.cue) == (doc_type, rank, cue)


def test_earliest_cue_wins_over_a_later_one() -> None:
    texts = ["Notification No. 11/2017-Central Tax (Rate)", "IN THE SUPREME COURT OF INDIA"]
    assert classify_texts(texts).doc_type == "notification"


def test_judgement_header_beats_an_act_named_in_its_text() -> None:
    texts = [
        "IN THE HIGH COURT OF KARNATAKA",
        "The petition concerns the THE CENTRAL GOODS AND SERVICES TAX ACT, 2017.",
    ]
    assert classify_texts(texts).doc_type == "judgement"


def test_act_title_cue_is_upper_case_only() -> None:
    # In running text the Act is in title case, so it is not a title cue.
    texts = ["The petitioner relies on the Central Goods and Services Tax Act, 2017 for relief."]
    assert classify_texts(texts).doc_type is None


def test_act_and_rules_cues_only_in_first_five_blocks() -> None:
    texts = ["para"] * 6 + ["THE CENTRAL GOODS AND SERVICES TAX ACT, 2017"]
    assert classify_texts(texts).doc_type is None


def test_order_heading_inside_a_judgement_is_not_an_order_cue() -> None:
    texts = ["IN THE SUPREME COURT OF INDIA", "ORDER", "1. Appeal dismissed."]
    result = classify_texts(texts)
    assert (result.doc_type, result.cue) == ("judgement", "judgement_sc")


def test_no_cue_returns_nothing() -> None:
    result = classify_texts(["Some unrelated paragraph of text."])
    assert (result.doc_type, result.authority_rank, result.cue) == (None, None, None)
