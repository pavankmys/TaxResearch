"""Citation parser for legal references."""

import re
from dataclasses import dataclass
from typing import Literal

from .aliases import Aliases, load_aliases
from .text import normalise_text


@dataclass(frozen=True)
class Citation:
    """Represents a single citation found in text."""

    kind: Literal["provision", "notification", "circular"]
    canonical_id: str | None  # None if unresolvable
    raw: str  # Original matched text
    confidence: float  # 0.0 to 1.0
    instrument: str | None  # Instrument code if resolved, else None
    ambiguous: bool  # True if sub-token like (i) could be letter or roman
    candidates: tuple[str, ...]  # Alternative resolutions (e.g., all known provisions)


def looks_like_citation(text: str) -> bool:
    """Quick heuristic check if text might contain a citation.

    Args:
        text: Text to check.

    Returns:
        True if text matches citation patterns, False otherwise.
    """
    if not text or not isinstance(text, str):
        return False

    text_lower = text.lower()

    # Quick patterns for common citation forms
    patterns = [
        r"\bs\.?\s*\d+",  # s. or s followed by digit
        r"\brule\s*\d+",  # rule followed by digit
        r"\bsection\s+\d+",  # section followed by digit
        r"\bnotif(?:ication)?\s+\d+/\d+",  # notification
        r"\bcircul(?:ar)?\s+\d+/\d+/\d+",  # circular
    ]

    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True

    return False


def parse_citation(
    text: str,
    default_instrument: str | None = None,
    aliases: Aliases | None = None,
) -> list[Citation]:
    """Parse citations from text.

    Handles multiple citations separated by "and" or ",".

    Args:
        text: Input text to parse.
        default_instrument: Default instrument code (e.g., "CGST_ACT").
        aliases: Loaded alias configuration.

    Returns:
        List of Citation objects found in text. Returns empty list if no citations found.
        Never raises on any input.
    """
    if not text or not isinstance(text, str):
        return []

    try:
        # Load aliases if not provided
        if aliases is None:
            try:
                aliases = load_aliases()
            except FileNotFoundError:
                # If aliases cannot be loaded, use empty aliases
                aliases = Aliases(
                    notification_series={},
                    act_aliases={},
                    rules_aliases={},
                )

        # Normalize text first
        text = normalise_text(text)

        # Try to extract citations using pattern matching (deterministic)
        citations = _extract_citations_regex(text, default_instrument, aliases)
        return citations

    except Exception:
        # On any error, return empty list (never raise)
        return []


