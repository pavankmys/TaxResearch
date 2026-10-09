"""Tests for the amendment-target locator parser (synthetic phrases)."""

import pytest
from legal_core.locator import Locator, Step, parse_locator


def _path(text: str) -> str | None:
    found = parse_locator(text)
    return found.path() if found else None


@pytest.mark.parametrize(
    ("text", "path"),
    [
        ("rule 36", "r36"),
        ("Rule 138E", "r138E"),
        ("section 16", "s16"),
        ("section 43A", "s43A"),
        ("the rule 36", "r36"),
        ("in rule 36", "r36"),
        ("rule 36(4)", "r36.4"),
        ("rule 36(4)(a)", "r36.4.a"),
        ("rule 36 ( 4 ) ( a )", "r36.4.a"),
        ("section 16(2)(c)(iv)", "s16.2.c.iv"),
        ("sub-rule (4) of rule 36", "r36.4"),
        ("sub rule (4) of rule 36", "r36.4"),
        ("sub-section (2) of section 16", "s16.2"),
        ("clause (a) of sub-rule (4) of rule 36", "r36.4.a"),
        ("clause (c) of sub-section (2) of section 16", "s16.2.c"),
        ("sub-clause (iv) of clause (c) of sub-section (2) of section 16", "s16.2.c.iv"),
        ("sub-rule (4A) of rule 36", "r36.4A"),
        ("sub-section (1A) of section 16", "s16.1A"),
        ("clause (aa) of sub-rule (3) of rule 9", "r9.3.aa"),
        ("the proviso to sub-rule (4) of rule 36", "r36.4.prov1"),
        ("the first proviso to sub-rule (4) of rule 36", "r36.4.prov1"),
        ("the second proviso to sub-rule (4) of rule 36", "r36.4.prov2"),
        ("third proviso to section 16", "s16.prov3"),
        ("Explanation to rule 36", "r36.expl1"),
        ("Explanation 2 to sub-section (2) of section 16", "s16.2.expl2"),
    ],
)
def test_provision_paths(text: str, path: str) -> None:
    assert _path(text) == path


def test_steps_run_from_the_outside_in() -> None:
    found = parse_locator("clause (a) of sub-rule (4) of rule 36")
    assert found is not None
    assert found.steps == (Step("rule", "36"), Step("subsection", "4"), Step("clause", "a"))
    assert not found.relative
    assert found.is_provision


def test_a_roman_label_after_a_clause_is_a_subclause_but_not_after_a_subsection() -> None:
    deep = parse_locator("section 16(2)(c)(iv)")
    assert deep is not None
    assert [s.level for s in deep.steps] == ["section", "subsection", "clause", "subclause"]
    shallow = parse_locator("section 16(2)(i)")
    assert shallow is not None
    assert [s.level for s in shallow.steps] == ["section", "subsection", "clause"]


@pytest.mark.parametrize(
    ("text", "instrument"),
    [
        ("rule 36 of the said rules", "said_rules"),
        ("section 16 of the said Act", "said_act"),
        ("section 16 of the Central Goods and Services Tax Act, 2017", "CGST_ACT"),
        ("rule 36 of the Central Goods and Services Tax Rules, 2017", "CGST_RULES"),
        ("section 5 of the Integrated Goods and Services Tax Act, 2017", "IGST_ACT"),
        ("rule 36 of the CGST Rules", "CGST_RULES"),
        ("rule 36", None),
    ],
)
def test_instrument_phrase(text: str, instrument: str | None) -> None:
    found = parse_locator(text)
    assert found is not None
    assert found.instrument == instrument
    assert found.path() is not None


def test_relative_locator_is_placed_inside_its_parent() -> None:
    parent = parse_locator("rule 36")
    child = parse_locator("clause (a) of sub-rule (4)")
    assert parent is not None
    assert child is not None
    assert child.relative
    assert child.path() is None
    placed = child.within(parent)
    assert placed.path() == "r36.4.a"
    assert not placed.relative


def test_within_leaves_an_absolute_locator_alone() -> None:
    parent = parse_locator("rule 36")
    other = parse_locator("rule 59")
    assert parent is not None
    assert other is not None
    assert other.within(parent) == other


def test_form_and_schedule_are_not_provisions() -> None:
    form = parse_locator("FORM GST ITC-04")
    assert isinstance(form, Locator)
    assert form.steps == (Step("form", "GST ITC-04"),)
    assert not form.is_provision
    assert form.path() is None
    schedule = parse_locator("Schedule III")
    assert schedule is not None
    assert schedule.steps == (Step("schedule", "III"),)
    assert schedule.path() is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "the words",
        "substitute the following",
        "rule",
        "rule thirty-six",
        "in rule 36 for",
    ],
)
def test_unreadable_phrases_give_none(text: str) -> None:
    assert parse_locator(text) is None


def test_never_raises_on_odd_input() -> None:
    for text in ["(((", "rule 36(", "section ;;;", "\x00", "rule 36(4)(a)(b)(c)(d)(e)(f)"]:
        parse_locator(text)  # must not raise
