"""Round-robin review assignment (pure function) and task priorities."""

import uuid

from worker.review import PRIORITY_BY_KIND, priority_for, round_robin_next


def test_first_task_goes_to_the_first_editor() -> None:
    editors = [uuid.UUID(int=n) for n in (1, 2, 3)]
    assert round_robin_next(editors, None) == editors[0]


def test_next_editor_follows_the_last_assignee_and_wraps() -> None:
    editors = [uuid.UUID(int=n) for n in (1, 2, 3)]
    assert round_robin_next(editors, editors[0]) == editors[1]
    assert round_robin_next(editors, editors[1]) == editors[2]
    assert round_robin_next(editors, editors[2]) == editors[0]


def test_unknown_last_assignee_starts_again() -> None:
    editors = [uuid.UUID(int=n) for n in (1, 2)]
    assert round_robin_next(editors, uuid.UUID(int=99)) == editors[0]


def test_no_editor_means_unassigned() -> None:
    assert round_robin_next([], uuid.UUID(int=1)) is None


def test_two_editors_alternate() -> None:
    editors = [uuid.UUID(int=10), uuid.UUID(int=20)]
    assigned: list[uuid.UUID | None] = []
    last: uuid.UUID | None = None
    for _ in range(4):
        last = round_robin_next(editors, last)
        assigned.append(last)
    assert assigned == [editors[0], editors[1], editors[0], editors[1]]


def test_priorities_by_kind() -> None:
    assert priority_for("parse_failure") == 2
    assert priority_for("metadata") == 3
    assert priority_for("miss_report") == 4
    assert priority_for("something_new") == 3
    assert PRIORITY_BY_KIND["parse_failure"] < PRIORITY_BY_KIND["metadata"]
