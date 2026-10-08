"""Reads the leading numbering of a block with the Lark grammar in grammar/numbering.lark."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lark import Lark, Token
from lark.exceptions import UnexpectedInput
from legal_core.text import normalise_text

GRAMMAR_PATH = Path(__file__).with_name("grammar") / "numbering.lark"


@dataclass(frozen=True)
class Marker:
    """One leading marker. kind is the grammar terminal: CHAPTER, NUMBER, PAREN, PROVISO,
    EXPLANATION, FORM or ANNEX."""

    kind: str
    text: str


@dataclass(frozen=True)
class Numbering:
    """The leading markers of a block, and the text after them."""

    markers: tuple[Marker, ...]
    tail: str


@lru_cache(maxsize=1)
def _parser() -> Lark:
    return Lark(GRAMMAR_PATH.read_text(encoding="utf-8"), parser="lalr", lexer="contextual")


def read_numbering(text: str) -> Numbering:
    """Split a block into its leading numbering markers and the rest of the text.

    The text is normalised first. A text the grammar rejects is returned whole as the tail.
    """
    normal = normalise_text(text)
    try:
        tree = _parser().parse(normal)
    except UnexpectedInput:
        return Numbering(markers=(), tail=normal)
    markers: list[Marker] = []
    tail = ""
    for child in tree.children:
        if not isinstance(child, Token):
            continue
        if child.type == "TAIL":
            tail = str(child)
        else:
            markers.append(Marker(kind=child.type, text=str(child)))
    return Numbering(markers=tuple(markers), tail=tail)
