"""Rule-based metadata extractors per document type (TSD 5.6; M3a plan).

Pure functions: the caller passes the blocks, the file name and "today". Each field gets a
confidence from the rule that found it: an exact header pattern 0.95, a fallback pattern 0.7,
an inference from the file name 0.5. Cross-checks halve a field's confidence and add an issue.
"""

import calendar
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from legal_core import Aliases, load_aliases, normalise_series, parse_citation
from legal_core.ids import circular_id, instruction_id, judgement_id, notification_id, order_id
from legal_core.text import normalise_text

from worker.config import (
    CaseNumberPattern,
    CourtConfig,
    config_dir,
    load_case_number_patterns,
    load_courts,
)
from worker.ingest.metadata import MetadataProposal, missing_required, validate_fields
from worker.ingest.structure import SegBlock

EXACT = 0.95
FALLBACK = 0.7
FILE_NAME = 0.5
CITATION = 0.8
GST_START = date(2017, 6, 1)
JUDGEMENT_START = date(1950, 1, 1)
HEADER_BLOCKS = 15
JUDGEMENT_HEADER_BLOCKS = 30
BODY_BLOCKS = 60
TAIL_BLOCKS = 10
MAX_SECTIONS = 200

_MONTHS: dict[str, int] = {}
for _index in range(1, 13):
    _MONTHS[calendar.month_name[_index].lower()] = _index
    _MONTHS[calendar.month_abbr[_index].lower()] = _index
_MONTHS["sept"] = 9

_TEXT_DATE = r"(\d{1,2})(?:st|nd|rd|th)?(?:\s+day\s+of)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})"
_NUMERIC_DATE = r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})"
_DATED = re.compile(r"\b(?:the|dated)\s*:?\s*(?:this\s+the\s+)?" + _TEXT_DATE, re.IGNORECASE)
_DATED_NUMERIC = re.compile(r"\bdated\s*:?\s*" + _NUMERIC_DATE, re.IGNORECASE)
_DATED_WORD = re.compile(r"\bdated\s*:?\s*(?:this\s+the\s+)?" + _TEXT_DATE, re.IGNORECASE)
_ANY_TEXT_DATE = re.compile(_TEXT_DATE, re.IGNORECASE)
_ANY_NUMERIC_DATE = re.compile(r"(?<!\d)" + _NUMERIC_DATE + r"(?!\d)")
_EFFECT = re.compile(
    r"(?:come\s+into\s+force|effect\s+from)\s+(?:on\s+)?(?:the\s+)?" + _TEXT_DATE, re.IGNORECASE
)
_NTF_HEADER = re.compile(
    r"Notification\s+No\.?\s*(\d{1,4})\s*/\s*(\d{4})\s*-\s*([A-Za-z][A-Za-z ()\.]*)"
)
_NTF_FALLBACK = re.compile(r"(?:Notification|Notf\.?)\s+No\.?\s*(\d{1,4})\s*/\s*(\d{4})", re.I)
_NTF_TITLE = re.compile(r"(\d{1,4})\s*/\s*(\d{4})")
_SERIES_WORDS = re.compile(
    r"\b(Central Tax \(Rate\)|Integrated Tax \(Rate\)|Union Territory Tax \(Rate\)|"
    r"Compensation Cess \(Rate\)|Central Tax|Integrated Tax|Union Territory Tax|"
    r"Compensation Cess)(?![A-Za-z])",
    re.IGNORECASE,
)
_GAZETTE = re.compile(r"G\.?\s*S\.?\s*R\.?\s*(\d+)\s*\(\s*E\s*\)", re.IGNORECASE)
_MOF = re.compile(r"Ministry\s+of\s+Finance\s*\(Department\s+of\s+Revenue\)", re.IGNORECASE)
_CIRCULAR = re.compile(r"Circular\s+No\.?\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d{4})", re.IGNORECASE)
_NUMBERED_NO = re.compile(
    r"(Instruction|Order|Circular)\s+No\.?\s*(\d+)\s*/\s*(\d{4})", re.IGNORECASE
)
_CIRCULAR_TITLE = re.compile(r"(\d+)\s*/\s*(\d+)\s*/\s*(\d{4})")
_DIN = re.compile(r"\bDIN\s*[:\-]?\s*([0-9A-Z]{20})\b")
_SUBJECT = re.compile(
    r"\b(?:Subject|Sub)\s*[:\-]\s*(.+?)(?=\s+(?:DIN\b|\d{1,3}\.\s)|$)", re.IGNORECASE
)
_ACT_TITLE = re.compile(r"^THE\s+[A-Z][A-Z ,\-]*\s+ACT,\s*(?:19|20)\d{2}$")
_RULES_TITLE = re.compile(r"^[A-Z][A-Z ,\-]*\s+RULES,\s*(?:19|20)\d{2}$")
_PARTY_LINE = re.compile(
    r"(.+?)\s*\.{2,}\s*(?:the\s+)?(Petitioners?|Appellants?|Respondents?|Applicants?)"
    r"(?:\s*\(s\))?",
    re.IGNORECASE,
)
_CORAM = re.compile(r"\bCORAM\s*:?\s*(.+)", re.IGNORECASE)
_JUDGE = re.compile(r"([A-Z][A-Za-z. ]{2,60}?),?\s*(?:J\.|JJ\.)")
_BENCH = re.compile(r"\b(DIVISION\s+BENCH|SINGLE\s+BENCH|BENCH)\b", re.IGNORECASE)
_HEADING_WORDS = re.compile(r"\b(facts|issues)\b", re.IGNORECASE)
_SECTION_CUE = re.compile(r"\b(sections?|rules?|s\.)\s*\d", re.IGNORECASE)
_PARAGRAPH = re.compile(r"^(\d{1,3})[.)](?=\s|$)")
_SCHEDULE_LINE = re.compile(r"^(SCHEDULE|ANNEXURE|TABLE)\b", re.IGNORECASE)


