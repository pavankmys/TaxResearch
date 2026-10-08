"""Tests for the word-recall harness in eval/extraction_recall.py."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .pdf_fixtures import born_digital

_HARNESS = Path(__file__).resolve().parents[3] / "eval" / "extraction_recall.py"


def _load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("extraction_recall", _HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["extraction_recall"] = module
    spec.loader.exec_module(module)
    return module


def test_word_recall_math() -> None:
    harness = _load_harness()
    assert harness.word_recall("one two three four", "one two three four") == 1.0
    assert harness.word_recall("one two three four", "one two three") == 0.75
    assert harness.word_recall("One, TWO three", "one two THREE extra") == 1.0
    assert harness.word_recall("a a b", "a b") == 2 / 3  # multiset: second "a" missing
    assert harness.word_recall("", "anything") == 1.0


def test_harness_passes_on_born_digital_fixture(tmp_path: Path) -> None:
    harness = _load_harness()
    paragraphs = [
        "1. The rate of tax on the supply of goods shall be as notified by the Government "
        "in the schedule annexed hereto, subject to the conditions stated therein.",
        "2. Every registered person shall furnish the return within the prescribed time and "
        "pay the tax due thereon in cash or by utilisation of credit available in the ledger.",
    ]
    (tmp_path / "sample.pdf").write_bytes(born_digital(paragraphs, pages=2))
    (tmp_path / "sample.expected.txt").write_text("\n\n".join(paragraphs), encoding="utf-8")
    assert harness.main([str(tmp_path)]) == 0


def test_harness_fails_when_words_are_missing(tmp_path: Path) -> None:
    harness = _load_harness()
    paragraphs = ["1. The rate of tax on the supply of goods shall be as notified " * 4]
    (tmp_path / "sample.pdf").write_bytes(born_digital(paragraphs, pages=1))
    (tmp_path / "sample.expected.txt").write_text(
        paragraphs[0] + " zebra quartz plinth", encoding="utf-8"
    )
    assert harness.main([str(tmp_path)]) == 1
