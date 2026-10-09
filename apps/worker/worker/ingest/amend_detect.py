"""Amendment detector: instruction units of a notification into structured proposals (TSD 5.7).

Pure functions, no database. The steps:

1. Join the blocks into one text and normalise quotes, so that a quoted rule that runs over
   several paragraphs stays together. Quoted strings are replaced by placeholders.
2. Split the text outside quotes into pieces (at ``;`` and at line breaks) and strip the
   numbering ("2.", "(i)", "(a)").
3. A piece that only introduces a scope ("In rule 59,-") sets the scope for the pieces after it.
4. Any other piece is read by the Lark clause grammar below: substitute, insert, omit.
   A piece with an amendment cue word that the grammar cannot read is kept as a raw unit.
5. Targets are read by ``legal_core.parse_locator`` and placed inside the current scope.
6. Every quoted text must be a verbatim substring of the source, or the unit becomes raw.

Resolving a path to a stored provision, and the dry run, belong to the stage and the applier.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Literal

from lark import Lark, Token, Tree
from lark.exceptions import LarkError
from legal_core import Locator, find_instruments, parse_locator

Op = Literal["substitute", "insert", "omit", "amend"]
Kind = Literal["words", "provision", "raw"]

_GRAMMAR = r"""
start: lead* clause

lead: IN_ LOC ","

?clause: sub_words | sub_read | ins_words | ins_prov | sub_prov | omit_words | omit_prov

sub_words: FOR_ THE_? WORDKIND? QSTR ","? THE_ WORDKIND? QSTR SHALL_BE SUBSTITUTED_
         | FOR_ THE_? WORDKIND? QSTR ","? SUBSTITUTE_ THE_? WORDKIND? QSTR
sub_read: FOR_ THE_? WORDKIND? QSTR ","? READ_ THE_? WORDKIND? QSTR
ins_words: (AFTER_ | BEFORE_) THE_? WORDKIND? QSTR ","? THE_ WORDKIND? QSTR SHALL_BE INSERTED_
         | (AFTER_ | BEFORE_) THE_? WORDKIND? QSTR ","? INSERT_ THE_? WORDKIND? QSTR
ins_prov: AFTER_ LOC "," THE_ FOLLOWING PROVKIND SHALL_BE INSERTED_ ","? QSTR
sub_prov: FOR_ LOC "," THE_ FOLLOWING PROVKIND? SHALL_BE SUBSTITUTED_ ","? QSTR
omit_words: THE_ WORDKIND QSTR SHALL_BE OMITTED_
          | OMIT_ THE_? WORDKIND QSTR
omit_prov: LOC SHALL_BE OMITTED_
         | OMIT_ LOC

IN_: /in\b/i
FOR_: /for\b/i
AFTER_: /after\b/i
BEFORE_: /before\b/i
THE_: /the\b/i
READ_: /read\b/i
SHALL_BE: /shall\s+be\b/i
SUBSTITUTED_: /substituted\b/i
SUBSTITUTE_: /substitute\b/i
INSERTED_: /inserted\b/i
INSERT_: /insert\b/i
OMITTED_: /omitted\b/i
OMIT_: /omit\b/i
FOLLOWING: /following\b/i
WORDKIND: /(?:words?|figures?|letters?|numbers?|numerals?|brackets?|expressions?|symbols?|signs?|commas?)(?:\s+and\s+(?:words?|figures?|letters?|numbers?|brackets?))*\b/i
PROVKIND: /(?:sub[\s\-]?)?(?:rules?|sections?|clauses?|paragraphs?|provisos?|explanations?|items?)\b/i
QSTR: /§\d+§/
LOC: /[^,§]+/

