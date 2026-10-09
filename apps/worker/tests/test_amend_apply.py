"""Applier and timeline on synthetic provision text (no database)."""

from datetime import date

import pytest
from worker.ingest.amend_apply import (
    AppliedOp,
    Step,
    apply_op,
    interval_at,
    op_from_amendment,
    plan_timeline,
    word_diff,
)

TEXT = "The registered person shall pay interest at twenty per cent. on the amount."


def test_substitute_words() -> None:
    r = apply_op(
        TEXT, AppliedOp("substitute_words", old_text="twenty per cent.", new_text="ten per cent.")
    )
    assert r.ok
    assert r.text == "The registered person shall pay interest at ten per cent. on the amount."
    assert r.diff == (
        "The registered person shall pay interest at [-twenty-]{+ten+} per cent. on the amount."
    )


def test_white_space_in_the_source_does_not_matter() -> None:
    text = "The tax\nshall be   paid in cash."
    r = apply_op(
        text, AppliedOp("substitute_words", old_text="shall be paid", new_text="is payable")
    )
    assert r.ok
    assert r.text == "The tax\nis payable in cash."


@pytest.mark.parametrize(
    ("op", "reason"),
    [
        (AppliedOp("substitute_words", old_text="thirty", new_text="x"), "old_text_not_found"),
        (AppliedOp("substitute_words", old_text="", new_text="x"), "words_missing"),
        (AppliedOp("insert_words", anchor_text="nowhere", new_text="x"), "anchor_not_found"),
        (AppliedOp("omit_words", old_text="absent"), "old_text_not_found"),
        (AppliedOp("insert_provision", new_text="(2A) New."), "provision_exists"),
        (AppliedOp("substitute_provision", new_text=""), "new_text_missing"),
    ],
)
def test_failures_have_a_reason_and_leave_the_text(op: AppliedOp, reason: str) -> None:
    r = apply_op(TEXT, op)
    assert (r.ok, r.reason, r.text) == (False, reason, TEXT)


def test_repeated_words_need_an_occurrence() -> None:
    op = AppliedOp("substitute_words", old_text="a", new_text="X")
    assert apply_op("a b a", op).reason == "old_text_ambiguous"
    out_of_range = AppliedOp("substitute_words", old_text="a", new_text="X", occurrence=9)
    assert apply_op("a b a", out_of_range).reason == "old_text_occurrence_out_of_range"


def test_words_match_whole_words_only() -> None:
    assert apply_op("taxable supply", AppliedOp("omit_words", old_text="tax")).reason == (
        "old_text_not_found"
    )


def test_an_occurrence_picks_one_of_several() -> None:
    r = apply_op(
        "a b a b a", AppliedOp("substitute_words", old_text="a", new_text="X", occurrence=2)
    )
    assert r.text == "a b X b a"


def test_insert_words_after_and_before() -> None:
    after = apply_op(
        "Sent to the proper officer within seven days.",
        AppliedOp(
            "insert_words",
            anchor_text="the proper officer",
            new_text="or the Commissioner",
            position="after",
        ),
    )
    assert after.text == "Sent to the proper officer or the Commissioner within seven days."
    before = apply_op(
        "Sent within seven days.",
        AppliedOp(
            "insert_words",
            anchor_text="within seven days",
            new_text="not later than",
            position="before",
        ),
    )
    assert before.text == "Sent not later than within seven days."


def test_insert_words_before_punctuation_has_no_space() -> None:
    r = apply_op(
        "Pay the tax, interest.",
        AppliedOp("insert_words", anchor_text="the tax", new_text="and fee", position="after"),
    )
    assert r.text == "Pay the tax and fee, interest."


def test_omit_words_closes_the_gap() -> None:
    r = apply_op(
        "Pay the tax and figures, in cash.", AppliedOp("omit_words", old_text="and figures")
    )
    assert r.text == "Pay the tax, in cash."
    r2 = apply_op("Pay the old tax now.", AppliedOp("omit_words", old_text="old"))
    assert r2.text == "Pay the tax now."


def test_whole_provision_operations() -> None:
    sub = apply_op("(4) Old.", AppliedOp("substitute_provision", new_text="(4) New."))
    assert (sub.ok, sub.text, sub.diff) == (True, "(4) New.", "(4) [-Old.-]{+New.+}")
    omit = apply_op("(7) Gone.", AppliedOp("omit_provision"))
    assert (omit.ok, omit.text, omit.diff) == (True, None, "[-(7) Gone.-]")
    new = apply_op(None, AppliedOp("insert_provision", new_text="(2A) Added."))
    assert (new.ok, new.text, new.diff) == (True, "(2A) Added.", "{+(2A) Added.+}")


def test_an_operation_on_a_missing_provision_fails() -> None:
    assert apply_op(None, AppliedOp("omit_provision")).reason == "provision_not_in_force"
    assert apply_op(None, AppliedOp("substitute_words", old_text="a", new_text="b")).reason == (
        "provision_not_in_force"
    )


