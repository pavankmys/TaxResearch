"""Deterministic applier and version timeline for amendments (TSD 4.10, 5.7 step 5, 5.9).

Pure functions, no database.

- :func:`apply_op` applies one operation to the text of a provision. A step that cannot be
  applied cleanly fails with a reason; nothing is guessed.
- :func:`plan_timeline` replays the approved amendments of one provision, in order, on top of its
  baseline text, and returns the dated versions that result.
- :func:`word_diff` marks the change as ``[-removed-]`` and ``{+added+}`` for the review pane.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from legal_core import word_diff

OpKind = Literal[
    "substitute_words",
    "insert_words",
    "omit_words",
    "substitute_provision",
    "omit_provision",
    "insert_provision",
]

_NO_SPACE_BEFORE = ",;.:)"
_TOKENS = re.compile(r"\s+|\S+")


@dataclass(frozen=True)
class AppliedOp:
    """One operation on one provision."""

    kind: OpKind
    old_text: str | None = None
    new_text: str | None = None
    anchor_text: str | None = None
    position: Literal["after", "before"] | None = None
    occurrence: int | None = None  # 1-based, when the words occur more than once


@dataclass(frozen=True)
class ApplyResult:
    """The text after the operation (None when the provision is omitted), or why it failed."""

    ok: bool
    text: str | None
    reason: str | None
    diff: str


def op_from_amendment(
    op: str,
    old_text: str | None,
    new_text: str | None,
    locator: dict[str, Any],
) -> AppliedOp | None:
    """The operation for an ``amendments`` row, or None when it cannot be applied (raw)."""
    kind = locator.get("kind")
    occurrence = locator.get("occurrence")
    table: dict[tuple[str, str], OpKind] = {
        ("substitute", "words"): "substitute_words",
        ("insert", "words"): "insert_words",
        ("omit", "words"): "omit_words",
        ("substitute", "provision"): "substitute_provision",
        ("omit", "provision"): "omit_provision",
        ("insert", "provision"): "insert_provision",
    }
    found = table.get((op, str(kind)))
    if found is None:
        return None
    return AppliedOp(
        kind=found,
        old_text=old_text,
        new_text=new_text,
        anchor_text=locator.get("anchor_text"),
        position=locator.get("position"),
        occurrence=int(occurrence) if occurrence else None,
    )


def _find_all(text: str, needle: str) -> list[tuple[int, int]]:
    """Spans of the needle in the text, ignoring differences in white space."""
    words = needle.split()
    if not words:
        return []
    pattern = r"\s+".join(re.escape(word) for word in words)
    if words[0][0].isalnum():
        pattern = r"(?<![A-Za-z0-9])" + pattern  # whole words: "tax" is not in "taxable"
    if words[-1][-1].isalnum():
        pattern += r"(?![A-Za-z0-9])"
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def _pick(
    spans: list[tuple[int, int]], occurrence: int | None, what: str
) -> tuple[tuple[int, int] | None, str | None]:
    if not spans:
        return None, f"{what}_not_found"
    if occurrence is not None:
        if 1 <= occurrence <= len(spans):
            return spans[occurrence - 1], None
        return None, f"{what}_occurrence_out_of_range"
    if len(spans) > 1:
        return None, f"{what}_ambiguous"
    return spans[0], None


def _fail(reason: str, text: str | None) -> ApplyResult:
    return ApplyResult(ok=False, text=text, reason=reason, diff="")


def _ok(old: str | None, new: str | None) -> ApplyResult:
    return ApplyResult(ok=True, text=new, reason=None, diff=word_diff(old, new))


def _join(left: str, middle: str, right: str) -> str:
    """Left + middle + right with one space at each join, none before closing punctuation."""
    out = left.rstrip(" ")
    if middle:
        out += ("" if not out or out.endswith("(") else " ") + middle
    tail = right.lstrip(" ")
    if tail:
        glue = "" if (not out or tail[0] in _NO_SPACE_BEFORE or out.endswith("(")) else " "
        out += glue + tail
    return out


def apply_op(text: str | None, op: AppliedOp) -> ApplyResult:
    """Apply one operation to a provision's text. ``text`` is None when it does not exist."""
    if op.kind == "insert_provision":
        if text is not None:
            return _fail("provision_exists", text)
        if not op.new_text:
            return _fail("new_text_missing", text)
        return _ok(None, op.new_text)
    if text is None:
        return _fail("provision_not_in_force", None)
    if op.kind == "omit_provision":
        return _ok(text, None)
    if op.kind == "substitute_provision":
        if not op.new_text:
            return _fail("new_text_missing", text)
        return _ok(text, op.new_text)
    if op.kind == "substitute_words":
        if not op.old_text or op.new_text is None:
            return _fail("words_missing", text)
        span, reason = _pick(_find_all(text, op.old_text), op.occurrence, "old_text")
        if span is None:
            return _fail(reason or "old_text_not_found", text)
        return _ok(text, text[: span[0]] + op.new_text + text[span[1] :])
    if op.kind == "omit_words":
        if not op.old_text:
            return _fail("words_missing", text)
        span, reason = _pick(_find_all(text, op.old_text), op.occurrence, "old_text")
        if span is None:
            return _fail(reason or "old_text_not_found", text)
        return _ok(text, _join(text[: span[0]], "", text[span[1] :]))
    if op.kind == "insert_words":
        if not op.anchor_text or not op.new_text:
            return _fail("words_missing", text)
        span, reason = _pick(_find_all(text, op.anchor_text), op.occurrence, "anchor")
        if span is None:
            return _fail(reason or "anchor_not_found", text)
        if op.position == "before":
            result = _join(text[: span[0]], op.new_text, text[span[0] :])
        else:
            result = _join(text[: span[1]], op.new_text, text[span[1] :])
        return _ok(text, result)
    return _fail("unknown_operation", text)


