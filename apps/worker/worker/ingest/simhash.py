"""64-bit simhash over word 3-shingles of normalised text (near-duplicate fingerprint)."""

import hashlib
import re

from legal_core.text import normalise_text

_MASK64 = (1 << 64) - 1
_SIGN_BIT = 1 << 63
_WORD = re.compile(r"\w+")


def _feature_hash(feature: str) -> int:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def simhash64(text: str) -> int:
    """Return the simhash of the text as a signed 64-bit integer (fits a Postgres bigint).

    Features are word 3-shingles; texts shorter than three words use single words.
    """
    tokens = _WORD.findall(normalise_text(text).lower())
    if len(tokens) >= 3:
        features = [" ".join(tokens[i : i + 3]) for i in range(len(tokens) - 2)]
    else:
        features = tokens
    if not features:
        return 0

    counters = [0] * 64
    for feature in features:
        value = _feature_hash(feature)
        for bit in range(64):
            counters[bit] += 1 if (value >> bit) & 1 else -1

    unsigned = 0
    for bit in range(64):
        if counters[bit] > 0:
            unsigned |= 1 << bit
    return unsigned - (1 << 64) if unsigned & _SIGN_BIT else unsigned


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two simhashes (signed or unsigned)."""
    return bin((a ^ b) & _MASK64).count("1")
