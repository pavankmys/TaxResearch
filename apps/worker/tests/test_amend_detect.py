"""Amendment detector on synthetic notifications (no database)."""

from datetime import date

import pytest
from worker.ingest.amend_detect import (
    BlockText,
    Proposal,
    detect,
    extract_effective,
    parse_date,
)

_PREAMBLE = [
    "In exercise of the powers conferred by section 164 of the Central Goods and Services Tax "
    "Act, 2017 (12 of 2017), the Central Government hereby makes the following rules further to "
    "amend the Central Goods and Services Tax Rules, 2017, namely:-",
    "1. (1) These rules may be called the Sample (Amendment) Rules, 2026.",
    "(2) They shall come into force on the date of their publication in the Official Gazette.",
]


def _blocks(*texts: str) -> list[BlockText]:
    return [BlockText(id=f"b{i}", text=t) for i, t in enumerate(texts)]


def _detect(*texts: str) -> list[Proposal]:
    return list(detect(_blocks(*_PREAMBLE, *texts)).proposals)


def test_substitute_words_under_a_scope_and_chained_leads() -> None:
    found = _detect(
        "2. In the said rules,-",
        "(i) in rule 36, in sub-rule (4), for the words “twenty per cent.”, the words "
        "“ten per cent.” shall be substituted;",
    )
    assert len(found) == 1
    p = found[0]
    assert (p.status, p.op, p.kind) == ("parsed", "substitute", "words")
    assert p.instrument == "CGST_RULES"
    assert p.target_path == "r36.4"
    assert (p.old_text, p.new_text) == ("twenty per cent.", "ten per cent.")
    assert p.problems == ()
    assert p.confidence == pytest.approx(0.9)


def test_relative_items_use_the_lead_in_scope() -> None:
    found = _detect(
        "2. In the said rules,-",
        "(i) in rule 59,-",
        "(a) in sub-rule (6), in clause (a), for the words “six months”, the words "
        "“three months” shall be substituted;",
        "(b) sub-rule (7) shall be omitted;",
        "(ii) in rule 60, the words “and figures” shall be omitted;",
    )
    assert [(p.op, p.kind, p.target_path) for p in found] == [
        ("substitute", "words", "r59.6.a"),
        ("omit", "provision", "r59.7"),
        ("omit", "words", "r60"),
    ]
    assert found[2].old_text == "and figures"


def test_insert_a_sub_rule_with_a_quoted_text_over_two_paragraphs() -> None:
    found = _detect(
        "2. In the said rules, in rule 37, after sub-rule (2), the following sub-rule shall be "
        "inserted, namely:-",
        "“(2A) The registered person shall pay the interest.",
        "Provided that the interest shall not exceed the tax.”;",
    )
    assert len(found) == 1
    p = found[0]
    assert (p.op, p.kind, p.status) == ("insert", "provision", "parsed")
    assert (p.anchor_path, p.position, p.new_label, p.target_path) == (
        "r37.2",
        "after",
        "2A",
        "r37.2A",
    )
    assert p.new_text is not None
    assert p.new_text.startswith("(2A) The registered person")
    assert p.new_text.endswith("exceed the tax.")
    assert p.block_ids == ("b3", "b4", "b5")
    assert p.instrument == "CGST_RULES"


def test_insert_a_rule_after_a_rule() -> None:
    found = _detect(
        "2. In the said rules, after rule 138E, the following rule shall be inserted, namely:-",
        "“138F. Sample rule.- Every person shall keep a record.”;",
    )
    assert len(found) == 1
    p = found[0]
    assert (p.anchor_path, p.target_path, p.new_label) == ("r138E", "r138F", "138F")


def test_insert_and_substitute_and_read_words() -> None:
    found = _detect(
        "2. In the said rules, in rule 10,-",
        "(a) after the words “the proper officer”, the words “or the Commissioner” "
        "shall be inserted;",
        "(b) for “Form A” read “Form B”;",
        "(c) before the words “within seven days”, insert the words “not later than”;",
    )
    assert [(p.op, p.kind, p.position) for p in found] == [
        ("insert", "words", "after"),
        ("substitute", "words", None),
        ("insert", "words", "before"),
    ]
    assert found[0].anchor_text == "the proper officer"
    assert found[0].new_text == "or the Commissioner"
    assert (found[1].old_text, found[1].new_text) == ("Form A", "Form B")
    assert all(p.target_path == "r10" for p in found)


