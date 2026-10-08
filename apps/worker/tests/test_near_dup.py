"""Near-duplicate candidate logic (pure): simhash distance, date, court and number matching."""

import uuid
from datetime import date

from worker.ingest.near_dup import (
    Candidate,
    Probe,
    merge_target,
    numbers_for,
    probable_duplicates,
)
from worker.ingest.simhash import simhash64

TEXT = "The rate of tax on the supply of goods shall be as notified in the schedule. " * 4


def _probe(**overrides: object) -> Probe:
    values: dict[str, object] = {
        "document_id": uuid.uuid4(),
        "version_id": uuid.uuid4(),
        "simhash": simhash64(TEXT),
        "doc_date": date(2017, 6, 28),
        "court": None,
        "numbers": frozenset({"canon:ntf:CT(R):11/2017"}),
    }
    values.update(overrides)
    return Probe(**values)  # type: ignore[arg-type]


def _candidate(**overrides: object) -> Candidate:
    values: dict[str, object] = {
        "document_id": uuid.uuid4(),
        "version_id": uuid.uuid4(),
        "simhash": simhash64(TEXT),
        "doc_date": date(2017, 6, 28),
        "court": None,
        "numbers": frozenset(),
    }
    values.update(overrides)
    return Candidate(**values)  # type: ignore[arg-type]


def test_same_text_same_date_is_a_probable_duplicate() -> None:
    probe = _probe()
    candidate = _candidate()
    assert probable_duplicates(probe, [candidate]) == [candidate]


def test_distant_simhash_is_not_a_duplicate() -> None:
    other = simhash64("Completely different words about a different subject entirely here. " * 4)
    assert probable_duplicates(_probe(), [_candidate(simhash=other)]) == []


def test_different_date_is_not_a_duplicate() -> None:
    assert probable_duplicates(_probe(), [_candidate(doc_date=date(2017, 7, 1))]) == []


def test_judgements_need_the_same_court() -> None:
    probe = _probe(court="SC")
    assert probable_duplicates(probe, [_candidate(court="HC-KA")]) == []
    assert len(probable_duplicates(probe, [_candidate(court="SC")])) == 1


def test_a_document_is_never_its_own_candidate() -> None:
    probe = _probe()
    assert probable_duplicates(probe, [_candidate(document_id=probe.document_id)]) == []


def test_merge_target_needs_a_shared_number() -> None:
    probe = _probe()
    without_number = _candidate(numbers=frozenset({"canon:ntf:CT(R):12/2017"}))
    with_number = _candidate(numbers=frozenset({"canon:ntf:CT(R):11/2017"}))
    assert merge_target(probe, [without_number]) is None
    assert merge_target(probe, [without_number, with_number]) == with_number


def test_missing_simhash_or_date_never_matches() -> None:
    assert probable_duplicates(_probe(simhash=None), [_candidate()]) == []
    assert probable_duplicates(_probe(doc_date=None), [_candidate()]) == []


def test_numbers_for_skips_provisional_ids() -> None:
    assert numbers_for("unk:0123456789abcdef", []) == frozenset()
    assert numbers_for("ntf:CT(R):11/2017", ["CA 1/2020"]) == frozenset(
        {"canon:ntf:CT(R):11/2017", "case:CA 1/2020"}
    )
