"""Tests for the 64-bit simhash fingerprint."""

import random

from worker.ingest.simhash import hamming, simhash64

_WORDS = (
    "tax supply goods services rate notification government schedule registered person "
    "return invoice credit input output integrated central state union territory exemption "
    "section rule act order appeal refund payment interest penalty officer proper"
).split()


def _text(seed: int, count: int) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choice(_WORDS) for _ in range(count))


def test_simhash_is_deterministic() -> None:
    text = _text(1, 200)
    assert simhash64(text) == simhash64(text)


def test_simhash_is_signed_64_bit() -> None:
    for seed in range(20):
        value = simhash64(_text(seed, 100))
        assert -(2**63) <= value < 2**63


def test_simhash_empty_text() -> None:
    assert simhash64("") == 0


def test_near_identical_texts_are_close() -> None:
    base = _text(7, 1200)
    changed = base.replace(base.split()[600], "zzzzqqq", 1)
    assert hamming(simhash64(base), simhash64(changed)) <= 3


def test_different_texts_are_far() -> None:
    assert hamming(simhash64(_text(3, 400)), simhash64(_text(4, 400))) > 10


def test_hamming_uses_unsigned_bits() -> None:
    assert hamming(0, 0) == 0
    assert hamming(-1, 0) == 64
    assert hamming(1, 3) == 1
