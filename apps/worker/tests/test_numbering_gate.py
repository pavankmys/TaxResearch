"""Numbering gate: gaps, duplicates and out-of-order numbers (pure)."""

from worker.ingest.structure import NumberedItem, numbering_problems


def _items(prefix: str, labels: list[str]) -> list[NumberedItem]:
    return [NumberedItem(prefix=prefix, label=label) for label in labels]


def test_sequential_numbers_have_no_problems() -> None:
    assert numbering_problems(_items("s", ["1", "2", "3"])) == []


def test_suffix_letters_are_in_order() -> None:
    assert numbering_problems(_items("s", ["15", "16", "16A", "17"])) == []


def test_gap_is_reported_with_the_missing_number() -> None:
    problems = numbering_problems(_items("p", ["1", "2", "4", "5"]))
    assert problems == [{"path": "p3", "problem": "gap", "detail": "no p3 between 1 and 5"}]


def test_duplicate_label_is_reported() -> None:
    problems = numbering_problems(_items("s", ["1", "2", "2", "3"]))
    assert [p["problem"] for p in problems] == ["duplicate"]
    assert problems[0]["path"] == "s2"


def test_duplicate_suffix_label_is_reported_but_not_a_base_clash() -> None:
    problems = numbering_problems(_items("s", ["16", "16A", "16A"]))
    assert [(p["path"], p["problem"]) for p in problems] == [("s16A", "duplicate")]


def test_out_of_order_is_reported() -> None:
    problems = numbering_problems(_items("s", ["1", "3", "2", "4"]))
    kinds = [(p["path"], p["problem"]) for p in problems]
    assert ("s2", "out_of_order") in kinds


def test_sub_numbered_circular_labels() -> None:
    assert numbering_problems(_items("p", ["4", "4.1", "4.2", "5"])) == []
    assert [p["problem"] for p in numbering_problems(_items("p", ["4.1", "4.1"]))] == ["duplicate"]


def test_empty_sequence_has_no_problems() -> None:
    assert numbering_problems([]) == []
