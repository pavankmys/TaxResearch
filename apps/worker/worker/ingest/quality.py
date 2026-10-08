"""Text quality checks (garble score, engine cross-check, language flag).

Also holds small text helpers shared by the PDF and HTML parsers: paragraph
labels and table-to-row rendering.
"""

import re

from legal_core.text import normalise_text

_PRIVATE_OR_REPLACEMENT = re.compile("[-�]")
_CID = re.compile(r"\(cid:\d+\)")
_CID_WEIGHT = 5
_NUMBERING = re.compile(r"^\(?([0-9]{1,3}|[a-z]{1,3}|[ivxlc]{1,6})[\.\)]\s")
_DEVANAGARI_LO = 0x0900
_DEVANAGARI_HI = 0x097F
_DEVANAGARI_PUNCT_LO = 0x0964  # danda and double danda
_DEVANAGARI_DIGIT_HI = 0x096F


def _is_devanagari_letter(ch: str) -> bool:
    code = ord(ch)
    return _DEVANAGARI_LO <= code <= _DEVANAGARI_HI and not (
        _DEVANAGARI_PUNCT_LO <= code <= _DEVANAGARI_DIGIT_HI
    )


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or _is_devanagari_letter(ch) or ch in "।॥"


def _is_nonword_token(token: str) -> bool:
    word_chars = sum(1 for ch in token if _is_word_char(ch))
    if word_chars == 0:
        return True
    return (len(token) - word_chars) / len(token) > 0.4


def garble_score(text: str) -> float:
    """Score how garbled extracted text looks, in [0, 1].

    Combines the share of private-use and replacement characters, `(cid:N)`
    markers (each counted as 5 characters), and non-word tokens (weighted 0.5).
    """
    if not text.strip():
        return 0.0
    non_space = sum(1 for ch in text if not ch.isspace())
    bad_chars = len(_PRIVATE_OR_REPLACEMENT.findall(text))
    bad_chars += _CID_WEIGHT * len(_CID.findall(text))
    char_part = bad_chars / max(non_space, 1)
    tokens = text.split()
    token_part = sum(1 for t in tokens if _is_nonword_token(t)) / len(tokens) if tokens else 0.0
    return min(1.0, char_part + 0.5 * token_part)


def cross_check_mismatch(a: int, b: int, margin: float) -> bool:
    """True when two character counts differ by more than `margin` (relative)."""
    return abs(a - b) / max(a, b, 1) > margin


def detect_lang(text: str) -> str | None:
    """Return "hi" when Devanagari dominates the letters, "en" for other letters, else None."""
    letters = 0
    devanagari = 0
    for ch in text:
        if _is_devanagari_letter(ch):
            letters += 1
            devanagari += 1
        elif ch.isalpha():
            letters += 1
    if letters == 0:
        return None
    return "hi" if devanagari / letters > 0.3 else "en"


def starts_numbered(text: str) -> bool:
    """True when the text opens with a paragraph number such as "23." or "(a)"."""
    return _NUMBERING.match(text + " ") is not None


def para_label(text: str) -> str | None:
    """Return the printed paragraph label at the start of text ("23.", "(a)") without the dot."""
    match = _NUMBERING.match(text + " ")
    if match is None:
        return None
    token = match.group(0).strip()
    if token.endswith("."):
        token = token[:-1]
    return token


def table_texts(rows: list[list[str]]) -> tuple[str, list[str]]:
    """Render a table as (table text, one text per data row).

    Empty rows are dropped. Each data row becomes "Header: cell; Header: cell", so the
    column meaning survives chunking. The table text joins cells with " | ".
    """
    cleaned = [[normalise_text(cell or "") for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(cell for cell in row)]
    if not cleaned:
        return "", []
    table_text = "\n".join(" | ".join(row) for row in cleaned)
    header = cleaned[0]
    row_texts: list[str] = []
    for row in cleaned[1:]:
        parts = []
        for col, cell in enumerate(row):
            if not cell:
                continue
            label = header[col] if col < len(header) and header[col] else f"Column {col + 1}"
            parts.append(f"{label}: {cell}")
        if parts:
            row_texts.append("; ".join(parts))
    return table_text, row_texts