%ignore /\s+/
"""  # noqa: E501 (the long terminals are regular expressions)

_CUE = re.compile(
    r"\b(?:substituted|inserted|omitted|rescinded|renumbered|in\s+supersession)\b", re.IGNORECASE
)
_MARKER = re.compile(r"^\s*(?:\d{1,3}[A-Z]?\.\s*|\(\s*(?:[a-z]{1,4}|\d{1,3}[A-Z]?)\s*\)\s*)+")
_QUOTE_CHARS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "„": '"', "«": '"'})
_DASHES = r"\-–—―:"  # for use inside a regex character class
_NAMELY = re.compile(r"[\s,]*\bnamely\b[\s,:" + _DASHES + r"]*(?=§)", re.IGNORECASE)
_DASH_BEFORE_QUOTE = re.compile(r"[\s," + _DASHES + r"]+(?=§\d+§\s*$)")
_TRAILING = re.compile(r"[\s;,.]+(?:and|or)?[\s;,.]*$", re.IGNORECASE)
_EFFECTIVE_TAIL = re.compile(
    r"[\s,]*\b(?:with\s+effect\s+from|w\.e\.f\.?)\s+(?P<when>[^§]*?)\s*$", re.IGNORECASE
)
_INSTRUMENT_COMMA = re.compile(r"\b(Act|Rules)\s*,\s*(\d{4})\b")  # "Tax Act, 2017" has a comma
_HEREINAFTER = re.compile(r"\(\s*hereinafter[^)]*\)", re.IGNORECASE)
_ORD_SUFFIX = re.compile(r"(\d+)(?:st|nd|rd|th)\b")
_MONTHS = {
    name: number
    for number, name in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august"]
        + ["september", "october", "november", "december"],
        start=1,
    )
}
_DATE_WORDS = re.compile(
    r"(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?(?P<m>[A-Za-z]+)[,\s]+(?P<y>\d{4})",
    re.IGNORECASE,
)
_DATE_DOTS = re.compile(r"(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{4})")
_NEW_LABEL = re.compile(
    r"^\s*(?:\(\s*(?P<paren>[0-9A-Za-z]{1,4})\s*\)|(?P<num>\d+[A-Z]{0,3})\s*\.)"
)

EffectiveKind = Literal["on_date", "on_gazette", "on_notification"]


@dataclass(frozen=True)
class Effective:
    """When an amendment or a notification takes effect, and the phrase that says so."""

    kind: EffectiveKind
    day: date | None
    phrase: str
    retrospective: bool = False


@dataclass(frozen=True)
class Proposal:
    """One detected instruction. ``status`` is ``raw`` when the grammar could not read it."""

    status: Literal["parsed", "raw"]
    op: Op
    kind: Kind
    instrument: str | None
    target_path: str | None  # chapter-less path of the provision changed (the new one for insert)
    anchor_path: str | None  # for an inserted provision: the provision it goes after or before
    position: Literal["after", "before"] | None
    anchor_text: str | None  # for inserted words: the words they go after or before
    old_text: str | None
    new_text: str | None
    new_label: str | None
    effective: Effective | None
    unit_text: str
    block_ids: tuple[str, ...]
    confidence: float
    problems: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BlockText:
    """A block as the detector needs it."""

    id: str
    text: str


@dataclass(frozen=True)
class Detected:
    """Everything found in one notification."""

    proposals: tuple[Proposal, ...]
    effective: Effective | None  # the notification's own coming into force


@lru_cache(maxsize=1)
def _parser() -> Lark:
    return Lark(_GRAMMAR, parser="earley", lexer="dynamic_complete", ambiguity="resolve")


def parse_date(text: str) -> date | None:
    """A date such as "1st day of April, 2026", "1st April 2026" or "01.04.2026"."""
    found = _DATE_WORDS.search(_ORD_SUFFIX.sub(r"\1", text))
    try:
        if found:
            month = _MONTHS.get(found.group("m").lower())
            if month:
                return date(int(found.group("y")), month, int(found.group("d")))
        dotted = _DATE_DOTS.search(text)
        if dotted:
            return date(int(dotted.group("y")), int(dotted.group("m")), int(dotted.group("d")))
    except ValueError:
        return None
    return None


_ON_NOTIFICATION = re.compile(
    r"\bon\s+such\s+date\s+as\s+the\s+(?:central\s+)?government\s+may\b", re.IGNORECASE
)
_ON_GAZETTE = re.compile(
    r"\b(?:come\s+into\s+force|take\s+effect|be\s+effective)\s+on\s+the\s+date\s+of\s+"
    r"(?:its\s+|their\s+|the\s+)?publication\s+in\s+the\s+official\s+gazette\b",
    re.IGNORECASE,
)
_COMES_INTO_FORCE = re.compile(
    r"\b(?P<deemed>deemed\s+to\s+have\s+)?come[s]?\s+into\s+force\s+(?:on|with\s+effect\s+from)\s+"
    r"(?P<when>[^;]{0,80})",
    re.IGNORECASE,
)


def extract_effective(text: str) -> Effective | None:
    """The notification's own coming into force, from its text (TSD 5.7 effective-date table)."""
    flat = " ".join(text.split())
    if _ON_NOTIFICATION.search(flat):
        found = _ON_NOTIFICATION.search(flat)
        assert found is not None
        return Effective("on_notification", None, found.group(0))
    if _ON_GAZETTE.search(flat):
        found = _ON_GAZETTE.search(flat)
        assert found is not None
        return Effective("on_gazette", None, found.group(0))
    match = _COMES_INTO_FORCE.search(flat)
    if match:
        day = parse_date(match.group("when"))
        if day is not None:
            return Effective("on_date", day, match.group(0).strip(), bool(match.group("deemed")))
    return None


