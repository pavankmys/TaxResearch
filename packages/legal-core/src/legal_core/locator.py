"""Lark parser for the target of an amendment instruction (TSD 5.7 step 3).

Reads one locator phrase, such as ``clause (a) of sub-rule (4) of rule 36`` or
``section 16(2)(c)(iv) of the said Act``, into steps from the outermost provision inwards.
A phrase the grammar cannot read gives ``None``: the caller keeps it as raw text for review.

The path produced by :meth:`Locator.path` has no chapter token (``r36.4.a``): a citation does
not name the chapter. Match it against stored provision paths with the chapter prefix removed.
"""

import re
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Literal

from lark import Lark, Token, Tree
from lark.exceptions import LarkError

Level = Literal[
    "section",
    "rule",
    "subsection",
    "clause",
    "subclause",
    "proviso",
    "explanation",
    "form",
    "schedule",
]

_GRAMMAR = r"""
start: segment (CONN segment)*

segment: proviso | explanation | form | schedule | unit

unit: LEVEL LABEL PAREN*
    | LEVEL PAREN+
proviso: ORDINAL? "proviso"i
explanation: "explanation"i LABEL?
form: "form"i FORMCODE+
schedule: "schedule"i LABEL

CONN: /(?:of|to)\b/i
LEVEL: /(?:section|subsection|rule|subrule|clause|subclause|item)\b/i
ORDINAL: /(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b/i
LABEL: /\d+[A-Za-z]{0,3}\b|[IVXLC]+\b/
PAREN: /\(\s*[0-9A-Za-z]{1,4}\s*\)/
FORMCODE: /[A-Za-z0-9][A-Za-z0-9\-]*/

%ignore /\s+/
"""

_ORDINALS = {
    word: number
    for number, word in enumerate(
        ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth"]
        + ["tenth"],
        start=1,
    )
}
_ROMAN = frozenset({"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"})
_LEVEL_OF_WORD: dict[str, Level] = {
    "section": "section",
    "rule": "rule",
    "subsection": "subsection",
    "subrule": "subsection",
    "clause": "clause",
    "subclause": "subclause",
    "item": "subclause",
}

_HYPHENATED = re.compile(r"\bsub[\s\-]+(section|rule|clause)\b", re.IGNORECASE)
_ARTICLE = re.compile(r"\b(?:the|this)\b\s*", re.IGNORECASE)
_INSTRUMENT_TAIL = re.compile(
    r"[\s,]*\b(?:of|under|in)\s+(?:the\s+)?(?P<name>said\s+(?:act|rules?)"
    r"|(?:central|integrated)\s+goods\s+and\s+services\s+tax\s+(?:act|rules)\s*,?\s*(?:2017)?"
    r"|(?:cgst|igst)\s+(?:act|rules))\s*[.;,]?\s*$",
    re.IGNORECASE,
)
_INSTRUMENT_CODES = {
    "central goods and services tax act": "CGST_ACT",
    "central goods and services tax rules": "CGST_RULES",
    "integrated goods and services tax act": "IGST_ACT",
    "integrated goods and services tax rules": "IGST_RULES",
    "cgst act": "CGST_ACT",
    "cgst rules": "CGST_RULES",
    "igst act": "IGST_ACT",
    "igst rules": "IGST_RULES",
}


@dataclass(frozen=True)
class Step:
    """One level of the locator: a level and its label (``36``, ``4``, ``a``)."""

    level: Level
    label: str


@dataclass(frozen=True)
class Locator:
    """A parsed target. ``steps`` run from the outermost provision to the innermost.

    ``relative`` is true when the first step is below a section or rule ("in sub-rule (4)"),
    so the caller must put it inside the provision named earlier in the instruction.
    ``instrument`` is a code (``CGST_ACT``), ``said_act`` / ``said_rules`` (resolved by the
    caller from the notification's opening words), or None when the phrase names none.
    """

    steps: tuple[Step, ...]
    instrument: str | None
    raw: str

    @property
    def relative(self) -> bool:
        return bool(self.steps) and self.steps[0].level not in {
            "section",
            "rule",
            "form",
            "schedule",
        }

    @property
    def is_provision(self) -> bool:
        """True when every step is a part of an Act or Rules (not a form or schedule)."""
        return bool(self.steps) and all(s.level not in {"form", "schedule"} for s in self.steps)

    def within(self, parent: "Locator") -> "Locator":
        """This locator placed inside ``parent`` when it is relative; otherwise unchanged."""
        if not self.relative:
            return self
        return replace(
            self, steps=parent.steps + self.steps, instrument=self.instrument or parent.instrument
        )

    def path(self) -> str | None:
        """Chapter-less provision path such as ``r36.4.a`` or ``s16.2.prov1``, or None."""
        if not self.is_provision or self.relative:
            return None
        tokens: list[str] = []
        for step in self.steps:
            if step.level == "section":
                tokens.append(f"s{step.label}")
            elif step.level == "rule":
                tokens.append(f"r{step.label}")
            elif step.level == "proviso":
                tokens.append(f"prov{step.label}")
            elif step.level == "explanation":
                tokens.append(f"expl{step.label}")
            else:
                tokens.append(step.label)
        return ".".join(tokens)


