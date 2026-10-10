"""Text and word diff utilities (TSD 4.10, FR-RES-08)."""

import difflib
import re

_TOKENS = re.compile(r"\s+|\S+")


def word_diff(old: str | None, new: str | None) -> str:
    """The change as text: ``[-removed-]`` and ``{+added+}`` around the words that differ."""
    old_tokens = _TOKENS.findall(old or "")
    new_tokens = _TOKENS.findall(new or "")
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        a=old_tokens, b=new_tokens, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            out.append("".join(old_tokens[i1:i2]))
            continue
        if i2 > i1:
            out.append("[-" + "".join(old_tokens[i1:i2]).strip() + "-]")
        if j2 > j1:
            out.append("{+" + "".join(new_tokens[j1:j2]).strip() + "+}")
        out.append(" ")
    return re.sub(r" {2,}", " ", "".join(out)).strip()