def _normalise(text: str) -> str:
    return text.translate(_QUOTE_CHARS)


def _split_outside_quotes(text: str) -> list[tuple[int, str]]:
    """Pieces split at ``;`` and line breaks that are not inside double quotes, with offsets."""
    pieces: list[tuple[int, str]] = []
    start = 0
    inside = False
    for index, char in enumerate(text):
        if char == '"':
            inside = not inside
        elif not inside and char in ";\n":
            if char == "\n" and text[index + 1 :].lstrip().startswith('"'):
                continue  # a line that opens a quote continues the instruction before it
            pieces.append((start, text[start:index]))
            start = index + 1
    pieces.append((start, text[start:]))
    return [(offset, piece) for offset, piece in pieces if piece.strip()]


def _placeholders(piece: str) -> tuple[str, list[str]]:
    """Replace each double-quoted string by §n§ and return the strings."""
    strings: list[str] = []

    def take(match: re.Match[str]) -> str:
        strings.append(match.group(1))
        return f"§{len(strings) - 1}§"

    return re.sub(r'"([^"]*)"', take, piece), strings


def _scope_of(piece: str, state: "_Scope") -> bool:
    """True when the piece only introduces a scope ("In rule 59,-"), which is then recorded."""
    flat = _HEREINAFTER.sub("", piece).strip()
    match = re.match(r"^in\s+(?P<loc>[^§]+?)[\s,:" + _DASHES + r"]*$", flat, re.IGNORECASE)
    if match is None or re.search(r"\b(?:for|after|before|omit|insert|substitut)", flat, re.I):
        return False
    # "In the said rules, in rule 10,-": a name of the instrument, then provisions
    changes: list[tuple[str | None, Locator | None]] = []
    for part in re.split(r",\s*(?:in\s+)?", match.group("loc")):
        part = part.strip()
        if not part:
            continue
        locator = parse_locator(part)
        if locator is not None:
            changes.append((None, locator))
            continue
        named = find_instruments(part)
        name = named[0][1] if named else _said(part)
        if name is None:
            return False
        changes.append((name, None))
    if not changes:
        return False
    for name, locator in changes:
        if locator is not None:
            state.place(locator)
        else:
            state.locator = None
            state.instrument = name
    return True


def _said(text: str) -> str | None:
    match = re.search(r"\bsaid\s+(act|rules?)\b", text, re.IGNORECASE)
    if match is None:
        return None
    return "said_rules" if match.group(1).lower().startswith("rule") else "said_act"


class _Scope:
    """The instrument and provision that the pieces after a lead-in apply to."""

    def __init__(self, default_instrument: str | None) -> None:
        self.instrument: str | None = default_instrument
        self.locator: Locator | None = None

    def place(self, locator: Locator) -> None:
        self.locator = locator.within(self.locator) if self.locator else locator
        self.instrument = locator.instrument or self.instrument

    def resolve(self, locator: Locator) -> Locator:
        """The locator placed inside the current scope when it is relative."""
        if locator.relative and self.locator is not None:
            return locator.within(self.locator)
        return locator


def _split_effective_tail(piece: str) -> tuple[str, Effective | None]:
    match = _EFFECTIVE_TAIL.search(piece)
    if match is None:
        return piece, None
    day = parse_date(match.group("when"))
    if day is None:
        return piece, None
    return piece[: match.start()], Effective("on_date", day, match.group(0).strip(" ,"))


def _strip_markers(piece: str) -> str:
    return _MARKER.sub("", piece, count=1).strip()


