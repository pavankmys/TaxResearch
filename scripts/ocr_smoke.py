#!/usr/bin/env python3
"""OCR smoke test for document processing pipeline.

Creates a synthetic PDF with text, runs OCR, and verifies text extraction.
Requires: pillow, pypdfium2, pdfplumber
Requires tesseract-ocr for full OCR testing (marked as integration test).
"""

import shutil
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import ocrmypdf
except ImportError:
    ocrmypdf = None


def make_synthetic_pdf(path: Path) -> None:
    """Create a synthetic PDF with text as an image (scanned document).

    Creates a white page with large text drawn using PIL, saved as a PDF.
    This creates an image-only PDF (no text layer), suitable for OCR testing.

    Args:
        path: Path where the PDF will be saved
    """
    if Image is None or ImageDraw is None:
        raise ImportError("pillow is required: pip install pillow")

    # Create a white image with dimensions suitable for A4 (300 DPI)
    width, height = 2100, 2970  # A4 at 300 DPI
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Draw text in a large font
    text = "SYNTHETIC SMOKE TEST SECTION SIXTEEN"
    text_bbox = draw.textbbox((0, 0), text)
    text_width = text_bbox[2] - text_bbox[0]

    # Center horizontally, position vertically
    x = (width - text_width) // 2
    y = height // 3

    draw.text((x, y), text, fill="black")

    # Save as single-page PDF (image only, no text layer)
    # Using PDF mode with PIL converts the image to PDF format
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PDF")
    print(f"✓ Created synthetic PDF: {path}")


def run_ocr(src: Path, dst: Path) -> None:
    """Run OCR on a PDF using ocrmypdf.

    Args:
        src: Source PDF path
        dst: Output PDF path (will have OCR text layer)
    """
    if ocrmypdf is None:
        raise ImportError("ocrmypdf is required: pip install ocrmypdf")

    # Check if tesseract is available
    tesseract_path = shutil.which("tesseract")
    if not tesseract_path:
        raise FileNotFoundError(
            "tesseract-ocr not found on PATH. "
            "Install with: apt install tesseract-ocr tesseract-ocr-eng"
        )

    # Run OCR with force flag
    try:
        ocrmypdf.ocr(
            str(src),
            str(dst),
            language="eng",
            force_ocr=True,
        )
        print(f"✓ OCR completed: {dst}")
    except Exception as e:
        print(f"✗ OCR failed: {e}")
        raise


def extract_text(pdf: Path) -> str:
    """Extract text from a PDF using pdfplumber.

    Args:
        pdf: Path to PDF file

    Returns:
        Concatenated text from all pages
    """
    if pdfplumber is None:
        raise ImportError("pdfplumber is required: pip install pdfplumber")

    text_parts = []
    try:
        with pdfplumber.open(pdf) as doc:
            for i, page in enumerate(doc.pages):
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
                status = "✓" if page_text.strip() else "✗"
                print(f"  {status} Page {i + 1}: {len(page_text)} chars")
    except Exception as e:
        print(f"✗ Text extraction failed: {e}")
        raise

    return "\n".join(text_parts)


def main() -> int:
    """Run the OCR smoke test.

    Returns:
        0 on success, 1 on failure
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Check for required dependencies
        missing = []
        if Image is None:
            missing.append("pillow")
        if pdfplumber is None:
            missing.append("pdfplumber")
        if ocrmypdf is None:
            missing.append("ocrmypdf")

        if missing:
            print(f"✗ Missing required packages: {', '.join(missing)}")
            print(f"  Install with: pip install {' '.join(missing)}")
            return 1

        # Check for tesseract
        tesseract_path = shutil.which("tesseract")
        if not tesseract_path:
            print("✗ tesseract-ocr not found on PATH")
            print("  Install with: apt install tesseract-ocr tesseract-ocr-eng")
            return 1

        try:
            # Create synthetic PDF
            print("Creating synthetic PDF...")
            pdf_src = tmpdir / "synthetic.pdf"
            make_synthetic_pdf(pdf_src)

            # Run OCR
            print("Running OCR...")
            pdf_ocr = tmpdir / "synthetic_ocr.pdf"
            run_ocr(pdf_src, pdf_ocr)

            # Extract text
            print("Extracting text from OCR result...")
            extracted_text = extract_text(pdf_ocr)

            # Verify key words
            print("\nVerifying extracted text...")
            found_smoke = "SMOKE" in extracted_text.upper()
            found_sixteen = "SIXTEEN" in extracted_text.upper()

            if found_smoke:
                print("✓ Found 'SMOKE' in extracted text")
            else:
                print("✗ Did not find 'SMOKE' in extracted text")

            if found_sixteen:
                print("✓ Found 'SIXTEEN' in extracted text")
            else:
                print("✗ Did not find 'SIXTEEN' in extracted text")

            if found_smoke and found_sixteen:
                print("\n✓ OCR smoke test PASSED")
                return 0
            else:
                print("\n✗ OCR smoke test FAILED: extracted text missing expected words")
                print(f"Extracted: {extracted_text[:200]}...")
                return 1

        except (ImportError, FileNotFoundError) as e:
            print(f"✗ {e}")
            return 1
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