@dataclass
class _Bag:
    """Field values, their confidences and the issues found while extracting."""

    values: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def put(self, name: str, value: Any, conf: float) -> None:  # noqa: ANN401
        if value in (None, "", []):
            return
        self.values[name] = value
        self.confidence[name] = conf

    def halve(self, name: str, issue: str) -> None:
        if name in self.confidence:
            self.confidence[name] = self.confidence[name] / 2
        self.issues.append(issue)


@dataclass(frozen=True)
class Context:
    """What the extractors read: the normalised texts, their kinds and the file name."""

    texts: tuple[str, ...]  # non-boilerplate block texts, normalised, in order
    kinds: tuple[str, ...]  # block kind of each text (heading, para, table, ...)
    title: str  # documents.title (the request title or the file name)
    file_name: str | None
    today: date

    def head(self, count: int) -> str:
        return "\n".join(self.texts[:count])

    def body(self) -> str:
        return "\n".join(self.texts[:BODY_BLOCKS])

    def tail(self) -> list[str]:
        return list(self.texts[-TAIL_BLOCKS:]) if self.texts else []


def context_from(
    blocks: Sequence[SegBlock], title: str, file_name: str | None, today: date
) -> Context:
    """Build the context from the version's blocks (boilerplate and empty blocks removed)."""
    pairs = [
        (normalise_text(block.text), block.kind) for block in blocks if not block.is_boilerplate
    ]
    pairs = [(text, kind) for text, kind in pairs if text]
    return Context(
        texts=tuple(text for text, _ in pairs),
        kinds=tuple(kind for _, kind in pairs),
        title=title,
        file_name=file_name,
        today=today,
    )


def parse_text_date(day: str, month: str, year: str) -> date | None:
    """A date from day, month name and year. None when the month or the day is invalid."""
    number = _MONTHS.get(month.lower().rstrip("."))
    if number is None:
        return None
    try:
        return date(int(year), number, int(day))
    except ValueError:
        return None