@lru_cache(maxsize=1)
def _parser() -> Lark:
    return Lark(_GRAMMAR, parser="earley", lexer="dynamic", ambiguity="resolve")


def _label(raw: str) -> str:
    """The label inside a token. A number keeps its letter suffix in capitals (``138E``);
    letters in brackets are lower case (``a``, ``iv``)."""
    inner = raw.strip("() ")
    digits = re.match(r"\d+", inner)
    if digits is not None:
        return digits.group(0) + inner[digits.end() :].upper()
    return inner.lower() if raw.startswith("(") else inner.upper()


def _nested_level(label: str, previous: Level) -> Level:
    """Level of a bracketed label that follows another one in compact form (``16(2)(c)(iv)``)."""
    if label[:1].isdigit():
        return "subsection"
    if label in _ROMAN and previous in {"clause", "subclause"}:
        return "subclause"
    return "clause"


def _steps_of(segment: Tree[Token]) -> list[Step]:
    child = segment.children[0]
    if not isinstance(child, Tree):  # the grammar only puts a sub-tree here
        return []
    kind = child.data
    tokens = [c for c in child.children if isinstance(c, Token)]
    if kind == "proviso":
        ordinal = next((t for t in tokens if t.type == "ORDINAL"), None)
        number = _ORDINALS[str(ordinal).lower()] if ordinal is not None else 1
        return [Step("proviso", str(number))]
    if kind == "explanation":
        number_token = next((t for t in tokens if t.type == "LABEL"), None)
        return [Step("explanation", _label(str(number_token)) if number_token else "1")]
    if kind == "form":
        return [Step("form", " ".join(str(t) for t in tokens if t.type == "FORMCODE").upper())]
    if kind == "schedule":
        return [Step("schedule", str(tokens[0]).upper())]
    level_word = str(tokens[0]).lower()
    level = _LEVEL_OF_WORD[level_word]
    steps: list[Step] = []
    rest = tokens[1:]
    if rest:  # "rule 36" or "sub-rule (4)": the first label belongs to the named level itself
        steps.append(Step(level, _label(str(rest[0]))))
    for token in rest[1:]:
        nested = _label(str(token))
        steps.append(Step(_nested_level(nested, steps[-1].level), nested))
    return steps


def _instrument(name: str | None) -> str | None:
    if name is None:
        return None
    key = re.sub(r"[\s,]+", " ", name.lower()).strip()
    key = re.sub(r"\s*2017$", "", key).strip()
    if key.startswith("said"):
        return "said_rules" if "rule" in key else "said_act"
    return _INSTRUMENT_CODES.get(key)


def parse_locator(text: str) -> Locator | None:
    """Read one locator phrase. Returns None for anything the grammar does not cover."""
    if not text or not isinstance(text, str):
        return None
    cleaned = " ".join(text.split())
    instrument: str | None = None
    tail = _INSTRUMENT_TAIL.search(cleaned)
    if tail is not None:
        instrument = _instrument(tail.group("name"))
        cleaned = cleaned[: tail.start()]
    cleaned = _HYPHENATED.sub(lambda m: "sub" + m.group(1).lower(), cleaned)
    cleaned = _ARTICLE.sub("", cleaned).replace(",", " ").strip()
    cleaned = re.sub(r"^(?:in|at)\s+", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        return None
    try:
        tree = _parser().parse(cleaned)
    except LarkError:
        return None
    parts: list[list[Step]] = []
    for node in tree.children:
        if isinstance(node, Tree) and node.data == "segment":
            parts.append(_steps_of(node))
    if not parts:
        return None
    steps = tuple(step for part in reversed(parts) for step in part)  # "(a) of 4 of rule 36"
    return Locator(steps=steps, instrument=instrument, raw=text.strip())


_INSTRUMENT_NAME = re.compile(
    r"\b(?P<name>(?:central|integrated)\s+goods\s+and\s+services\s+tax\s+(?:act|rules)"
    r"|(?:cgst|igst)\s+(?:act|rules))\b",
    re.IGNORECASE,
)


def find_instruments(text: str) -> list[tuple[int, str]]:
    """Instrument codes named in the text, with their positions, in order of appearance.

    ``Central Goods and Services Tax Rules, 2017`` gives ``CGST_RULES``. "The said Act" is not
    found here: it only means something relative to a name found earlier.
    """
    found: list[tuple[int, str]] = []
    for match in _INSTRUMENT_NAME.finditer(text):
        code = _instrument(match.group("name"))
        if code is not None:
            found.append((match.start(), code))
    return found
