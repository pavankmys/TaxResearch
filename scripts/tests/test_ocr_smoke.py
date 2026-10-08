"""Tests for OCR smoke test script.

Tests for make_synthetic_pdf work without tesseract.
Full OCR tests are marked as integration tests and require tesseract.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Import the functions to test
sys.path.insert(0, str(Path(__file__).parent.parent))
from ocr_smoke import extract_text, make_synthetic_pdf  # noqa: E402


def test_make_synthetic_pdf_creates_file() -> None:
    """Test that make_synthetic_pdf creates a valid PDF file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "test.pdf"
        make_synthetic_pdf(pdf_path)

        # Check file was created
        assert pdf_path.exists(), "PDF file was not created"
        assert pdf_path.stat().st_size > 0, "PDF file is empty"

        # Check it looks like a PDF (has PDF header)
        with open(pdf_path, "rb") as f:
            header = f.read(4)
            assert header == b"%PDF", "File is not a valid PDF"


def test_make_synthetic_pdf_single_page() -> None:
    """Test that synthetic PDF has exactly one page."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "test.pdf"
        make_synthetic_pdf(pdf_path)

        # Try to verify page count using pdfplumber if available
        try:
            import pdfplumber

            with pdfplumber.open(pdf_path) as doc:
                assert len(doc.pages) == 1, f"Expected 1 page, got {len(doc.pages)}"
        except ImportError:
            # Skip if pdfplumber not available
            pytest.skip("pdfplumber not available")


def test_make_synthetic_pdf_no_text_layer() -> None:
    """Test that synthetic PDF has no text layer (image-only)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "test.pdf"
        make_synthetic_pdf(pdf_path)

        # Check with pdfplumber that text extraction is empty (no text layer)
        try:
            import pdfplumber

            with pdfplumber.open(pdf_path) as doc:
                for page in doc.pages:
                    text = page.extract_text() or ""
                    # Image-only PDF should have no extractable text before OCR
                    assert len(text.strip()) == 0, "PDF should have no text layer"
        except ImportError:
            pytest.skip("pdfplumber not available")


@pytest.mark.integration
def test_ocr_smoke_full_pipeline() -> None:
    """Full OCR pipeline test requiring tesseract.

    This test:
    1. Creates a synthetic PDF
    2. Runs OCR
    3. Extracts text
    4. Verifies expected words are found
    """
    # Check tesseract is available
    if not shutil.which("tesseract"):
        pytest.skip("tesseract-ocr not found on PATH")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        from ocr_smoke import run_ocr

        # Create and OCR
        pdf_src = tmpdir / "synthetic.pdf"
        pdf_ocr = tmpdir / "synthetic_ocr.pdf"

        make_synthetic_pdf(pdf_src)
        run_ocr(pdf_src, pdf_ocr)

        # Extract and verify
        extracted_text = extract_text(pdf_ocr)
        assert extracted_text, "No text extracted"

        # Check for key words
        upper_text = extracted_text.upper()
        assert "SMOKE" in upper_text, "SMOKE not found in extracted text"
        assert "SIXTEEN" in upper_text, "SIXTEEN not found in extracted text"