def _tidy(piece: str) -> str:
    piece = _NAMELY.sub(" ", piece)
    piece = _DASH_BEFORE_QUOTE.sub(" ", piece)
    return _TRAILING.sub("", piece).strip()


def _tokens(tree: Tree[Token], kinds: set[str]) -> list[Token]:
    return [t for t in tree.scan_values(lambda v: isinstance(v, Token) and v.type in kinds)]


def _new_label(new_text: str) -> str | None:
    match = _NEW_LABEL.match(new_text)
    if match is None:
        return None
    label = match.group("paren") or match.group("num")
    return label.upper() if label[:1].isdigit() else label.lower()


def _path_with_label(anchor: Locator | None, kind_word: str, label: str | None) -> str | None:
    """Chapter-less path of an inserted provision, from where it goes and its first label."""
    if anchor is None or label is None or not anchor.is_provision or anchor.relative:
        return None
    steps = list(anchor.steps)
    top = kind_word.lower().replace("-", "").replace(" ", "")
    if top in {"rule", "rules"}:
        return f"r{label}"
    if top in {"section", "sections"}:
        return f"s{label}"
    parent = (
        Locator(tuple(steps[:-1]), anchor.instrument, anchor.raw).path() if steps[:-1] else None
    )
    return f"{parent}.{label}" if parent else None


def _problem_proposal(
    base: dict[str, object], problems: list[str], status: Literal["parsed", "raw"] = "parsed"
) -> Proposal:
    confidence = 0.0 if status == "raw" else (0.9 if not problems else 0.5)
    return Proposal(status=status, problems=tuple(problems), confidence=confidence, **base)  # type: ignore[arg-type]


def _clause_proposal(
    tree: Tree[Token],
    strings: list[str],
    scope: _Scope,
    unit_text: str,
    block_ids: tuple[str, ...],
    unit_effective: Effective | None,
) -> Proposal | None:
    problems: list[str] = []
    leads = [t for t in tree.children if isinstance(t, Tree) and t.data == "lead"]
    parent = scope.locator
    instrument = scope.instrument
    for lead in leads:
        lead_text = str(_tokens(lead, {"LOC"})[0])
        loc = parse_locator(lead_text)
        if loc is None:
            named = find_instruments(lead_text)
            if not named and _said(lead_text) is None:
                return None
            instrument = named[0][1] if named else _said(lead_text)  # "In the said rules,"
            parent = None
            continue
        parent = loc.within(parent) if parent and loc.relative else loc
        instrument = loc.instrument or instrument
    clause = tree.children[-1]
    if not isinstance(clause, Tree):
        return None
    kind_name = clause.data
    qs = [strings[int(str(t)[1:-1])] for t in _tokens(clause, {"QSTR"})]
    locs = _tokens(clause, {"LOC"})
    clause_loc: Locator | None = None
    if locs:
        clause_loc = parse_locator(str(locs[0]).strip())
        if clause_loc is None:
            return None
        clause_loc = clause_loc.within(parent) if parent and clause_loc.relative else clause_loc
        instrument = clause_loc.instrument or instrument
    op: Op
    kind: Kind
    target: Locator | None = parent
    old = new = anchor_text = new_label = anchor_path = None
    position: Literal["after", "before"] | None = None
    target_path: str | None = None
    if kind_name in {"sub_words", "sub_read"}:
        op, kind, old, new = "substitute", "words", qs[0], qs[1]
    elif kind_name == "ins_words":
        op, kind, anchor_text, new = "insert", "words", qs[0], qs[1]
        position = "before" if _tokens(clause, {"BEFORE_"}) else "after"
    elif kind_name == "omit_words":
        op, kind, old = "omit", "words", qs[0]
    elif kind_name == "omit_prov":
        op, kind, target = "omit", "provision", clause_loc
    elif kind_name == "sub_prov":
        op, kind, target, new = "substitute", "provision", clause_loc, qs[0]
    elif kind_name == "ins_prov":
        op, kind, new = "insert", "provision", qs[0]
        anchor = clause_loc
        position = "after"
        new_label = _new_label(new)
        provkind = str(_tokens(clause, {"PROVKIND"})[0])
        target_path = _path_with_label(anchor, provkind, new_label)
        anchor_path = anchor.path() if anchor else None
        target = None
        if new_label is None:
            problems.append("new_label_unknown")
        if target_path is None:
            problems.append("target_unresolved")
    else:
        return None
    if kind_name != "ins_prov":
        target_path = target.path() if target else None
        if target is None or target_path is None:
            problems.append("target_unresolved")
    if instrument in {"said_act", "said_rules"} or instrument is None:
        problems.append("instrument_unresolved")
    base: dict[str, object] = {
        "op": op,
        "kind": kind,
        "instrument": instrument,
        "target_path": target_path,
        "anchor_path": anchor_path,
        "position": position,
        "anchor_text": anchor_text,
        "old_text": old,
        "new_text": new,
        "new_label": new_label,
        "effective": unit_effective,
        "unit_text": unit_text,
        "block_ids": block_ids,
    }
    return _problem_proposal(base, problems)


