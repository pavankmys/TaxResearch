"""Word-recall harness for PDF extraction (TSD 5.13).

Usage: python eval/extraction_recall.py <dir> [--min 0.995]

For each <name>.pdf with a <name>.expected.txt beside it, parses the PDF and measures the
share of expected words (lower-cased \\w+ tokens, multiset) found in the extracted page text.
Exits 1 when the overall recall is below --min.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from legal_core.text import normalise_text  # noqa: E402
from worker.ingest.pdf import parse_pdf  # noqa: E402
from worker.ingest.types import ParseConfig  # noqa: E402

DEFAULT_MIN = 0.995
_WORD = re.compile(r"\w+")


def _words(text: str) -> Counter[str]:
    return Counter(_WORD.findall(normalise_text(text).lower()))


def word_recall(expected: str, actual: str) -> float:
    """Share of expected words that appear in actual (multiset intersection)."""
    expected_words = _words(expected)
    total = sum(expected_words.values())
    if total == 0:
        return 1.0
    found = sum((expected_words & _words(actual)).values())
    return found / total


def run(directory: Path, minimum: float) -> int:
    cases = sorted(directory.glob("*.pdf"))
    rows: list[tuple[str, int, float]] = []
    total_expected = 0
    total_found = 0.0
    for pdf_path in cases:
        expected_path = pdf_path.with_suffix(".expected.txt")
        if not expected_path.exists():
            continue
        expected = expected_path.read_text(encoding="utf-8")
        result = parse_pdf(pdf_path.read_bytes(), ParseConfig())
        actual = "\n".join(page.text for page in result.pages)
        count = sum(_words(expected).values())
        recall = word_recall(expected, actual)
        rows.append((pdf_path.name, count, recall))
        total_expected += count
        total_found += recall * count

    if not rows:
        print(f"No <name>.pdf with <name>.expected.txt found in {directory}", file=sys.stderr)
        return 1

    width = max(len(name) for name, _, _ in rows)
    print(f"{'file':<{width}}  {'words':>7}  {'recall':>8}")
    for name, count, recall in rows:
        print(f"{name:<{width}}  {count:>7}  {recall:>8.4f}")
    overall = total_found / total_expected if total_expected else 1.0
    print(f"{'OVERALL':<{width}}  {total_expected:>7}  {overall:>8.4f}  (min {minimum})")
    return 0 if overall >= minimum else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--min", type=float, default=DEFAULT_MIN, dest="minimum")
    args = parser.parse_args(argv)
    return run(args.directory, args.minimum)


if __name__ == "__main__":
    sys.exit(main())
