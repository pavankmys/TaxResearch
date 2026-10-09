"""Structure paths for blocks, and the numbering gate (TSD 5.5; plan decision 3).

Pure functions: no database access. ``segment`` returns one path per input block, in the same
order, plus the numbered items that the numbering gate checks.

Path formats:
    Acts       ch5.s16.2.c.iv   (chapter, section, subsection, clause, subclause)
               s16.2.c.prov1, s16.expl1   (provisos and explanations attach to the deepest node)
    Rules      r36.4            (same, with rule numbers)
    Acts and Rules also use: toc (the arrangement-of-sections index, excluded from numbering),
               sched1 (a schedule and its items), <path>.fn3 (a footnote line, which does not
               change the position)
    Notifications  pre, p3, p3.i2 (amending unit 2 of paragraph 3), sched1, sched1.row12
    Circulars      hdr, p4, p4.2
    Judgements     hdr, facts.p12, order.p40 (the printed number stays in the label)
    Other          p<index>

Boilerplate blocks inherit the current path and do not change the state.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from legal_core.text import normalise_text

from worker.ingest.numbering import Marker, read_numbering

SEGMENTER_VERSION = "seg-2"

ROMAN_SUBCLAUSES = frozenset({"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"})
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}

_PARAGRAPH = re.compile(r"^(\d{1,3})[.)](?=\s|$)")
_SUB_PARAGRAPH = re.compile(r"^(\d{1,3})\.(\d{1,3})(?=\s|$)")
_AMEND_CUE = re.compile(r"\b(substituted|inserted|omitted)\b", re.IGNORECASE)
_AMEND_UNIT = re.compile(
    r"^(\(\s*(?:[a-z]{1,4}|\d{1,3})\s*\)|in\s+(?:rule|section|the\s+said|sub-section|clause|"
    r"paragraph|the\s+notification)\b)",
    re.IGNORECASE,
)
_SCHEDULE_HEADING = re.compile(r"^(SCHEDULE|Schedule|ANNEXURE|Annexure|Table|TABLE)\b")
_TOC_HEADING = re.compile(
    r"^(?:ARRANGEMENT\s+OF\s+(?:SECTIONS|RULES)|(?:TABLE\s+OF\s+)?CONTENTS)\b", re.IGNORECASE
)
_TITLE_LINE = re.compile(r"^THE\b.{3,120}\b(?:ACT|RULES)\b.*\d{4}\W*$")
_ACT_SCHEDULE = re.compile(r"^(?:THE\s+)?SCHEDULE\s+[IVXLC]+\b", re.IGNORECASE)
_FOOTNOTE_VERB = re.compile(
    r"(?:inserted|substituted|omitted|amended|added|renumbered|repealed)\b|\b(?:ins|subs)\.",
    re.IGNORECASE,
)
_FOOTNOTE_SOURCE = re.compile(
    r"\bw\.e\.f\b|\bvide\b|\bby\s+(?:the\s+)?(?:Act|Finance|Taxation|Notification|Notf)\b"
    r"|\bAct\s+\d+\s+of\s+\d{4}\b|\bNo\.\s*\d+\s*/\s*\d{4}\b",
    re.IGNORECASE,
)
_FOOTNOTE_START = re.compile(r"^\d{1,3}\s*\.?\s*\S")
_FOOTNOTE_MAX_CHARS = 300
_FORM_MAX_CHARS = 60
_NUMBER_MAX_JUMP = 25
_TABLE_ROW_NUMBER = re.compile(r"^\d{1,3}[A-Z]{0,2}\.\s*\|")  # "150. | | Natural or cultured..."
_SUB_MAX_JUMP = 10
_NUM_PARTS = re.compile(r"^(\d+)([A-Z]*)$")
# Layout noise in the leading characters of "as amended" PDFs: an amendment bracket with its
# footnote digit ("1[20. Manner"), spaced markers ("( 1 )", "80 .") and a missing space after
# the dot ("31.Residual").
_LEAD_BRACKET = re.compile(r"^(?:\d{1,3}\s*)?\[\s*")
_LEAD_PAREN = re.compile(r"^\(\s*([0-9A-Za-z]{1,4})\s*\)\s*")
_LEAD_SPACED_DOT = re.compile(r"^(\d{1,3}[A-Z]{0,2})\s+\.(?=\s|-|—|–|$)")
_LEAD_NO_SPACE = re.compile(r"^(\d{1,3}[A-Z]{0,2}\.)(?=[A-Z])")
# (i), (v) and (x) straight after (h), (u) and (w) are the next letter, not a roman subclause.
_LETTER_BEFORE_ROMAN = {"i": "h", "v": "u", "x": "w"}
_LABEL_WORD = re.compile(
    r"\b(facts|issues|arguments|submissions|analysis|findings|discussion|conclusion|order)\b",
    re.IGNORECASE,
)
_JUDGEMENT_LABELS = {
    "facts": "facts",
    "issues": "issues",
    "arguments": "arguments",
    "submissions": "arguments",
    "findings": "findings",
    "analysis": "findings",
    "discussion": "findings",
    "conclusion": "order",
    "order": "order",
}


@dataclass(frozen=True)
class SegBlock:
    """What the segmenter needs from a block."""

    kind: str  # heading | para | table | table_row | footnote
    text: str
    is_boilerplate: bool = False


@dataclass(frozen=True)
class NumberedItem:
    """A numbered unit for the gate. prefix is s (Act section), r (rule) or p (paragraph)."""

    prefix: str
    label: str  # "16A", "3", "4.2"


@dataclass(frozen=True)
class Segmentation:
    """Paths aligned with the input blocks, and the numbered items in document order."""

    paths: tuple[str, ...]
    numbered: tuple[NumberedItem, ...]


def _roman_value(token: str) -> int:
    total = 0
    previous = 0
    for char in reversed(token.lower()):
        value = _ROMAN_VALUES[char]
        total = total - value if value < previous else total + value
        previous = max(previous, value)
    return total


def _clean_lead(text: str) -> str:
    """The block text with the layout noise removed from its leading markers.

    Used to find the markers only: the stored block text is never changed.
    """
    cleaned = _LEAD_BRACKET.sub("", text.strip())
    out = ""
    while True:
        match = _LEAD_PAREN.match(cleaned)
        if match is None:
            break
        out += f"({match.group(1)})"
        cleaned = cleaned[match.end() :]
    cleaned = out + cleaned
    cleaned = _LEAD_SPACED_DOT.sub(r"\1.", cleaned)
    return _LEAD_NO_SPACE.sub(r"\1 ", cleaned)


def _lead_markers(text: str) -> tuple[Marker, ...]:
    return read_numbering(_clean_lead(text)).markers


def _number_parts(token: str) -> tuple[int, str] | None:
    match = _NUM_PARTS.match(token)
    return (int(match.group(1)), match.group(2)) if match else None


def _is_footnote(text: str) -> bool:
    """A short line that starts with a number and records an amendment ("5Inserted vide ...")."""
    return (
        len(text) <= _FOOTNOTE_MAX_CHARS
        and _FOOTNOTE_START.match(text) is not None
        and _FOOTNOTE_VERB.search(text) is not None
        and _FOOTNOTE_SOURCE.search(text) is not None
    )


class _ActSegmenter:
    """Acts (and Rules when ``rules`` is set): chapter, section, sub, clause, subclause.

    A marker that cannot be the next one in sequence (a wrapped line that starts with "(1)", a
    cross-reference that starts with a number) does not move the position: the block stays in
    the current path. Footnote lines and schedules get their own paths.
    """

    _LEVEL_CHAPTER, _LEVEL_SECTION, _LEVEL_SUB, _LEVEL_CLAUSE, _LEVEL_SUBCLAUSE = range(5)

    def __init__(self, rules: bool) -> None:
        self._prefix = "r" if rules else "s"
        self._levels: list[str | None] = [None] * 5
        self._counts: dict[str, int] = {}
        self._forms = 0
        self._annexes = 0
        self._schedules = 0
        self._footnotes = 0
        self._in_schedule = False
        self._last_number: tuple[int, str] | None = None
        self.current = "pre"
        self.numbered: list[NumberedItem] = []

    def _base(self) -> str:
        parts = [level for level in self._levels if level]
        return ".".join(parts) if parts else "pre"

    def _set(self, level: int, token: str) -> None:
        self._levels[level] = token
        for deeper in range(level + 1, 5):
            self._levels[deeper] = None

    def _clear(self) -> None:
        self._levels = [None] * 5

    def _paren_level(self, inner: str) -> int:
        if inner[0].isdigit():
            return self._LEVEL_SUB
        clause = self._levels[self._LEVEL_CLAUSE]
        subclause = self._levels[self._LEVEL_SUBCLAUSE]
        if inner in ROMAN_SUBCLAUSES and (clause is not None or subclause is not None):
            if subclause is None and _LETTER_BEFORE_ROMAN.get(inner) == clause:
                return self._LEVEL_CLAUSE
            return self._LEVEL_SUBCLAUSE
        return self._LEVEL_CLAUSE

    def _number_in_sequence(self, label: str) -> bool:
        parts = _number_parts(label)
        if parts is None or label.startswith("0"):
            return False
        if self._last_number is None:
            return True
        base, suffix = parts
        last_base, last_suffix = self._last_number
        if base == last_base:
            return suffix > last_suffix
        return last_base < base <= last_base + _NUMBER_MAX_JUMP

    def _paren_in_sequence(self, inner: str, level: int) -> bool:
        current = self._levels[level]
        if current is None:
            return True
        if level == self._LEVEL_SUB:
            new, old = _number_parts(inner), _number_parts(current)
            if new is None or old is None:
                return False
            if new[0] == old[0]:
                return new[1] > old[1]
            return old[0] < new[0] <= old[0] + _SUB_MAX_JUMP
        if level == self._LEVEL_SUBCLAUSE:
            return _roman_value(inner) > _roman_value(current)
        return (len(inner), inner) > (len(current), current)

    def _accepts(self, kind: str, text: str, block: SegBlock) -> bool:
        if kind == "NUMBER":
            if _TABLE_ROW_NUMBER.match(block.text.strip()):
                return False  # a numbered table row (a tariff list), not a section or rule
            return self._number_in_sequence(text.rstrip("."))
        if kind == "PAREN":
            inner = text[1:-1]
            return self._paren_in_sequence(inner, self._paren_level(inner))
        if kind == "FORM":
            return block.kind == "heading" or len(block.text.strip()) <= _FORM_MAX_CHARS
        return True

    def _count(self, kind: str) -> int:
        key = f"{self._base()}|{kind}"
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    def _apply(self, kind: str, text: str) -> str:
        if kind == "CHAPTER":
            numeral = text.split()[-1]
            self._set(self._LEVEL_CHAPTER, f"ch{_roman_value(numeral)}")
            return self._base()
        if kind == "NUMBER":
            label = text.rstrip(".")
            self._set(self._LEVEL_SECTION, f"{self._prefix}{label}")
            self._last_number = _number_parts(label)
            self.numbered.append(NumberedItem(prefix=self._prefix, label=label))
            return self._base()
        if kind == "PAREN":
            inner = text[1:-1]
            level = self._paren_level(inner)
            self._set(level, inner)
            return self._base()
        if kind == "PROVISO":
            return f"{self._base()}.prov{self._count('prov')}"
        if kind == "EXPLANATION":
            return f"{self._base()}.expl{self._count('expl')}"
        if kind == "FORM":
            self._forms += 1
            self._clear()
            return f"form{self._forms}"
        if kind == "ANNEX":
            self._annexes += 1
            self._clear()
            return f"annex{self._annexes}"
        raise AssertionError(f"unknown marker kind: {kind}")

    def step(self, block: SegBlock) -> str:
        text = block.text.strip()
        if _ACT_SCHEDULE.match(text) and (block.kind == "heading" or len(text) <= _FORM_MAX_CHARS):
            self._schedules += 1
            self._in_schedule = True
            self._clear()
            self.current = f"sched{self._schedules}"
            return self.current
        if self._in_schedule:
            return self.current
        if _is_footnote(text):
            self._footnotes += 1
            return f"{self.current}.fn{self._footnotes}"
        path = self.current
        for marker in _lead_markers(block.text):
            if not self._accepts(marker.kind, marker.text, block):
                break
            path = self._apply(marker.kind, marker.text)
        self.current = path
        return path


class _NotificationSegmenter:
    """Preamble, numbered paragraphs, amending units, schedules and table rows."""

    def __init__(self) -> None:
        self.current = "pre"
        self.numbered: list[NumberedItem] = []
        self._para: str | None = None
        self._items = 0
        self._schedules = 0
        self._rows = 0
        self._in_schedule = False

    def _open_schedule(self) -> None:
        self._schedules += 1
        self._rows = 0
        self._in_schedule = True

    def step(self, block: SegBlock) -> str:
        text = normalise_text(block.text)
        if block.kind == "table_row":
            if not self._in_schedule:
                self._open_schedule()
            self._rows += 1
            self.current = f"sched{self._schedules}.row{self._rows}"
            return self.current

        match = _PARAGRAPH.match(text)
        if match:
            self._para = match.group(1)
            self._items = 0
            self._in_schedule = False
            self.numbered.append(NumberedItem(prefix="p", label=self._para))
            self.current = f"p{self._para}"
            return self.current

        if len(text) <= 80 and _is_schedule_heading(block, text):
            self._open_schedule()
            self.current = f"sched{self._schedules}"
            return self.current

        if self._in_schedule:
            self.current = f"sched{self._schedules}"
            return self.current

        if self._para is None:
            self.current = "pre"
            return self.current

        if _AMEND_UNIT.match(text) and _AMEND_CUE.search(text):
            self._items += 1
            self.current = f"p{self._para}.i{self._items}"
            return self.current

        own = f"p{self._para}"
        if self.current != own and not self.current.startswith(f"{own}.i"):
            self.current = own
        return self.current


class _CircularSegmenter:
    """Header until the first numbered paragraph, then p<n> and sub-numbered p<n>.<m>."""

    def __init__(self) -> None:
        self.current = "hdr"
        self.numbered: list[NumberedItem] = []
        self._in_header = True

    def step(self, block: SegBlock) -> str:
        text = normalise_text(block.text)
        sub = _SUB_PARAGRAPH.match(text)
        if sub:
            self._in_header = False
            label = f"{sub.group(1)}.{sub.group(2)}"
            self.numbered.append(NumberedItem(prefix="p", label=label))
            self.current = f"p{label}"
            return self.current
        match = _PARAGRAPH.match(text)
        if match:
            self._in_header = False
            self.numbered.append(NumberedItem(prefix="p", label=match.group(1)))
            self.current = f"p{match.group(1)}"
            return self.current
        if self._in_header:
            self.current = "hdr"
        return self.current


class _JudgementSegmenter:
    """Header until the first numbered paragraph or label heading; then labelled paragraphs."""

    def __init__(self) -> None:
        self.current = "hdr"
        self.numbered: list[NumberedItem] = []
        self._in_header = True
        self._label: str | None = None
        self._running = 0

    def step(self, block: SegBlock) -> str:
        text = normalise_text(block.text)
        heading = _is_heading(block, text)
        if heading and len(text) <= 40:
            word = _LABEL_WORD.search(text)
            if word is not None:
                self._label = _JUDGEMENT_LABELS[word.group(1).lower()]
                self._in_header = False
                self.current = self._label
                return self.current
        match = _PARAGRAPH.match(text)
        if match and not heading:
            self._in_header = False
            self._running += 1
            self.numbered.append(NumberedItem(prefix="p", label=match.group(1)))
            self.current = f"{self._label or 'body'}.p{match.group(1)}"
            return self.current
        if self._in_header:
            self.current = "hdr"
            return self.current
        if heading:
            self.current = self._label or "body"
            return self.current
        self._running += 1
        self.current = f"{self._label or 'body'}.p{self._running}"
        return self.current


class _OtherSegmenter:
    """Every block gets its own paragraph index."""

    def __init__(self) -> None:
        self.current = "p0"
        self.numbered: list[NumberedItem] = []
        self._index = 0

    def step(self, block: SegBlock) -> str:
        self._index += 1
        self.current = f"p{self._index}"
        return self.current


def _is_schedule_heading(block: SegBlock, text: str) -> bool:
    """A short heading block, or a short line that starts with the keyword (not a sentence)."""
    if _PARAGRAPH.match(text):
        return False
    return block.kind == "heading" or _SCHEDULE_HEADING.match(text) is not None


def _is_heading(block: SegBlock, text: str) -> bool:
    if block.kind == "heading":
        return True
    return len(text) <= 60 and text == text.upper() and bool(re.search(r"[A-Z]", text))


Segmenter = _ActSegmenter | _NotificationSegmenter | _CircularSegmenter | _JudgementSegmenter


def make_segmenter(doc_type: str) -> Segmenter | _OtherSegmenter:
    """The segmenter for a doc_type."""
    if doc_type == "act":
        return _ActSegmenter(rules=False)
    if doc_type == "rules":
        return _ActSegmenter(rules=True)
    if doc_type == "notification":
        return _NotificationSegmenter()
    if doc_type in {"circular", "instruction", "order"}:
        return _CircularSegmenter()
    if doc_type == "judgement":
        return _JudgementSegmenter()
    return _OtherSegmenter()


def _toc_span(blocks: Sequence[SegBlock]) -> tuple[int, int, int] | None:
    """The arrangement-of-sections index of an Act or Rules: (start, preamble_start, end).

    It starts at a heading such as "ARRANGEMENT OF SECTIONS" and ends at the first block whose
    leading chapter or number repeats an entry of the index, which is where the body begins.
    The title line, if there is one, and the blocks after it up to ``end`` are the preamble.
    """
    start = next(
        (
            i
            for i, b in enumerate(blocks)
            if not b.is_boilerplate
            and len(b.text.strip()) <= _FORM_MAX_CHARS
            and _TOC_HEADING.match(b.text.strip())
        ),
        None,
    )
    if start is None:
        return None
    seen: set[tuple[str, str]] = set()
    for j in range(start + 1, len(blocks)):
        if blocks[j].is_boilerplate:
            continue
        markers = _lead_markers(blocks[j].text)
        if not markers or markers[0].kind not in {"CHAPTER", "NUMBER"}:
            continue
        key = (markers[0].kind, markers[0].text.rstrip("."))
        if key not in seen:
            seen.add(key)
            continue
        preamble = j
        for k in range(j - 1, start, -1):
            title = blocks[k].text.strip()
            if title == title.upper() and _TITLE_LINE.match(title):
                preamble = k
                break
        return start, preamble, j
    return None


def segment(doc_type: str, blocks: Sequence[SegBlock]) -> Segmentation:
    """Structure path for every block, in order, plus the numbered items for the gate."""
    segmenter = make_segmenter(doc_type)
    is_law = doc_type in {"act", "rules"}
    span = _toc_span(blocks) if is_law else None
    paths: list[str] = []
    last_kind = ""  # kind of the latest block that was segmented
    last_path = "pre"
    for index, block in enumerate(blocks):
        if span is not None and index < span[2]:
            # front matter ("list of amending Acts", abbreviations), the index, then the preamble
            paths.append("toc" if span[0] <= index < span[1] else "pre")
            continue
        if block.is_boilerplate:
            paths.append(segmenter.current)
            continue
        if is_law and block.kind == "table_row" and last_kind in {"table", "table_row"}:
            paths.append(last_path)  # the parser emits a table and then its rows
            continue
        path = segmenter.step(block)
        paths.append(path)
        last_kind, last_path = block.kind, path
    return Segmentation(paths=tuple(paths), numbered=tuple(segmenter.numbered))


_BASE_NUMBER = re.compile(r"^(\d+)")


def numbering_problems(items: Sequence[NumberedItem]) -> list[dict[str, str]]:
    """Gaps, duplicates and out-of-order numbers, as entries for the parse_failure task.

    Duplicates compare the full label (16 and 16A are different). Order and gaps use the
    integer part, so 16A after 16 is in order.
    """
    problems: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    bases: set[int] = set()
    last_base: int | None = None
    for item in items:
        path = f"{item.prefix}{item.label}"
        key = (item.prefix, item.label)
        if key in seen:
            problems.append(
                {"path": path, "problem": "duplicate", "detail": f"{path} appears more than once"}
            )
        seen.add(key)
        match = _BASE_NUMBER.match(item.label)
        if match is None:
            continue
        base = int(match.group(1))
        if last_base is not None and base < last_base:
            problems.append(
                {
                    "path": path,
                    "problem": "out_of_order",
                    "detail": f"{path} follows {item.prefix}{last_base}",
                }
            )
        last_base = base
        bases.add(base)
    if bases:
        prefix = items[0].prefix
        for number in range(min(bases), max(bases) + 1):
            if number not in bases:
                problems.append(
                    {
                        "path": f"{prefix}{number}",
                        "problem": "gap",
                        "detail": f"no {prefix}{number} between {min(bases)} and {max(bases)}",
                    }
                )
    return problems