def test_word_diff_of_equal_text_has_no_markers() -> None:
    assert word_diff("same text", "same text") == "same text"


def test_op_from_amendment() -> None:
    op = op_from_amendment(
        "insert", None, "or X", {"kind": "words", "anchor_text": "the officer", "position": "after"}
    )
    assert op == AppliedOp("insert_words", None, "or X", "the officer", "after", None)
    assert op_from_amendment("amend", None, None, {"kind": "raw"}) is None


# --- timeline ---------------------------------------------------------------------------


def _step(i: str, op: AppliedOp, day: date, *order: str) -> Step:
    return Step(i, op, day, tuple(order))


_SUB = AppliedOp("substitute_words", old_text="twenty", new_text="ten")


def test_timeline_splits_the_baseline_at_the_effective_date() -> None:
    plan = plan_timeline("rate is twenty", date(2020, 1, 1), [_step("a1", _SUB, date(2023, 4, 1))])
    assert [(i.valid_from, i.valid_to, i.text, i.amendment_id) for i in plan.intervals] == [
        (date(2020, 1, 1), date(2023, 4, 1), "rate is twenty", None),
        (date(2023, 4, 1), None, "rate is ten", "a1"),
    ]
    assert plan.failures == ()


def test_amendments_apply_in_effective_order_not_input_order() -> None:
    steps = [
        _step(
            "late", AppliedOp("substitute_words", old_text="ten", new_text="five"), date(2024, 1, 1)
        ),
        _step("early", _SUB, date(2023, 1, 1)),
    ]
    plan = plan_timeline("rate is twenty", date(2020, 1, 1), steps)
    assert [i.text for i in plan.intervals] == ["rate is twenty", "rate is ten", "rate is five"]


def test_same_day_ties_use_the_order_key() -> None:
    steps = [
        _step(
            "b",
            AppliedOp("substitute_words", old_text="ten", new_text="five"),
            date(2023, 1, 1),
            "2023-01-01",
            "z",
        ),
        _step("a", _SUB, date(2023, 1, 1), "2022-12-30", "y"),
    ]
    plan = plan_timeline("rate is twenty", date(2020, 1, 1), steps)
    assert [i.text for i in plan.intervals] == ["rate is twenty", "rate is five"]
    assert plan.intervals[-1].amendment_id == "b"
    assert plan.intervals[0].valid_to == date(2023, 1, 1)


def test_an_amendment_on_or_before_the_baseline_date_is_already_in_the_text() -> None:
    plan = plan_timeline("rate is ten", date(2023, 1, 1), [_step("old", _SUB, date(2023, 1, 1))])
    assert [i.text for i in plan.intervals] == ["rate is ten"]
    assert [(s.amendment_id, s.reason) for s in plan.skipped] == [("old", "before_baseline")]


def test_a_failing_step_is_recorded_and_the_replay_goes_on() -> None:
    steps = [
        _step(
            "bad", AppliedOp("substitute_words", old_text="missing", new_text="x"), date(2022, 1, 1)
        ),
        _step("good", _SUB, date(2023, 1, 1)),
    ]
    plan = plan_timeline("rate is twenty", date(2020, 1, 1), steps)
    assert [(f.amendment_id, f.reason) for f in plan.failures] == [("bad", "old_text_not_found")]
    assert [i.text for i in plan.intervals] == ["rate is twenty", "rate is ten"]


def test_omission_ends_the_provision_and_an_insert_can_bring_it_back() -> None:
    steps = [
        _step("gone", AppliedOp("omit_provision"), date(2022, 1, 1)),
        _step("back", AppliedOp("insert_provision", new_text="(7) Again."), date(2024, 1, 1)),
    ]
    plan = plan_timeline("(7) Old.", date(2020, 1, 1), steps)
    assert [(i.valid_from, i.valid_to, i.text) for i in plan.intervals] == [
        (date(2020, 1, 1), date(2022, 1, 1), "(7) Old."),
        (date(2024, 1, 1), None, "(7) Again."),
    ]


def test_an_inserted_provision_starts_at_its_effective_date() -> None:
    plan = plan_timeline(
        None,
        None,
        [_step("new", AppliedOp("insert_provision", new_text="(2A) New."), date(2025, 7, 1))],
    )
    assert [(i.valid_from, i.valid_to, i.text, i.amendment_id) for i in plan.intervals] == [
        (date(2025, 7, 1), None, "(2A) New.", "new")
    ]


def test_interval_at() -> None:
    plan = plan_timeline("rate is twenty", date(2020, 1, 1), [_step("a1", _SUB, date(2023, 4, 1))])
    assert interval_at(plan.intervals, date(2019, 12, 31)) is None
    found = interval_at(plan.intervals, date(2023, 3, 31))
    assert found is not None
    assert found.text == "rate is twenty"
    found = interval_at(plan.intervals, date(2023, 4, 1))
    assert found is not None
    assert found.text == "rate is ten"