@dataclass(frozen=True)
class Step:
    """An approved amendment to replay. ``order`` breaks ties between the same effective date."""

    amendment_id: str
    op: AppliedOp
    effective_from: date
    order: tuple[str, ...] = ()


@dataclass(frozen=True)
class Interval:
    """One dated version of a provision. ``amendment_id`` is None for the baseline text."""

    valid_from: date
    valid_to: date | None
    text: str
    amendment_id: str | None


@dataclass(frozen=True)
class Failure:
    """A step that was not applied, and why."""

    amendment_id: str
    reason: str


@dataclass(frozen=True)
class Timeline:
    """The versions that result from a replay, and the steps that were left out."""

    intervals: tuple[Interval, ...]
    failures: tuple[Failure, ...]
    skipped: tuple[Failure, ...]


def plan_timeline(
    baseline_text: str | None, baseline_from: date | None, steps: Sequence[Step]
) -> Timeline:
    """Replay ``steps`` in order of effective date (then ``order``) on the baseline text.

    A step whose effective date is on or before the baseline date is already part of the
    baseline text and is skipped. A step that does not apply cleanly is recorded as a failure
    and the replay goes on without it. Two steps on one day give one version.
    """
    text = baseline_text
    start = baseline_from if baseline_text is not None else None
    current: str | None = None  # amendment that produced the current text
    intervals: list[Interval] = []
    failures: list[Failure] = []
    skipped: list[Failure] = []
    for step in sorted(steps, key=lambda s: (s.effective_from, s.order, s.amendment_id)):
        day = step.effective_from
        if baseline_text is not None and baseline_from is not None and day <= baseline_from:
            skipped.append(Failure(step.amendment_id, "before_baseline"))
            continue
        result = apply_op(text, step.op)
        if not result.ok:
            failures.append(Failure(step.amendment_id, result.reason or "failed"))
            continue
        if text is not None and start is not None and start < day:
            intervals.append(Interval(start, day, text, current))
        text, start, current = result.text, day, step.amendment_id
    if text is not None and start is not None:
        intervals.append(Interval(start, None, text, current))
    return Timeline(tuple(intervals), tuple(failures), tuple(skipped))


def interval_at(intervals: Sequence[Interval], day: date) -> Interval | None:
    """The version in force on a day, or None."""
    for interval in intervals:
        if interval.valid_from <= day and (interval.valid_to is None or day < interval.valid_to):
            return interval
    return None