def _extract_citations_regex(
    text: str,
    default_instrument: str | None,
    aliases: Aliases,
) -> list[Citation]:
    """Extract citations using deterministic regex patterns.

    NOTE: TSD 6.3 specifies a Lark (PEG) grammar. The M0 stub uses regular
    expressions instead. Replace with the Lark grammar when ranges and case-name
    citations are added; the golden-table tests define the required behaviour.
    """
    citations: list[Citation] = []

    # Provision patterns: s. 16(2)(c) CGST, section 74A IGST, etc.
    # Captures: (1) section number, (2) entire parentheses substring (e.g., "(2)(c)")
    prov_patterns = [
        (r"s\.?\s*(\d+[a-z]?)((?:\([^)]+\))*)", "section"),
        (r"sec(?:tion)?\.?\s*(\d+[a-z]?)((?:\([^)]+\))*)", "section"),
    ]

    # Rule patterns: rule 36(4) CGST Rules
    # Captures: (1) rule number, (2) entire parentheses substring (e.g., "(4)(a)")
    rule_patterns = [
        (r"\brules?\s*(\d+[a-z]?)((?:\([^)]+\))*)", "rule"),
        (r"\br\.?\s*(\d+[a-z]?)((?:\([^)]+\))*)", "rule"),
    ]

    # Notification patterns: Notf 11/2017-CT(R), Notification No. 11/2017-CT(R)
    notif_patterns = [
        r"(?:notif(?:ication)?|notf\.?)\s+(?:no\.?\s*)?(\d+)\s*/\s*(\d{4})\s*-\s*([a-z()\s]+)",
    ]

    # Circular patterns: Circular 183/15/2022, Circ. No. 183/15/2022
    circular_patterns = [
        r"(?:circular|circ\.?)\s+(?:no\.?\s*)?(\d+)\s*/\s*(\d+)\s*/\s*(\d{4})",
    ]

    # Extract provisions and rules
    # First, find all provision/rule matches without instruments
    all_patterns = prov_patterns + rule_patterns
    matches_by_position: dict[tuple[int, int], tuple[str, str, str]] = {}

    for pattern, kind in all_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            sec_no = match.group(1)
            subs_str = match.group(2) or ""
            start, end = match.span()
            # Store: (sec_no, subs_str, kind)
            matches_by_position[(start, end)] = (sec_no, subs_str, kind)

    # Find shared instrument at the end of all citations
    # e.g., in "s.16 and s.17 CGST", CGST applies to both
    shared_instrument = None
    # Look for instrument keywords after the last citation
    if matches_by_position:
        last_match_end = max((start_end[1] for start_end, _ in matches_by_position.items()))
        remaining_text = text[last_match_end:]
        # Look for CGST, IGST, UTGST, Act, Rules keywords
        shared_match = re.search(
            r"(?:and\s+)?([a-z]+(?:\s+[a-z]+)?)\s*(?:act|rules)?",
            remaining_text,
            re.IGNORECASE,
        )
        if shared_match:
            potential_instr = shared_match.group(1).strip()
            # Validate it looks like an instrument
            keywords = ["cgst", "igst", "utgst", "act", "rules", "cess", "comp"]
            if any(kw in potential_instr.lower() for kw in keywords):
                shared_instrument = potential_instr

    for (start, end), (sec_no, subs_str, kind) in matches_by_position.items():
        instr = None

        # First try to find an instrument immediately after this citation
        following_text = text[end : min(end + 40, len(text))]
        separators = ("and", "s", "r", ",")
        if following_text.strip() and not following_text.strip().startswith(separators):
            # There's non-separator text right after, might be an instrument
            instr_match = re.search(
                r"^(?:\s+(?:of\s+)?)?([a-z]+(?:\s+[a-z]+)?)",
                following_text,
                re.IGNORECASE,
            )
            if instr_match:
                potential_instr = instr_match.group(1).strip()
                keywords = ["cgst", "igst", "utgst", "act", "rules", "cess", "comp"]
                if any(kw in potential_instr.lower() for kw in keywords):
                    instr = potential_instr

        # Fall back to shared instrument
        if not instr:
            instr = shared_instrument

        # Fall back to default
        if not instr:
            instr = default_instrument

        # Parse sub-sections from parentheses
        path_prefix = "r" if kind == "rule" else "s"
        path = _build_provision_path(sec_no, subs_str, path_prefix)

        # Determine instrument
        resolved_instrument = _resolve_instrument(
            instr, default_instrument, aliases, is_rule=kind == "rule"
        )

        canonical = None
        candidates: tuple[str, ...] = ()
        ambiguous = _has_ambiguous_sub(subs_str)

        if resolved_instrument:
            canonical = f"prov:{resolved_instrument}:{path}"
            confidence = 0.9
        else:
            # Return candidates (all known instruments)
            if kind == "rule":
                candidates = tuple(
                    f"prov:{instr_code}:{path}"
                    for instr_code in ["CGST_RULES", "IGST_RULES", "UTGST_RULES"]
                )
            else:
                candidates = tuple(
                    f"prov:{instr_code}:{path}"
                    for instr_code in ["CGST_ACT", "IGST_ACT", "UTGST_ACT"]
                )
            confidence = 0.6

        # Build raw text from the match
        raw = text[start:end].strip()
        citations.append(
            Citation(
                kind="provision",
                canonical_id=canonical,
                raw=raw,
                confidence=confidence,
                instrument=resolved_instrument,
                ambiguous=ambiguous,
                candidates=candidates,
            )
        )

    # Extract notifications
    for pattern in notif_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            number = match.group(1)
            year = match.group(2)
            series = match.group(3).strip()

            # Normalize series
            normalized_series = _resolve_series(series, aliases)

            if normalized_series:
                canonical = f"ntf:{normalized_series}:{number}/{year}"
                confidence = 0.95
            else:
                canonical = None
                confidence = 0.5

            raw = match.group(0)
            citations.append(
                Citation(
                    kind="notification",
                    canonical_id=canonical,
                    raw=raw,
                    confidence=confidence,
                    instrument=None,
                    ambiguous=False,
                    candidates=(),
                )
            )

    # Extract circulars
    for pattern in circular_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            a = match.group(1)
            b = match.group(2)
            year = match.group(3)

            canonical = f"cir:{a}/{b}/{year}"
            raw = match.group(0)
            citations.append(
                Citation(
                    kind="circular",
                    canonical_id=canonical,
                    raw=raw,
                    confidence=0.95,
                    instrument=None,
                    ambiguous=False,
                    candidates=(),
                )
            )

    return citations


