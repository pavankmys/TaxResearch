"""Pure builder for provision trees from segmented blocks (M4a).

No database access. Every token of a structure path is classified by its own shape, so a clause
directly under a section (``ch5.s16.a``) and a path without chapters (``s16.2``) both work:

    ch5 chapter | s16 section (Acts) | r36 rule (Rules) | 2, 2A subsection
    a clause | iv subclause (a roman token under a clause) | prov1 proviso | expl1 explanation

A block whose path has any other token (``pre``, ``toc``, ``fn3``, ``form1``, ``sched1``,
``p3``) is not part of a provision and is skipped.
"""

import hashlib
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

_CHAPTER = re.compile(r"^ch(\d+)$")
_SECTION = re.compile(r"^s(\d+[A-Z]{0,3})$")
_RULE = re.compile(r"^r(\d+[A-Z]{0,3})$")
_SUBSECTION = re.compile(r"^\d{1,3}[A-Z]{0,2}$")
_LETTERS = re.compile(r"^[a-z]{1,3}$")
_ROMAN = frozenset({"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"})
_PROVISO = re.compile(r"^prov(\d+)$")
_EXPLANATION = re.compile(r"^expl(\d+)$")
_CHAPTER_WORD = re.compile(r"^CHAPTER\s+[IVXLC]+\b\W*", re.IGNORECASE)
# "16. Heading.- (1) ..." also with an amendment bracket ("1[20. Heading") or a spaced dot.
_SECTION_HEADING = re.compile(
    r"^\s*(?:\d{1,3}\s*)?\[?\s*\d{1,3}[A-Z]{0,3}\s?\.\s*(?P<h>[^\n]+?)"
    r"(?:\s*\.\s*[-–—]|\s[-–—]\s)"
)


@dataclass(frozen=True)
class BlockIn:
    """A block of the document version, as the builder needs it."""

    id: str
    ordinal: int
    kind: str
    text: str
    structure_path: str | None
    is_boilerplate: bool


@dataclass(frozen=True)
class ProvisionDraft:
    """One provision to store: its place in the tree, label, heading and baseline text."""

    path: str
    parent_path: str | None
    level: str
    number_label: str | None
    ordinal: int  # 1-based position among the siblings, by first appearance
    heading: str | None
    text: str
    block_ids: tuple[str, ...]


class BuildResult(NamedTuple):
    """Drafts (parents before children, then document order) and what was left out."""

    drafts: list[ProvisionDraft]
    skipped_blocks: int
    skipped_paths: dict[str, int]  # first token that is not part of a provision -> blocks


def text_sha256(text: str) -> str:
    """Hex SHA-256 of the UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _classify(
    token: str, parent_level: str | None, *, rules: bool, first: bool
) -> tuple[str, str] | None:
    """(level, number_label) for one path token, or None when it is not a provision token."""
    if match := _CHAPTER.match(token):
        return ("chapter", match.group(1)) if first else None
    match = (_RULE if rules else _SECTION).match(token)
    if match:
        if parent_level not in {None, "chapter"}:
            return None
        return ("rule" if rules else "section", match.group(1))
    if parent_level is None or parent_level == "chapter":
        return None  # below the top, every other token needs a section or rule above it
    if match := _PROVISO.match(token):
        return "proviso", match.group(1)
    if match := _EXPLANATION.match(token):
        return "explanation", match.group(1)
    if _SUBSECTION.match(token):
        return ("subsection", token) if parent_level in {"section", "rule"} else None
    if _LETTERS.match(token):
        if token in _ROMAN and parent_level in {"clause", "subclause"}:
            return "subclause", token
        return "clause", token
    return None


def _levels(path: str, *, rules: bool) -> tuple[list[tuple[str, str]], str | None]:
    """Level and label of every token, and the first token that is not a provision token."""
    out: list[tuple[str, str]] = []
    parent: str | None = None
    for index, token in enumerate(path.split(".")):
        found = _classify(token, parent, rules=rules, first=index == 0)
        if found is None:
            return out, token
        out.append(found)
        parent = found[0]
    return out, None


def _chapter_heading(texts: list[str]) -> str | None:
    kept = [t for t in (_CHAPTER_WORD.sub("", text).strip() for text in texts) if t]
    return " ".join(kept) if kept else None


def build_provisions(blocks: Sequence[BlockIn], *, rules: bool) -> BuildResult:
    """Provision drafts for the blocks of an Act (``rules=False``) or Rules (``rules=True``)."""
    skipped_blocks = 0
    skipped_paths: dict[str, int] = defaultdict(int)
    order: list[str] = []  # every path, ancestors first, in order of first appearance
    meta: dict[str, tuple[str | None, str, str]] = {}  # path -> (parent path, level, label)
    texts: dict[str, list[tuple[str, str]]] = defaultdict(list)  # path -> [(block id, text)]
    tables: dict[str, list[str]] = defaultdict(list)  # path -> texts of its table blocks
    heading_blocks: dict[str, list[str]] = defaultdict(list)

    for block in sorted(blocks, key=lambda b: b.ordinal):
        if block.is_boilerplate or block.structure_path is None:
            skipped_blocks += 1
            continue
        path = block.structure_path
        levels, bad = _levels(path, rules=rules)
        if bad is not None:
            skipped_blocks += 1
            skipped_paths[bad] += 1
            continue
        tokens = path.split(".")
        for depth, (level, label) in enumerate(levels):
            prefix = ".".join(tokens[: depth + 1])
            if prefix not in meta:
                parent = ".".join(tokens[:depth]) if depth else None
                meta[prefix] = (parent, level, label)
                order.append(prefix)
        text = block.text.strip()
        if block.kind == "table_row" and tables[path]:
            continue  # the parser emits a table and then its rows: the table has the text
        if block.kind == "table":
            tables[path].append(text)
        if block.kind == "heading":
            heading_blocks[path].append(text)
        texts[path].append((block.id, text))

    siblings: dict[str | None, int] = defaultdict(int)
    drafts: list[ProvisionDraft] = []
    for path in order:
        parent, level, label = meta[path]
        siblings[parent] += 1
        own = texts.get(path, [])
        heading: str | None = None
        if level == "chapter":
            heading = _chapter_heading(heading_blocks.get(path, []))
        elif level in {"section", "rule"} and own:
            found = _SECTION_HEADING.match(own[0][1])
            heading = found.group("h") if found else None
        drafts.append(
            ProvisionDraft(
                path=path,
                parent_path=parent,
                level=level,
                number_label=label,
                ordinal=siblings[parent],
                heading=heading,
                text="\n".join(text for _, text in own),
                block_ids=tuple(block_id for block_id, _ in own),
            )
        )
    return BuildResult(
        drafts=drafts, skipped_blocks=skipped_blocks, skipped_paths=dict(skipped_paths)
    )
