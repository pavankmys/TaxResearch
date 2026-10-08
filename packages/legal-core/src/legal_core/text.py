"""Text normalization utilities."""

import re
import unicodedata


def normalise_text(s: str) -> str:
    """Normalize text for canonical processing.

    Applies:
    - Unicode NFKC normalization
    - Converts en/em/minus dashes to "-"
    - Converts curly quotes to straight quotes
    - Collapses all whitespace to single space
    - Strips leading/trailing whitespace

    No case folding is applied.

    Args:
        s: Input string.

    Returns:
        Normalized string.
    """
    if not isinstance(s, str):
        s = str(s)

    # Unicode NFKC normalization
    s = unicodedata.normalize("NFKC", s)

    # Replace various dash variants with hyphen-minus
    # en dash (U+2013), em dash (U+2014), minus sign (U+2212), hyphen (U+2010)
    s = re.sub(r"[–—−‐]", "-", s)

    # Replace curly quotes with straight quotes
    s = s.replace("‘", "'")  # Left single quotation mark
    s = s.replace("’", "'")  # Right single quotation mark (apostrophe)
    s = s.replace("“", '"')  # Left double quotation mark
    s = s.replace("”", '"')  # Right double quotation mark

    # Collapse all whitespace (spaces, tabs, newlines, etc.) to single space
    s = re.sub(r"\s+", " ", s)

    # Strip leading/trailing whitespace
    s = s.strip()

    return s