def _raw(unit_text: str, block_ids: tuple[str, ...], scope: _Scope, why: str) -> Proposal:
    base: dict[str, object] = {
        "op": "amend",
        "kind": "raw",
        "instrument": scope.instrument,
        "target_path": scope.locator.path() if scope.locator else None,
        "anchor_path": None,
        "position": None,
        "anchor_text": None,
        "old_text": None,
        "new_text": None,
        "new_label": None,
        "effective": None,
        "unit_text": unit_text,
        "block_ids": block_ids,
    }
    return _problem_proposal(base, [why], status="raw")


def _verbatim(proposal: Proposal, source: str) -> bool:
    flat = " ".join(source.split())
    texts = (proposal.old_text, proposal.new_text, proposal.anchor_text)
    return all(t is None or " ".join(t.split()) in flat for t in texts)


def _block_ids_for(
    blocks: Sequence[BlockText], starts: list[int], lo: int, hi: int
) -> tuple[str, ...]:
    ids = [
        block.id
        for block, start in zip(blocks, starts, strict=True)
        if start < hi and start + len(block.text) + 1 > lo
    ]
    return tuple(ids)


def detect(blocks: Sequence[BlockText], *, default_instrument: str | None = None) -> Detected:
    """Proposals found in a notification's blocks, in document order."""
    texts = [_normalise(b.text) for b in blocks]
    starts: list[int] = []
    position = 0
    for text in texts:
        starts.append(position)
        position += len(text) + 1
    joined = "\n".join(texts)
    named = find_instruments(joined)
    rules_named = next((c for _, c in named if c.endswith("RULES")), None)
    act_named = next((c for _, c in named if c.endswith("ACT")), None)
    scope = _Scope(default_instrument)
    proposals: list[Proposal] = []
    for offset, raw_piece in _split_outside_quotes(joined):
        piece_ids = _block_ids_for(blocks, starts, offset, offset + len(raw_piece))
        body = _strip_markers(raw_piece)
        if re.match(r"^\s*\d{1,3}\.", raw_piece):  # a new numbered paragraph resets the scope
            scope.locator = None
        if not body:
            continue
        shaped, strings = _placeholders(body)
        shaped = _INSTRUMENT_COMMA.sub(r"\1 \2", _HEREINAFTER.sub("", shaped))
        if _scope_of(shaped, scope):
            continue
        shaped, unit_effective = _split_effective_tail(shaped)
        shaped = _tidy(shaped)
        tree = None
        if shaped:
            try:
                tree = _parser().parse(shaped)
            except LarkError:
                tree = None
        proposal = None
        if tree is not None:
            proposal = _clause_proposal(tree, strings, scope, body, piece_ids, unit_effective)
        if proposal is None:
            if _CUE.search(body):
                proposals.append(_raw(body, piece_ids, scope, "grammar_no_match"))
            continue
        if not _verbatim(proposal, joined):
            proposals.append(_raw(body, piece_ids, scope, "verbatim_failed"))
            continue
        proposals.append(proposal)

    def resolve(p: Proposal) -> Proposal:
        code = p.instrument
        if code == "said_rules":
            code = rules_named
        elif code == "said_act":
            code = act_named
        if code == p.instrument:
            return p
        problems = tuple(x for x in p.problems if x != "instrument_unresolved")
        if code is None:
            problems = (*problems, "instrument_unresolved")
        confidence = p.confidence if p.status == "raw" else (0.5 if problems else 0.9)
        return Proposal(
            **{**p.__dict__, "instrument": code, "problems": problems, "confidence": confidence}
        )

    return Detected(
        proposals=tuple(resolve(p) for p in proposals), effective=extract_effective(joined)
    )