def _numeric(day: str, month: str, year: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _first_date(
    text: str, dated_patterns: Sequence[tuple[re.Pattern[str], Callable[..., date | None]]]
) -> date | None:
    for pattern, builder in dated_patterns:
        for match in pattern.finditer(text):
            value = builder(*match.groups())
            if value is not None:
                return value
    return None


_DATED_ANY = (
    (_DATED, lambda d, m, y: parse_text_date(d, m, y)),
    (_DATED_NUMERIC, _numeric),
)
_ANY_DATE = (
    (_ANY_TEXT_DATE, lambda d, m, y: parse_text_date(d, m, y)),
    (_ANY_NUMERIC_DATE, _numeric),
)


def _date_with_confidence(text: str) -> tuple[date, float] | None:
    dated = _first_date(text, _DATED_ANY)
    if dated is not None:
        return dated, EXACT
    any_date = _first_date(text, _ANY_DATE)
    if any_date is not None:
        return any_date, FALLBACK
    return None


@lru_cache(maxsize=1)
def _aliases() -> Aliases:
    return load_aliases(config_dir() / "citation_aliases.yaml")


def _series_code(raw: str) -> str | None:
    cleaned = re.sub(r"\s+(dated|dt\.?)$", "", raw.strip(" .,"), flags=re.IGNORECASE)
    for candidate in (cleaned, cleaned.replace(" (", "(")):
        code = normalise_series(candidate, _aliases())
        if code is not None:
            return code
    return None


def _sections_referred(ctx: Context) -> tuple[list[str], float]:
    found: list[str] = []
    for text in ctx.texts:
        for sentence in re.split(r"(?<=[.;])\s+", text):
            if not _SECTION_CUE.search(sentence):
                continue
            for citation in parse_citation(sentence, aliases=_aliases()):
                if citation.canonical_id and citation.confidence >= CITATION:
                    if citation.canonical_id not in found:
                        found.append(citation.canonical_id)
                    if len(found) >= MAX_SECTIONS:
                        return found, CITATION
    return found, CITATION


def _heading_title(ctx: Context, count: int) -> str | None:
    """The first heading block (or upper-case line) among the first ``count`` blocks."""
    for text, kind in zip(ctx.texts[:count], ctx.kinds[:count], strict=False):
        if len(text) < 10 or _PARAGRAPH.match(text):
            continue
        if _SCHEDULE_LINE.match(text):
            continue
        if kind == "heading" or (len(text) <= 120 and text == text.upper()):
            return text[:300]
    return None


def _cross_check_date(bag: _Bag, name: str, value: date, ctx: Context, floor: date) -> None:
    if not floor <= value <= ctx.today:
        bag.halve(name, f"crosscheck:{name} out of range: {value.isoformat()}")


def _cross_check_title_number(
    bag: _Bag, ctx: Context, pattern: re.Pattern[str], parts: tuple[str, ...]
) -> None:
    """Halve the number confidence when the title has a number that differs from the header."""
    match = pattern.search(ctx.title)
    if match is None:
        return
    if tuple(match.groups()) != parts:
        bag.halve("number", "crosscheck:number disagrees with title")
        if "year" in bag.confidence:
            bag.halve("year", "crosscheck:year disagrees with title")


# ---------------------------------------------------------------- notifications


def _notification(ctx: Context) -> _Bag:
    bag = _Bag()
    head = ctx.head(HEADER_BLOCKS)
    number: str | None = None
    year: int | None = None
    series: str | None = None
    series_raw: str | None = None

    header = _NTF_HEADER.search(head)
    if header is not None:
        number, year_text, series_raw = header.group(1), header.group(2), header.group(3)
        year = int(year_text)
        series = _series_code(series_raw)
        if series is None:
            # The header line may run on into the next sentence: keep the known series name.
            known = _SERIES_WORDS.search(series_raw)
            if known is not None:
                series_raw = known.group(1)
                series = _series_code(series_raw)
        bag.put("number", number, EXACT)
        bag.put("year", year, EXACT)
        if series is None:
            bag.issues.append(f"unrecognised_series:{series_raw.strip()}")
        else:
            bag.put("series", series, EXACT)
    else:
        fallback = _NTF_FALLBACK.search(head)
        if fallback is not None:
            number, year = fallback.group(1), int(fallback.group(2))
            bag.put("number", number, FALLBACK)
            bag.put("year", year, FALLBACK)
        series_word = _SERIES_WORDS.search(ctx.body())
        if series_word is not None:
            series = _series_code(series_word.group(1))
            if series is not None:
                bag.put("series", series, FALLBACK)
                series_raw = series_word.group(1)
    if number is None and ctx.file_name:
        from_name = re.search(r"(\d{1,4})[_\-](\d{4})", ctx.file_name)
        if from_name is not None:
            number, year = from_name.group(1), int(from_name.group(2))
            bag.put("number", number, FILE_NAME)
            bag.put("year", year, FILE_NAME)

    _notification_dates(bag, ctx, head)
    if number is not None and year is not None:
        _cross_check_title_number(bag, ctx, _NTF_TITLE, (number, str(year)))
    _common_authority(bag, ctx)
    _canonical_notification(bag, series, number, year)

    title = _heading_title(ctx, HEADER_BLOCKS)
    if title is not None:
        bag.put("title", title, FALLBACK)
    elif series_raw and number and year:
        bag.put("title", f"Notification No. {number}/{year}-{series_raw.strip()}", FALLBACK)
    elif ctx.file_name:
        bag.put("title", ctx.file_name, FILE_NAME)
    return bag


def _notification_dates(bag: _Bag, ctx: Context, head: str) -> None:
    found = _date_with_confidence(head)
    if found is None:
        found = _date_with_confidence(ctx.body())
        if found is not None:
            found = (found[0], FALLBACK)
    if found is not None:
        bag.put("doc_date", found[0], found[1])
        _cross_check_date(bag, "doc_date", found[0], ctx, GST_START)

    effect = _EFFECT.search(ctx.body())
    if effect is not None:
        effective = parse_text_date(*effect.groups())
        if effective is not None:
            bag.put("effective_date", effective, EXACT)
            bag.put("in_force_date", effective, EXACT)

    gazette = _GAZETTE.search(head)
    if gazette is not None:
        bag.put("gazette_ref", f"G.S.R. {gazette.group(1)}(E)", EXACT)


def _common_authority(bag: _Bag, ctx: Context) -> None:
    if _MOF.search(ctx.head(HEADER_BLOCKS)) is not None:
        bag.put("issuing_authority", "Ministry of Finance (Department of Revenue)", EXACT)
    else:
        bag.put("issuing_authority", "CBIC", FALLBACK)


def _canonical_notification(
    bag: _Bag, series: str | None, number: str | None, year: int | None
) -> None:
    if series is None or number is None or year is None:
        return
    try:
        canonical = notification_id(series, number, year)
    except ValueError:
        bag.issues.append("invalid_canonical: notification")
        return
    conf = min(
        bag.confidence.get("series", 0.0),
        bag.confidence.get("number", 0.0),
        bag.confidence.get("year", 0.0),
    )
    bag.put("canonical_id", canonical, conf)


# ---------------------------------------------------------------- circulars, instructions, orders


def _circular(ctx: Context, doc_type: str) -> _Bag:
    bag = _Bag()
    head = ctx.head(HEADER_BLOCKS)
    bag.put("circular_kind", doc_type, EXACT)
    number: str | None = None
    parts: tuple[str, str, str] | None = None
    if doc_type == "circular":
        match = _CIRCULAR.search(head)
        if match is not None:
            parts = (match.group(1), match.group(2), match.group(3))
            number = f"{parts[0]}/{parts[1]}/{parts[2]}"
            bag.put("number", number, EXACT)
        else:
            _circular_fallback(bag, ctx, head)
    else:
        match = _NUMBERED_NO.search(head)
        if match is not None:
            bag.put("number", match.group(2), EXACT)
            bag.put("year", int(match.group(3)), EXACT)
    _circular_common(bag, ctx, head, doc_type)
    return bag


def _circular_fallback(bag: _Bag, ctx: Context, head: str) -> None:
    fallback = re.search(r"Circular\s+No\.?\s*(\d+)\s*/\s*(\d+)", head, re.IGNORECASE)
    if fallback is not None:
        bag.put("number", f"{fallback.group(1)}/{fallback.group(2)}", FALLBACK)
    elif ctx.file_name:
        from_name = re.search(r"(\d+)[_\-](\d+)[_\-](\d{4})", ctx.file_name)
        if from_name is not None:
            bag.put("number", "/".join(from_name.groups()), FILE_NAME)


def _circular_common(bag: _Bag, ctx: Context, head: str, doc_type: str) -> None:
    found = _date_with_confidence(head)
    if found is None:
        found = _date_with_confidence(ctx.body())
        if found is not None:
            found = (found[0], FALLBACK)
    if found is not None:
        bag.put("doc_date", found[0], found[1])
        _cross_check_date(bag, "doc_date", found[0], ctx, GST_START)

    subject: str | None = None
    for text in ctx.texts[: HEADER_BLOCKS * 2]:
        match = _SUBJECT.search(text)
        if match is not None:
            subject = match.group(1).strip()[:300]
            break
    if subject:
        bag.put("subject", subject, EXACT)

    din = _DIN.search(ctx.body())
    if din is not None:
        bag.put("din", din.group(1), EXACT)

    if doc_type == "circular":
        number = bag.values.get("number")
        if isinstance(number, str) and number.count("/") == 2:
            _cross_check_title_number(bag, ctx, _CIRCULAR_TITLE, tuple(number.split("/")))
    _circular_canonical(bag, doc_type)
    _circular_title(bag, ctx, subject, doc_type)


def _circular_canonical(bag: _Bag, doc_type: str) -> None:
    number = bag.values.get("number")
    if number is None or (doc_type != "circular" and "year" not in bag.values):
        return
    try:
        if doc_type == "circular":
            a, b, year = str(number).split("/")
            canonical = circular_id(a, b, year)
        elif doc_type == "instruction":
            canonical = instruction_id(str(number), int(bag.values.get("year", 0)))
        else:
            canonical = order_id(str(number), int(bag.values.get("year", 0)))
    except ValueError:
        bag.issues.append(f"invalid_canonical: {doc_type}")
        return
    conf = bag.confidence.get("number", 0.0)
    if doc_type != "circular":
        conf = min(conf, bag.confidence.get("year", 0.0))
    bag.put("canonical_id", canonical, conf)


def _circular_title(bag: _Bag, ctx: Context, subject: str | None, doc_type: str) -> None:
    if subject:
        bag.put("title", subject, EXACT)
        return
    heading = _heading_title(ctx, HEADER_BLOCKS)
    if heading is not None:
        bag.put("title", heading, FALLBACK)
    elif bag.values.get("number") is not None:
        label = {"circular": "Circular", "instruction": "Instruction", "order": "Order"}[doc_type]
        bag.put("title", f"{label} No. {bag.values['number']}", FALLBACK)
    elif ctx.file_name:
        bag.put("title", ctx.file_name, FILE_NAME)


# ---------------------------------------------------------------- judgements


def _judgement(
    ctx: Context, courts: dict[str, CourtConfig], patterns: Sequence[CaseNumberPattern]
) -> _Bag:
    bag = _Bag()
    head = ctx.head(JUDGEMENT_HEADER_BLOCKS)
    body = ctx.body()
    _judgement_court(bag, head, body, courts)
    _judgement_case_numbers(bag, head, body, patterns)
    _judgement_decision_date(bag, ctx)
    _judgement_parties(bag, head)
    _judgement_judges(bag, head)
    _judgement_bench(bag, ctx)
    _cross_check_court(bag, courts)

    if bag.values.get("decision_date") is not None:
        _cross_check_date(bag, "decision_date", bag.values["decision_date"], ctx, JUDGEMENT_START)

    _judgement_canonical(bag)
    _judgement_title(bag, ctx)
    return bag


def _judgement_court(bag: _Bag, head: str, body: str, courts: dict[str, CourtConfig]) -> None:
    for scope, conf in ((head, EXACT), (body, FALLBACK)):
        best: tuple[int, CourtConfig] | None = None
        for court in courts.values():
            for pattern in court.patterns:
                match = pattern.search(scope)
                if match is not None and (best is None or match.start() < best[0]):
                    best = (match.start(), court)
        if best is not None:
            court = best[1]
            bag.put("court_code", court.code, conf)
            bag.put("court_level", court.level, conf)
            bag.put("court_name", court.name, conf)
            return


def _judgement_case_numbers(
    bag: _Bag, head: str, body: str, patterns: Sequence[CaseNumberPattern]
) -> None:
    for scope, conf in ((head, EXACT), (body, FALLBACK)):
        found: list[str] = []
        for entry in patterns:
            for match in entry.pattern.finditer(scope):
                value = f"{entry.abbr} {int(match.group('number'))}/{match.group('year')}"
                if value not in found:
                    found.append(value)
        if found:
            bag.put("case_numbers", found, conf)
            return


def _judgement_decision_date(bag: _Bag, ctx: Context) -> None:
    tail_text = "\n".join(ctx.tail())
    last: date | None = None
    for match in _DATED_WORD.finditer(tail_text):
        value = parse_text_date(*match.groups())
        if value is not None:
            last = value
    for match in _DATED_NUMERIC.finditer(tail_text):
        value = _numeric(*match.groups())
        if value is not None:
            last = value
    if last is not None:
        bag.put("decision_date", last, EXACT)
        return
    found = _date_with_confidence(ctx.head(JUDGEMENT_HEADER_BLOCKS))
    if found is None:
        found = _date_with_confidence(ctx.body())
        if found is not None:
            found = (found[0], FALLBACK)
    if found is not None:
        bag.put("decision_date", found[0], found[1])


def _judgement_parties(bag: _Bag, head: str) -> None:
    petitioners: list[str] = []
    respondents: list[str] = []
    for match in _PARTY_LINE.finditer(head):
        name = match.group(1).strip(" ,.;:")
        if not name:
            continue
        role = match.group(2).lower()
        target = respondents if role.startswith("respond") else petitioners
        if name not in target:
            target.append(name)
    if petitioners or respondents:
        conf = EXACT if petitioners and respondents else FALLBACK
        bag.put("parties", {"petitioners": petitioners, "respondents": respondents}, conf)


_HONORIFIC = re.compile(
    r"^(?:Hon'?ble\s+)?(?:(?:Mr|Ms|Mrs|Dr|Shri|Smt)\.?\s+)*(?:Justice\s+)?", re.I
)


def _clean_judge(raw: str) -> str | None:
    """A judge's name without honorifics, or None for a fragment such as a lone "J"."""
    name = _HONORIFIC.sub("", raw.strip(" ,.:")).strip(" ,.:")
    return name if len(name) >= 3 else None


def _judgement_judges(bag: _Bag, head: str) -> None:
    judges: list[str] = []
    candidates: list[str] = []
    for line in head.split("\n"):
        coram = _CORAM.search(line)
        if coram is not None:
            candidates.extend(re.split(r",|\band\b", coram.group(1)))
    candidates.extend(match.group(1) for match in _JUDGE.finditer(head))
    for raw in candidates:
        name = _clean_judge(raw)
        if name is not None and name not in judges:
            judges.append(name)
    if judges:
        bag.put("judges", judges, FALLBACK)


def _judgement_bench(bag: _Bag, ctx: Context) -> None:
    for text in ctx.texts[:JUDGEMENT_HEADER_BLOCKS]:
        if _BENCH.search(text) is not None and len(text) <= 120:
            bag.put("bench", text, FALLBACK)
            return


def _cross_check_court(bag: _Bag, courts: dict[str, CourtConfig]) -> None:
    code = bag.values.get("court_code")
    if code is not None and code not in courts:
        bag.halve("court_code", f"crosscheck:court_code {code} not in courts.yaml")


def _judgement_canonical(bag: _Bag) -> None:
    code = bag.values.get("court_code")
    cases = bag.values.get("case_numbers")
    decided = bag.values.get("decision_date")
    if code is None or not cases or decided is None:
        return
    try:
        canonical = judgement_id(str(code), str(cases[0]), decided)
    except ValueError:
        bag.issues.append("invalid_canonical: judgement")
        return
    conf = min(
        bag.confidence.get("court_code", 0.0),
        bag.confidence.get("case_numbers", 0.0),
        bag.confidence.get("decision_date", 0.0),
    )
    bag.put("canonical_id", canonical, conf)


def _judgement_title(bag: _Bag, ctx: Context) -> None:
    parties = bag.values.get("parties")
    if isinstance(parties, dict) and parties.get("petitioners") and parties.get("respondents"):
        bag.put("title", f"{parties['petitioners'][0]} v. {parties['respondents'][0]}", FALLBACK)
        return
    heading = _heading_title(ctx, JUDGEMENT_HEADER_BLOCKS)
    if heading is not None:
        bag.put("title", heading, FALLBACK)
    elif ctx.file_name:
        bag.put("title", ctx.file_name, FILE_NAME)


# ---------------------------------------------------------------- acts, rules, other


def _instrument(ctx: Context, doc_type: str) -> _Bag:
    bag = _Bag()
    title: str | None = None
    pattern = _RULES_TITLE if doc_type == "rules" else _ACT_TITLE
    for text in ctx.texts[:HEADER_BLOCKS]:
        if pattern.match(text):
            title = text
            bag.put("title", title, EXACT)
            break
    if title is None:
        heading = _heading_title(ctx, HEADER_BLOCKS)
        if heading is not None:
            bag.put("title", heading, FALLBACK)
        elif ctx.file_name:
            bag.put("title", ctx.file_name, FILE_NAME)
    return bag


def _other(ctx: Context) -> _Bag:
    bag = _Bag()
    heading = _heading_title(ctx, HEADER_BLOCKS)
    if heading is not None:
        bag.put("title", heading, FALLBACK)
    elif ctx.file_name:
        bag.put("title", ctx.file_name, FILE_NAME)
    return bag


# ---------------------------------------------------------------- entry point


def _with_common(bag: _Bag, ctx: Context, doc_type: str) -> None:
    """Sections referred to, and the doc_type itself."""
    if doc_type != "other":
        sections, conf = _sections_referred(ctx)
        bag.put("sections_referred", sections, conf)
    bag.put("doc_type", doc_type, EXACT)


def extract_metadata(
    doc_type: str,
    blocks: Sequence[SegBlock],
    *,
    title: str,
    file_name: str | None,
    today: date,
) -> MetadataProposal:
    """Run the rule extractor for a doc_type and return a validated proposal.

    The canonical ID is part of the proposal. The caller decides whether to apply it.
    """
    ctx = context_from(blocks, title, file_name, today)
    if doc_type == "notification":
        bag = _notification(ctx)
    elif doc_type in {"circular", "instruction", "order"}:
        bag = _circular(ctx, doc_type)
    elif doc_type == "judgement":
        bag = _judgement(ctx, load_courts(), load_case_number_patterns())
    elif doc_type in {"act", "rules"}:
        bag = _instrument(ctx, doc_type)
    else:
        bag = _other(ctx)
    _with_common(bag, ctx, doc_type)
    return _finish(doc_type, bag)


def _finish(doc_type: str, bag: _Bag) -> MetadataProposal:
    for name in missing_required(doc_type, bag.values):
        bag.issues.append(f"missing:{name}")
    fields = validate_fields(doc_type, bag.values)
    confidence = {name: round(value, 4) for name, value in bag.confidence.items() if name in fields}
    return MetadataProposal(
        fields=fields,
        confidence=confidence,
        issues=sorted(set(bag.issues)),
    )


def file_name_of(url: str | None) -> str | None:
    """The last path segment of a file:// or http(s) URL, without the watch-folder prefix."""
    if not url:
        return None
    name = url.rsplit("/", 1)[-1]
    name = re.sub(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}__", "", name)
    return Path(name).name or None