def _build_provision_path(sec_no: str, subs_str: str, prefix: str = "s") -> str:
    """Build provision/rule path from number and sub-sections.

    Args:
        sec_no: Section or rule number (e.g., "16", "36", "74A").
        subs_str: Parenthesized sub-sections (e.g., "(2)(c)").
        prefix: Path prefix ("s" for section, "r" for rule). Defaults to "s".

    Returns:
        Path string preserving case in number, lowercasing sub-sections.
        Examples: "s16.2.c", "r36.4", "s74A"
    """
    path = f"{prefix}{sec_no}"  # Preserve case of section/rule number

    if not subs_str:
        return path

    # Parse sub-sections: (2)(c)(i) -> 2.c.i (lowercase)
    sub_parts = re.findall(r"\(([^)]+)\)", subs_str)
    for part in sub_parts:
        part = part.strip().lower()
        path += f".{part}"

    return path


def _resolve_instrument(
    instr: str | None,
    default_instrument: str | None,
    aliases: Aliases,
    is_rule: bool = False,
) -> str | None:
    """Resolve instrument name to canonical code.

    Args:
        instr: Instrument string (e.g., "CGST", "CGST Act").
        default_instrument: Default instrument if none specified.
        aliases: Alias configuration.
        is_rule: Whether this is a rule (not section).

    Returns:
        Canonical instrument code, or None if unresolvable.
    """
    if not instr:
        return default_instrument

    instr_lower = instr.lower().strip()

    # Try to match act aliases
    for alias_lower, code in aliases.act_aliases.items():
        if alias_lower in instr_lower or instr_lower in alias_lower:
            if not is_rule or "RULES" in code:
                return code

    # Try to match rules aliases
    for alias_lower, code in aliases.rules_aliases.items():
        if alias_lower in instr_lower or instr_lower in alias_lower:
            if "RULES" in code:
                return code

    # Try to match common patterns directly
    if "cgst" in instr_lower:
        return "CGST_RULES" if is_rule else "CGST_ACT"
    if "igst" in instr_lower:
        return "IGST_RULES" if is_rule else "IGST_ACT"
    if "utgst" in instr_lower:
        return "UTGST_RULES" if is_rule else "UTGST_ACT"

    return default_instrument


def _resolve_series(series_str: str, aliases: Aliases) -> str | None:
    """Resolve notification series to canonical code.

    Args:
        series_str: Series string (e.g., "CT(R)", "Central Tax (Rate)").
        aliases: Alias configuration.

    Returns:
        Canonical series code, or None if unresolvable.
    """
    if not series_str:
        return None

    series_lower = series_str.lower().strip()

    # Try direct lookup in aliases
    for alias_lower, code in aliases.notification_series.items():
        if alias_lower == series_lower:
            return code

    # Try partial match
    for alias_lower, code in aliases.notification_series.items():
        if series_lower in alias_lower or alias_lower in series_lower:
            return code

    return None


def _has_ambiguous_sub(subs_str: str) -> bool:
    """Check if sub-sections contain ambiguous tokens like (i), (v), (x).

    These can be interpreted as either letters or roman numerals.
    Only single-letter tokens that are i, v, or x are ambiguous.
    (c), (d), (l), (m) are NOT ambiguous. (ii), (iv), etc. are NOT ambiguous.

    Args:
        subs_str: Sub-sections string (e.g., "(2)(i)(c)").

    Returns:
        True if ambiguous tokens are found.
    """
    if not subs_str:
        return False

    # Extract all sub-tokens
    subs = re.findall(r"\(([^)]+)\)", subs_str)

    # Ambiguous: ONLY single-letter tokens that are i, v, or x
    ambiguous_letters = {"i", "v", "x"}

    for sub in subs:
        sub_lower = sub.lower().strip()
        # Only single characters (not multi-char like "ii" or "iv")
        if len(sub_lower) == 1 and sub_lower in ambiguous_letters:
            return True

    return False