def test_substitute_a_whole_sub_rule() -> None:
    found = _detect(
        "2. In the said rules, in rule 36, for sub-rule (4), the following sub-rule shall be "
        "substituted, namely:-",
        "“(4) The input tax credit shall be as per the statement.”;",
    )
    assert len(found) == 1
    assert (found[0].op, found[0].kind, found[0].target_path) == (
        "substitute",
        "provision",
        "r36.4",
    )
    assert found[0].new_text == "(4) The input tax credit shall be as per the statement."


def test_an_act_amendment_uses_the_named_act() -> None:
    found = detect(
        _blocks(
            "In section 16 of the Central Goods and Services Tax Act, 2017 (hereinafter referred "
            "to as the said Act), for sub-section (4), the following shall be substituted, "
            "namely:-",
            "“(4) A registered person shall not take credit after the due date.”;",
        )
    ).proposals
    assert len(found) == 1
    assert found[0].instrument == "CGST_ACT"
    assert found[0].target_path == "s16.4"


def test_unit_with_an_effective_date_phrase() -> None:
    found = _detect(
        "2. In the said rules, in rule 36, in sub-rule (4), for the words “X”, the words "
        "“Y” shall be substituted with effect from the 1st day of July, 2025."
    )
    assert len(found) == 1
    eff = found[0].effective
    assert eff is not None
    assert (eff.kind, eff.day) == ("on_date", date(2025, 7, 1))


def test_unreadable_amendment_is_kept_as_raw() -> None:
    found = _detect(
        "2. In the said rules, the entry against serial number 5 in the Table shall be "
        "substituted by the following entry."
    )
    assert len(found) == 1
    assert (found[0].status, found[0].kind, found[0].confidence) == ("raw", "raw", 0.0)
    assert "grammar_no_match" in found[0].problems


def test_text_without_amendment_words_gives_nothing() -> None:
    assert _detect("2. The Central Government hereby notifies the following dates.") == []


def test_unresolved_target_and_instrument_are_flagged() -> None:
    found = detect(
        _blocks("In the said rules, in sub-rule (4), the words “X” shall be omitted;")
    ).proposals
    assert len(found) == 1
    assert "target_unresolved" in found[0].problems
    assert "instrument_unresolved" in found[0].problems
    assert found[0].confidence == pytest.approx(0.5)


def test_the_notifications_own_effective_date() -> None:
    result = detect(_blocks(*_PREAMBLE))
    assert result.effective is not None
    assert result.effective.kind == "on_gazette"


@pytest.mark.parametrize(
    ("text", "kind", "day", "retro"),
    [
        (
            "It shall come into force on the date of its publication in the Official Gazette.",
            "on_gazette",
            None,
            False,
        ),
        (
            "It shall come into force on the 1st day of April, 2026.",
            "on_date",
            date(2026, 4, 1),
            False,
        ),
        (
            "This notification shall be deemed to have come into force on the "
            "1st day of April, 2026.",
            "on_date",
            date(2026, 4, 1),
            True,
        ),
        (
            "It shall come into force with effect from 01.10.2025.",
            "on_date",
            date(2025, 10, 1),
            False,
        ),
        (
            "It shall come into force on such date as the Central Government may, by notification, "
            "appoint.",
            "on_notification",
            None,
            False,
        ),
    ],
)
def test_extract_effective(text: str, kind: str, day: date | None, retro: bool) -> None:
    found = extract_effective(text)
    assert found is not None
    assert (found.kind, found.day, found.retrospective) == (kind, day, retro)


def test_extract_effective_none() -> None:
    assert extract_effective("Nothing about dates here.") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1st day of April, 2026", date(2026, 4, 1)),
        ("the 7th May, 2026", date(2026, 5, 7)),
        ("22nd June 2017", date(2017, 6, 22)),
        ("31.12.2025", date(2025, 12, 31)),
        ("31st February, 2025", None),
        ("no date", None),
    ],
)
def test_parse_date(text: str, expected: date | None) -> None:
    assert parse_date(text) == expected
